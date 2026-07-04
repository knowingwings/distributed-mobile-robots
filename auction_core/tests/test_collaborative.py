"""Collaborative tasks end-to-end: recruitment, sync execution, failures.

The scenario class both original implementations stubbed out. Uses the same
fast timings as test_coordination (dt = 0.5 s, eta = 3, lease 3 s).
"""

from auction_core.scheduling.benefits import RobotState
from auction_core.types import Task
from auction_core.validation.system_sim import SystemSim

FAST = dict(
    heartbeat_interval=0.5,
    eta=3,
    epsilon=0.05,
    quiescence_rounds=8,
    round_timeout=6.0,
)


def robots(n):
    spots = [(0.5, 0.5), (3.5, 0.5), (2.0, 3.5), (0.5, 3.5)]
    return [RobotState(id=i, position=spots[i % 4], speed=1.0) for i in range(n)]


def mixed_mission():
    return [
        Task(0, position=(1.0, 1.0), duration=3.0),
        Task(1, position=(2.0, 2.0), duration=4.0, required_robots=2),
        Task(2, position=(3.0, 1.0), duration=2.0),
        Task(3, position=(1.5, 3.0), duration=3.0, required_robots=2,
             prerequisites=frozenset({0})),
        Task(4, position=(3.0, 3.0), duration=2.0, prerequisites=frozenset({1})),
    ]


def assert_complete_once(result, tasks):
    assert result.mission_time is not None, (
        "mission incomplete; events:\n"
        + "\n".join(f"{t:7.1f} {e}" for t, e in result.events)
    )
    counts = result.completed_counts
    assert set(counts) == {t.id for t in tasks}
    assert not any(c > 1 for c in counts.values()), counts


def collab_executions(result, task_id):
    return {e.role: e for e in result.executions if e.task_id == task_id}


def test_mixed_mission_happy_path():
    tasks = mixed_mission()
    result = SystemSim(robots(3), tasks, seed=1, **FAST).run(max_time=900.0)
    assert_complete_once(result, tasks)
    for tid in (1, 3):
        roles = collab_executions(result, tid)
        assert {"leader", "follower"} <= set(roles), (tid, roles)
        # Synchronised: both sides ran the same window.
        assert roles["leader"].finish == roles["follower"].finish
        assert roles["leader"].partner == roles["follower"].robot


def test_two_robots_single_collab():
    tasks = [Task(0, position=(2.0, 2.0), duration=3.0, required_robots=2)]
    result = SystemSim(robots(2), tasks, seed=2, **FAST).run(max_time=900.0)
    assert_complete_once(result, tasks)


def test_collab_waits_for_second_robot():
    # Round 1 assigns the solo task AND the collaborative task to the two
    # idle robots — the collab leader must wait until the solo robot frees,
    # then recruit it.
    tasks = [
        Task(0, position=(1.0, 1.0), duration=5.0),
        Task(1, position=(2.0, 2.0), duration=3.0, required_robots=2),
    ]
    result = SystemSim(robots(2), tasks, seed=3, **FAST).run(max_time=900.0)
    assert_complete_once(result, tasks)
    roles = collab_executions(result, 1)
    # Collaboration could only start after the solo task released a robot.
    solo_finish = result.completion_time(0)
    assert roles["leader"].finish > solo_finish


def test_leader_killed_mid_collaboration():
    tasks = mixed_mission()
    # Kill robot 2 (usually a collab participant) mid-mission; whoever leads
    # at t=6 may die — mission must still complete exactly once per task.
    result = SystemSim(
        robots(3), tasks, seed=5, kill_at={2: 6.0}, **FAST
    ).run(max_time=900.0)
    assert_complete_once(result, tasks)
    assert all(e.finish <= 6.0 for e in result.executions if e.robot == 2)


def test_follower_killed_leader_rerecruits():
    # 4 robots so a replacement follower exists; kill one mid-mission.
    tasks = [
        Task(0, position=(2.0, 2.0), duration=6.0, required_robots=2),
        Task(1, position=(1.0, 1.0), duration=2.0),
        Task(2, position=(3.0, 1.0), duration=2.0),
    ]
    result = SystemSim(
        robots(4), tasks, seed=7, kill_at={3: 4.0}, **FAST
    ).run(max_time=900.0)
    assert_complete_once(result, tasks)


def test_mixed_mission_under_loss():
    tasks = mixed_mission()
    result = SystemSim(
        robots(3), tasks, loss=0.3, seed=11,
        **{**FAST, "quiescence_rounds": 40},
    ).run(max_time=1800.0)
    assert_complete_once(result, tasks)
