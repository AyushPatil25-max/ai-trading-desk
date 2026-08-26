"""
Validation API Routes — Phase 5.4

FastAPI endpoints for executing walk-forward strategy validation, querying
out-of-sample performance, leakage reports, attributions, and scorecards.
"""

from datetime import datetime
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.scanner.universe import StockUniverse, UniverseType
from backend.validation.validation_config import WalkForwardConfig
from backend.validation.validation_state import (
    AblationResult,
    CostSensitivityPoint,
    LeakageFinding,
    PerformanceMetrics,
    RobustnessResult,
    SpecialistAttribution,
    ValidationScorecard,
    WalkForwardResult,
    WalkForwardWindow,
)
from backend.validation.walk_forward import WalkForwardEngine

router = APIRouter(prefix="/api/validation", tags=["validation"])

# In-memory validation cache
_validation_results: Dict[str, WalkForwardResult] = {}


class ValidationRequest(BaseModel):
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    universe_type: UniverseType = UniverseType.NIFTY_50
    config: Optional[WalkForwardConfig] = None


@router.post("/walk-forward", response_model=WalkForwardResult)
async def run_walk_forward_validation(request: Optional[ValidationRequest] = None) -> WalkForwardResult:
    """
    Execute out-of-sample walk-forward backtesting and strategy validation.
    """
    req = request or ValidationRequest()
    cfg = req.config or WalkForwardConfig(universe_type=req.universe_type)
    universe = StockUniverse(req.universe_type)
    engine = WalkForwardEngine(config=cfg, universe=universe)

    t0 = req.start_date or datetime(2023, 1, 1)
    t1 = req.end_date or datetime(2024, 1, 1)

    # Standard sample dataset for API verification
    sample_datasets = {
        c.symbol: {
            "current_price": 2500.0,
            "ohlcv_historical": [
                {"timestamp": "2023-03-01 10:00:00", "close": 2400.0},
                {"timestamp": "2023-06-01 10:00:00", "close": 2450.0},
                {"timestamp": "2023-09-01 10:00:00", "close": 2500.0},
                {"timestamp": "2023-12-01 10:00:00", "close": 2550.0},
            ] * 10,
            "technical_indicators": {"ema_20": 2450.0, "ema_50": 2400.0, "rsi_14": 58.0},
            "fundamental_data": {"pe_ratio": 22.0, "net_profit": 5000.0},
            "news_data": {},
            "institutional_data": [],
        }
        for c in universe.get_snapshot(t0).constituents
    }

    try:
        res = await engine.run_walk_forward(sample_datasets, start_date=t0, end_date=t1)
        _validation_results[res.run_id] = res
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Walk-forward validation failed: {str(e)}")


@router.get("/{run_id}", response_model=WalkForwardResult)
async def get_validation_result(run_id: str) -> WalkForwardResult:
    """Retrieve full validation result by run_id."""
    res = _validation_results.get(run_id)
    if not res:
        raise HTTPException(status_code=404, detail=f"Validation run '{run_id}' not found.")
    return res


@router.get("/{run_id}/windows", response_model=List[WalkForwardWindow])
async def get_validation_windows(run_id: str) -> List[WalkForwardWindow]:
    """Retrieve walk-forward window partitions."""
    res = _validation_results.get(run_id)
    if not res:
        raise HTTPException(status_code=404, detail=f"Validation run '{run_id}' not found.")
    return res.windows


@router.get("/{run_id}/performance", response_model=PerformanceMetrics)
async def get_validation_performance(run_id: str) -> PerformanceMetrics:
    """Retrieve overall out-of-sample performance metrics."""
    res = _validation_results.get(run_id)
    if not res:
        raise HTTPException(status_code=404, detail=f"Validation run '{run_id}' not found.")
    return res.overall_out_of_sample_metrics


@router.get("/{run_id}/attribution", response_model=List[SpecialistAttribution])
async def get_specialist_attribution(run_id: str) -> List[SpecialistAttribution]:
    """Retrieve specialist contribution breakdown."""
    res = _validation_results.get(run_id)
    if not res:
        raise HTTPException(status_code=404, detail=f"Validation run '{run_id}' not found.")
    return res.specialist_attribution


@router.get("/{run_id}/leakage", response_model=List[LeakageFinding])
async def get_leakage_findings(run_id: str) -> List[LeakageFinding]:
    """Retrieve all Point-in-Time leakage findings."""
    res = _validation_results.get(run_id)
    if not res:
        raise HTTPException(status_code=404, detail=f"Validation run '{run_id}' not found.")
    findings = []
    for w in res.windows:
        findings.extend(w.leakage_findings)
    return findings


@router.get("/{run_id}/robustness", response_model=List[RobustnessResult])
async def get_robustness_metrics(run_id: str) -> List[RobustnessResult]:
    """Retrieve perturbation robustness metrics."""
    res = _validation_results.get(run_id)
    if not res:
        raise HTTPException(status_code=404, detail=f"Validation run '{run_id}' not found.")
    return res.robustness
