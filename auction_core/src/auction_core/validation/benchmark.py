"""Head-to-head allocator benchmark.

Two suites, honestly separated:

- "allocators": paired comparison of RepeatedRounds vs SSI (both bid rules)
  on IDENTICAL solo-only instances (same seeds), sweeping K, fleet size,
  loss, and delay. Metrics: makespan (and /CPM ratio), messages, ticks.
  SSI has no collaborative mechanism and the repeated-rounds *allocator*
  (unlike the coordination stack) rejects collabs, so this suite is
  solo-only by design.

- "collab": the full coordination stack (SystemSim) sweeping the
  collaborative fraction of the mission — measures what leader-follower
  recruitment costs in makespan and messages.

Usage:
    python -m auction_core.validation.benchmark --suite allocators --out results/bench_allocators.csv
    python -m auction_core.validation.benchmark --suite collab --out results/bench_collab.csv
"""

from __future__ import annotations

import argparse
import csv
import itertools
import os
import random
import sys
from multiprocessing import Pool

from ..allocator.repeated_rounds import RepeatedRoundsAllocator
from ..allocator.ssi import SSIAllocator
from ..scheduling.benefits import BenefitModel, RobotState
from ..scheduling.cpm import makespan_lower_bound
from ..scheduling.dag import TaskDag
from ..types import RoundConfig, Task
from .harness import run_round, suggested_quiescence
from .system_sim import SystemSim
from .transport import SimTransport, complete

TICK_MS = 50.0
WORKSPACE = (4.0, 4.0)
ROBOT_SPEED = 0.26

K_LEVELS = (4, 8, 16, 32)
ROBOT_LEVELS = (2, 4, 8)
LOSS_LEVELS = (0.0, 0.3)
DELAY_LEVELS_MS = (0, 200)
COLLAB_LEVELS = (0.0, 0.2, 0.4)
EPSILON = 0.05


def scenario(
    num_tasks: int, num_robots: int, seed: int, collab_fraction: float = 0.0
) -> tuple[list[RobotState], list[Task]]:
    rng = random.Random(seed)
    robots = [
        RobotState(
            id=i,
            position=(rng.uniform(0, WORKSPACE[0]), rng.uniform(0, WORKSPACE[1])),
            speed=ROBOT_SPEED,
        )
        for i in range(num_robots)
    ]
    tasks = []
    for tid in range(num_tasks):
        prereqs = (
            frozenset(rng.sample(range(tid), k=min(tid, rng.randint(1, 3))))
            if tid and rng.random() < 0.3
            else frozenset()
        )
        tasks.append(
            Task(
                id=tid,
                position=(
                    rng.uniform(0, WORKSPACE[0]),
                    rng.uniform(0, WORKSPACE[1]),
                ),
                duration=rng.uniform(5.0, 10.0),
                prerequisites=prereqs,
                required_robots=2 if rng.random() < collab_fraction else 1,
            )
        )
    return robots, tasks


# ------------------------------------------------------------- allocator suite


def run_allocator_case(args) -> list[dict]:
    k, n, loss, delay_ms, rep = args
    seed = hash((k, n, int(loss * 10), delay_ms, rep)) & 0x7FFFFFFF
    robots, tasks = scenario(k, n, seed)
    bound = makespan_lower_bound(TaskDag(tasks), n)
    delay_ticks = round(delay_ms / TICK_MS)
    rng = random.Random(seed + 1)

    def transport_factory(ids):
        return SimTransport(
            complete(ids),
            delay_ticks=delay_ticks,
            loss_prob=loss,
            seed=rng.randrange(2**31),
        )

    quiescence = suggested_quiescence(complete(range(n)), delay_ticks, loss_prob=loss)
    config = RoundConfig(epsilon=EPSILON, quiescence_rounds=quiescence)

    ticks_box = [0]

    def round_runner(benefits, cfg):
        transport = transport_factory(set(benefits))
        result = run_round(benefits, transport, cfg)
        ticks_box[0] += result.ticks
        return result

    allocators = {
        "rounds": lambda: RepeatedRoundsAllocator(BenefitModel(), round_runner, config),
        "ssi-makespan": lambda: SSIAllocator(
            "min-makespan",
            transport_factory=transport_factory,
            quiescence_rounds=quiescence,
        ),
        "ssi-sumcost": lambda: SSIAllocator(
            "sum-cost",
            transport_factory=transport_factory,
            quiescence_rounds=quiescence,
        ),
    }

    rows = []
    for name, make in allocators.items():
        ticks_box[0] = 0
        result = make().allocate(robots, tasks)
        assert not result.unallocated, (name, result.unallocated)
        assert len(result.schedule) == k
        ticks = result.allocation_ticks or ticks_box[0]
        rows.append(
            {
                "suite": "allocators",
                "allocator": name,
                "K": k,
                "robots": n,
                "loss": loss,
                "delay_ms": delay_ms,
                "collab_fraction": 0.0,
                "rep": rep,
                "seed": seed,
                "makespan": round(result.makespan, 3),
                "cpm_bound": round(bound, 3),
                "ratio": round(result.makespan / bound, 4) if bound else 0.0,
                "messages": result.total_messages,
                "ticks": ticks,
            }
        )
    return rows


# ----------------------------------------------------------------- collab suite


def run_collab_case(args) -> list[dict]:
    k, n, collab_fraction, rep = args
    seed = hash((k, n, int(collab_fraction * 10), rep, "collab")) & 0x7FFFFFFF
    robots, tasks = scenario(k, n, seed, collab_fraction)
    bound = makespan_lower_bound(TaskDag(tasks), n)
    sim = SystemSim(
        robots,
        tasks,
        seed=seed + 1,
        heartbeat_interval=0.5,
        eta=3,
        epsilon=EPSILON,
        quiescence_rounds=8,
        round_timeout=6.0,
    )
    result = sim.run(max_time=3600.0)
    assert result.mission_time is not None, (k, n, collab_fraction, rep)
    counts = result.completed_counts
    assert not any(c > 1 for c in counts.values()), counts
    return [
        {
            "suite": "collab",
            "allocator": "coordination-stack",
            "K": k,
            "robots": n,
            "loss": 0.0,
            "delay_ms": 0,
            "collab_fraction": collab_fraction,
            "rep": rep,
            "seed": seed,
            "makespan": round(result.mission_time, 3),
            "cpm_bound": round(bound, 3),
            "ratio": round(result.mission_time / bound, 4) if bound else 0.0,
            "messages": result.messages_sent,
            "ticks": int(result.mission_time / sim.tick_period),
        }
    ]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=["allocators", "collab"], required=True)
    parser.add_argument("--reps", type=int, default=15)
    parser.add_argument("--out", required=True)
    parser.add_argument("--jobs", type=int, default=None)
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args(argv)

    reps = 3 if args.quick else args.reps
    if args.suite == "allocators":
        k_levels = (4, 8) if args.quick else K_LEVELS
        cases = [
            (k, n, loss, delay, rep)
            for k, n, loss, delay in itertools.product(
                k_levels, ROBOT_LEVELS, LOSS_LEVELS, DELAY_LEVELS_MS
            )
            for rep in range(reps)
        ]
        runner = run_allocator_case
    else:
        k_levels = (8,) if args.quick else (8, 16)
        cases = [
            (k, n, cf, rep)
            for k, n, cf in itertools.product(k_levels, (2, 4), COLLAB_LEVELS)
            for rep in range(reps)
        ]
        runner = run_collab_case

    with Pool(args.jobs) as pool:
        rows = [r for batch in pool.map(runner, cases, chunksize=4) for r in batch]

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} rows -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
