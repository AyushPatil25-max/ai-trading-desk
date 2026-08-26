"""
Simulation Package — Phase 5.2

Historical replay, Point-In-Time filtering, realistic paper broker simulation,
performance metrics, and simulation reporting.
"""

from backend.simulation.performance import PerformanceEngine
from backend.simulation.pit_filter import PointInTimeFilter
from backend.simulation.replay_engine import HistoricalReplayEngine
from backend.simulation.report import SimulationReportBuilder
from backend.simulation.simulation_config import (
    ExecutionMode,
    SimulationConfig,
    SimulationMode,
)
from backend.simulation.simulation_state import (
    DataQualityStatistics,
    DecisionJournalEntry,
    EquityCurvePoint,
    PerformanceMetrics,
    SimulationReport,
    TradeJournalEntry,
)

__all__ = [
    "DataQualityStatistics",
    "DecisionJournalEntry",
    "EquityCurvePoint",
    "ExecutionMode",
    "HistoricalReplayEngine",
    "PerformanceEngine",
    "PerformanceMetrics",
    "PointInTimeFilter",
    "SimulationConfig",
    "SimulationMode",
    "SimulationReport",
    "SimulationReportBuilder",
    "TradeJournalEntry",
]
