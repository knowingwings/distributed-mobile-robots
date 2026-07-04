"""Per-agent auction engine: Zavlanos et al. (2008), Algorithm 1.

Each agent is a deterministic, sans-I/O state machine. One call to `tick()`
is one auction iteration: decide whether we have been outbid, if so re-select
the best task and raise its price by gamma = v - w + epsilon, then broadcast
our price table. `handle_message()` merges a neighbour's table (max-merge).

Time, transport, and topology live outside: the caller delivers messages and
calls tick(). This is what lets the same engine run under pytest, a lossy
simulated network, ROS 2, or a DTN store-and-forward link unchanged.

Deliberate departures from the dissertation's Algorithm 1 (all justified in
maths-evaluation.md sections 2.6 and 6.1-6.2):
  - tasks remain contestable for the whole round (outbidding is mandatory);
  - the price rises by v - w + epsilon, not by epsilon + bid;
  - an agent bids whenever it is unassigned or outbid, regardless of the
    sign of its net value — with m >= n every agent ends up assigned, so a
    round cannot "converge" with allocatable tasks unassigned.
"""

from __future__ import annotations

from typing import Mapping, Optional

from ..types import AgentId, PriceTableMessage, RoundConfig, TaskId
from .prices import PriceTable


class AuctionAgent:
    def __init__(
        self,
        agent_id: AgentId,
        benefits: Mapping[TaskId, float],
        config: RoundConfig,
    ):
        if agent_id < 0:
            raise ValueError("agent ids must be >= 0")
        if not benefits:
            raise ValueError("an agent needs at least one task to bid on")
        self.id = agent_id
        self.config = config
        self._benefits = dict(benefits)
        self.prices = PriceTable(self._benefits.keys())
        self.assignment: Optional[TaskId] = None
        self._quiescent_ticks = 0
        self._dirty = True  # state changed since the quiescence counter last advanced

    # ------------------------------------------------------------------ inputs

    def handle_message(self, message: PriceTableMessage) -> None:
        if message.sender == self.id:
            return
        if self.prices.merge(message.entries):
            self._dirty = True

    # ------------------------------------------------------------------- logic

    def tick(self) -> list[PriceTableMessage]:
        """One auction iteration. Returns the messages to broadcast (empty
        once the agent considers the round quiescent)."""
        if self._outbid():
            self._place_bid()
            self._dirty = True

        if self._dirty:
            self._quiescent_ticks = 0
            self._dirty = False
        else:
            self._quiescent_ticks += 1

        if self.terminated:
            return []
        return [PriceTableMessage(self.id, self.prices.snapshot())]

    def _outbid(self) -> bool:
        """Alg. 1 line 2: bid if unassigned, or if we no longer hold the
        highest-bidder slot for our task (covers both a higher price from
        elsewhere and an equal price lost on the max-index tie-break)."""
        if self.assignment is None:
            return True
        return self.prices.bidder(self.assignment) != self.id

    def _place_bid(self) -> None:
        """Alg. 1 lines 3-4: pick the max-net-value task, raise its price by
        gamma = v - w + epsilon (w = second-best net value; when there is no
        second task, gamma = epsilon)."""
        best_task: Optional[TaskId] = None
        v = w = float("-inf")
        for task_id, benefit in self._benefits.items():
            net = benefit - self.prices.price(task_id)
            # Strict > keeps the scan deterministic: first-seen wins equal
            # nets locally; cross-agent ties are what the bidder index solves.
            if net > v:
                w = v
                v, best_task = net, task_id
            elif net > w:
                w = net
        assert best_task is not None
        gamma = self.config.epsilon if w == float("-inf") else (v - w) + self.config.epsilon
        self.prices.bid(best_task, gamma, self.id, self.config.epsilon)
        self.assignment = best_task

    # ------------------------------------------------------------------ status

    @property
    def terminated(self) -> bool:
        """Round complete from this agent's viewpoint: price table unchanged
        for quiescence_rounds consecutive ticks. A later message that changes
        the table un-terminates the agent (see harness for the global check)."""
        return self._quiescent_ticks >= self.config.quiescence_rounds

    @property
    def net_value(self) -> float:
        assert self.assignment is not None
        return self._benefits[self.assignment] - self.prices.price(self.assignment)
