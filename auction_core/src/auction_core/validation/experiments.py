"""Factorial experiment runner — the dissertation's design, on correct mechanics.

Factors (matching the original experimental design):
    K       tasks               {4, 8, 16, 32}
    delay   comm delay (ms)     {0, 50, 200, 500}   (1 tick = 50 ms)
    loss    packet loss prob    {0, 0.1, 0.3, 0.5}
    epsilon min bid increment   {0.01, 0.05, 0.2, 0.5}

This time delay and loss are actually in the message path (the original
MATLAB swept a comm_delay parameter nothing read), and quality is measured
where the theory speaks: per-round total benefit against the Hungarian
optimum on the same frozen matrix, alongside system-level makespan against
the CPM lower bound (a bound, not an optimum).

Usage:
    python -m auction_core.validation.experiments --reps 15 --robots 2 \
        --out results/factorial.csv [--quick]
"""

from __future__ import annotations

import argparse
import csv
import itertools
import random
import sys
from dataclasses import dataclass
from multiprocessing import Pool

from ..types import RoundConfig, Task
from ..allocator.repeated_rounds import RepeatedRoundsAllocator
from ..scheduling.benefits import BenefitModel, RobotState
from ..scheduling.cpm import makespan_lower_bound
from ..scheduling.dag import TaskDag
from .harness import run_round, suggested_quiescence
from .hungarian import optimal_assignment, total_benefit
from .transport import SimTransport, complete

TICK_MS = 50.0
WORKSPACE = (4.0, 4.0)          # dissertation environment scale
ROBOT_SPEED = 0.26              # TurtleBot3 Waffle Pi max linear velocity
K_LEVELS = (4, 8, 16, 32)
DELAY_LEVELS_MS = (0, 50, 200, 500)
LOSS_LEVELS = (0.0, 0.1, 0.3, 0.5)
EPSILON_LEVELS = (0.01, 0.05, 0.2, 0.5)


@dataclass(frozen=True)
class RunSpec:
    num_tasks: int
    delay_ms: int
    loss: float
    epsilon: float
    robots: int
    rep: int


def _scenario(spec: RunSpec, rng: random.Random) -> tuple[list[RobotState], list[Task]]:
    robots = [
        RobotState(
            id=i,
            position=(
                rng.uniform(0, WORKSPACE[0]),
                rng.uniform(0, WORKSPACE[1]),
            ),
            speed=ROBOT_SPEED,
        )
        for i in range(spec.robots)
    ]
    tasks = []
    for tid in range(spec.num_tasks):
        prereqs = frozenset(
            rng.sample(range(tid), k=min(tid, rng.randint(1, 3)))
        ) if tid and rng.random() < 0.3 else frozenset()
        tasks.append(
            Task(
                id=tid,
                position=(
                    rng.uniform(0, WORKSPACE[0]),
                    rng.uniform(0, WORKSPACE[1]),
                ),
                duration=rng.uniform(5.0, 10.0),
                prerequisites=prereqs,
            )
        )
    return robots, tasks


def run_one(spec: RunSpec) -> dict:
    rng = random.Random(
        (spec.num_tasks, spec.delay_ms, int(spec.loss * 10),
         int(spec.epsilon * 100), spec.robots, spec.rep).__hash__() & 0x7FFFFFFF
    )
    robots, tasks = _scenario(spec, rng)
    delay_ticks = round(spec.delay_ms / TICK_MS)
    config = RoundConfig(
        epsilon=spec.epsilon,
        quiescence_rounds=suggested_quiescence(
            complete(range(spec.robots)), delay_ticks, loss_prob=spec.loss
        ),
    )

    round_ticks: list[int] = []
    round_gaps: list[float] = []

    def round_runner(benefits, cfg):
        # Topology over this round's participants (idle robots only).
        transport = SimTransport(
            complete(benefits.keys()),
            delay_ticks=delay_ticks,
            loss_prob=spec.loss,
            seed=rng.randrange(2**31),
        )
        result = run_round(benefits, transport, cfg)
        round_ticks.append(result.ticks)
        _, optimum = optimal_assignment(benefits)
        round_gaps.append(optimum - total_benefit(benefits, result.assignment))
        return result

    allocator = RepeatedRoundsAllocator(BenefitModel(), round_runner, config)
    allocation = allocator.allocate(robots, tasks)

    bound = makespan_lower_bound(TaskDag(tasks), spec.robots)
    return {
        "K": spec.num_tasks,
        "delay_ms": spec.delay_ms,
        "loss": spec.loss,
        "epsilon": spec.epsilon,
        "robots": spec.robots,
        "rep": spec.rep,
        "makespan": round(allocation.makespan, 3),
        "cpm_lower_bound": round(bound, 3),
        "rounds": allocation.rounds,
        "total_messages": allocation.total_messages,
        "mean_round_ticks": round(sum(round_ticks) / len(round_ticks), 2),
        "max_round_gap": round(max(round_gaps), 6),
        "n_epsilon_bound": round(spec.robots * spec.epsilon, 6),
        "gap_within_bound": max(round_gaps) <= spec.robots * spec.epsilon + 1e-9,
        "tasks_scheduled": len(allocation.schedule),
        "tasks_unallocated": len(allocation.unallocated),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reps", type=int, default=15)
    parser.add_argument("--robots", type=int, default=2)
    parser.add_argument("--out", default="results/factorial.csv")
    parser.add_argument("--jobs", type=int, default=None)
    parser.add_argument(
        "--quick", action="store_true",
        help="3 reps, K <= 16 — a smoke-test sweep",
    )
    args = parser.parse_args(argv)

    k_levels = tuple(k for k in K_LEVELS if k <= 16) if args.quick else K_LEVELS
    reps = 3 if args.quick else args.reps
    specs = [
        RunSpec(k, d, l, e, args.robots, rep)
        for k, d, l, e in itertools.product(
            k_levels, DELAY_LEVELS_MS, LOSS_LEVELS, EPSILON_LEVELS
        )
        for rep in range(reps)
    ]

    with Pool(args.jobs) as pool:
        rows = pool.map(run_one, specs, chunksize=8)

    import os
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    violations = [r for r in rows if not r["gap_within_bound"]]
    print(f"{len(rows)} runs -> {args.out}")
    print(f"guarantee violations: {len(violations)}")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
