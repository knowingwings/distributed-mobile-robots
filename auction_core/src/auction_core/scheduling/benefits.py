"""Benefit (beta_ij) definition — frozen per round.

All task-attractiveness heuristics live here, OUTSIDE the auction: the
engine sees a constant benefit matrix per round, which is what keeps the
per-round guarantees valid (evaluation requirement 6). Cross-round
adaptivity (workload balancing as robots accumulate work, positions moving)
happens naturally because the model is re-evaluated between rounds.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..types import AgentId, Task, TaskId


@dataclass
class RobotState:
    id: AgentId
    position: tuple[float, ...] = ()
    capabilities: tuple[float, ...] = ()
    speed: float = 1.0
    workload: float = 0.0  # total duration of work already taken this run


def _distance(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    if not a or not b:
        return 0.0
    return math.dist(a, b)


def _capability_similarity(robot: tuple[float, ...], task: tuple[float, ...]) -> float:
    """Cosine similarity (Appendix B section 2.4); neutral 1.0 when either
    side declares no capability profile."""
    if not robot or not task:
        return 1.0
    dot = sum(r * t for r, t in zip(robot, task))
    norm = math.hypot(*robot) * math.hypot(*task)
    return dot / norm if norm > 0 else 0.0


@dataclass(frozen=True)
class BenefitModel:
    """beta_ij = w_dist / (1 + d_ij) + w_cap * s_ij - w_load * normalised load.

    Deliberately small: distance, capability match, workload balance. The
    original 8-term bid formula's extra terms existed to fight broken
    convergence criteria and are gone with the criteria they patched.
    """

    distance_weight: float = 1.0
    capability_weight: float = 1.0
    workload_weight: float = 0.5
    workload_scale: float = 10.0

    def benefit(self, robot: RobotState, task: Task) -> float:
        d = _distance(robot.position, task.position)
        s = _capability_similarity(robot.capabilities, task.capabilities)
        load = robot.workload / self.workload_scale
        return (
            self.distance_weight / (1.0 + d)
            + self.capability_weight * s
            - self.workload_weight * load
        )

    def matrix(
        self, robots: list[RobotState], tasks: list[Task]
    ) -> dict[AgentId, dict[TaskId, float]]:
        return {
            r.id: {t.id: self.benefit(r, t) for t in tasks} for r in robots
        }

    def joint_benefit(
        self,
        me: RobotState,
        task: Task,
        others: dict[AgentId, tuple[float, ...]],
    ) -> float:
        """Bid estimate for a collaborative task: own benefit plus the best
        follower's estimated benefit, from gossiped positions. An estimate,
        not a guarantee — the actual follower is chosen by the recruitment
        auction after winning. With no known others, falls back to the solo
        benefit (the recruitment stage will then wait for a follower)."""
        own = self.benefit(me, task)
        follower_estimates = [
            self.benefit(
                RobotState(id=other_id, position=pos, capabilities=me.capabilities),
                task,
            )
            for other_id, pos in others.items()
            if other_id != me.id
        ]
        return own + (max(follower_estimates) if follower_estimates else 0.0)
