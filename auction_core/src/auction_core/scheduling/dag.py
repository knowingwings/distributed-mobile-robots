"""Task dependency DAG and the availability set (Appendix B section 7.2).

A task is available once all its prerequisites are complete. The allocator
re-auctions whenever the availability set or the idle-robot set changes;
this module just answers "what can run now".
"""

from __future__ import annotations

from typing import Iterable, Mapping

from ..types import Task, TaskId


class DependencyCycle(ValueError):
    pass


class TaskDag:
    def __init__(self, tasks: Iterable[Task]):
        self.tasks: Mapping[TaskId, Task] = {t.id: t for t in tasks}
        for task in self.tasks.values():
            missing = task.prerequisites - self.tasks.keys()
            if missing:
                raise ValueError(f"task {task.id} depends on unknown tasks {missing}")
        self._topological_order()  # raises DependencyCycle if cyclic

    def _topological_order(self) -> list[TaskId]:
        in_degree = {tid: len(t.prerequisites) for tid, t in self.tasks.items()}
        frontier = [tid for tid, deg in in_degree.items() if deg == 0]
        order: list[TaskId] = []
        while frontier:
            tid = frontier.pop()
            order.append(tid)
            for other in self.tasks.values():
                if tid in other.prerequisites:
                    in_degree[other.id] -= 1
                    if in_degree[other.id] == 0:
                        frontier.append(other.id)
        if len(order) != len(self.tasks):
            raise DependencyCycle("task dependencies contain a cycle")
        return order

    def available(self, completed: frozenset[TaskId] | set[TaskId]) -> set[TaskId]:
        return {
            tid
            for tid, task in self.tasks.items()
            if tid not in completed and task.prerequisites <= set(completed)
        }

    def dependents(self, task_id: TaskId) -> set[TaskId]:
        """Transitive closure of tasks that (directly or not) require task_id."""
        out: set[TaskId] = set()
        frontier = {task_id}
        while frontier:
            frontier = {
                t.id
                for t in self.tasks.values()
                if t.id not in out and (t.prerequisites & frontier)
            }
            out |= frontier
        return out
