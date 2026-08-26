"""
Scanner API Routes — Phase 5.3

FastAPI endpoints for executing opportunity scans, querying ranked candidates,
initiating batch replay, and viewing compute efficiency metrics.
"""

from datetime import datetime
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.scanner.batch_replay import BatchReplayEngine, BatchReplayResult
from backend.scanner.opportunity_scanner import OpportunityScanner, ScannerEfficiencyReport, ScannerResult
from backend.scanner.ranking import CandidateScore
from backend.scanner.scanner_config import ScannerConfig
from backend.scanner.universe import StockUniverse, UniverseType

router = APIRouter(prefix="/api/scanner", tags=["scanner"])

# In-memory result cache
_scanner_results: Dict[str, ScannerResult] = {}
_batch_results: Dict[str, BatchReplayResult] = {}


class ScanRequest(BaseModel):
    universe_type: UniverseType = UniverseType.NIFTY_50
    as_of: Optional[datetime] = None
    config: Optional[ScannerConfig] = None


@router.post("/run", response_model=ScannerResult)
async def run_scanner(request: Optional[ScanRequest] = None) -> ScannerResult:
    """
    Execute a deterministic opportunity scan across the selected universe.
    """
    req = request or ScanRequest()
    cfg = req.config or ScannerConfig()
    as_of = req.as_of or datetime.utcnow()
    universe = StockUniverse(universe_type=req.universe_type)
    scanner = OpportunityScanner(config=cfg)

    # Sample standard offline dataset for endpoint testing
    sample_datasets = {
        c.symbol: {
            "current_price": 2500.0,
            "ohlcv_historical": [
                {"timestamp": as_of.isoformat(), "open": 2480.0, "high": 2520.0, "low": 2470.0, "close": 2500.0, "volume": 50000}
            ] * 25,
            "technical_indicators": {"ema_20": 2450.0, "ema_50": 2400.0, "rsi_14": 58.0},
            "fundamental_data": {"pe_ratio": 22.0, "net_profit": 5000.0, "revenue_growth": 0.15, "roe": 0.18},
            "news_data": {"articles": [{"title": "Strong Q3", "published_at": as_of.isoformat()}]},
            "institutional_data": [],
        }
        for c in universe.get_snapshot(as_of).constituents
    }

    result = scanner.scan_universe(universe, sample_datasets, as_of=as_of)
    _scanner_results[result.run_id] = result
    return result


@router.get("/{run_id}", response_model=ScannerResult)
async def get_scanner_result(run_id: str) -> ScannerResult:
    """Retrieve full scan result by run_id."""
    res = _scanner_results.get(run_id)
    if not res:
        raise HTTPException(status_code=404, detail=f"Scanner run '{run_id}' not found.")
    return res


@router.get("/{run_id}/candidates", response_model=List[CandidateScore])
async def get_scanner_candidates(run_id: str) -> List[CandidateScore]:
    """Retrieve ranked candidate scores for a scan run."""
    res = _scanner_results.get(run_id)
    if not res:
        raise HTTPException(status_code=404, detail=f"Scanner run '{run_id}' not found.")
    return res.ranking_result.selected_candidates


@router.get("/{run_id}/efficiency", response_model=ScannerEfficiencyReport)
async def get_scanner_efficiency(run_id: str) -> ScannerEfficiencyReport:
    """Retrieve compute efficiency metrics for a scan run."""
    res = _scanner_results.get(run_id)
    if not res:
        raise HTTPException(status_code=404, detail=f"Scanner run '{run_id}' not found.")
    return res.efficiency


@router.post("/batch-replay", response_model=BatchReplayResult)
async def run_batch_replay_endpoint(request: Optional[ScanRequest] = None) -> BatchReplayResult:
    """
    Execute batch replay over a universe using the Two-Stage Scanner pipeline.
    """
    req = request or ScanRequest()
    cfg = req.config or ScannerConfig()
    universe = StockUniverse(universe_type=req.universe_type)
    batch_engine = BatchReplayEngine(universe=universe, scanner_config=cfg)

    t0 = datetime(2024, 1, 1, 10, 0, 0)
    t1 = datetime(2024, 1, 2, 10, 0, 0)
    sample_datasets = {
        c.symbol: {
            "current_price": 2500.0,
            "ohlcv_historical": [
                {"timestamp": t0.isoformat(), "open": 2480.0, "high": 2520.0, "low": 2470.0, "close": 2500.0, "volume": 50000},
                {"timestamp": t1.isoformat(), "open": 2500.0, "high": 2550.0, "low": 2490.0, "close": 2540.0, "volume": 60000},
            ] * 15,
            "technical_indicators": {"ema_20": 2450.0, "ema_50": 2400.0, "rsi_14": 58.0},
            "fundamental_data": {"pe_ratio": 22.0, "net_profit": 5000.0, "revenue_growth": 0.15, "roe": 0.18},
            "news_data": {},
            "institutional_data": [],
        }
        for c in universe.get_snapshot(t0).constituents
    }

    res = await batch_engine.run_batch_replay(sample_datasets, start_date=t0, end_date=t1)
    _batch_results[res.batch_run_id] = res
    return res
