"""
Phase 11 — Historical Backtesting & Evaluation Harness REST API Routes

FastAPI router exposing endpoints for launching historical replay runs,
inspecting performance metrics, trade ledgers, equity curves, attributions,
and audit reports.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.domain.evaluation_harness_schemas import (
    HistoricalEvaluationConfig,
    HistoricalEvaluationReport,
    HistoricalTradeRecord,
    EquityCurvePoint,
    PerformanceMetrics,
    RiskMetrics,
    PerformanceAttribution,
)
from backend.application.evaluation_harness import global_evaluation_harness


router = APIRouter(prefix="/api/evaluation", tags=["Historical Evaluation Harness"])

# In-memory registry of completed evaluation reports
_evaluation_reports: Dict[str, HistoricalEvaluationReport] = {}


class EvaluationRunRequest(BaseModel):
    """Payload for triggering an evaluation run."""
    config: Optional[HistoricalEvaluationConfig] = None
    symbols: Optional[List[str]] = None


@router.post("/run", response_model=HistoricalEvaluationReport)
def trigger_evaluation(req: Optional[EvaluationRunRequest] = None) -> HistoricalEvaluationReport:
    """
    Trigger a historical evaluation replay run.
    Uses point-in-time fixtures or specified historical dataset.
    """
    cfg = req.config if req and req.config else HistoricalEvaluationConfig()
    symbols = req.symbols if req and req.symbols else ["RELIANCE.NS", "TCS.NS", "INFY.NS"]

    # Build standard deterministic historical dataset fixture if not passed
    base_ts = datetime.now(timezone.utc)
    dataset: Dict[str, List[Dict[str, Any]]] = {}

    for sym in symbols:
        bars = []
        base_p = 1000.0 if sym != "TCS.NS" else 3000.0
        for i in range(30):
            bar_ts = base_ts - (30 - i) * __import__("datetime").timedelta(days=1)
            p = base_p + (i * 5.0)
            bars.append({
                "timestamp": bar_ts.isoformat(),
                "open": p - 2.0,
                "high": p + 5.0,
                "low": p - 3.0,
                "close": p,
                "volume": 150000.0,
            })
        dataset[sym] = bars

    report = global_evaluation_harness.run_evaluation(dataset=dataset, config=cfg)
    _evaluation_reports[report.run_id] = report
    return report


@router.get("/runs", response_model=List[Dict[str, Any]])
def list_evaluations() -> List[Dict[str, Any]]:
    """List recent completed historical evaluation runs."""
    summaries = []
    for r_id, rep in _evaluation_reports.items():
        summaries.append({
            "run_id": r_id,
            "started_at": rep.started_at,
            "duration_ms": rep.duration_ms,
            "total_bars": rep.total_bars_evaluated,
            "total_trades": len(rep.trade_ledger),
            "total_return_pct": rep.performance_metrics.total_return_pct,
            "sharpe_ratio": rep.performance_metrics.sharpe_ratio,
            "max_drawdown_pct": rep.performance_metrics.max_drawdown_pct,
            "quality_score": rep.data_quality.quality_score,
        })
    return summaries


@router.get("/runs/{run_id}", response_model=HistoricalEvaluationReport)
def get_evaluation_report(run_id: str) -> HistoricalEvaluationReport:
    """Retrieve full master evaluation report for a given run ID."""
    if run_id not in _evaluation_reports:
        raise HTTPException(status_code=404, detail=f"Evaluation run '{run_id}' not found.")
    return _evaluation_reports[run_id]


@router.get("/runs/{run_id}/ledger", response_model=List[HistoricalTradeRecord])
def get_trade_ledger(run_id: str) -> List[HistoricalTradeRecord]:
    """Retrieve the trade ledger for a specific evaluation run."""
    if run_id not in _evaluation_reports:
        raise HTTPException(status_code=404, detail=f"Evaluation run '{run_id}' not found.")
    return _evaluation_reports[run_id].trade_ledger


@router.get("/runs/{run_id}/equity", response_model=List[EquityCurvePoint])
def get_equity_curve(run_id: str) -> List[EquityCurvePoint]:
    """Retrieve the chronological equity curve for a specific evaluation run."""
    if run_id not in _evaluation_reports:
        raise HTTPException(status_code=404, detail=f"Evaluation run '{run_id}' not found.")
    return _evaluation_reports[run_id].equity_curve


@router.get("/runs/{run_id}/metrics", response_model=Dict[str, Any])
def get_metrics(run_id: str) -> Dict[str, Any]:
    """Retrieve performance and risk metrics for a specific evaluation run."""
    if run_id not in _evaluation_reports:
        raise HTTPException(status_code=404, detail=f"Evaluation run '{run_id}' not found.")
    rep = _evaluation_reports[run_id]
    return {
        "performance": rep.performance_metrics.model_dump(),
        "risk": rep.risk_metrics.model_dump(),
        "benchmark": rep.benchmark_comparison.model_dump(),
    }


@router.get("/runs/{run_id}/attribution", response_model=PerformanceAttribution)
def get_attribution(run_id: str) -> PerformanceAttribution:
    """Retrieve performance attribution (regime, score, conviction) for an evaluation run."""
    if run_id not in _evaluation_reports:
        raise HTTPException(status_code=404, detail=f"Evaluation run '{run_id}' not found.")
    return _evaluation_reports[run_id].attribution
