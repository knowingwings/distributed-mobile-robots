"""Whole-mission system simulator.

The phase-1 harness validates ONE auction round. This runs the full
phase-2 stack — N CoordinationParticipants over a lossy/delayed transport,
with heartbeats, leases, rotating-coordinator round framing, mock task
execution, and scripted robot failures — the same composition the ROS
nodes host, minus DDS.

Execution is mocked exactly as the ROS mock executor will behave: a
dispatched task finishes travel + duration seconds later; a killed robot
goes silent instantly (its work never completes; recovery must happen via
lease expiry, not cooperation).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Mapping, Optional

from ..coordination.messages import TaskInjected
from ..coordination.participant import CoordinationParticipant
from ..scheduling.benefits import BenefitModel, RobotState, _distance
from ..types import AgentId, Task, TaskId
from .transport import SimTransport, Topology, complete


@dataclass
class Execution:
    task_id: TaskId
    robot: AgentId
    started: float
    finish: float


@dataclass
class SystemResult:
    mission_time: Optional[float]  # None if the mission did not complete
    executions: list[Execution] = field(default_factory=list)
    events: list[tuple[float, str]] = field(default_factory=list)
    messages_sent: int = 0

    @property
    def completed_counts(self) -> dict[TaskId, int]:
        counts: dict[TaskId, int] = {}
        for e in self.executions:
            counts[e.task_id] = counts.get(e.task_id, 0) + 1
        return counts

    def completion_time(self, task_id: TaskId) -> Optional[float]:
        times = [e.finish for e in self.executions if e.task_id == task_id]
        return min(times) if times else None


class SystemSim:
    def __init__(
        self,
        robots: list[RobotState],
        tasks: list[Task],
        model: BenefitModel | None = None,
        *,
        topology: Topology | None = None,
        delay_ticks: int = 0,
        loss: float = 0.0,
        seed: int = 0,
        tick_period: float = 0.1,
        kill_at: Mapping[AgentId, float] | None = None,
        inject: list[tuple[float, Task]] | None = None,
        **participant_kwargs,
    ):
        self.tick_period = tick_period
        self.kill_at = dict(kill_at or {})
        self.inject = sorted(inject or [], key=lambda x: x[0])
        self.tasks = list(tasks)
        self.transport = SimTransport(
            topology or complete(r.id for r in robots),
            delay_ticks=delay_ticks,
            loss_prob=loss,
            seed=seed,
        )
        self.participants: dict[AgentId, CoordinationParticipant] = {}
        for robot in robots:
            p = CoordinationParticipant(
                robot, model or BenefitModel(), **participant_kwargs
            )
            p.load_mission(self.tasks)
            self.participants[robot.id] = p
        self.dead: set[AgentId] = set()
        self._executing: dict[AgentId, Execution] = {}

    def run(self, max_time: float = 600.0) -> SystemResult:
        result = SystemResult(mission_time=None)
        rng = random.Random(0)  # only for deterministic iteration jitter-free
        del rng
        ticks = int(max_time / self.tick_period)
        for i in range(ticks):
            now = i * self.tick_period

            for robot, kill_time in self.kill_at.items():
                if robot not in self.dead and now >= kill_time:
                    self.dead.add(robot)
                    self._executing.pop(robot, None)
                    result.events.append((now, f"robot {robot} killed"))

            while self.inject and now >= self.inject[0][0]:
                _, task = self.inject.pop(0)
                self.tasks.append(task)
                injected = TaskInjected(task, now)
                for robot, p in self.participants.items():
                    if robot not in self.dead:
                        p.handle(injected, now)
                result.events.append((now, f"task {task.id} injected"))

            for dest, message in self.transport.deliver_due(i):
                if dest in self.dead:
                    continue
                self.participants[dest].handle(message, now)

            for robot, p in self.participants.items():
                if robot in self.dead:
                    continue
                for msg in p.tick(now):
                    self.transport.send_payload(msg, robot, i)
                for task_id in p.pop_aborts():
                    self._executing.pop(robot, None)
                    result.events.append(
                        (now, f"robot {robot} aborted task {task_id} (lost lease)")
                    )
                for task_id in p.pop_dispatches():
                    task = next(t for t in self.tasks if t.id == task_id)
                    travel = (
                        _distance(p.me.position, task.position) / p.me.speed
                        if p.me.speed > 0
                        else 0.0
                    )
                    execution = Execution(
                        task_id, robot, started=now, finish=now + travel + task.duration
                    )
                    self._executing[robot] = execution
                    result.events.append(
                        (now, f"robot {robot} started task {task_id}")
                    )

            for robot, execution in list(self._executing.items()):
                if now >= execution.finish:
                    del self._executing[robot]
                    p = self.participants[robot]
                    for msg in p.task_finished(execution.task_id, now):
                        self.transport.send_payload(msg, robot, i)
                    result.executions.append(execution)
                    result.events.append(
                        (now, f"robot {robot} completed task {execution.task_id}")
                    )

            live = [
                p for r, p in self.participants.items() if r not in self.dead
            ]
            if live and all(p.mission_complete for p in live):
                result.mission_time = now
                break

        result.messages_sent = self.transport.messages_sent
        return result
