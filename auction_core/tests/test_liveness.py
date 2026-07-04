"""Heartbeat detection and lease semantics."""

import pytest

from auction_core.liveness.heartbeat import HeartbeatMonitor
from auction_core.liveness.lease import TaskLeases


# ------------------------------------------------------------------ heartbeats


def test_alive_within_timeout():
    m = HeartbeatMonitor(interval=1.0, eta=3)
    m.record(0, now=0.0)
    assert m.is_alive(0, now=3.0)      # exactly eta * dt: still alive
    assert not m.is_alive(0, now=3.1)  # past the boundary: dead


def test_sweep_reports_failure_once():
    m = HeartbeatMonitor(interval=1.0, eta=3)
    m.record(0, now=0.0)
    assert m.sweep(1.0).failed == []
    assert m.sweep(4.0).failed == [0]
    assert m.sweep(5.0).failed == []  # already known dead — no re-report


def test_sweep_reports_recovery():
    m = HeartbeatMonitor(interval=1.0, eta=3)
    m.record(0, now=0.0)
    m.sweep(4.0)
    m.record(0, now=4.5)  # robot comes back (e.g. partition healed)
    update = m.sweep(4.6)
    assert update.recovered == [0]
    assert update.failed == []


def test_out_of_order_heartbeats_ignored():
    m = HeartbeatMonitor(interval=1.0, eta=3)
    m.record(0, now=5.0)
    m.record(0, now=2.0)  # stale, delayed delivery — must not rewind
    assert m.is_alive(0, now=7.0)


def test_unknown_robot_not_alive_not_failed():
    m = HeartbeatMonitor()
    assert not m.is_alive(99, now=0.0)
    assert m.sweep(100.0).failed == []  # undiscovered != dead


def test_alive_set():
    m = HeartbeatMonitor(interval=1.0, eta=3)
    m.record(0, now=0.0)
    m.record(1, now=8.0)
    assert m.alive(now=9.0) == {1}


# ---------------------------------------------------------------------- leases


def test_lease_grant_renew_expire():
    leases = TaskLeases(duration=3.0)
    leases.grant(7, holder=1, now=0.0)
    assert leases.holder(7) == 1
    assert leases.renew(7, holder=1, now=2.0)
    assert leases.sweep(now=4.0) == []          # renewed at 2.0 -> valid to 5.0
    expired = leases.sweep(now=5.0)
    assert [l.task_id for l in expired] == [7]  # orphaned
    assert leases.holder(7) is None


def test_stale_holder_cannot_renew_or_release():
    leases = TaskLeases(duration=3.0)
    leases.grant(7, holder=1, now=0.0)
    leases.sweep(now=10.0)              # expired, orphaned
    leases.grant(7, holder=2, now=10.0)  # reallocated to robot 2
    assert not leases.renew(7, holder=1, now=11.0)   # zombie robot 1 rejected
    assert not leases.release(7, holder=1)
    assert leases.holder(7) == 2


def test_release_on_completion():
    leases = TaskLeases(duration=3.0)
    leases.grant(7, holder=1, now=0.0)
    assert leases.release(7, holder=1)
    assert leases.sweep(now=100.0) == []  # nothing to orphan


def test_held_by():
    leases = TaskLeases(duration=3.0)
    leases.grant(1, holder=0, now=0.0)
    leases.grant(2, holder=0, now=0.0)
    leases.grant(3, holder=1, now=0.0)
    assert leases.held_by(0) == {1, 2}


def test_invalid_params():
    with pytest.raises(ValueError):
        HeartbeatMonitor(interval=0.0)
    with pytest.raises(ValueError):
        TaskLeases(duration=0.0)
