"""Merge semantics of the price table: the CRDT-ish properties that make the
auction tolerant of message loss, duplication, and reordering."""

import pytest

from auction_core.types import NO_BIDDER, PriceEntry
from auction_core.auction.prices import PriceTable


def make_table(entries):
    t = PriceTable(entries.keys())
    t.merge(entries)
    return t


def test_initial_entries():
    t = PriceTable([1, 2])
    assert t.price(1) == 0.0
    assert t.bidder(1) == NO_BIDDER


def test_merge_takes_higher_price():
    t = make_table({1: PriceEntry(2.0, 0)})
    assert t.merge({1: PriceEntry(3.0, 1)}) is True
    assert t.entry(1) == PriceEntry(3.0, 1)


def test_merge_ignores_lower_price():
    t = make_table({1: PriceEntry(3.0, 1)})
    assert t.merge({1: PriceEntry(2.0, 0)}) is False
    assert t.entry(1) == PriceEntry(3.0, 1)


def test_merge_tie_breaks_to_larger_agent_id():
    t = make_table({1: PriceEntry(3.0, 1)})
    assert t.merge({1: PriceEntry(3.0, 2)}) is True
    assert t.bidder(1) == 2
    # And the reverse direction does nothing: max-index wins ties everywhere.
    assert t.merge({1: PriceEntry(3.0, 0)}) is False


def test_merge_idempotent():
    entries = {1: PriceEntry(3.0, 1), 2: PriceEntry(1.0, 0)}
    t = make_table(entries)
    assert t.merge(entries) is False  # replaying the same message is a no-op
    assert t.snapshot() == entries


def test_merge_commutative():
    a = {1: PriceEntry(3.0, 1), 2: PriceEntry(1.0, 0)}
    b = {1: PriceEntry(2.0, 4), 2: PriceEntry(1.0, 3)}
    t1 = PriceTable([1, 2])
    t1.merge(a)
    t1.merge(b)
    t2 = PriceTable([1, 2])
    t2.merge(b)
    t2.merge(a)
    assert t1.snapshot() == t2.snapshot()


def test_merge_ignores_unknown_tasks():
    t = PriceTable([1])
    assert t.merge({99: PriceEntry(5.0, 0)}) is False


def test_bid_raises_price_and_claims():
    t = PriceTable([1])
    t.bid(1, increment=0.5, bidder=3, epsilon=0.1)
    assert t.entry(1) == PriceEntry(0.5, 3)


def test_bid_below_epsilon_asserts():
    t = PriceTable([1])
    with pytest.raises(AssertionError):
        t.bid(1, increment=0.05, bidder=3, epsilon=0.1)
