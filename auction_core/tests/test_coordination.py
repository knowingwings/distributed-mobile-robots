"""End-to-end coordination: rounds, failover, and lease-driven recovery.

These exercise the full phase-2 stack in simulation — the same participant
code the ROS nodes host. Timings use dt = 0.5 s heartbeats, eta = 3
(timeout 1.5 s), lease duration 3 s unless stated.
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


def demo_robots():
    return [
        RobotState(id=0, position=(0.5, 0.5), speed=1.0),
        RobotState(id=1, position=(3.5, 0.5), speed=1.0),
        RobotState(id=2, position=(2.0, 3.5), speed=1.0),
    ]


def demo_tasks():
    return [
        Task(0, position=(1.0, 1.0), duration=4.0),
        Task(1, position=(3.0, 1.0), duration=3.0),
        Task(2, position=(2.0, 2.0), duration=5.0),
        Task(3, position=(0.5, 3.0), duration=3.5, prerequisites=frozenset({0})),
        Task(4, position=(3.5, 3.0), duration=4.0, prerequisites=frozenset({1})),
        Task(5, position=(2.0, 0.5), duration=3.0, prerequisites=frozenset({1, 2})),
        Task(6, position=(1.5, 3.5), duration=3.0, prerequisites=frozenset({3})),
        Task(7, position=(3.0, 3.5), duration=5.0, prerequisites=frozenset({4, 5})),
    ]


def assert_valid_mission(result, tasks):
    assert result.mission_time is not None, (
        "mission did not complete; events:\n"
        + "\n".join(f"{t:7.1f} {e}" for t, e in result.events)
    )
    counts = result.completed_counts
    assert set(counts) == {t.id for t in tasks}
    dup = {t: c for t, c in counts.items() if c > 1}
    assert not dup, f"tasks executed more than once: {dup}"
    by_id = {t.id: t for t in tasks}
    for task in tasks:
        for prereq in by_id[task.id].prerequisites:
            assert result.completion_time(prereq) <= result.completion_time(task.id)


def test_happy_path_mission_completes():
    result = SystemSim(demo_robots(), demo_tasks(), seed=1, **FAST).run()
    assert_valid_mission(result, demo_tasks())


def test_mission_under_loss_and_delay():
    result = SystemSim(
        demo_robots(),
        demo_tasks(),
        loss=0.3,
        delay_ticks=2,
        seed=7,
        **{**FAST, "quiescence_rounds": 40},  # sized for 30% loss
    ).run(max_time=900.0)
    assert_valid_mission(result, demo_tasks())


def test_coordinator_killed_mid_mission():
    # Robot 0 is the initial coordinator (lowest id). Killing it forces
    # failover to robot 1 AND recovery of whatever robot 0 held.
    result = SystemSim(
        demo_robots(), demo_tasks(), seed=3, kill_at={0: 5.0}, **FAST
    ).run(max_time=900.0)
    assert result.mission_time is not None, (
        "mission did not survive coordinator death; events:\n"
        + "\n".join(f"{t:7.1f} {e}" for t, e in result.events)
    )
    counts = result.completed_counts
    assert set(counts) == {t.id for t in demo_tasks()}
    assert not any(c > 1 for c in counts.values())
    # Nothing completes under robot 0's name after its death.
    assert all(e.finish <= 5.0 for e in result.executions if e.robot == 0)


def test_worker_killed_tasks_recovered():
    result = SystemSim(
        demo_robots(), demo_tasks(), seed=5, kill_at={2: 4.0}, **FAST
    ).run(max_time=900.0)
    assert_valid_mission(result, demo_tasks())
    # Everything robot 2 was executing at death was re-run by survivors.
    assert all(e.robot != 2 or e.finish <= 4.0 for e in result.executions)


def test_recovery_latency_bounded():
    # A task orphaned by robot death must restart within detection window
    # (eta * dt = 1.5 s) + lease duration (3 s) + round timeout slack.
    result = SystemSim(
        demo_robots(), demo_tasks(), seed=5, kill_at={2: 4.0}, **FAST
    ).run(max_time=900.0)
    kill_time = 4.0
    restarted = [
        t
        for t, e in result.events
        if t > kill_time and e.startswith("robot") and "started task" in e
    ]
    assert restarted, "no reallocation happened after the kill"
    # First post-kill dispatch within detection + lease + one round frame.
    assert min(restarted) - kill_time <= 1.5 + 3.0 + FAST["round_timeout"]


def test_runtime_task_injection():
    extra = Task(99, position=(1.0, 3.0), duration=2.0)
    tasks = demo_tasks()
    result = SystemSim(
        demo_robots(), tasks, seed=11, inject=[(6.0, extra)], **FAST
    ).run(max_time=900.0)
    assert_valid_mission(result, tasks + [extra])
    assert result.completion_time(99) is not None


def test_single_robot_completes_alone():
    result = SystemSim(
        [RobotState(id=0, position=(0.0, 0.0), speed=1.0)],
        demo_tasks(),
        seed=2,
        **FAST,
    ).run(max_time=900.0)
    assert_valid_mission(result, demo_tasks())
