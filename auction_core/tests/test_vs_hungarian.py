"""Property-based verification of the theoretical guarantees.

Randomised instances (benefits, topology, delay, loss, epsilon) must always:
  - terminate,
  - land within n*epsilon of the Hungarian optimum on the same matrix,
  - match the optimum exactly for integer benefits with epsilon < 1/n,
  - satisfy epsilon-complementary slackness at the converged prices.

This suite is the machine that would have caught every anomaly in the
original implementations.
"""

import random

from hypothesis import given, settings, strategies as st

from auction_core.types import RoundConfig
from auction_core.validation.harness import run_round, suggested_quiescence
from auction_core.validation.hungarian import optimal_assignment, total_benefit
from auction_core.validation.transport import (
    SimTransport,
    complete,
    line,
    random_connected,
)

FLOAT_TOL = 1e-9


@st.composite
def instances(draw, integer_benefits=False):
    n = draw(st.integers(min_value=2, max_value=5))
    m = draw(st.integers(min_value=n, max_value=n + 4))
    if integer_benefits:
        benefit = st.integers(min_value=0, max_value=10).map(float)
    else:
        benefit = st.floats(
            min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False
        )
    benefits = {
        a: {t: draw(benefit) for t in range(m)} for a in range(n)
    }
    topo_kind = draw(st.sampled_from(["complete", "line", "random"]))
    topo_seed = draw(st.integers(min_value=0, max_value=2**16))
    if topo_kind == "complete":
        topology = complete(range(n))
    elif topo_kind == "line":
        topology = line(range(n))
    else:
        topology = random_connected(range(n), 0.4, random.Random(topo_seed))
    delay = draw(st.integers(min_value=0, max_value=3))
    loss = draw(st.floats(min_value=0.0, max_value=0.5))
    seed = draw(st.integers(min_value=0, max_value=2**16))
    return benefits, topology, delay, loss, seed


def run(benefits, topology, delay, loss, seed, epsilon):
    config = RoundConfig(
        epsilon=epsilon,
        quiescence_rounds=suggested_quiescence(topology, delay),
    )
    transport = SimTransport(
        topology, delay_ticks=delay, loss_prob=loss, seed=seed
    )
    return config, run_round(benefits, transport, config, max_ticks=200_000)


@settings(max_examples=150, deadline=None)
@given(data=instances(), epsilon=st.floats(min_value=0.01, max_value=0.5))
def test_within_n_epsilon_of_optimal(data, epsilon):
    benefits, topology, delay, loss, seed = data
    _, result = run(benefits, topology, delay, loss, seed, epsilon)
    achieved = total_benefit(benefits, result.assignment)
    _, optimum = optimal_assignment(benefits)
    n = len(benefits)
    assert achieved >= optimum - n * epsilon - FLOAT_TOL
    # Everyone ends up assigned: no premature convergence, ever.
    assert all(t is not None for t in result.assignment.values())


@settings(max_examples=75, deadline=None)
@given(data=instances(integer_benefits=True))
def test_integer_benefits_exact_optimum(data):
    benefits, topology, delay, loss, seed = data
    n = len(benefits)
    epsilon = 0.9 / n  # n * epsilon < 1 forces exact optimality
    _, result = run(benefits, topology, delay, loss, seed, epsilon)
    achieved = total_benefit(benefits, result.assignment)
    _, optimum = optimal_assignment(benefits)
    assert abs(achieved - optimum) < FLOAT_TOL


@settings(max_examples=75, deadline=None)
@given(data=instances(), epsilon=st.floats(min_value=0.01, max_value=0.5))
def test_epsilon_complementary_slackness(data, epsilon):
    # Definition 4.1 / condition (2) of the paper, checked at the converged
    # global prices: every agent's net value is within epsilon of the best
    # available anywhere. This is the condition the original price rule
    # violated at the very first assignment.
    benefits, topology, delay, loss, seed = data
    _, result = run(benefits, topology, delay, loss, seed, epsilon)
    prices = {t: e.price for t, e in result.prices.items()}
    for agent, task in result.assignment.items():
        assert task is not None
        held = benefits[agent][task] - prices[task]
        best = max(benefits[agent][t] - prices[t] for t in prices)
        assert held >= best - epsilon - FLOAT_TOL
