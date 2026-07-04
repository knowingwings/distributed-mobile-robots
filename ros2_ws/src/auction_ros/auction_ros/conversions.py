"""Pure conversion functions: auction_msgs <-> auction_core dataclasses.

The only place where the two vocabularies meet. No rclpy, no node state —
unit-testable with generated messages alone (round-trip tests in
test/test_conversions.py).
"""

from __future__ import annotations

from auction_core.coordination.messages import (
    Heartbeat,
    LeaseRenewal,
    RoundAnnouncement,
    RoundGossip,
    TaskCompleted,
)
from auction_core.types import PriceEntry, PriceTableMessage, Task

import auction_msgs.msg as m


# ------------------------------------------------------------------ to core


def heartbeat_to_core(msg: m.Heartbeat) -> Heartbeat:
    return Heartbeat(sender=msg.sender, stamp=msg.stamp, idle=msg.idle)


def announcement_to_core(msg: m.RoundAnnouncement) -> RoundAnnouncement:
    return RoundAnnouncement(
        round_id=msg.round_id,
        coordinator=msg.coordinator,
        task_ids=tuple(msg.task_ids),
        participants=tuple(msg.participants),
        idle_slots=msg.idle_slots,
        epsilon=msg.epsilon,
        quiescence_rounds=msg.quiescence_rounds,
    )


def gossip_to_core(msg: m.RoundGossip) -> RoundGossip:
    entries = {
        e.task_id: PriceEntry(e.price, e.bidder) for e in msg.table.entries
    }
    return RoundGossip(
        round_id=msg.round_id,
        inner=PriceTableMessage(sender=msg.table.sender, entries=entries),
    )


def lease_to_core(msg: m.LeaseRenewal) -> LeaseRenewal:
    return LeaseRenewal(task_id=msg.task_id, holder=msg.holder, stamp=msg.stamp)


def completed_to_core(msg: m.TaskCompleted) -> TaskCompleted:
    return TaskCompleted(task_id=msg.task_id, by=msg.by, stamp=msg.stamp)


def task_to_core(msg: m.TaskSpec) -> Task:
    return Task(
        id=msg.id,
        position=tuple(msg.position),
        duration=msg.duration,
        capabilities=tuple(msg.capabilities),
        prerequisites=frozenset(msg.prerequisites),
        required_robots=msg.required_robots,
    )


# ---------------------------------------------------------------- from core


def heartbeat_to_msg(hb: Heartbeat) -> m.Heartbeat:
    return m.Heartbeat(sender=hb.sender, stamp=hb.stamp, idle=hb.idle)


def announcement_to_msg(a: RoundAnnouncement) -> m.RoundAnnouncement:
    return m.RoundAnnouncement(
        round_id=a.round_id,
        coordinator=a.coordinator,
        task_ids=list(a.task_ids),
        participants=list(a.participants),
        idle_slots=a.idle_slots,
        epsilon=a.epsilon,
        quiescence_rounds=a.quiescence_rounds,
    )


def gossip_to_msg(g: RoundGossip) -> m.RoundGossip:
    return m.RoundGossip(
        round_id=g.round_id,
        table=m.PriceTable(
            sender=g.inner.sender,
            entries=[
                m.PriceEntry(task_id=t, price=e.price, bidder=e.bidder)
                for t, e in g.inner.entries.items()
            ],
        ),
    )


def lease_to_msg(l: LeaseRenewal) -> m.LeaseRenewal:
    return m.LeaseRenewal(task_id=l.task_id, holder=l.holder, stamp=l.stamp)


def completed_to_msg(c: TaskCompleted) -> m.TaskCompleted:
    return m.TaskCompleted(task_id=c.task_id, by=c.by, stamp=c.stamp)


def task_to_msg(t: Task) -> m.TaskSpec:
    return m.TaskSpec(
        id=t.id,
        position=list(t.position),
        duration=t.duration,
        capabilities=list(t.capabilities),
        prerequisites=list(t.prerequisites),
        required_robots=t.required_robots,
    )
