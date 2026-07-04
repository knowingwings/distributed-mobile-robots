"""SSI allocator: selection, bid rules, playback."""

import random

import pytest

from auction_core.allocator.ssi import SSIAllocator
from auction_core.scheduling.benefits import RobotState
from auction_core.scheduling.cpm import makespan_lower_bound
from auction_core.scheduling.dag import TaskDag
from auction_core.types import Task
from auction_core.validation.harness import suggested_quiescence
from auction_core.validation.transport import SimTransport, complete


def robots(n):
    return [RobotState(id=i, position=(float(4 * i), 0.0), speed=1.0) for i in range(n)]


def test_single_task_goes_to_closest():
    # min-makespan: closest robot has the lowest completion time.
    result = SSIAllocator().allocate(
        robots(2), [Task(0, position=(0.5, 0.0), duration=1.0)]
    )
    assert [s.robot_id for s in result.schedule] == [0]


def test_all_tasks_allocated_exactly_once():
    tasks = [Task(i, position=(float(i), 1.0), duration=2.0) for i in range(6)]
    result = SSIAllocator().allocate(robots(3), tasks)
    assert sorted(s.task_id for s in result.schedule) == list(range(6))
    assert not result.unallocated
    assert result.rounds == 6


def test_min_makespan_balances_load():
    # Four identical tasks at one point equidistant-ish: min-makespan should
    # spread 2/2 rather than piling onto one robot.
    tasks = [Task(i, position=(2.0, 0.0), duration=3.0) for i in range(4)]
    result = SSIAllocator("min-makespan").allocate(robots(2), tasks)
    counts = {}
    for s in result.schedule:
        counts[s.robot_id] = counts.get(s.robot_id, 0) + 1
    assert counts == {0: 2, 1: 2}


def test_sum_cost_prefers_cheapest_robot():
    # sum-cost ignores workload: the closer robot hoovers everything up.
    tasks = [Task(i, position=(0.5, 0.0), duration=1.0) for i in range(3)]
    result = SSIAllocator("sum-cost").allocate(robots(2), tasks)
    assert all(s.robot_id == 0 for s in result.schedule)


def test_playback_respects_dag():
    tasks = [
        Task(0, position=(1.0, 0.0), duration=2.0),
        Task(1, position=(4.0, 0.0), duration=1.0, prerequisites=frozenset({0})),
        Task(2, position=(2.0, 0.0), duration=1.0, prerequisites=frozenset({1})),
    ]
    result = SSIAllocator().allocate(robots(2), tasks)
    by_task = {s.task_id: s for s in result.schedule}
    assert by_task[1].start >= by_task[0].finish
    assert by_task[2].start >= by_task[1].finish
    assert result.makespan >= makespan_lower_bound(TaskDag(tasks), 2)


def test_cross_robot_dependency_no_deadlock():
    # Robot 0 will take tasks 0 and 2 (near it); robot 1 takes 1 (near it),
    # but 1 depends on 2 and 2 has no deps: playback must reorder robot 0's
    # execution (skip-to-runnable) without stalling.
    tasks = [
        Task(0, position=(0.2, 0.0), duration=5.0),
        Task(1, position=(4.0, 0.0), duration=1.0, prerequisites=frozenset({2})),
        Task(2, position=(0.4, 0.0), duration=1.0),
    ]
    result = SSIAllocator().allocate(robots(2), tasks)
    assert sorted(s.task_id for s in result.schedule) == [0, 1, 2]


def test_collaborative_rejected_and_dependents_blocked():
    tasks = [
        Task(0, duration=1.0, required_robots=2),
        Task(1, duration=1.0, prerequisites=frozenset({0})),
        Task(2, position=(1.0, 0.0), duration=1.0),
    ]
    result = SSIAllocator().allocate(robots(2), tasks)
    assert set(result.unallocated) == {0, 1}
    assert [s.task_id for s in result.schedule] == [2]


def test_settles_under_lossy_transport():
    rng = random.Random(3)
    loss = 0.3
    allocator = SSIAllocator(
        transport_factory=lambda ids: SimTransport(
            complete(ids), loss_prob=loss, seed=rng.randrange(2**31)
        ),
        quiescence_rounds=suggested_quiescence(complete(range(3)), 0, loss_prob=loss),
    )
    tasks = [Task(i, position=(float(i), 2.0), duration=1.0) for i in range(5)]
    result = allocator.allocate(robots(3), tasks)
    assert sorted(s.task_id for s in result.schedule) == list(range(5))
    assert result.total_messages > 0
    assert result.allocation_ticks > 0


def test_single_robot():
    tasks = [Task(i, position=(1.0, 1.0), duration=1.0) for i in range(3)]
    result = SSIAllocator().allocate(robots(1), tasks)
    assert len(result.schedule) == 3
