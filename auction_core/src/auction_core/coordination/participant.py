"""CoordinationParticipant: the phase-2 distributed state machine.

Every robot runs exactly one. It composes the phase-1 pieces without
changing them: HeartbeatMonitor + TaskLeases (liveness), TaskDag +
BenefitModel (scheduling), AuctionAgent (allocation) — and adds the round
orchestration that phase 1's centralised allocator faked.

Roles:
- Everyone: heartbeat + anti-entropy of completions, lease replica upkeep,
  price-gossip relay for rounds it is not bidding in (so multi-hop
  topologies converge even when intermediate robots are busy).
- Coordinator (= minimum alive id, a predicate re-evaluated every tick, not
  an elected role): frames rounds — available tasks x idle robots — and
  announces them. Coordinator death simply moves the predicate to the next
  id after the heartbeat timeout; a stale coordinator's announcements lose
  by the precedence rule (higher round_id wins, ties to lower coordinator).
- Round participant: hosts a fresh AuctionAgent per announcement; on
  quiescence with a real task won, grants itself the lease, starts renewing
  at heartbeat cadence, and exposes the task to the host for execution.

Recovery is emergent: a dead robot stops renewing -> its leases expire on
every replica -> the tasks are available again -> the (possibly new)
coordinator frames an ordinary round for them.

Sans-I/O contract as everywhere: `handle(msg, now)` / `tick(now)` ->
outgoing messages; the host (system simulator or ROS node) owns time,
transport, and task execution.
"""

from __future__ import annotations

from typing import Optional

from ..allocator.repeated_rounds import _IDLE_BASE
from ..auction.engine import AuctionAgent
from ..auction.prices import PriceTable
from ..liveness.heartbeat import HeartbeatMonitor
from ..liveness.lease import TaskLeases
from ..scheduling.benefits import BenefitModel, RobotState
from ..scheduling.dag import TaskDag
from ..types import AgentId, PriceTableMessage, RoundConfig, Task, TaskId
from .messages import (
    CoordinationMessage,
    Heartbeat,
    LeaseRenewal,
    RoundAnnouncement,
    RoundGossip,
    TaskCompleted,
    TaskInjected,
)


