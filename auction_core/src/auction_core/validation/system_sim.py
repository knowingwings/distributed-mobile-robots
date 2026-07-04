"""Whole-mission system simulator.

Runs the full coordination stack — N CoordinationParticipants over a lossy/
delayed transport, with heartbeats, leases, rotating-coordinator rounds,
leader-follower collaborations, mock execution, and scripted failures — the
same composition the ROS nodes host, minus DDS.

Execution model: a solo task finishes travel + duration after dispatch. A
collaborative task starts when BOTH robots have arrived (max of the two
travel times) and occupies both for the duration; the leader completes it.
A killed robot goes silent instantly; whatever it was part of unravels via
leases and heartbeats, never via cooperation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional

from ..coordination.messages import TaskInjected
from ..coordination.participant import CoordinationParticipant, Dispatch
from ..scheduling.benefits import BenefitModel, RobotState, _distance
from ..types import AgentId, Task, TaskId
from .transport import SimTransport, Topology, complete


@dataclass
class Execution:
    task_id: TaskId
    robot: AgentId
    started: float
    finish: float
    role: str = "solo"
    partner: AgentId = -1


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
            if e.role != "follower":
                counts[e.task_id] = counts.get(e.task_id, 0) + 1
        return counts

    def completion_time(self, task_id: TaskId) -> Optional[float]:
        times = [
            e.finish for e in self.executions
            if e.task_id == task_id and e.role != "follower"
        ]
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
        # task -> role -> (robot, arrival time); a collaboration starts when
        # both roles have arrived.
        self._collab_wait: dict[TaskId, dict[str, tuple[AgentId, float]]] = {}

    # ------------------------------------------------------------------ run

    def run(self, max_time: float = 600.0) -> SystemResult:
        result = SystemResult(mission_time=None)
        ticks = int(max_time / self.tick_period)
        for i in range(ticks):
            now = i * self.tick_period
            self._kill_due(now, result)
            self._inject_due(now, result)

            for dest, message in self.transport.deliver_due(i):
                if dest not in self.dead:
                    self.participants[dest].handle(message, now)

            for robot, p in self.participants.items():
                if robot in self.dead:
                    continue
                for msg in p.tick(now):
                    self.transport.send_payload(msg, robot, i)
                for dispatch in p.pop_aborts():
                    self._cancel(robot, dispatch, now, result)
                for dispatch in p.pop_dispatches():
                    self._start(robot, dispatch, now, result)

            self._finish_due(now, result)

            live = [p for r, p in self.participants.items() if r not in self.dead]
            if live and all(p.mission_complete for p in live):
                result.mission_time = now
                break

        result.messages_sent = self.transport.messages_sent
        return result

    # --------------------------------------------------------------- helpers

    def _kill_due(self, now: float, result: SystemResult) -> None:
        for robot, kill_time in self.kill_at.items():
            if robot in self.dead or now < kill_time:
                continue
            self.dead.add(robot)
            self._executing.pop(robot, None)
            for waiting in self._collab_wait.values():
                for role in list(waiting):
                    if waiting[role][0] == robot:
                        del waiting[role]
            result.events.append((now, f"robot {robot} killed"))

    def _inject_due(self, now: float, result: SystemResult) -> None:
        while self.inject and now >= self.inject[0][0]:
            _, task = self.inject.pop(0)
            self.tasks.append(task)
            injected = TaskInjected(task, now)
            for robot, p in self.participants.items():
                if robot not in self.dead:
                    p.handle(injected, now)
            result.events.append((now, f"task {task.id} injected"))

    def _task(self, task_id: TaskId) -> Task:
        return next(t for t in self.tasks if t.id == task_id)

    def _travel(self, robot: AgentId, task: Task) -> float:
        p = self.participants[robot]
        if p.me.speed <= 0:
            return 0.0
        return _distance(p.me.position, task.position) / p.me.speed

    def _start(
        self, robot: AgentId, dispatch: Dispatch, now: float, result: SystemResult
    ) -> None:
        task = self._task(dispatch.task_id)
        arrival = now + self._travel(robot, task)
        if dispatch.role == "solo":
            self._executing[robot] = Execution(
                task.id, robot, started=now, finish=arrival + task.duration
            )
            result.events.append((now, f"robot {robot} started task {task.id}"))
            return

        waiting = self._collab_wait.setdefault(task.id, {})
        waiting[dispatch.role] = (robot, arrival)
        result.events.append(
            (now, f"robot {robot} joined task {task.id} as {dispatch.role}")
        )
        if {"leader", "follower"} <= set(waiting):
            leader, follower = waiting["leader"], waiting["follower"]
            start = max(leader[1], follower[1])
            finish = start + task.duration
            self._executing[leader[0]] = Execution(
                task.id, leader[0], now, finish, role="leader", partner=follower[0]
            )
            self._executing[follower[0]] = Execution(
                task.id, follower[0], now, finish, role="follower", partner=leader[0]
            )
            del self._collab_wait[task.id]
            result.events.append(
                (now, f"task {task.id} collaboration running "
                      f"({leader[0]} + {follower[0]})")
            )

    def _cancel(
        self, robot: AgentId, dispatch: Dispatch, now: float, result: SystemResult
    ) -> None:
        entry = self._executing.get(robot)
        if entry is not None and entry.task_id == dispatch.task_id:
            del self._executing[robot]
        waiting = self._collab_wait.get(dispatch.task_id)
        if waiting is not None:
            for role in list(waiting):
                if waiting[role][0] == robot:
                    del waiting[role]
            if not waiting:
                del self._collab_wait[dispatch.task_id]
        result.events.append(
            (now, f"robot {robot} aborted task {dispatch.task_id} "
                  f"({dispatch.role}, lost claim)")
        )

    def _finish_due(self, now: float, result: SystemResult) -> None:
        for robot, entry in list(self._executing.items()):
            if now < entry.finish or robot not in self._executing:
                continue
            del self._executing[robot]
            p = self.participants[robot]
            if entry.role == "follower":
                p.collaboration_finished(entry.task_id)
            else:
                # solo or leader: completes the task and broadcasts.
                tick_index = int(now / self.tick_period)
                for msg in p.task_finished(entry.task_id, now):
                    self.transport.send_payload(msg, robot, tick_index)
            result.executions.append(entry)
            result.events.append(
                (now, f"robot {robot} completed task {entry.task_id} ({entry.role})")
            )
