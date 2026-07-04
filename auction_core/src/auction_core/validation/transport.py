"""Simulated transport: topology, delay, loss, partitions.

Models the communication environment the theory cares about — the network
diameter (multi-hop propagation), per-link delays, Bernoulli packet loss,
and time-varying connectivity (partitions) — without any physics. Delays are
measured in ticks (one tick = one auction iteration = one communication
cycle); the experiment layer maps milliseconds onto ticks.

Everything is seeded and deterministic: the same seed replays the same
message weather, which property-based tests rely on.
"""

from __future__ import annotations

import heapq
import itertools
import random
from typing import Callable, Iterable, Mapping

from ..types import AgentId, PriceTableMessage

Topology = Mapping[AgentId, frozenset[AgentId]]
# A time-varying topology: tick -> adjacency. Constant topologies are wrapped.
TopologyFn = Callable[[int], Topology]


def complete(agent_ids: Iterable[AgentId]) -> Topology:
    ids = frozenset(agent_ids)
    return {i: ids - {i} for i in ids}


def line(agent_ids: Iterable[AgentId]) -> Topology:
    """Worst-case diameter: agents connected in index order."""
    ids = sorted(agent_ids)
    adj: dict[AgentId, set[AgentId]] = {i: set() for i in ids}
    for a, b in itertools.pairwise(ids):
        adj[a].add(b)
        adj[b].add(a)
    return {i: frozenset(n) for i, n in adj.items()}


def random_connected(agent_ids: Iterable[AgentId], edge_prob: float, rng: random.Random) -> Topology:
    """Random graph forced connected by seeding a random spanning path."""
    ids = sorted(agent_ids)
    order = ids[:]
    rng.shuffle(order)
    adj: dict[AgentId, set[AgentId]] = {i: set() for i in ids}
    for a, b in itertools.pairwise(order):
        adj[a].add(b)
        adj[b].add(a)
    for a, b in itertools.combinations(ids, 2):
        if b not in adj[a] and rng.random() < edge_prob:
            adj[a].add(b)
            adj[b].add(a)
    return {i: frozenset(n) for i, n in adj.items()}


def diameter(topology: Topology) -> int:
    """BFS all-pairs longest shortest path. Raises if disconnected."""
    best = 0
    for source in topology:
        dist = {source: 0}
        frontier = [source]
        while frontier:
            nxt = []
            for node in frontier:
                for neigh in topology[node]:
                    if neigh not in dist:
                        dist[neigh] = dist[node] + 1
                        nxt.append(neigh)
            frontier = nxt
        if len(dist) != len(topology):
            raise ValueError("topology is disconnected")
        best = max(best, max(dist.values()))
    return max(best, 1)


class SimTransport:
    """Broadcast-to-neighbours message fabric with loss and delay.

    delay_ticks: constant int, or a callable (rng) -> int sampled per message.
    loss_prob: independent Bernoulli drop per (message, link).
    topology: constant adjacency or a TopologyFn for partitions/mobility.
    """

    def __init__(
        self,
        topology: Topology | TopologyFn,
        *,
        delay_ticks: int | Callable[[random.Random], int] = 0,
        loss_prob: float = 0.0,
        seed: int = 0,
    ):
        self._topology_fn: TopologyFn = (
            topology if callable(topology) else (lambda _tick, _t=topology: _t)
        )
        self._delay = delay_ticks
        self._loss = loss_prob
        self._rng = random.Random(seed)
        self._queue: list[tuple[int, int, AgentId, PriceTableMessage]] = []
        self._seq = itertools.count()  # heap tie-break, keeps FIFO per deliver-tick
        self.messages_sent = 0

    def send(self, message: PriceTableMessage, now: int) -> None:
        """Broadcast to the sender's current neighbours."""
        neighbours = self._topology_fn(now).get(message.sender, frozenset())
        for dest in neighbours:
            self.messages_sent += 1
            if self._rng.random() < self._loss:
                continue
            delay = self._delay(self._rng) if callable(self._delay) else self._delay
            deliver_at = now + 1 + max(0, delay)
            heapq.heappush(self._queue, (deliver_at, next(self._seq), dest, message))

    def deliver_due(self, now: int) -> list[tuple[AgentId, PriceTableMessage]]:
        due = []
        while self._queue and self._queue[0][0] <= now:
            _, _, dest, message = heapq.heappop(self._queue)
            due.append((dest, message))
        return due

    @property
    def idle(self) -> bool:
        return not self._queue
