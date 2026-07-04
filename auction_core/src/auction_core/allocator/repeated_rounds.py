"""Repeated frozen-beta rounds allocator.

Event-driven composition of provable auction rounds: whenever there are idle
robots AND available tasks (all prerequisites complete), freeze the benefit
matrix, run one distributed auction round, dispatch the winners, then advance
simulated execution time to the next task completion and repeat.

Guarantee inventory (honest version):
  - within a round: total-benefit within n*epsilon of optimal for that
    round's frozen matrix (engine property, tested against Hungarian);
  - across rounds: makespan quality is a product of the BenefitModel
    (workload/distance terms), REPORTED against the CPM lower bound —
    no optimality claim is made or implied (maths-evaluation.md section 2.3).

m >= n inside a round is maintained by padding with idle sentinel tasks
whose benefit sits strictly below every real benefit, so surplus robots
absorb the idle slots and real tasks are never declined.
"""

from __future__ import annotations

from dataclasses import replace

from ..types import AgentId, RoundConfig, Task, TaskId
from ..scheduling.benefits import BenefitModel, RobotState, _distance
from ..scheduling.dag import TaskDag
from .base import AllocationResult, Allocator, RoundRunner, ScheduledTask

_IDLE_BASE = -1  # sentinel ids count down from -1; real task ids are >= 0


class RepeatedRoundsAllocator(Allocator):
    def __init__(
        self,
        benefit_model: BenefitModel,
        round_runner: RoundRunner,
        round_config: RoundConfig,
    ):
        self._model = benefit_model
        self._run_round = round_runner
        self._config = round_config

    def allocate(
        self, robots: list[RobotState], tasks: list[Task]
    ) -> AllocationResult:
        robots = [replace(r) for r in robots]  # simulate on private copies
        unallocated: dict[TaskId, str] = {}
        supported: list[Task] = []
        for task in tasks:
            if task.collaborative:
                unallocated[task.id] = "collaborative tasks unsupported in v1"
            else:
                supported.append(task)
        for task in tasks:
            if task.collaborative:
                dag_all = TaskDag(tasks)
                for blocked in dag_all.dependents(task.id):
                    unallocated.setdefault(
                        blocked, f"blocked by unallocatable prerequisite {task.id}"
                    )
        schedulable = [t for t in supported if t.id not in unallocated]
        dag = TaskDag(schedulable) if schedulable else None

        schedule: list[ScheduledTask] = []
        completed: set[TaskId] = set()
        running: dict[AgentId, tuple[TaskId, float]] = {}  # robot -> (task, finish)
        robot_by_id = {r.id: r for r in robots}
        now = 0.0
        rounds = 0
        messages = 0

        while dag is not None and len(completed) < len(schedulable):
            in_progress = {task for task, _ in running.values()}
            available = sorted(dag.available(completed) - in_progress)
            idle = [r for r in robots if r.id not in running]

            if available and idle:
                benefits = self._round_benefits(idle, [dag.tasks[t] for t in available])
                result = self._run_round(benefits, self._config)
                rounds += 1
                messages += result.messages_sent
                for agent_id, task_id in result.assignment.items():
                    if task_id is None or task_id < 0:
                        continue  # idle sentinel: robot sits this round out
                    robot = robot_by_id[agent_id]
                    task = dag.tasks[task_id]
                    travel = (
                        _distance(robot.position, task.position) / robot.speed
                        if robot.speed > 0
                        else 0.0
                    )
                    finish = now + travel + task.duration
                    running[agent_id] = (task_id, finish)
                    schedule.append(
                        ScheduledTask(task_id, agent_id, start=now, finish=finish)
                    )
                    robot.workload += task.duration
                if any(t >= 0 for t, _ in running.values()):
                    continue  # someone is working; fall through to time advance

            if not running:
                # No progress possible: idle robots but nothing available
                # (or no robots). With a validated DAG this only happens if
                # everything left is blocked — report and stop, don't spin.
                for tid in sorted(set(dag.tasks) - completed):
                    unallocated.setdefault(tid, "no progress possible")
                break

            # Advance to the next completion.
            finishing_robot = min(running, key=lambda r: running[r][1])
            task_id, finish = running.pop(finishing_robot)
            now = finish
            completed.add(task_id)
            robot = robot_by_id[finishing_robot]
            robot.position = dag.tasks[task_id].position or robot.position

        makespan = max((s.finish for s in schedule), default=0.0)
        return AllocationResult(
            schedule=schedule,
            makespan=makespan,
            rounds=rounds,
            total_messages=messages,
            unallocated=unallocated,
        )

    def _round_benefits(self, idle: list[RobotState], available: list[Task]):
        benefits = self._model.matrix(idle, available)
        deficit = len(idle) - len(available)
        if deficit > 0:
            # Pad m up to n with idle sentinels priced strictly below every
            # real option so they only absorb surplus robots.
            for robot_benefits in benefits.values():
                floor = min(robot_benefits.values()) - 1.0
                for k in range(deficit):
                    robot_benefits[_IDLE_BASE - k] = floor
        return benefits
