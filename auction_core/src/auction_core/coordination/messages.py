"""Coordination message vocabulary.

Plain dataclasses, mirrored 1:1 by the ROS msgs in `auction_msgs`. Every
handler is idempotent: heartbeats and renewals are keyed by (sender, stamp),
completions form a grow-only set, announcements are resolved by the
precedence rule (higher round_id wins; ties go to the LOWER coordinator id,
because the rightful coordinator is the minimum alive id). Rebroadcasting
any of these is therefore always safe — the BEST_EFFORT + rebroadcast QoS
choice rests on this property.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..types import AgentId, PriceTableMessage, Task, TaskId


@dataclass(frozen=True)
class Heartbeat:
    sender: AgentId
    stamp: float
    idle: bool  # advertises availability for round framing


@dataclass(frozen=True)
class RoundAnnouncement:
    """Coordinator frames a round: which tasks, which robots, what config.
    idle_slots pads m >= n — participants materialise sentinel tasks with
    ids -1..-idle_slots locally, priced below every real benefit."""

    round_id: int
    coordinator: AgentId
    task_ids: tuple[TaskId, ...]
    participants: tuple[AgentId, ...]
    idle_slots: int
    epsilon: float
    quiescence_rounds: int

    def precedes(self, other: "RoundAnnouncement") -> bool:
        """True if `other` should replace this announcement."""
        if other.round_id != self.round_id:
            return other.round_id > self.round_id
        return other.coordinator < self.coordinator


@dataclass(frozen=True)
class RoundGossip:
    """Auction price gossip scoped to one round — tables from different
    rounds must never merge."""

    round_id: int
    inner: PriceTableMessage


@dataclass(frozen=True)
class LeaseRenewal:
    task_id: TaskId
    holder: AgentId
    stamp: float


@dataclass(frozen=True)
class TaskCompleted:
    task_id: TaskId
    by: AgentId
    stamp: float


@dataclass(frozen=True)
class TaskInjected:
    task: Task
    stamp: float


CoordinationMessage = (
    Heartbeat
    | RoundAnnouncement
    | RoundGossip
    | LeaseRenewal
    | TaskCompleted
    | TaskInjected
)
