"""Scheduling layer + RepeatedRoundsAllocator behaviour."""

import pytest

from auction_core.types import RoundConfig, Task
from auction_core.allocator.repeated_rounds import RepeatedRoundsAllocator
from auction_core.scheduling.benefits import BenefitModel, RobotState
from auction_core.scheduling.cpm import critical_path_length, makespan_lower_bound
from auction_core.scheduling.dag import DependencyCycle, TaskDag
from auction_core.validation.harness import run_round
from auction_core.validation.transport import SimTransport, complete

CFG = RoundConfig(epsilon=0.01, quiescence_rounds=2)


def sim_round_runner(benefits, config):
    """Fresh ideal complete-topology network per round."""
    return run_round(benefits, SimTransport(complete(benefits.keys())), config)


def allocator(model=None):
    return RepeatedRoundsAllocator(model or BenefitModel(), sim_round_runner, CFG)


def robots(n):
    return [RobotState(id=i, position=(float(i), 0.0)) for i in range(n)]


# ------------------------------------------------------------------ scheduling


def test_dag_cycle_raises():
    with pytest.raises(DependencyCycle):
        TaskDag(
            [
                Task(0, prerequisites=frozenset({1})),
                Task(1, prerequisites=frozenset({0})),
            ]
        )


def test_dag_availability():
    dag = TaskDag(
        [Task(0), Task(1, prerequisites=frozenset({0})), Task(2)]
    )
    assert dag.available(set()) == {0, 2}
    assert dag.available({0}) == {0, 1, 2} - {0}


def test_critical_path_and_lower_bound():
    dag = TaskDag(
        [
            Task(0, duration=2.0),
            Task(1, duration=3.0, prerequisites=frozenset({0})),
            Task(2, duration=1.0),
        ]
    )
    assert critical_path_length(dag) == 5.0
    # max(load 6/2=3, longest 3, critical path 5) = 5
    assert makespan_lower_bound(dag, num_robots=2) == 5.0


# ------------------------------------------------------------------- allocator


def test_chain_respects_precedence():
    tasks = [
        Task(0, duration=1.0),
        Task(1, duration=1.0, prerequisites=frozenset({0})),
        Task(2, duration=1.0, prerequisites=frozenset({1})),
    ]
    result = allocator().allocate(robots(2), tasks)
    assert not result.unallocated
    by_task = {s.task_id: s for s in result.schedule}
    assert by_task[1].start >= by_task[0].finish
    assert by_task[2].start >= by_task[1].finish
    assert result.makespan >= critical_path_length(TaskDag(tasks))


def test_independent_tasks_run_in_parallel():
    tasks = [Task(i, duration=2.0) for i in range(4)]
    result = allocator().allocate(robots(2), tasks)
    assert not result.unallocated
    assert len(result.schedule) == 4
    # Two robots working in parallel: strictly faster than serial execution.
    assert result.makespan < sum(t.duration for t in tasks)
    assert result.makespan >= makespan_lower_bound(TaskDag(tasks), 2)


def test_more_robots_than_tasks_pads_idle():
    tasks = [Task(0, duration=1.0, position=(0.0, 0.0))]
    result = allocator().allocate(robots(3), tasks)
    assert len(result.schedule) == 1
    assert not result.unallocated
    assert result.rounds == 1


def test_collaborative_rejected_and_dependents_blocked():
    tasks = [
        Task(0, duration=1.0, required_robots=2),
        Task(1, duration=1.0, prerequisites=frozenset({0})),
        Task(2, duration=1.0),
    ]
    result = allocator().allocate(robots(2), tasks)
    assert set(result.unallocated) == {0, 1}
    assert "collaborative" in result.unallocated[0]
    assert "blocked" in result.unallocated[1]
    assert [s.task_id for s in result.schedule] == [2]


def test_workload_balances_across_identical_robots():
    # Six identical tasks at one spot, two identical robots: the workload
    # term must spread the work 3/3 rather than letting one robot hoard.
    tasks = [Task(i, duration=1.0, position=(5.0, 5.0)) for i in range(6)]
    two = [RobotState(id=0, position=(5.0, 5.0)), RobotState(id=1, position=(5.0, 5.0))]
    result = allocator().allocate(two, tasks)
    counts = {0: 0, 1: 0}
    for s in result.schedule:
        counts[s.robot_id] += 1
    assert counts == {0: 3, 1: 3}
