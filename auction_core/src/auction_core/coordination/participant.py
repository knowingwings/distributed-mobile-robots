"""CoordinationParticipant: the distributed state machine every robot runs.

Composes the validated pieces without changing them: HeartbeatMonitor +
TaskLeases (liveness), TaskDag + BenefitModel (scheduling), AuctionAgent
(allocation) — plus the round orchestration phase 1's centralised allocator
faked, and (phase 3) collaborative tasks via leader-follower recruitment.

Roles:
- Everyone: heartbeat (with position + idle flag) and completion
  anti-entropy, lease replica upkeep, passive price-gossip relaying for
  auctions it is not bidding in.
- Coordinator (= minimum alive id, a predicate re-evaluated every tick):
  frames rounds — available tasks x idle robots — and announces them.
  Collaborative tasks are framed only when at least two robots are idle.
- Round participant: hosts a fresh AuctionAgent per announcement. Bids on
  collaborative tasks use the joint estimate (own + best follower from
  gossiped positions).
- Leader (won a collaborative task): holds the lease, recruits a follower
  through a single-item auction among idle robots (fresh seq per attempt),
  pairs via the lease's `follower` field, executes synchronised with the
  follower. Follower death -> abort + re-recruit. No follower materialises
  before `round_timeout` -> release the lease so the task re-enters framing.
- Follower (won a recruitment): busy with partner=leader, no lease of its
  own; aborts if the task's lease stops naming its leader (leader death).

Recovery stays emergent: leases expire -> tasks re-enter ordinary rounds.

Sans-I/O contract as everywhere: `handle(msg, now)` / `tick(now)` ->
outgoing messages; the host (system simulator or ROS node) owns time,
transport, and execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from ..allocator.repeated_rounds import _IDLE_BASE
from ..auction.engine import AuctionAgent
from ..auction.prices import PriceTable
from ..liveness.heartbeat import HeartbeatMonitor
from ..liveness.lease import TaskLeases
from ..scheduling.benefits import BenefitModel, RobotState
from ..scheduling.dag import TaskDag
from ..types import NO_BIDDER, AgentId, PriceTableMessage, RoundConfig, Task, TaskId
from .messages import (
    NO_FOLLOWER,
    CoordinationMessage,
    Heartbeat,
    LeaseRenewal,
    RecruitAnnouncement,
    RoundAnnouncement,
    RoundGossip,
    TaskCompleted,
    TaskInjected,
    round_scope,
)

Role = Literal["solo", "leader", "follower"]


@dataclass(frozen=True)
class Dispatch:
    """What the host should execute: a task, in a role, with a partner
    (NO_FOLLOWER for solo)."""

    task_id: TaskId
    role: Role
    partner: AgentId = NO_FOLLOWER


@dataclass
class _Recruiting:
    """Leader-side state while looking for / confirming a follower."""

    task_id: TaskId
    seq: int
    started_at: float
    announced_at: float
    table: Optional[PriceTable] = None  # our view of the recruitment auction
    quiet: int = 0


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
        self.leases = TaskLeases(lease_duration or 2 * eta * heartbeat_interval)
        self.epsilon = epsilon
        self.quiescence_rounds = quiescence_rounds
        self.round_timeout = round_timeout

        self.tasks: dict[TaskId, Task] = {}
        self.completed: dict[TaskId, AgentId] = {}  # task -> original completer
        self.unsupported: dict[TaskId, str] = {}
        self.dispatch: Optional[Dispatch] = None  # what we are executing

        self._peer_state: dict[AgentId, tuple[float, bool, tuple[float, ...]]] = {}
        self._announcement: Optional[RoundAnnouncement] = None
        self._round_opened_at: float = 0.0
        self._agent: Optional[AuctionAgent] = None
        self._agent_scope: Optional[str] = None
        self._relay: Optional[PriceTable] = None
        self._relay_scope: Optional[str] = None
        self._relay_dirty = False
        self._recruiting: Optional[_Recruiting] = None
        self._recruit_seq: int = 0
        self._pending_follow: Optional[tuple[TaskId, AgentId, float]] = None
        self._latest_recruit: dict[TaskId, RecruitAnnouncement] = {}
        self._max_round_seen = 0
        self._last_heartbeat = float("-inf")
        self._dispatches: list[Dispatch] = []
        self._aborts: list[Dispatch] = []

    # ------------------------------------------------------------ mission API

    def load_mission(self, tasks: list[Task]) -> None:
        for task in tasks:
            self._add_task(task)

    def _add_task(self, task: Task) -> None:
        if task.required_robots > 2:
            self.unsupported[task.id] = "tasks needing >2 robots unsupported"
            return
        self.tasks[task.id] = task

    @property
    def executing(self) -> Optional[TaskId]:
        return self.dispatch.task_id if self.dispatch else None

    @property
    def mission_complete(self) -> bool:
        return bool(self.tasks) and set(self.tasks) <= set(self.completed)

    def pop_dispatches(self) -> list[Dispatch]:
        out, self._dispatches = self._dispatches, []
        return out

    def pop_aborts(self) -> list[Dispatch]:
        out, self._aborts = self._aborts, []
        return out

    def task_finished(self, task_id: TaskId, now: float) -> list[CoordinationMessage]:
        """Host callback: execution finished (solo, or the leader of a
        completed collaboration)."""
        assert self.dispatch is not None and self.dispatch.task_id == task_id
        assert self.dispatch.role in ("solo", "leader")
        self.dispatch = None
        self.completed[task_id] = self.me.id
        self.leases.release(task_id, self.me.id)
        self.me.workload += self.tasks[task_id].duration
        self.me.position = self.tasks[task_id].position or self.me.position
        return [TaskCompleted(task_id, self.me.id, now)]

    def collaboration_finished(self, task_id: TaskId) -> None:
        """Host callback for the FOLLOWER side: the joint task is done (the
        leader broadcasts the completion). Idempotent; also triggered
        internally when the leader's TaskCompleted arrives first."""
        if (
            self.dispatch is not None
            and self.dispatch.task_id == task_id
            and self.dispatch.role == "follower"
        ):
            self.me.workload += self.tasks[task_id].duration
            self.me.position = self.tasks[task_id].position or self.me.position
            self.dispatch = None

    # -------------------------------------------------------------- messaging

    def handle(self, msg: CoordinationMessage, now: float) -> list[CoordinationMessage]:
        if isinstance(msg, Heartbeat):
            self._on_heartbeat(msg, now)
        elif isinstance(msg, RoundAnnouncement):
            self._on_announcement(msg, now)
        elif isinstance(msg, RecruitAnnouncement):
            self._on_recruit(msg, now)
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
        self.monitor.record(msg.sender, now)
        prev = self._peer_state.get(msg.sender)
        if prev is None or msg.stamp > prev[0]:
            self._peer_state[msg.sender] = (msg.stamp, msg.idle, msg.position)

    def _on_announcement(self, msg: RoundAnnouncement, now: float) -> None:
        if self._announcement is not None and not self._announcement.precedes(msg):
            return
        self._announcement = msg
        self._max_round_seen = max(self._max_round_seen, msg.round_id)
        self._round_opened_at = now
        scope = round_scope(msg.coordinator, msg.round_id)
        # A newer coordinator round pre-empts bidding in an older coordinator
        # round — but never an execution, a recruitment we lead, or a
        # recruitment we are BIDDING in (pre-empting a recruitment bid left
        # the leader paired with a robot that no longer knew it had bid).
        bidding_recruitment = (
            self._agent is not None
            and self._agent_scope is not None
            and self._agent_scope.startswith("l")
        )
        if self.me.id in msg.participants and self._can_bid() and not bidding_recruitment:
            self._agent = AuctionAgent(
                self.me.id,
                self._benefit_row(msg.task_ids, msg.idle_slots),
                RoundConfig(msg.epsilon, msg.quiescence_rounds),
            )
            self._agent_scope = scope
            self._relay = None
            self._relay_scope = None
        elif self._agent_scope != scope:
            self._start_relay(scope, list(msg.task_ids), msg.idle_slots)

    def _can_bid(self) -> bool:
        return (
            self.dispatch is None
            and self._recruiting is None
            and self._pending_follow is None
        )

    def _on_recruit(self, msg: RecruitAnnouncement, now: float) -> None:
        latest = self._latest_recruit.get(msg.task_id)
        if latest is not None and msg.seq <= latest.seq:
            return
        # Only honour the robot our lease replica says holds the task —
        # zombies cannot recruit.
        holder = self.leases.holder(msg.task_id)
        if holder is not None and holder != msg.leader:
            return
        self._latest_recruit[msg.task_id] = msg
        if msg.leader == self.me.id:
            return
        if self.me.id in msg.participants and self._can_bid():
            self._agent = AuctionAgent(
                self.me.id,
                self._recruit_row(msg),
                RoundConfig(msg.epsilon, msg.quiescence_rounds),
            )
            self._agent_scope = msg.scope
            self._relay = None
            self._relay_scope = None
        elif self._agent_scope != msg.scope:
            slots = max(0, len(msg.participants) - 1)
            self._start_relay(msg.scope, [msg.task_id], slots)

    def _start_relay(self, scope: str, task_ids: list[TaskId], idle_slots: int) -> None:
        ids = list(task_ids) + [_IDLE_BASE - k for k in range(idle_slots)]
        self._relay = PriceTable(ids)
        self._relay_scope = scope
        self._relay_dirty = False

    def _recruit_row(self, msg: RecruitAnnouncement) -> dict[TaskId, float]:
        row = {
            msg.task_id: (
                self.model.benefit(self.me, self.tasks[msg.task_id])
                if msg.task_id in self.tasks
                else 0.0
            )
        }
        slots = max(0, len(msg.participants) - 1)
        floor = min(row.values()) - 1.0
        for k in range(slots):
            row[_IDLE_BASE - k] = floor
        return row

    def _benefit_row(
        self, task_ids: tuple[TaskId, ...], idle_slots: int
    ) -> dict[TaskId, float]:
        others = {
            robot: pos
            for robot, (_, _, pos) in self._peer_state.items()
            if pos
        }
        row: dict[TaskId, float] = {}
        for tid in task_ids:
            task = self.tasks.get(tid)
            if task is None:
                row[tid] = 0.0
            elif task.collaborative:
                row[tid] = self.model.joint_benefit(self.me, task, others)
            else:
                row[tid] = self.model.benefit(self.me, task)
        if idle_slots:
            floor = min(row.values()) - 1.0
            for k in range(idle_slots):
                row[_IDLE_BASE - k] = floor
        return row

    def _on_gossip(self, msg: RoundGossip) -> None:
        if self._agent is not None and msg.scope == self._agent_scope:
            self._agent.handle_message(msg.inner)
        elif self._relay is not None and msg.scope == self._relay_scope:
            if self._relay.merge(msg.inner.entries):
                self._relay_dirty = True
        # Leader watches its own recruitment auction through a private table.
        r = self._recruiting
        if r is not None and r.table is not None:
            latest = self._latest_recruit.get(r.task_id)
            if latest is not None and msg.scope == latest.scope:
                if r.table.merge(msg.inner.entries):
                    r.quiet = 0

    def _on_lease_renewal(self, msg: LeaseRenewal, now: float) -> None:
        holder = self.leases.holder(msg.task_id)
        if holder is None:
            self.leases.grant(msg.task_id, msg.holder, now)
        elif holder == msg.holder:
            self.leases.renew(msg.task_id, msg.holder, now)
        elif msg.holder < holder:
            # Deterministic conflict resolution: every replica converges on
            # the lower id; the loser aborts via the holder check in tick().
            self.leases.release(msg.task_id, holder)
            self.leases.grant(msg.task_id, msg.holder, now)

        # Follower pairing: the leader names its follower in the renewal.
        if msg.follower != self.me.id or msg.holder == self.me.id:
            return
        if self._pending_follow is not None:
            task_id, leader, _ = self._pending_follow
            if msg.task_id == task_id and msg.holder == leader:
                self._pending_follow = None
                self._accept_follow(task_id, leader)
        elif msg.task_id in self.tasks and self._can_bid():
            # No local pending state, but the leader picked us from converged
            # auction prices — our bid implies willingness. This heals races
            # where our recruitment agent was superseded or the pending
            # window expired; renewals repeat at heartbeat cadence, so the
            # pairing lands once we are free.
            latest = self._latest_recruit.get(msg.task_id)
            recruit_scope_ok = (
                self._agent is None
                or (latest is not None and self._agent_scope == latest.scope)
            )
            if recruit_scope_ok:
                self._accept_follow(msg.task_id, msg.holder)

    def _accept_follow(self, task_id: TaskId, leader: AgentId) -> None:
        if self._agent_scope is not None and self._agent_scope.startswith("l"):
            self._agent = None  # we got the job; stop bidding for it
            self._agent_scope = None
        self.dispatch = Dispatch(task_id, "follower", leader)
        self._dispatches.append(self.dispatch)

    def _on_completed(self, msg: TaskCompleted) -> None:
        self.completed.setdefault(msg.task_id, msg.by)
        holder = self.leases.holder(msg.task_id)
        if holder is not None:
            self.leases.release(msg.task_id, holder)
        # Follower learns the collaboration is over from the leader.
        self.collaboration_finished(msg.task_id)

    # ------------------------------------------------------------------- tick

    def tick(self, now: float) -> list[CoordinationMessage]:
        out: list[CoordinationMessage] = []
        self.monitor.record(self.me.id, now)
        self.monitor.sweep(now)
        self.leases.sweep(now)

        self._check_ownership(now)
        out.extend(self._tick_auction(now))
        out.extend(self._tick_recruitment(now))
        out.extend(self._tick_heartbeat(now))
        out.extend(self._tick_coordinator(now))
        return out

    def _check_ownership(self, now: float) -> None:
        """Abort work whose backing claim has evaporated."""
        d = self.dispatch
        if d is None:
            return
        holder = self.leases.holder(d.task_id)
        if d.role in ("solo", "leader"):
            if holder is not None and holder != self.me.id:
                self._abort(d)
        elif d.role == "follower":
            # Leader died (lease expired) or task changed hands.
            if holder != d.partner:
                self._abort(d)

    def _abort(self, dispatch: Dispatch) -> None:
        self._aborts.append(dispatch)
        self.dispatch = None
        if self._recruiting is not None and self._recruiting.task_id == dispatch.task_id:
            self._recruiting = None

    # ---- auction participation (coordinator rounds and recruitments alike)

    def _tick_auction(self, now: float) -> list[CoordinationMessage]:
        out: list[CoordinationMessage] = []
        if self._agent is not None:
            scope = self._agent_scope
            for msg in self._agent.tick():
                out.append(RoundGossip(scope, msg))
            if self._agent.terminated:
                won = self._agent.assignment
                self._agent = None
                self._agent_scope = None
                out.extend(self._on_auction_won(scope, won, now))
        elif self._relay is not None and self._relay_dirty:
            self._relay_dirty = False
            out.append(
                RoundGossip(
                    self._relay_scope,
                    PriceTableMessage(self.me.id, self._relay.snapshot()),
                )
            )
        return out

    def _on_auction_won(
        self, scope: str, won: Optional[TaskId], now: float
    ) -> list[CoordinationMessage]:
        if won is None or won < 0 or won in self.completed:
            return []
        task = self.tasks.get(won)
        if scope.startswith("l"):
            # Recruitment won: wait for the leader to confirm the pairing.
            latest = self._latest_recruit.get(won)
            leader = latest.leader if latest is not None else NO_FOLLOWER
            self._pending_follow = (won, leader, now)
            return []
        if task is not None and task.collaborative:
            # Collaborative round win: become leader, recruit before working.
            self.leases.grant(won, self.me.id, now)
            self._begin_recruitment(won, now)
            return [LeaseRenewal(won, self.me.id, now)]
        self.leases.grant(won, self.me.id, now)
        self.dispatch = Dispatch(won, "solo")
        self._dispatches.append(self.dispatch)
        return [LeaseRenewal(won, self.me.id, now)]

    # ------------------------------------------------------- leader machinery

    def _begin_recruitment(self, task_id: TaskId, now: float) -> None:
        self._recruit_seq += 1
        self._recruiting = _Recruiting(
            task_id=task_id,
            seq=self._recruit_seq,
            started_at=now,
            announced_at=float("-inf"),
        )

    def _tick_recruitment(self, now: float) -> list[CoordinationMessage]:
        r = self._recruiting
        if r is None:
            return []
        out: list[CoordinationMessage] = []

        # Give up entirely: release the lease so the task re-enters framing.
        if now - r.started_at > self.round_timeout and r.table is None:
            self.leases.release(r.task_id, self.me.id)
            self._recruiting = None
            return []

        if r.table is None:
            invitees = sorted(self._idle_robots(now) - {self.me.id})
            if not invitees:
                out.append(LeaseRenewal(r.task_id, self.me.id, now))  # keep claim
                return out
            announcement = RecruitAnnouncement(
                leader=self.me.id,
                task_id=r.task_id,
                seq=r.seq,
                participants=tuple(invitees),
                epsilon=self.epsilon,
                quiescence_rounds=self.quiescence_rounds,
            )
            self._latest_recruit[r.task_id] = announcement
            slots = max(0, len(invitees) - 1)
            r.table = PriceTable([r.task_id] + [_IDLE_BASE - k for k in range(slots)])
            r.announced_at = now
            r.quiet = 0
            out.append(announcement)
            return out

        # Watching the auction: settled when the task has a bidder and the
        # table has been quiet for the quiescence window.
        r.quiet += 1
        entry = r.table.entry(r.task_id)
        if entry.bidder != NO_BIDDER and r.quiet >= self.quiescence_rounds:
            follower = entry.bidder
            self._recruiting = None
            self.dispatch = Dispatch(r.task_id, "leader", follower)
            self._dispatches.append(self.dispatch)
            out.append(LeaseRenewal(r.task_id, self.me.id, now, follower=follower))
        elif now - r.announced_at > self.round_timeout:
            # Nobody bid (announcement lost, invitees got busy): retry with a
            # fresh seq and the current idle set.
            self._begin_recruitment(r.task_id, now)
            out.append(LeaseRenewal(r.task_id, self.me.id, now))
        else:
            # Re-announce at heartbeat cadence for lossy links.
            latest = self._latest_recruit[r.task_id]
            if now - r.announced_at >= self.heartbeat_interval:
                out.append(latest)
        return out

    def _tick_leader_execution(self, now: float) -> None:
        """Follower death check while jointly executing."""
        d = self.dispatch
        if (
            d is not None
            and d.role == "leader"
            and not self.monitor.is_alive(d.partner, now)
        ):
            self._abort(d)  # host cancels the joint execution
            # Keep the lease and try again with someone else.
            self.leases.grant(d.task_id, self.me.id, now)
            self._begin_recruitment(d.task_id, now)

    # -------------------------------------------------------------- heartbeat

    def _tick_heartbeat(self, now: float) -> list[CoordinationMessage]:
        self._tick_leader_execution(now)
        self._expire_pending_follow(now)
        if now - self._last_heartbeat < self.heartbeat_interval:
            return []
        self._last_heartbeat = now
        out: list[CoordinationMessage] = [
            Heartbeat(self.me.id, now, self._is_idle, self.me.position)
        ]
        if (
            self._announcement is not None
            and self._announcement.coordinator == self.me.id
        ):
            out.append(self._announcement)
        d = self.dispatch
        if d is not None and d.role in ("solo", "leader"):
            follower = d.partner if d.role == "leader" else NO_FOLLOWER
            self.leases.renew(d.task_id, self.me.id, now)
            out.append(LeaseRenewal(d.task_id, self.me.id, now, follower=follower))
        for task_id, completer in self.completed.items():
            out.append(TaskCompleted(task_id, completer, now))
        return out

    def _expire_pending_follow(self, now: float) -> None:
        if self._pending_follow is not None:
            _, _, since = self._pending_follow
            if now - since > self.round_timeout:
                self._pending_follow = None  # leader never confirmed

    @property
    def _is_idle(self) -> bool:
        return self._can_bid() and self._agent is None

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

        idle = sorted(self._idle_robots(now))
        available = sorted(self._available_tasks(allow_collab=len(idle) >= 2))
        if not available or not idle:
            return []
        # Collaborations are framed ONE per round, alone: if several were
        # framed together, two robots can each win one, both become leaders,
        # and each waits forever for the other as follower (mutual-leader
        # livelock — found by the benchmark's collab suite). Framing a single
        # collab with every idle robot participating guarantees the sentinel
        # winners stay idle and recruitable.
        collabs = [t for t in available if self.tasks[t].collaborative]
        if collabs:
            available = [min(collabs)]

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
        assert self._announcement is not None
        if self._agent is not None and self._agent_scope == round_scope(
            self._announcement.coordinator, self._announcement.round_id
        ):
            return True
        if now - self._round_opened_at > self.round_timeout:
            return False
        settled = all(
            tid in self.completed or self.leases.holder(tid) is not None
            for tid in self._announcement.task_ids
        )
        return not settled

    def _available_tasks(self, allow_collab: bool) -> set[TaskId]:
        if not self.tasks:
            return set()
        dag = TaskDag(self.tasks.values())
        return {
            tid
            for tid in dag.available(set(self.completed) & set(self.tasks))
            if self.leases.holder(tid) is None
            and (allow_collab or not self.tasks[tid].collaborative)
        }

    def _idle_robots(self, now: float) -> set[AgentId]:
        idle = {
            robot
            for robot, (_, is_idle, _) in self._peer_state.items()
            if is_idle and self.monitor.is_alive(robot, now)
        }
        if self._is_idle:
            idle.add(self.me.id)
        return idle
