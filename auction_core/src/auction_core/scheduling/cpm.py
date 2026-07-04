"""Critical path method and the makespan lower bound.

Appendix B sections 7.4 and 3.3 — the parts of the original maths that were
correct and are adopted as-is. The lower bound is what allocator results are
reported against (never as an "optimality gap": it is a bound, not an
optimum — conflating the two produced the dissertation's negative gaps).
"""

from __future__ import annotations

from .dag import TaskDag


def critical_path_length(dag: TaskDag) -> float:
    """Length (total duration) of the longest dependency chain."""
    earliest_finish: dict[int, float] = {}

    def finish(tid: int) -> float:
        if tid not in earliest_finish:
            task = dag.tasks[tid]
            start = max(
                (finish(p) for p in task.prerequisites), default=0.0
            )
            earliest_finish[tid] = start + task.duration
        return earliest_finish[tid]

    return max((finish(tid) for tid in dag.tasks), default=0.0)


def makespan_lower_bound(dag: TaskDag, num_robots: int) -> float:
    """max(mean load per robot, longest single task, critical path)."""
    durations = [t.duration for t in dag.tasks.values()]
    if not durations:
        return 0.0
    return max(
        sum(durations) / num_robots,
        max(durations),
        critical_path_length(dag),
    )
