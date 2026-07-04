"""Core value types shared across the auction, scheduling, and validation layers.

Everything here is a plain, immutable-by-convention data structure: the core is
sans-I/O and these types are what flows between agents (as messages) and layers
(as inputs/results). Transport adapters (simulated, ROS 2, DTN) serialise these
and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional

# Agent and task identifiers. Total order on AgentId is load-bearing: ties in
# the price table are broken toward the larger agent id (Zavlanos' max-index
# rule), which is what makes concurrent equal bids resolve identically at every
# agent without further communication.
AgentId = int
TaskId = int

# Sentinel bidder for a task no one has bid on. Any real agent id must be >= 0
# so that the first genuine bid wins the tie-break against the sentinel.
NO_BIDDER: AgentId = -1


@dataclass(frozen=True, order=True)
class PriceEntry:
    """A task's price and the highest bidder that set it.

    Ordering is lexicographic (price, then bidder), which is exactly the
    max-price / max-index merge rule — `max(a, b)` on two entries implements
    Zavlanos Algorithm 1, line 1.
    """

    price: float
    bidder: AgentId

    @staticmethod
    def initial() -> "PriceEntry":
        return PriceEntry(0.0, NO_BIDDER)


@dataclass(frozen=True)
class PriceTableMessage:
    """One agent's view of all task prices, broadcast to its neighbours.

    The receiver merges entry-wise with `max()`. Merging is associative,
    commutative, and idempotent, so duplication, reordering, and loss of
    messages never corrupt state — they only delay convergence.
    """

    sender: AgentId
    entries: Mapping[TaskId, PriceEntry]


@dataclass(frozen=True)
class Task:
    """A unit of work. Collaborative fields are carried from day one but the
    v1 allocator does not schedule tasks with required_robots > 1."""

    id: TaskId
    position: tuple[float, ...] = ()
    duration: float = 1.0
    capabilities: tuple[float, ...] = ()
    prerequisites: frozenset[TaskId] = field(default_factory=frozenset)
    required_robots: int = 1

    @property
    def collaborative(self) -> bool:
        return self.required_robots > 1


@dataclass(frozen=True)
class RoundConfig:
    """Parameters of a single auction round.

    epsilon: minimum bid increment (> 0). The final assignment's total benefit
        is within n*epsilon of optimal for n participating agents; with
        integer benefits and epsilon < 1/n it is exactly optimal.
    quiescence_rounds: an agent declares the round terminated after its price
        table has been unchanged for this many consecutive ticks. Must cover
        the network diameter (and, with delayed links, diameter x max delay);
        the harness/wrapper chooses it, the engine just counts.
    """

    epsilon: float
    quiescence_rounds: int

    def __post_init__(self) -> None:
        if self.epsilon <= 0:
            raise ValueError(f"epsilon must be > 0, got {self.epsilon}")
        if self.quiescence_rounds < 1:
            raise ValueError(
                f"quiescence_rounds must be >= 1, got {self.quiescence_rounds}"
            )


@dataclass
class RoundResult:
    """Outcome of one auction round as observed by the harness/allocator."""

    assignment: dict[AgentId, Optional[TaskId]]
    ticks: int
    messages_sent: int
    prices: dict[TaskId, PriceEntry]
