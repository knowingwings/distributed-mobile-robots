"""Transport semantics + full rounds over imperfect networks.

Includes the paper's Fig. 2 scenario shape: contention between agents that
are not adjacent, with pricing information propagating multi-hop through a
line topology.
"""

import random

import pytest

from auction_core.types import PriceTableMessage, PriceEntry, RoundConfig
from auction_core.validation.transport import (
    SimTransport,
    complete,
    diameter,
    line,
    random_connected,
)
from auction_core.validation.harness import run_round, suggested_quiescence


def cfg(topology, max_delay=0, epsilon=0.01):
    return RoundConfig(
        epsilon=epsilon,
        quiescence_rounds=suggested_quiescence(topology, max_delay),
    )


# --------------------------------------------------------------- transport unit


def test_diameter():
    assert diameter(complete(range(4))) == 1
    assert diameter(line(range(4))) == 3
    topo = random_connected(range(6), edge_prob=0.3, rng=random.Random(1))
    assert 1 <= diameter(topo) <= 5


def test_delivery_delay():
    t = SimTransport(line(range(2)), delay_ticks=2)
    t.send(PriceTableMessage(0, {0: PriceEntry(1.0, 0)}), now=0)
    assert t.deliver_due(2) == []
    delivered = t.deliver_due(3)  # now + 1 + delay
    assert [dest for dest, _ in delivered] == [1]
    assert t.idle


def test_total_loss_drops_everything():
    t = SimTransport(complete(range(3)), loss_prob=1.0)
    t.send(PriceTableMessage(0, {0: PriceEntry(1.0, 0)}), now=0)
    assert t.idle
    assert t.messages_sent == 2  # sends are counted even when the link eats them


# ------------------------------------------------------------------ full rounds

BENEFITS_4 = {
    0: {0: 9.0, 1: 7.0, 2: 2.0, 3: 1.0},
    1: {0: 9.0, 1: 2.0, 2: 6.0, 3: 1.0},
    2: {0: 9.0, 1: 2.0, 2: 1.0, 3: 5.0},
    3: {0: 12.0, 1: 1.0, 2: 1.0, 3: 1.0},
}
OPTIMAL_4 = {0: 1, 1: 2, 2: 3, 3: 0}  # unique optimum, total 30


def test_line_topology_multi_hop_contention():
    # Agents 0 and 3 fight over task 0 from opposite ends of a line: price
    # information has to relay through 1 and 2 (Fig. 2 of the paper).
    topo = line(range(4))
    result = run_round(BENEFITS_4, SimTransport(topo), cfg(topo))
    assert result.assignment == OPTIMAL_4


def test_line_slower_than_complete():
    line_topo, complete_topo = line(range(4)), complete(range(4))
    r_line = run_round(BENEFITS_4, SimTransport(line_topo), cfg(line_topo))
    r_complete = run_round(BENEFITS_4, SimTransport(complete_topo), cfg(complete_topo))
    assert r_line.ticks > r_complete.ticks  # diameter dominates (Prop 3.2)


def test_converges_under_delay():
    topo = complete(range(4))
    result = run_round(
        BENEFITS_4,
        SimTransport(topo, delay_ticks=3, seed=7),
        cfg(topo, max_delay=3),
    )
    assert result.assignment == OPTIMAL_4


@pytest.mark.parametrize("loss", [0.1, 0.3, 0.5])
def test_converges_under_loss(loss):
    topo = complete(range(4))
    result = run_round(
        BENEFITS_4,
        SimTransport(topo, loss_prob=loss, seed=42),
        cfg(topo),
    )
    assert result.assignment == OPTIMAL_4


def test_partition_stalls_then_heals():
    # Ticks 0-9: {0,1} and {2,3} are separate cliques; from tick 10 the
    # network is complete. Both sides independently claim task 0 during the
    # partition; healing must resolve the conflict through outbidding. The
    # quiescence window must outlast the partition — the DTN sizing rule.
    parted = {
        0: frozenset({1}),
        1: frozenset({0}),
        2: frozenset({3}),
        3: frozenset({2}),
    }
    healed = complete(range(4))

    def topology(tick):
        return parted if tick < 10 else healed

    config = RoundConfig(epsilon=0.01, quiescence_rounds=15)
    result = run_round(BENEFITS_4, SimTransport(topology), config)
    assert result.assignment == OPTIMAL_4