class CoordinationParticipant:
    def __init__(
        self,
        me: RobotState,
        model: BenefitModel,
        *,
        heartbeat_interval: float = 1.0,
        eta: int = 3,
        lease_duration: Optional[float] = None,
        epsilon: float = 0.05,
        quiescence_rounds: int = 8,
        round_timeout: float = 30.0,
    ):
        self.me = me
        self.model = model
        self.heartbeat_interval = heartbeat_interval
        self.monitor = HeartbeatMonitor(heartbeat_interval, eta)
        # A lease must outlive the heartbeat timeout: a robot may not be
        # stripped of work faster than it can be declared dead.
        self.leases = TaskLeases(lease_duration or 2 * eta * heartbeat_interval)
        self.epsilon = epsilon
        self.quiescence_rounds = quiescence_rounds
        self.round_timeout = round_timeout

        self.tasks: dict[TaskId, Task] = {}
        self.completed: set[TaskId] = set()
        self.unsupported: dict[TaskId, str] = {}
        self.executing: Optional[TaskId] = None

        self._idle_flags: dict[AgentId, tuple[float, bool]] = {}
        self._announcement: Optional[RoundAnnouncement] = None
        self._round_opened_at: float = 0.0
        self._agent: Optional[AuctionAgent] = None
        self._relay: Optional[PriceTable] = None
        self._relay_dirty = False
        self._max_round_seen = 0
        self._last_heartbeat = float("-inf")
        self._dispatches: list[TaskId] = []
        self._aborts: list[TaskId] = []

    # ------------------------------------------------------------ mission API

    def load_mission(self, tasks: list[Task]) -> None:
        for task in tasks:
            self._add_task(task)

    def _add_task(self, task: Task) -> None:
        if task.collaborative:
            self.unsupported[task.id] = "collaborative tasks unsupported in v1"
            return
        self.tasks[task.id] = task

    @property
    def mission_complete(self) -> bool:
        return bool(self.tasks) and set(self.tasks) <= self.completed

    def pop_dispatches(self) -> list[TaskId]:
        out, self._dispatches = self._dispatches, []
        return out

    def pop_aborts(self) -> list[TaskId]:
        out, self._aborts = self._aborts, []
        return out

    def task_finished(self, task_id: TaskId, now: float) -> list[CoordinationMessage]:
        """Host callback: execution of `task_id` finished successfully."""
        assert self.executing == task_id
        self.executing = None
        self.completed.add(task_id)
        self.leases.release(task_id, self.me.id)
        self.me.workload += self.tasks[task_id].duration
        self.me.position = self.tasks[task_id].position or self.me.position
        return [TaskCompleted(task_id, self.me.id, now)]

    # -------------------------------------------------------------- messaging

    def handle(self, msg: CoordinationMessage, now: float) -> list[CoordinationMessage]:
        if isinstance(msg, Heartbeat):
            self._on_heartbeat(msg, now)
        elif isinstance(msg, RoundAnnouncement):
            self._on_announcement(msg, now)
        elif isinstance(msg, RoundGossip):
            self._on_gossip(msg)
        elif isinstance(msg, LeaseRenewal):
            self._on_lease_renewal(msg, now)
        elif isinstance(msg, TaskCompleted):
            self._on_completed(msg)
        elif isinstance(msg, TaskInjected):
            self._add_task(msg.task)
        return []

    def _on_heartbeat(self, msg: Heartbeat, now: float) -> None:
        if msg.sender == self.me.id:
            return
        # Liveness is receipt-based (robust to clock skew); the idle flag is
        # ordered by the sender's stamp (robust to reordered delivery).
        self.monitor.record(msg.sender, now)
        prev = self._idle_flags.get(msg.sender)
        if prev is None or msg.stamp > prev[0]:
            self._idle_flags[msg.sender] = (msg.stamp, msg.idle)

    def _on_announcement(self, msg: RoundAnnouncement, now: float) -> None:
        if self._announcement is not None and not self._announcement.precedes(msg):
            return
        self._announcement = msg
        self._max_round_seen = max(self._max_round_seen, msg.round_id)
        # Adoption time approximates the round opening; without this, a
        # coordinator that fails over onto a never-settling round would have
        # no timeout and could never frame the recovery round.
        self._round_opened_at = now
        round_task_ids = list(msg.task_ids) + [
            _IDLE_BASE - k for k in range(msg.idle_slots)
        ]
        if self.me.id in msg.participants:
            self._agent = AuctionAgent(
                self.me.id,
                self._benefit_row(msg.task_ids, msg.idle_slots),
                RoundConfig(msg.epsilon, msg.quiescence_rounds),
            )
            self._relay = None
        else:
            self._agent = None
            self._relay = PriceTable(round_task_ids)
            self._relay_dirty = False

    def _benefit_row(
        self, task_ids: tuple[TaskId, ...], idle_slots: int
    ) -> dict[TaskId, float]:
        row = {
            tid: (
                self.model.benefit(self.me, self.tasks[tid])
                if tid in self.tasks
                else 0.0  # not yet learned via anti-entropy: neutral bid
            )
            for tid in task_ids
        }
        if idle_slots:
            floor = min(row.values()) - 1.0
            for k in range(idle_slots):
                row[_IDLE_BASE - k] = floor
        return row

    def _on_gossip(self, msg: RoundGossip) -> None:
        if self._announcement is None or msg.round_id != self._announcement.round_id:
            return
        if self._agent is not None:
            self._agent.handle_message(msg.inner)
        elif self._relay is not None:
            if self._relay.merge(msg.inner.entries):
                self._relay_dirty = True

    def _on_lease_renewal(self, msg: LeaseRenewal, now: float) -> None:
        holder = self.leases.holder(msg.task_id)
        if holder is None:
            self.leases.grant(msg.task_id, msg.holder, now)
        elif holder == msg.holder:
            self.leases.renew(msg.task_id, msg.holder, now)
        elif msg.holder < holder:
            # Deterministic conflict resolution: if two robots ever both
            # believe they won a task (quiescence window undersized), every
            # replica converges on the lower id and the loser aborts via the
            # executing-holder check in tick().
            self.leases.release(msg.task_id, holder)
            self.leases.grant(msg.task_id, msg.holder, now)

    def _on_completed(self, msg: TaskCompleted) -> None:
        self.completed.add(msg.task_id)
        holder = self.leases.holder(msg.task_id)
        if holder is not None:
            self.leases.release(msg.task_id, holder)

    # ------------------------------------------------------------------- tick

    def tick(self, now: float) -> list[CoordinationMessage]:
        out: list[CoordinationMessage] = []
        self.monitor.record(self.me.id, now)
        self.monitor.sweep(now)
        self.leases.sweep(now)

        # If someone else now holds the lease on what we're executing, our
        # claim was reallocated (we were presumed dead) — stop work.
        if self.executing is not None:
            holder = self.leases.holder(self.executing)
            if holder is not None and holder != self.me.id:
                self._aborts.append(self.executing)
                self.executing = None

        out.extend(self._tick_round(now))
        out.extend(self._tick_heartbeat(now))
        out.extend(self._tick_coordinator(now))
        return out

    def _tick_round(self, now: float) -> list[CoordinationMessage]:
        assert self._announcement is not None or self._agent is None
        out: list[CoordinationMessage] = []
        if self._agent is not None:
            round_id = self._announcement.round_id
            for msg in self._agent.tick():
                out.append(RoundGossip(round_id, msg))
            if self._agent.terminated:
                won = self._agent.assignment
                self._agent = None
                if won is not None and won >= 0 and won not in self.completed:
                    self.leases.grant(won, self.me.id, now)
                    self.executing = won
                    self._dispatches.append(won)
                    out.append(LeaseRenewal(won, self.me.id, now))
        elif self._relay is not None and self._relay_dirty:
            # Passive relay: forward merged prices so multi-hop rounds
            # converge through busy robots. Only echoes new information.
            self._relay_dirty = False
            out.append(
                RoundGossip(
                    self._announcement.round_id,
                    PriceTableMessage(self.me.id, self._relay.snapshot()),
                )
            )
        return out

    def _tick_heartbeat(self, now: float) -> list[CoordinationMessage]:
        if now - self._last_heartbeat < self.heartbeat_interval:
            return []
        self._last_heartbeat = now
        out: list[CoordinationMessage] = [Heartbeat(self.me.id, now, self._is_idle)]
        # Rebroadcast our own framing while it is the latest known round, so
        # participants that missed the (lossy) announcement still join.
        if (
            self._announcement is not None
            and self._announcement.coordinator == self.me.id
        ):
            out.append(self._announcement)
        # Anti-entropy piggybacked at heartbeat cadence: keep renewing our
        # lease, and re-announce completions we know about (small missions;
        # a digest scheme replaces this at scale).
        if self.executing is not None:
            self.leases.renew(self.executing, self.me.id, now)
            out.append(LeaseRenewal(self.executing, self.me.id, now))
        for task_id in self.completed:
            out.append(TaskCompleted(task_id, self.me.id, now))
        return out

    @property
    def _is_idle(self) -> bool:
        return self.executing is None and self._agent is None

    # ------------------------------------------------------------ coordinator

    def _alive_ids(self, now: float) -> set[AgentId]:
        return self.monitor.alive(now) | {self.me.id}

    def is_coordinator(self, now: float) -> bool:
        return self.me.id == min(self._alive_ids(now))

    def _tick_coordinator(self, now: float) -> list[CoordinationMessage]:
        if not self.is_coordinator(now):
            return []
        if self._announcement is not None and self._round_open(now):
            return []

        available = sorted(self._available_tasks())
        idle = sorted(self._idle_robots(now))
        if not available or not idle:
            return []

        announcement = RoundAnnouncement(
            round_id=self._max_round_seen + 1,
            coordinator=self.me.id,
            task_ids=tuple(available),
            participants=tuple(idle),
            idle_slots=max(0, len(idle) - len(available)),
            epsilon=self.epsilon,
            quiescence_rounds=self.quiescence_rounds,
        )
        self._on_announcement(announcement, now)  # adopt our own framing
        return [announcement]

    def _round_open(self, now: float) -> bool:
        """A framed round stays open until every announced real task is
        leased or completed, or the timeout expires (covers lost winners)."""
        assert self._announcement is not None
        if self._agent is not None:
            return True  # we are still bidding in it ourselves
        if self._round_opened_at is not None:
            if now - self._round_opened_at > self.round_timeout:
                return False
        settled = all(
            tid in self.completed or self.leases.holder(tid) is not None
            for tid in self._announcement.task_ids
        )
        return not settled

    def _available_tasks(self) -> set[TaskId]:
        if not self.tasks:
            return set()
        dag = TaskDag(self.tasks.values())
        return {
            tid
            for tid in dag.available(self.completed & set(self.tasks))
            if self.leases.holder(tid) is None
        }

    def _idle_robots(self, now: float) -> set[AgentId]:
        idle = {
            robot
            for robot, (_, is_idle) in self._idle_flags.items()
            if is_idle and self.monitor.is_alive(robot, now)
        }
        if self._is_idle:
            idle.add(self.me.id)
        return idle
