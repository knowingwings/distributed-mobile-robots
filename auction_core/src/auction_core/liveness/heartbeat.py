"""Heartbeat-based failure detection (dissertation Appendix B section 6.1).

Explicit detection: every robot broadcasts a heartbeat each interval dt; a
robot is declared failed when nothing has been heard from it for eta
consecutive intervals (timeout eta * dt). With per-message loss probability
(1 - p_success), the false-positive probability of declaring a live robot
dead is (1 - p_success)^eta — eta trades detection latency against false
positives. Defaults dt = 1.0 s, eta = 3 per the original spec.

Sans-I/O like the auction engine: callers feed observed heartbeats and the
current time; `sweep()` reports state transitions. The same monitor runs
under the system simulator and inside the ROS node.

A robot unseen since before the monitor started is only declared failed
after it has first been seen (unknown robots are not "dead", they are
undiscovered — the mission layer decides team membership).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..types import AgentId


@dataclass
class LivenessUpdate:
    """State transitions found by a sweep."""

    failed: list[AgentId] = field(default_factory=list)
    recovered: list[AgentId] = field(default_factory=list)


class HeartbeatMonitor:
    def __init__(self, interval: float = 1.0, eta: int = 3):
        if interval <= 0 or eta < 1:
            raise ValueError("interval must be > 0 and eta >= 1")
        self.timeout = eta * interval
        self._last_seen: dict[AgentId, float] = {}
        self._alive: dict[AgentId, bool] = {}

    def record(self, robot: AgentId, now: float) -> None:
        prev = self._last_seen.get(robot)
        if prev is None or now > prev:
            self._last_seen[robot] = now

    def sweep(self, now: float) -> LivenessUpdate:
        """Re-evaluate liveness; returns robots that changed state. A robot
        heard from again after being declared failed is reported recovered
        (partial-failure semantics are the mission layer's concern)."""
        update = LivenessUpdate()
        for robot, last_seen in self._last_seen.items():
            alive_now = (now - last_seen) <= self.timeout
            alive_before = self._alive.get(robot)
            if alive_before is None:
                self._alive[robot] = alive_now
                if not alive_now:
                    update.failed.append(robot)
                continue
            if alive_now != alive_before:
                self._alive[robot] = alive_now
                (update.recovered if alive_now else update.failed).append(robot)
        return update

    def alive(self, now: float) -> set[AgentId]:
        return {
            robot
            for robot, last_seen in self._last_seen.items()
            if (now - last_seen) <= self.timeout
        }

    def is_alive(self, robot: AgentId, now: float) -> bool:
        last_seen = self._last_seen.get(robot)
        return last_seen is not None and (now - last_seen) <= self.timeout
