"""
Phase 24 — Deterministic Historical Replay & Walk-Forward Validation REST API Routes

Endpoints for triggering historical replays, walk-forward validations, inspecting
equity curves, trade ledgers, reproducibility fingerprints, and execution assumptions.

Safety Invariant:
- STRICTLY HISTORICAL / REPLAY / SIMULATION.
- Zero real-money order submission authority.
- TIER_4_LIVE_REAL_MONEY remains permanently locked, unroutable, and fail-closed.
"""

from datetime import datetime, timezone, timedelta
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.domain.replay_schemas import (
    DeterministicBacktestResult,
    ExecutionAssumptions,
    HistoricalDataPoint,
    ReplayConfig,
    ReplayMode,
    WalkForwardPartition,
)
from backend.application.deterministic_replay_engine import global_replay_engine

logger = logging.getLogger(__name__)

replay_router = APIRouter(
    prefix="/api/replay",
    tags=["Deterministic Historical Replay & Walk-Forward Validation"],
)


# ── Request Models ────────────────────────────────────────────────────────────

class ReplayRunRequest(BaseModel):
    """Payload for triggering a deterministic historical replay."""
    config: Optional[ReplayConfig] = None
    symbols: Optional[List[str]] = None
    bars_per_symbol: int = Field(default=30, ge=5, le=500)
    dataset: Optional[Dict[str, List[Dict[str, Any]]]] = None


class WalkForwardRequest(BaseModel):
    """Payload for triggering walk-forward cross validation."""
    config: Optional[ReplayConfig] = None
    symbols: Optional[List[str]] = None
    bars_per_symbol: int = Field(default=50, ge=30, le=500)
    dataset: Optional[Dict[str, List[Dict[str, Any]]]] = None


# ── Helper Fixture Generator ──────────────────────────────────────────────────

def _generate_deterministic_fixtures(symbols: List[str], bars_count: int) -> Dict[str, List[Dict[str, Any]]]:
    """Generate a clean, deterministic chronological OHLCV dataset fixture."""
    base_ts = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
    dataset: Dict[str, List[Dict[str, Any]]] = {}

    for sym in symbols:
        bars = []
        base_p = 1000.0 if "RELIANCE" in sym else (3500.0 if "TCS" in sym else 1500.0)
        for i in range(bars_count):
            bar_ts = base_ts + timedelta(days=i)
            # Deterministic wave pattern
            drift = math_sin = 15.0 * (1.0 if (i % 6) < 3 else -0.8)
            p = base_p + (i * 2.5) + drift
            bars.append({
                "symbol": sym,
                "event_timestamp": bar_ts.isoformat(),
                "open": round(p - 3.0, 2),
                "high": round(p + 6.0, 2),
                "low": round(p - 5.0, 2),
                "close": round(p + 1.0, 2),
                "volume": 25000.0 + (i * 500.0),
            })
        dataset[sym] = bars

    return dataset


# ── REST Endpoints ────────────────────────────────────────────────────────────

@replay_router.post("/run", response_model=DeterministicBacktestResult)
def trigger_historical_replay(req: Optional[ReplayRunRequest] = None) -> DeterministicBacktestResult:
    """
    Execute a deterministic historical replay across a multi-symbol dataset.
    If no dataset is provided, uses a deterministic point-in-time fixture.
    """
    cfg = req.config if req and req.config else ReplayConfig()
    symbols = req.symbols if req and req.symbols else cfg.symbols
    cfg.symbols = symbols

    bars_count = req.bars_per_symbol if req else 30
    dataset = req.dataset if req and req.dataset else _generate_deterministic_fixtures(symbols, bars_count)

    result = global_replay_engine.run_replay(dataset=dataset, config=cfg)
    return result


@replay_router.post("/walk-forward", response_model=DeterministicBacktestResult)
def trigger_walk_forward_validation(req: Optional[WalkForwardRequest] = None) -> DeterministicBacktestResult:
    """
    Execute walk-forward cross validation across chronological window partitions.
    Separates IN_SAMPLE from OUT_OF_SAMPLE without parameter retraining leakage.
    """
    cfg = req.config if req and req.config else ReplayConfig(walk_forward_enabled=True)
    symbols = req.symbols if req and req.symbols else cfg.symbols
    cfg.symbols = symbols
    cfg.walk_forward_enabled = True

    bars_count = req.bars_per_symbol if req else 50
    dataset = req.dataset if req and req.dataset else _generate_deterministic_fixtures(symbols, bars_count)

    result = global_replay_engine.run_walk_forward(dataset=dataset, config=cfg)
    return result


@replay_router.get("/runs")
def list_replay_runs() -> Dict[str, Any]:
    """List summaries and reproducibility fingerprints for all completed replay runs."""
    runs = global_replay_engine.list_results()
    return {
        "count": len(runs),
        "runs": runs,
        "mode": "HISTORICAL_REPLAY_SIMULATION",
        "live_trading_permanently_locked": True,
    }


@replay_router.get("/runs/{run_id}", response_model=DeterministicBacktestResult)
def get_replay_run(run_id: str) -> DeterministicBacktestResult:
    """Retrieve full deterministic backtest report by run ID."""
    result = global_replay_engine.get_result(run_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Replay run '{run_id}' not found")
    return result


@replay_router.get("/fingerprint/{run_id}")
def get_run_fingerprint(run_id: str) -> Dict[str, Any]:
    """Retrieve reproducibility fingerprint and parameter hash for a backtest run."""
    result = global_replay_engine.get_result(run_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Replay run '{run_id}' not found")
    return {
        "run_id": result.run_id,
        "fingerprint": result.fingerprint,
        "seed": result.config.seed,
        "symbols": result.symbols,
        "initial_capital": result.initial_capital,
        "final_equity": result.final_equity,
        "audit_status": result.audit_status,
        "mode": result.mode,
    }


@replay_router.get("/config")
def get_default_replay_configuration() -> Dict[str, Any]:
    """Inspect default execution assumptions, cost parameters, and safety constraints."""
    assumptions = ExecutionAssumptions()
    return {
        "assumptions": assumptions.model_dump(),
        "total_roundtrip_cost_pct": assumptions.total_roundtrip_cost_pct,
        "live_money_execution": "LOCKED",
        "mode": "HISTORICAL_SIMULATION_ONLY",
    }
