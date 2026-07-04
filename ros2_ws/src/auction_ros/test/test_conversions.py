"""Round-trip tests: core dataclass -> ROS msg -> core dataclass."""

from auction_core.coordination.messages import (
    Heartbeat,
    LeaseRenewal,
    RoundAnnouncement,
    RoundGossip,
    TaskCompleted,
)
from auction_core.types import PriceEntry, PriceTableMessage, Task

from auction_ros import conversions as conv


def test_heartbeat_round_trip():
    hb = Heartbeat(sender=3, stamp=12.5, idle=True)
    assert conv.heartbeat_to_core(conv.heartbeat_to_msg(hb)) == hb


def test_announcement_round_trip():
    a = RoundAnnouncement(
        round_id=7, coordinator=1, task_ids=(4, 5), participants=(1, 2),
        idle_slots=1, epsilon=0.05, quiescence_rounds=8,
    )
    assert conv.announcement_to_core(conv.announcement_to_msg(a)) == a


def test_gossip_round_trip():
    g = RoundGossip(
        round_id=7,
        inner=PriceTableMessage(
            sender=2, entries={4: PriceEntry(1.5, 2), -1: PriceEntry(0.0, -1)}
        ),
    )
    back = conv.gossip_to_core(conv.gossip_to_msg(g))
    assert back.round_id == g.round_id
    assert back.inner.sender == g.inner.sender
    assert dict(back.inner.entries) == dict(g.inner.entries)


def test_lease_and_completed_round_trip():
    l = LeaseRenewal(task_id=4, holder=2, stamp=3.25)
    c = TaskCompleted(task_id=4, by=2, stamp=9.0)
    assert conv.lease_to_core(conv.lease_to_msg(l)) == l
    assert conv.completed_to_core(conv.completed_to_msg(c)) == c


def test_task_round_trip():
    t = Task(
        id=9, position=(1.0, 2.0), duration=4.5,
        capabilities=(0.5, 1.0), prerequisites=frozenset({1, 2}),
        required_robots=2,
    )
    assert conv.task_to_core(conv.task_to_msg(t)) == t
