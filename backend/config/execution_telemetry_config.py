"""
Phase 32 — Execution Telemetry & Drift Observability Configuration

Provides configurable, bounds-checked thresholds for latency profiling,
health metrics, drift detection, and in-memory retention limits.

Safety Invariants:
- All values are bounds-checked with safe, deterministic fallbacks.
- Invalid configuration fails closed to conservative operational limits.
- Telemetry thresholds NEVER modify execution logic or bypass safety controls.
"""

import os
from typing import Any, Dict


# ── Default Thresholds ────────────────────────────────────────────────────────

DEFAULT_EXECUTION_LATENCY_WARN_MS = 50.0      # 50ms warning for internal pipeline
DEFAULT_EXECUTION_LATENCY_CRITICAL_MS = 200.0  # 200ms critical threshold
DEFAULT_BROKER_LATENCY_WARN_MS = 500.0        # 500ms warning for broker I/O
DEFAULT_BROKER_LATENCY_CRITICAL_MS = 2000.0    # 2000ms critical threshold
DEFAULT_EXECUTION_ERROR_RATE_WARN = 0.05       # 5% error rate warning
DEFAULT_EXECUTION_ERROR_RATE_CRITICAL = 0.15   # 15% error rate critical
DEFAULT_TELEMETRY_RETENTION_LIMIT = 1000       # Bounded in-memory records
DEFAULT_DRIFT_BASELINE_WINDOW = 50             # Number of samples for baseline
DEFAULT_DRIFT_SENSITIVITY_RATIO = 1.5          # 1.5x shift triggers drift alert


def get_execution_latency_warn_ms() -> float:
    try:
        val = float(os.getenv("EXECUTION_LATENCY_WARN_MS", DEFAULT_EXECUTION_LATENCY_WARN_MS))
        return max(1.0, min(val, 5000.0))
    except (ValueError, TypeError):
        return DEFAULT_EXECUTION_LATENCY_WARN_MS


def get_execution_latency_critical_ms() -> float:
    try:
        val = float(os.getenv("EXECUTION_LATENCY_CRITICAL_MS", DEFAULT_EXECUTION_LATENCY_CRITICAL_MS))
        return max(5.0, min(val, 10000.0))
    except (ValueError, TypeError):
        return DEFAULT_EXECUTION_LATENCY_CRITICAL_MS


def get_broker_latency_warn_ms() -> float:
    try:
        val = float(os.getenv("BROKER_LATENCY_WARN_MS", DEFAULT_BROKER_LATENCY_WARN_MS))
        return max(10.0, min(val, 15000.0))
    except (ValueError, TypeError):
        return DEFAULT_BROKER_LATENCY_WARN_MS


def get_broker_latency_critical_ms() -> float:
    try:
        val = float(os.getenv("BROKER_LATENCY_CRITICAL_MS", DEFAULT_BROKER_LATENCY_CRITICAL_MS))
        return max(50.0, min(val, 30000.0))
    except (ValueError, TypeError):
        return DEFAULT_BROKER_LATENCY_CRITICAL_MS


def get_execution_error_rate_warn() -> float:
    try:
        val = float(os.getenv("EXECUTION_ERROR_RATE_WARN", DEFAULT_EXECUTION_ERROR_RATE_WARN))
        return max(0.01, min(val, 0.50))
    except (ValueError, TypeError):
        return DEFAULT_EXECUTION_ERROR_RATE_WARN


def get_execution_error_rate_critical() -> float:
    try:
        val = float(os.getenv("EXECUTION_ERROR_RATE_CRITICAL", DEFAULT_EXECUTION_ERROR_RATE_CRITICAL))
        return max(0.05, min(val, 0.90))
    except (ValueError, TypeError):
        return DEFAULT_EXECUTION_ERROR_RATE_CRITICAL


def get_telemetry_retention_limit() -> int:
    try:
        val = int(os.getenv("TELEMETRY_RETENTION_LIMIT", DEFAULT_TELEMETRY_RETENTION_LIMIT))
        return max(100, min(val, 10000))
    except (ValueError, TypeError):
        return DEFAULT_TELEMETRY_RETENTION_LIMIT


def get_drift_baseline_window() -> int:
    try:
        val = int(os.getenv("DRIFT_BASELINE_WINDOW", DEFAULT_DRIFT_BASELINE_WINDOW))
        return max(10, min(val, 500))
    except (ValueError, TypeError):
        return DEFAULT_DRIFT_BASELINE_WINDOW


def get_drift_sensitivity_ratio() -> float:
    try:
        val = float(os.getenv("DRIFT_SENSITIVITY_RATIO", DEFAULT_DRIFT_SENSITIVITY_RATIO))
        return max(1.1, min(val, 5.0))
    except (ValueError, TypeError):
        return DEFAULT_DRIFT_SENSITIVITY_RATIO


def get_all_telemetry_config() -> Dict[str, Any]:
    return {
        "execution_latency_warn_ms": get_execution_latency_warn_ms(),
        "execution_latency_critical_ms": get_execution_latency_critical_ms(),
        "broker_latency_warn_ms": get_broker_latency_warn_ms(),
        "broker_latency_critical_ms": get_broker_latency_critical_ms(),
        "execution_error_rate_warn": get_execution_error_rate_warn(),
        "execution_error_rate_critical": get_execution_error_rate_critical(),
        "telemetry_retention_limit": get_telemetry_retention_limit(),
        "drift_baseline_window": get_drift_baseline_window(),
        "drift_sensitivity_ratio": get_drift_sensitivity_ratio(),
    }
