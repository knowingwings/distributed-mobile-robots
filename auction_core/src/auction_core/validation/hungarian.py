"""Centralised optimal reference via the Hungarian algorithm.

Ground truth for the auction's guarantee: on the SAME frozen benefit matrix,
the distributed round's total benefit must be within n*epsilon of this
optimum. Comparing like with like here is evaluation requirement 9 — the
original project compared makespan against a non-optimal baseline and got
impossible negative gaps.
"""

from __future__ import annotations

from typing import Mapping, Optional

import numpy as np
from scipy.optimize import linear_sum_assignment

from ..types import AgentId, TaskId


def optimal_assignment(
    benefits: Mapping[AgentId, Mapping[TaskId, float]],
) -> tuple[dict[AgentId, Optional[TaskId]], float]:
    """Maximum-total-benefit assignment (m >= n, rectangular OK)."""
    agent_ids = sorted(benefits)
    task_sets = {frozenset(b.keys()) for b in benefits.values()}
    if len(task_sets) != 1:
        raise ValueError("all agents must share one task set")
    task_ids = sorted(next(iter(task_sets)))
    matrix = np.array(
        [[benefits[a][t] for t in task_ids] for a in agent_ids], dtype=float
    )
    rows, cols = linear_sum_assignment(matrix, maximize=True)
    assignment: dict[AgentId, Optional[TaskId]] = {a: None for a in agent_ids}
    for r, c in zip(rows, cols):
        assignment[agent_ids[r]] = task_ids[c]
    return assignment, float(matrix[rows, cols].sum())


def total_benefit(
    benefits: Mapping[AgentId, Mapping[TaskId, float]],
    assignment: Mapping[AgentId, Optional[TaskId]],
) -> float:
    return sum(
        benefits[a][t] for a, t in assignment.items() if t is not None
    )
