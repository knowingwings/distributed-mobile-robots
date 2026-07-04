"""Allocator interface: strategies that compose auction rounds into a full
multi-task allocation. RepeatedRoundsAllocator is v1; an SSI-style allocator
slots in behind the same interface later for head-to-head comparison."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Mapping, Optional

from ..types import AgentId, RoundConfig, RoundResult, Task, TaskId
from ..scheduling.benefits import RobotState

# A round runner executes one frozen-benefit auction round and returns the
# result. The validation harness provides one backed by SimTransport; the
# future ROS 2 wrapper provides one backed by real communication.
RoundRunner = Callable[
    [Mapping[AgentId, Mapping[TaskId, float]], RoundConfig], RoundResult
]


@dataclass
class ScheduledTask:
    task_id: TaskId
    robot_id: AgentId
    start: float
    finish: float


@dataclass
class AllocationResult:
    schedule: list[ScheduledTask]
    makespan: float
    rounds: int
    total_messages: int
    # Tasks this allocator cannot handle (v1: collaborative ones), plus any
    # tasks blocked behind them in the DAG. Reported, never silently dropped.
    unallocated: dict[TaskId, str] = field(default_factory=dict)
    # Communication ticks spent allocating (benchmark metric; 0 where the
    # allocator's host, not the allocator, owns the clock).
    allocation_ticks: int = 0


class Allocator(ABC):
    @abstractmethod
    def allocate(
        self, robots: list[RobotState], tasks: list[Task]
    ) -> AllocationResult:
        ...
