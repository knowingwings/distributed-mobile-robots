"""Hand-checked small instances for the auction engine.

These run the engine over an ideal synchronous complete network (every
message delivered before the next tick) — the transport-free baseline. The
lossy/delayed/multi-hop cases live with the harness tests.
"""

from auction_core.types import RoundConfig
from auction_core.auction.engine import AuctionAgent


def run_synchronous(agents, max_ticks=500):
    """Ideal network: everyone ticks, then all messages reach everyone."""
    ticks = 0
    while not all(a.terminated for a in agents):
        assert ticks < max_ticks, "auction failed to terminate"
        outbox = []
        for a in agents:
            outbox.extend(a.tick())
        for msg in outbox:
            for a in agents:
                a.handle_message(msg)
        ticks += 1
    return ticks


CFG = RoundConfig(epsilon=0.01, quiescence_rounds=2)


def test_uncontested_preferences():
    a0 = AuctionAgent(0, {0: 10.0, 1: 1.0}, CFG)
    a1 = AuctionAgent(1, {0: 1.0, 1: 10.0}, CFG)
    run_synchronous([a0, a1])
    assert a0.assignment == 0
    assert a1.assignment == 1


def test_contention_resolves_to_optimal():
    # Both prefer task 0, but a0 has far more to lose by settling for task 1.
    # Optimal: a0 -> t0, a1 -> t1 (total 15 vs 11). With epsilon = 0.01 the
    # n*eps = 0.02 gap cannot flip a 4.0 margin, so the outcome is forced.
    a0 = AuctionAgent(0, {0: 10.0, 1: 1.0}, CFG)
    a1 = AuctionAgent(1, {0: 10.0, 1: 5.0}, CFG)
    run_synchronous([a0, a1])
    assert a0.assignment == 0
    assert a1.assignment == 1


def test_identical_benefits_tie_breaks_to_max_index():
    # Fully symmetric agents: the max-index rule must give the contested
    # winner deterministically, and both must still end up assigned.
    a0 = AuctionAgent(0, {0: 5.0, 1: 5.0}, CFG)
    a1 = AuctionAgent(1, {0: 5.0, 1: 5.0}, CFG)
    run_synchronous([a0, a1])
    assert {a0.assignment, a1.assignment} == {0, 1}


def test_single_agent_single_task():
    a0 = AuctionAgent(0, {0: 1.0}, CFG)
    run_synchronous([a0])
    assert a0.assignment == 0
    assert a0.prices.price(0) == CFG.epsilon  # gamma = epsilon when no runner-up


def test_negative_benefits_still_assign():
    # Unattractive tasks must still be taken (m >= n): no premature
    # convergence with unassigned tasks — the defect in the original spec.
    a0 = AuctionAgent(0, {0: -1.0, 1: -2.0}, CFG)
    a1 = AuctionAgent(1, {0: -1.0, 1: -2.0}, CFG)
    run_synchronous([a0, a1])
    assert {a0.assignment, a1.assignment} == {0, 1}


def test_three_agents_three_tasks_distinct_optimum():
    # Benefit matrix with a unique optimal perm: (0->2, 1->0, 2->1) = 24.
    b = {
        0: {0: 3.0, 1: 1.0, 2: 9.0},
        1: {0: 8.0, 1: 2.0, 2: 4.0},
        2: {0: 5.0, 1: 7.0, 2: 1.0},
    }
    agents = [AuctionAgent(i, b[i], CFG) for i in range(3)]
    run_synchronous(agents)
    assert [a.assignment for a in agents] == [2, 0, 1]


def test_more_tasks_than_agents():
    # m > n: the two most valuable tasks are taken, the third left unsold.
    a0 = AuctionAgent(0, {0: 9.0, 1: 5.0, 2: 1.0}, CFG)
    a1 = AuctionAgent(1, {0: 9.0, 1: 5.0, 2: 1.0}, CFG)
    run_synchronous([a0, a1])
    assert {a0.assignment, a1.assignment} == {0, 1}
