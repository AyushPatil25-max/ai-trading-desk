"""
Phase 24 — Application Layer Safety Engine Adapter

Re-exports and delegates all safety engine components from backend.execution.safety_engine.
Maintains unified access for both backend.application and backend.execution paths.
"""

from backend.execution.safety_engine import (
    KillSwitch,
    DuplicateTracker,
    ExecutionSafetyEngine,
    ManualOrderSafetyGate,
    global_manual_order_safety_gate,
    global_kill_switch,
    global_execution_safety_engine,
    check_manual_order_safety,
    build_dhan_order_payload,
)

global_safety_engine = global_execution_safety_engine

__all__ = [
    "KillSwitch",
    "DuplicateTracker",
    "ExecutionSafetyEngine",
    "ManualOrderSafetyGate",
    "global_manual_order_safety_gate",
    "global_kill_switch",
    "global_execution_safety_engine",
    "global_safety_engine",
    "check_manual_order_safety",
    "build_dhan_order_payload",
]
