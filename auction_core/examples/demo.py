"""End-to-end demo: 3 robots, 8 DAG tasks, lossy line-topology network.

Run:  python auction_core/examples/demo.py
"""

import random

from auction_core.types import RoundConfig, Task
from auction_core.allocator.repeated_rounds import RepeatedRoundsAllocator
from auction_core.scheduling.benefits import BenefitModel, RobotState
from auction_core.scheduling.cpm import makespan_lower_bound
from auction_core.scheduling.dag import TaskDag
from auction_core.validation.harness import run_round, suggested_quiescence
from auction_core.validation.transport import SimTransport, line

rng = random.Random(7)

robots = [
    RobotState(id=i, position=(rng.uniform(0, 4), rng.uniform(0, 4)), speed=0.26)
    for i in range(3)
]
tasks = [
    Task(0, position=(1.0, 1.0), duration=6.0),
    Task(1, position=(3.0, 1.0), duration=5.0),
    Task(2, position=(2.0, 2.0), duration=8.0),
    Task(3, position=(0.5, 3.0), duration=5.5, prerequisites=frozenset({0})),
    Task(4, position=(3.5, 3.0), duration=7.0, prerequisites=frozenset({1})),
    Task(5, position=(2.0, 0.5), duration=6.0, prerequisites=frozenset({1, 2})),
    Task(6, position=(1.5, 3.5), duration=5.0, prerequisites=frozenset({3})),
    Task(7, position=(3.0, 3.5), duration=9.0, prerequisites=frozenset({4, 5})),
]

# Worst-case diameter over the full team; per round the topology is the
# line over that round's participants (idle robots).
config = RoundConfig(
    epsilon=0.05,
    quiescence_rounds=suggested_quiescence(line(range(len(robots))), 1),
)


def round_runner(benefits, cfg):
    topology = line(benefits.keys())
    transport = SimTransport(
        topology, delay_ticks=1, loss_prob=0.3, seed=rng.randrange(2**31)
    )
    return run_round(benefits, transport, cfg)


allocator = RepeatedRoundsAllocator(BenefitModel(), round_runner, config)
result = allocator.allocate(robots, tasks)

print(f"{'task':>4} {'robot':>5} {'start':>8} {'finish':>8}")
for s in sorted(result.schedule, key=lambda s: s.start):
    print(f"{s.task_id:>4} {s.robot_id:>5} {s.start:>8.1f} {s.finish:>8.1f}")
print(
    f"\nmakespan {result.makespan:.1f}s  "
    f"(CPM lower bound {makespan_lower_bound(TaskDag(tasks), len(robots)):.1f}s)  "
    f"rounds {result.rounds}  messages {result.total_messages}"
)
if result.unallocated:
    print(f"unallocated: {result.unallocated}")
