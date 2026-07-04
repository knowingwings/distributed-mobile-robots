"""auction_core: platform-agnostic distributed auction task allocation.

Layers:
- auction:    the provable per-round assignment engine (Zavlanos Algorithm 1)
- scheduling: task DAG, critical path, benefit definition
- allocator:  strategies composing rounds into full multi-task allocations
- validation: reference solver, simulated transport, experiment harness
"""

from .types import (
    AgentId,
    NO_BIDDER,
    PriceEntry,
    PriceTableMessage,
    RoundConfig,
    RoundResult,
    Task,
    TaskId,
)

__all__ = [
    "AgentId",
    "NO_BIDDER",
    "PriceEntry",
    "PriceTableMessage",
    "RoundConfig",
    "RoundResult",
    "Task",
    "TaskId",
]
