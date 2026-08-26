"""
Simulation API Routes — Phase 5.2

FastAPI endpoints for initiating simulations, querying results, equity curves,
and trade journals.
"""

from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException

from backend.simulation.replay_engine import HistoricalReplayEngine
from backend.simulation.simulation_config import SimulationConfig
from backend.simulation.simulation_state import (
    DecisionJournalEntry,
    EquityCurvePoint,
    SimulationReport,
    TradeJournalEntry,
)

router = APIRouter(prefix="/api/simulation", tags=["simulation"])

# In-memory store for active/completed simulation reports
_simulation_reports: Dict[str, SimulationReport] = {}


@router.post("/run", response_model=SimulationReport)
async def run_simulation(config: Optional[SimulationConfig] = None) -> SimulationReport:
    """
    Execute a historical paper trading simulation.
    """
    sim_config = config or SimulationConfig()
    engine = HistoricalReplayEngine(config=sim_config)

    # In production/API mode, if no external dataset is provided in payload,
    # generate a standard sample replay dataset for verification
    sample_dataset = {
        symbol: {
            "current_price": 100.0,
            "ohlcv_historical": [
                {"timestamp": "2024-01-01T00:00:00", "open": 98.0, "high": 102.0, "low": 97.0, "close": 100.0, "volume": 10000},
                {"timestamp": "2024-01-02T00:00:00", "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0, "volume": 12000},
                {"timestamp": "2024-01-03T00:00:00", "open": 104.0, "high": 106.0, "low": 103.0, "close": 105.0, "volume": 9000},
            ],
            "fundamental_data": {},
            "news_data": {},
            "institutional_data": [],
        }
        for symbol in sim_config.symbols
    }

    try:
        report = await engine.run(sample_dataset)
        _simulation_reports[report.simulation_id] = report
        return report
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Simulation failed: {str(e)}")


@router.get("/{simulation_id}", response_model=SimulationReport)
async def get_simulation_report(simulation_id: str) -> SimulationReport:
    """Retrieve full simulation report by ID."""
    report = _simulation_reports.get(simulation_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"Simulation '{simulation_id}' not found.")
    return report


@router.get("/{simulation_id}/equity", response_model=List[EquityCurvePoint])
async def get_equity_curve(simulation_id: str) -> List[EquityCurvePoint]:
    """Retrieve equity curve points for charting."""
    report = _simulation_reports.get(simulation_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"Simulation '{simulation_id}' not found.")
    return report.equity_curve


@router.get("/{simulation_id}/trades", response_model=List[TradeJournalEntry])
async def get_trade_journal(simulation_id: str) -> List[TradeJournalEntry]:
    """Retrieve trade journal entries."""
    report = _simulation_reports.get(simulation_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"Simulation '{simulation_id}' not found.")
    return report.trade_journal


@router.get("/{simulation_id}/decisions", response_model=List[DecisionJournalEntry])
async def get_decision_journal(simulation_id: str) -> List[DecisionJournalEntry]:
    """Retrieve decision journal entries."""
    report = _simulation_reports.get(simulation_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"Simulation '{simulation_id}' not found.")
    return report.decision_journal
