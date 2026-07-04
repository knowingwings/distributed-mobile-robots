"""Local price table with max-merge semantics.

Each agent keeps its own copy of every task's (price, highest bidder). Copies
are reconciled by entry-wise max() — the max-price / max-index update of
Zavlanos Algorithm 1. Two invariants are enforced here and nowhere bypassed:

  I1 (monotonicity): an entry never decreases under any operation.
  I2 (minimum increment): a local bid raises the price by at least epsilon.

These are the invariants the convergence and epsilon-complementary-slackness
proofs stand on (maths-evaluation.md section 4); violating code should die
loudly, not converge quietly to something unprovable.
"""

from __future__ import annotations

from typing import Iterable, Mapping

from ..types import AgentId, PriceEntry, TaskId


class PriceTable:
    def __init__(self, task_ids: Iterable[TaskId]):
        self._entries: dict[TaskId, PriceEntry] = {
            t: PriceEntry.initial() for t in task_ids
        }

    def entry(self, task_id: TaskId) -> PriceEntry:
        return self._entries[task_id]

    def price(self, task_id: TaskId) -> float:
        return self._entries[task_id].price

    def bidder(self, task_id: TaskId) -> AgentId:
        return self._entries[task_id].bidder

    @property
    def task_ids(self) -> Iterable[TaskId]:
        return self._entries.keys()

    def snapshot(self) -> dict[TaskId, PriceEntry]:
        return dict(self._entries)

    def merge(self, incoming: Mapping[TaskId, PriceEntry]) -> bool:
        """Entry-wise max-merge of another agent's view. Returns True if any
        entry changed. Unknown task ids are ignored (round membership is fixed
        by the allocator; a well-formed system never sends them)."""
        changed = False
        for task_id, theirs in incoming.items():
            ours = self._entries.get(task_id)
            if ours is None:
                continue
            merged = max(ours, theirs)
            if merged != ours:
                # I1: max() can only move an entry up in (price, bidder) order.
                assert merged.price >= ours.price
                self._entries[task_id] = merged
                changed = True
        return changed

    def bid(self, task_id: TaskId, increment: float, bidder: AgentId, epsilon: float) -> None:
        """Record a local bid: raise task price by `increment` and claim the
        highest-bidder slot. I2 is asserted, not clamped — an increment below
        epsilon means the engine's gamma computation is broken."""
        assert increment >= epsilon, (
            f"bid increment {increment} < epsilon {epsilon} (invariant I2)"
        )
        ours = self._entries[task_id]
        updated = PriceEntry(ours.price + increment, bidder)
        assert updated > ours  # I1
        self._entries[task_id] = updated
