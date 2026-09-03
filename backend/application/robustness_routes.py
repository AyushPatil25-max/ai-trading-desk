"""
Phase 25 — Strategy Robustness & Monte Carlo Validation REST API Routes

Endpoints for parameter sensitivity surfaces, market regime attributions,
Monte Carlo percentiles, bootstrap confidence intervals, execution friction stress tests,
symbol concentration, leave-one-out cross validation, and the 12-category Unified Robustness Scorecard.

Safety Invariant:
- Real-money live trading remains permanently locked and fail-closed.
- Zero live order execution authority.
"""

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.domain.replay_schemas import ReplayConfig
from backend.domain.robustness_schemas import (
    BootstrapConfidenceInterval,
    FrictionStressResult,
    LeaveOneOutResult,
    MarketStressResult,
    MonteCarloPercentiles,
    ParameterSensitivitySurface,
    RegimePerformanceAttribution,
    RobustnessAnalysisReport,
    RobustnessAnalysisRequest,
    RobustnessScorecard,
    SymbolContribution,
)
from backend.application.strategy_robustness_engine import (
    StrategyRobustnessEngine,
    global_robustness_engine,
)

robustness_router = APIRouter(prefix="/api/robustness", tags=["Strategy Robustness & Validation"])


def _generate_synthetic_robustness_dataset(symbols: List[str], bars_count: int = 35) -> Dict[str, List[Dict[str, Any]]]:
    """Generate deterministic synthetic multi-symbol fixture for robustness analysis."""
    base_ts = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
    dataset: Dict[str, List[Dict[str, Any]]] = {}
    base_prices = {"TCS.NS": 3500.0, "RELIANCE.NS": 2500.0, "INFY.NS": 1500.0, "HDFCBANK.NS": 1600.0}

    for sym in symbols:
        p0 = base_prices.get(sym, 2000.0)
        bars: List[Dict[str, Any]] = []
        for i in range(bars_count):
            t = base_ts + timedelta(days=i)
            # Deterministic wave pattern
            drift = 8.0 * (1 if (i % 6) < 3 else -1)
            p = p0 + (i * 3.0) + drift
            bars.append({
                "symbol": sym,
                "event_timestamp": t.isoformat(),
                "open": p - 4.0,
                "high": p + 10.0,
                "low": p - 6.0,
                "close": p + 2.0,
                "volume": 25000.0 + (i * 200.0),
            })
        dataset[sym] = bars
    return dataset


@robustness_router.get("/status")
def get_robustness_status() -> Dict[str, Any]:
    """Get system readiness and safety configuration for Strategy Robustness & Validation."""
    return {
        "status": "OPERATIONAL",
        "mode": "RESEARCH_AND_VALIDATION_SIMULATION_ONLY",
        "live_money_execution": "LOCKED",
        "tier_4_live_real_money": "FAIL_CLOSED",
        "evaluations_completed": len(global_robustness_engine.list_reports()),
        "schema_version": "25.0.0",
    }


@robustness_router.post("/analyze", response_model=RobustnessAnalysisReport)
def trigger_robustness_analysis(request: Optional[RobustnessAnalysisRequest] = None) -> RobustnessAnalysisReport:
    """Execute complete strategy robustness analysis across all 10 evaluation dimensions."""
    req = request or RobustnessAnalysisRequest()
    dataset = req.dataset
    if not dataset:
        dataset = _generate_synthetic_robustness_dataset(req.symbols, req.bars_per_symbol)

    cfg = ReplayConfig(
        symbols=req.symbols,
        seed=req.seed,
        holding_period_bars=5,
    )

    report = global_robustness_engine.analyze_strategy(
        dataset=dataset,
        config=cfg,
        monte_carlo_iterations=req.monte_carlo_iterations,
        seed=req.seed,
    )
    return report


@robustness_router.get("/reports")
def list_robustness_reports() -> Dict[str, Any]:
    """List completed robustness reports."""
    reports = global_robustness_engine.list_reports()
    return {"count": len(reports), "reports": reports}


@robustness_router.get("/report/{analysis_id}", response_model=RobustnessAnalysisReport)
def get_robustness_report(analysis_id: str) -> RobustnessAnalysisReport:
    """Retrieve full robustness analysis report by analysis ID."""
    report = global_robustness_engine.get_report(analysis_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"Robustness report '{analysis_id}' not found.")
    return report


@robustness_router.get("/scorecard/{analysis_id}", response_model=RobustnessScorecard)
def get_robustness_scorecard(analysis_id: str) -> RobustnessScorecard:
    """Retrieve the Unified 12-Category Robustness Scorecard."""
    report = global_robustness_engine.get_report(analysis_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"Robustness report '{analysis_id}' not found.")
    return report.scorecard


@robustness_router.get("/sensitivity/{analysis_id}", response_model=List[ParameterSensitivitySurface])
def get_parameter_sensitivity(analysis_id: str) -> List[ParameterSensitivitySurface]:
    """Retrieve parameter sensitivity surfaces."""
    report = global_robustness_engine.get_report(analysis_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"Robustness report '{analysis_id}' not found.")
    return report.sensitivity


@robustness_router.get("/regimes/{analysis_id}", response_model=List[RegimePerformanceAttribution])
def get_regime_attributions(analysis_id: str) -> List[RegimePerformanceAttribution]:
    """Retrieve Point-in-Time market regime performance attributions."""
    report = global_robustness_engine.get_report(analysis_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"Robustness report '{analysis_id}' not found.")
    return report.regimes


@robustness_router.get("/monte-carlo/{analysis_id}", response_model=MonteCarloPercentiles)
def get_monte_carlo_results(analysis_id: str) -> MonteCarloPercentiles:
    """Retrieve Monte Carlo trade-sequence percentile distributions."""
    report = global_robustness_engine.get_report(analysis_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"Robustness report '{analysis_id}' not found.")
    return report.monte_carlo


@robustness_router.get("/bootstrap/{analysis_id}", response_model=List[BootstrapConfidenceInterval])
def get_bootstrap_cis(analysis_id: str) -> List[BootstrapConfidenceInterval]:
    """Retrieve bootstrap 95% confidence intervals."""
    report = global_robustness_engine.get_report(analysis_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"Robustness report '{analysis_id}' not found.")
    return report.bootstrap


@robustness_router.get("/stress/{analysis_id}")
def get_stress_results(analysis_id: str) -> Dict[str, Any]:
    """Retrieve execution friction and market stress test results."""
    report = global_robustness_engine.get_report(analysis_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"Robustness report '{analysis_id}' not found.")
    return {
        "friction_stress": report.friction_stress,
        "market_stress": report.market_stress,
    }


@robustness_router.get("/symbols/{analysis_id}")
def get_symbol_robustness(analysis_id: str) -> Dict[str, Any]:
    """Retrieve symbol concentration and Leave-One-Out (LOSO) results."""
    report = global_robustness_engine.get_report(analysis_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"Robustness report '{analysis_id}' not found.")
    return {
        "symbol_contributions": report.symbol_contributions,
        "leave_one_out": report.leave_one_out,
    }
