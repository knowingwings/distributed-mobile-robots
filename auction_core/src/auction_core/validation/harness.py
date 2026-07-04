"""Round harness: wire N agents through a SimTransport and run to quiescence.

This is the validation-side event loop — the same role the ROS 2 wrapper
plays on a robot, which is exactly why it exists: anything proven here about
the engine holds on hardware modulo transport fidelity.

Global termination = every agent quiescent AND no messages in flight. The
harness also verifies assignment consistency (each task held by at most one
agent, and by exactly the agent its converged price table names) — silently
inconsistent allocations were one of the original implementations' failure
modes, so here they raise.
"""

from __future__ import annotations

import math
from typing import Mapping, Optional

from ..types import AgentId, PriceEntry, RoundConfig, RoundResult, TaskId
from ..auction.engine import AuctionAgent
from .transport import SimTransport, Topology, diameter


class RoundDidNotTerminate(RuntimeError):
    pass


class InconsistentAssignment(RuntimeError):
    pass


def suggested_quiescence(
    topology: Topology,
    max_delay_ticks: int,
    loss_prob: float = 0.0,
    failure_odds: float = 1e-9,
) -> int:
    """Quiescence window sized for the communication environment.

    Lossless: diameter hops, each taking at most 1 + max_delay ticks — a
    window that provably outlasts one full propagation.

    With Bernoulli loss, silent-termination agreement is inherently
    probabilistic (two-generals): a conflicting claim survives only if every
    broadcast on the critical link is lost for the whole window, i.e. with
    probability loss^Q. The window is scaled so that chance is below
    failure_odds; the harness's consistency check still raises if the
    improbable happens. Deterministic termination under loss needs
    acknowledgements — that is the phase-2 liveness layer's job, not the
    auction's.
    """
    base = diameter(topology) * (1 + max_delay_ticks) + 1
    if loss_prob <= 0.0:
        return base
    retries = math.ceil(math.log(failure_odds) / math.log(loss_prob))
    return base * max(1, retries)


def run_round(
    benefits: Mapping[AgentId, Mapping[TaskId, float]],
    transport: SimTransport,
    config: RoundConfig,
    *,
    max_ticks: int = 100_000,
) -> RoundResult:
    """Run one distributed auction round to completion.

    benefits: per-agent benefit vector over a COMMON task set, frozen for the
    round (evaluation requirement 6). Requires m >= n; the allocator pads
    with idle tasks when needed.
    """
    task_sets = {frozenset(b.keys()) for b in benefits.values()}
    if len(task_sets) != 1:
        raise ValueError("all agents must bid over the same task set")
    (task_ids,) = task_sets
    if len(task_ids) < len(benefits):
        raise ValueError(
            f"m >= n required: {len(task_ids)} tasks for {len(benefits)} agents"
        )

    agents = {
        agent_id: AuctionAgent(agent_id, b, config) for agent_id, b in benefits.items()
    }

    tick = 0
    while True:
        if tick >= max_ticks:
            raise RoundDidNotTerminate(
                f"no quiescence after {max_ticks} ticks "
                f"(n={len(agents)}, m={len(task_ids)}, eps={config.epsilon})"
            )
        for dest, message in transport.deliver_due(tick):
            if dest not in agents:
                raise ValueError(
                    f"transport delivered to agent {dest}, which is not in "
                    f"this round — build the topology over the round's "
                    f"participants ({sorted(agents)})"
                )
            agents[dest].handle_message(message)
        for agent in agents.values():
            for message in agent.tick():
                transport.send(message, tick)
        if transport.idle and all(a.terminated for a in agents.values()):
            break
        tick += 1

    return RoundResult(
        assignment=_consistent_assignment(agents),
        ticks=tick,
        messages_sent=transport.messages_sent,
        prices=_merged_prices(agents),
    )


def _merged_prices(agents: Mapping[AgentId, AuctionAgent]) -> dict[TaskId, PriceEntry]:
    merged: dict[TaskId, PriceEntry] = {}
    for agent in agents.values():
        for task_id, entry in agent.prices.snapshot().items():
            current = merged.get(task_id)
            merged[task_id] = entry if current is None else max(current, entry)
    return merged


def _consistent_assignment(
    agents: Mapping[AgentId, AuctionAgent],
) -> dict[AgentId, Optional[TaskId]]:
    """Cross-check each agent's claimed task against the converged global
    price table; at quiescence with empty queues these must agree."""
    global_prices = _merged_prices(agents)
    assignment: dict[AgentId, Optional[TaskId]] = {}
    holders: dict[TaskId, AgentId] = {}
    for agent_id, agent in agents.items():
        task = agent.assignment
        assignment[agent_id] = task
        if task is None:
            continue
        if global_prices[task].bidder != agent_id:
            raise InconsistentAssignment(
                f"agent {agent_id} believes it holds task {task}, but the "
                f"converged highest bidder is {global_prices[task].bidder}"
            )
        if task in holders:
            raise InconsistentAssignment(
                f"task {task} claimed by both {holders[task]} and {agent_id}"
            )
        holders[task] = agent_id
    return assignment
