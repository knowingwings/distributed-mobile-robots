"""Sequential single-item (SSI) auction allocator.

The comparison point for repeated frozen-beta rounds (Lagoudakis et al. line
of work): tasks are auctioned ONE at a time; each robot bids the marginal
cost of appending the task to its personal schedule; the globally best
(bid, robot) pair wins and commits; repeat until everything is allocated.
Constant-factor makespan bounds exist for the min-makespan bid rule in the
unconstrained case — with a precedence DAG the guarantee story is weaker,
which is exactly what the benchmark is for.

Distribution is honest: the per-item winner is found by max-consensus over
the same lossy/delayed SimTransport the round engine uses. A candidate is
a totally ordered (bid, robot, task) triple; each robot broadcasts its best
and merges what it hears (idempotent max), declaring the item settled after
a quiescence window — so message counts and loss/delay effects are directly
comparable with the round-based allocator.

Bid rules:
  - "min-makespan": bid = -(robot's completion time after appending) —
    greedily minimises the growing maximum.
  - "sum-cost":     bid = -(marginal travel + duration) — greedily
    minimises total work.

Execution playback: allocation is up-front, so makespan comes from playing
the schedules against the DAG. Each idle robot runs the earliest task in
its schedule that is runnable (prerequisites globally complete); if none is
runnable it waits. Because prerequisites form a DAG, some incomplete task
with satisfied prerequisites always exists, so playback cannot deadlock.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Literal

from ..scheduling.benefits import RobotState, _distance
from ..scheduling.dag import TaskDag
from ..types import AgentId, Task, TaskId
from ..validation.harness import suggested_quiescence
from ..validation.transport import SimTransport, Topology, complete
from .base import AllocationResult, Allocator, ScheduledTask

BidRule = Literal["min-makespan", "sum-cost"]

# SimTransport factory so each item auction gets a fresh fabric with the
# caller's loss/delay profile (mirrors how the round runner is injected).
TransportFactory = Callable[[set[AgentId]], SimTransport]


@dataclass(frozen=True, order=True)
class Candidate:
    """Totally ordered bid candidate — max() implements the selection."""

    bid: float
    robot: AgentId
    task: TaskId


@dataclass(frozen=True)
class CandidateMessage:
    item_index: int  # scopes candidates to one item auction
    candidate: Candidate
    sender: AgentId


@dataclass
class _PlannedRobot:
    state: RobotState
    schedule: list[TaskId]
    end_position: tuple[float, ...]
    end_time: float


class SSIAllocator(Allocator):
    def __init__(
        self,
        bid_rule: BidRule = "min-makespan",
        *,
        transport_factory: TransportFactory | None = None,
        quiescence_rounds: int | None = None,
        max_ticks_per_item: int = 50_000,
    ):
        self.bid_rule: BidRule = bid_rule
        self._transport_factory = transport_factory or (
            lambda ids: SimTransport(complete(ids))
        )
        self._quiescence = quiescence_rounds
        self._max_ticks = max_ticks_per_item

    # ------------------------------------------------------------- allocation

    def allocate(
        self, robots: list[RobotState], tasks: list[Task]
    ) -> AllocationResult:
        unallocated: dict[TaskId, str] = {}
        schedulable: list[Task] = []
        for task in tasks:
            if task.collaborative:
                unallocated[task.id] = "collaborative tasks unsupported in SSI v1"
            else:
                schedulable.append(task)
        for task in tasks:
            if task.collaborative:
                dag_all = TaskDag(tasks)
                for blocked in dag_all.dependents(task.id):
                    unallocated.setdefault(
                        blocked, f"blocked by unallocatable prerequisite {task.id}"
                    )
        schedulable = [t for t in schedulable if t.id not in unallocated]
        by_id = {t.id: t for t in schedulable}

        planned = {
            r.id: _PlannedRobot(
                state=replace(r),
                schedule=[],
                end_position=r.position,
                end_time=0.0,
            )
            for r in robots
        }

        remaining = set(by_id)
        messages = 0
        ticks = 0
        for item_index in range(len(schedulable)):
            candidates = {
                rid: self._best_candidate(p, remaining, by_id)
                for rid, p in planned.items()
            }
            winner, item_ticks, item_msgs = self._select(
                item_index, candidates, set(planned)
            )
            messages += item_msgs
            ticks += item_ticks
            p = planned[winner.robot]
            task = by_id[winner.task]
            p.schedule.append(winner.task)
            p.end_time += self._travel(p, task) + task.duration
            p.end_position = task.position or p.end_position
            remaining.discard(winner.task)

        schedule, makespan = self._playback(planned, by_id)
        result = AllocationResult(
            schedule=schedule,
            makespan=makespan,
            rounds=len(schedulable),
            total_messages=messages,
            unallocated=unallocated,
        )
        result.allocation_ticks = ticks  # benchmark metadata
        return result

    # ------------------------------------------------------------------- bids

    @staticmethod
    def _travel(p: _PlannedRobot, task: Task) -> float:
        if p.state.speed <= 0:
            return 0.0
        return _distance(p.end_position, task.position) / p.state.speed

    def _best_candidate(
        self,
        p: _PlannedRobot,
        remaining: set[TaskId],
        by_id: dict[TaskId, Task],
    ) -> Candidate:
        best: Candidate | None = None
        for task_id in remaining:
            task = by_id[task_id]
            marginal = self._travel(p, task) + task.duration
            if self.bid_rule == "min-makespan":
                bid = -(p.end_time + marginal)
            else:  # sum-cost
                bid = -marginal
            candidate = Candidate(bid, p.state.id, task_id)
            if best is None or candidate > best:
                best = candidate
        assert best is not None
        return best

    # -------------------------------------------------- distributed selection

    def _select(
        self,
        item_index: int,
        own_candidates: dict[AgentId, Candidate],
        agent_ids: set[AgentId],
    ) -> tuple[Candidate, int, int]:
        """Max-consensus on the candidate order over the injected transport.
        Every robot repeatedly broadcasts the best candidate it knows; the
        total order makes merging idempotent and convergent. Quiescence
        mirrors the round engine's termination."""
        if len(agent_ids) == 1:
            (only,) = own_candidates.values()
            return only, 0, 0

        transport = self._transport_factory(agent_ids)
        quiescence = self._quiescence or suggested_quiescence(
            complete(agent_ids), 0
        )
        best = dict(own_candidates)
        quiet = {a: 0 for a in agent_ids}

        tick = 0
        while True:
            if tick >= self._max_ticks:
                raise RuntimeError(f"SSI item {item_index} did not settle")
            for dest, msg in transport.deliver_due(tick):
                if msg.item_index != item_index:
                    continue
                if msg.candidate > best[dest]:
                    best[dest] = msg.candidate
                    quiet[dest] = 0
            done = True
            for agent in agent_ids:
                if quiet[agent] >= quiescence:
                    continue
                done = False
                quiet[agent] += 1
                transport.send_payload(
                    CandidateMessage(item_index, best[agent], agent), agent, tick
                )
            if done and transport.idle:
                break
            tick += 1

        winners = set(best.values())
        assert len(winners) == 1, f"selection diverged: {winners}"
        return next(iter(winners)), tick, transport.messages_sent

    # --------------------------------------------------------------- playback

    @staticmethod
    def _playback(
        planned: dict[AgentId, _PlannedRobot], by_id: dict[TaskId, Task]
    ) -> tuple[list[ScheduledTask], float]:
        completed: set[TaskId] = set()
        pending = {rid: list(p.schedule) for rid, p in planned.items()}
        position = {rid: p.state.position for rid, p in planned.items()}
        free_at = {rid: 0.0 for rid in planned}
        running: dict[AgentId, ScheduledTask] = {}
        schedule: list[ScheduledTask] = []

        def runnable(rid: AgentId) -> TaskId | None:
            for task_id in pending[rid]:
                if by_id[task_id].prerequisites <= completed:
                    return task_id
            return None

        now = 0.0
        total = sum(len(s) for s in pending.values())
        while len(completed) < total:
            progressed = False
            for rid in sorted(planned):
                if rid in running or not pending[rid] or free_at[rid] > now:
                    continue
                task_id = runnable(rid)
                if task_id is None:
                    continue
                pending[rid].remove(task_id)
                task = by_id[task_id]
                p = planned[rid].state
                travel = (
                    _distance(position[rid], task.position) / p.speed
                    if p.speed > 0
                    else 0.0
                )
                entry = ScheduledTask(
                    task_id, rid, start=now, finish=now + travel + task.duration
                )
                running[rid] = entry
                position[rid] = task.position or position[rid]
                progressed = True
            if not running:
                assert progressed, "playback stalled — DAG invariant violated"
                continue
            # advance to next completion
            rid = min(running, key=lambda r: running[r].finish)
            entry = running.pop(rid)
            now = entry.finish
            free_at[rid] = now
            completed.add(entry.task_id)
            schedule.append(entry)

        makespan = max((s.finish for s in schedule), default=0.0)
        return schedule, makespan
