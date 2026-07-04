"""Task ownership leases.

A robot that wins a task holds it under a lease renewed at heartbeat cadence
while executing. If renewals stop — robot died, partitioned away, or gave
up — the lease expires and the task is ORPHANED: it re-enters the available
set and the next auction round reallocates it. Recovery is therefore not a
special mode; it is lease expiry plus an ordinary round (recovery time =
detection window + Prop 3.2 on the orphaned subproblem).

Failure handling is local and passive by construction — no global recovery
flag, no coordinator bookkeeping — which is precisely what the original
implementation's recovery lacked.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..types import AgentId, TaskId


@dataclass(frozen=True)
class Lease:
    task_id: TaskId
    holder: AgentId
    expires_at: float


class TaskLeases:
    def __init__(self, duration: float):
        """duration: lease validity per renewal. Choose >= heartbeat timeout
        (eta * dt) so a robot is not stripped of tasks faster than it can be
        declared dead — a single missed renewal must not orphan work."""
        if duration <= 0:
            raise ValueError("lease duration must be > 0")
        self.duration = duration
        self._leases: dict[TaskId, Lease] = {}

    def grant(self, task_id: TaskId, holder: AgentId, now: float) -> Lease:
        lease = Lease(task_id, holder, now + self.duration)
        self._leases[task_id] = lease
        return lease

    def renew(self, task_id: TaskId, holder: AgentId, now: float) -> bool:
        """Renew if `holder` still owns the lease (a stale holder whose task
        was reallocated cannot steal it back). Returns success."""
        current = self._leases.get(task_id)
        if current is None or current.holder != holder:
            return False
        self._leases[task_id] = Lease(task_id, holder, now + self.duration)
        return True

    def release(self, task_id: TaskId, holder: AgentId) -> bool:
        """Voluntary release (task completed or abandoned)."""
        current = self._leases.get(task_id)
        if current is None or current.holder != holder:
            return False
        del self._leases[task_id]
        return True

    def sweep(self, now: float) -> list[Lease]:
        """Remove and return expired leases — these tasks are now orphaned."""
        expired = [l for l in self._leases.values() if l.expires_at <= now]
        for lease in expired:
            del self._leases[lease.task_id]
        return expired

    def holder(self, task_id: TaskId) -> AgentId | None:
        lease = self._leases.get(task_id)
        return lease.holder if lease else None

    def held_by(self, robot: AgentId) -> set[TaskId]:
        return {t for t, l in self._leases.items() if l.holder == robot}
