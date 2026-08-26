"""
Batch Replay Engine — Phase 5.3

Executes historical replay across large stock universes using a two-stage architecture:
Stage A (Deterministic scanning & top-k ranking) -> Stage B (Specialists, Debate, Committee, Paper Execution).
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Set
import uuid
from pydantic import BaseModel, Field

from backend.scanner.opportunity_scanner import OpportunityScanner, ScannerEfficiencyReport, ScannerResult
from backend.scanner.scanner_config import ScannerConfig
from backend.scanner.universe import StockUniverse, UniverseSnapshot
from backend.simulation.performance import PerformanceEngine
from backend.simulation.replay_engine import HistoricalReplayEngine
from backend.simulation.simulation_config import SimulationConfig
from backend.simulation.simulation_state import (
    DataQualityStatistics,
    DecisionJournalEntry,
    EquityCurvePoint,
    SimulationReport,
    TradeJournalEntry,
)


class BatchReplayEfficiency(BaseModel):
    total_replays_count: int = 0
    total_screened_universe_size: int = 0
    total_candidates_evaluated: int = 0
    total_candidates_selected: int = 0
    total_specialist_executions_avoided: int = 0
    total_specialist_executions_performed: int = 0
    total_llm_calls_saved: int = 0
    average_scan_latency_ms: float = 0.0


class BatchReplayResult(BaseModel):
    batch_run_id: str
    universe_type: str
    start_date: datetime
    end_date: datetime
    simulation_report: SimulationReport
    batch_efficiency: BatchReplayEfficiency
    scan_results: List[ScannerResult] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class BatchReplayEngine:
    """
    Runs time-series batch universe simulation with Stage-A scanning.
    """

    def __init__(
        self,
        universe: Optional[StockUniverse] = None,
        scanner_config: Optional[ScannerConfig] = None,
        simulation_config: Optional[SimulationConfig] = None,
        scanner: Optional[OpportunityScanner] = None,
        replay_engine: Optional[HistoricalReplayEngine] = None,
    ) -> None:
        self.universe = universe or StockUniverse()
        self.scanner_config = scanner_config or ScannerConfig()
        self.simulation_config = simulation_config or SimulationConfig(
            initial_cash=100000.0,
            commission_rate=0.0003,
            slippage_rate=0.0005,
        )
        self.scanner = scanner or OpportunityScanner(config=self.scanner_config)
        self.replay_engine = replay_engine or HistoricalReplayEngine(config=self.simulation_config)

    def _extract_timeline(self, datasets: Dict[str, Dict[str, Any]]) -> List[datetime]:
        timestamps: Set[datetime] = set()
        for symbol, data in datasets.items():
            ohlcv = data.get("ohlcv_historical", [])
            for bar in ohlcv:
                ts_raw = bar.get("timestamp") or bar.get("date")
                if isinstance(ts_raw, datetime):
                    timestamps.add(ts_raw)
                elif isinstance(ts_raw, str):
                    try:
                        parsed = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).replace(tzinfo=None)
                        timestamps.add(parsed)
                    except Exception:
                        pass
        return sorted(list(timestamps))

    async def run_batch_replay(
        self,
        historical_datasets: Dict[str, Dict[str, Any]],
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> BatchReplayResult:
        batch_run_id = f"batch-{uuid.uuid4().hex[:8]}"
        timeline = self._extract_timeline(historical_datasets)

        if start_date:
            timeline = [t for t in timeline if t >= start_date]
        if end_date:
            timeline = [t for t in timeline if t <= end_date]

        if not timeline:
            timeline = [self.simulation_config.start_date]

        effective_start = timeline[0]
        effective_end = timeline[-1]

        scan_results: List[ScannerResult] = []
        total_screened_universe = 0
        total_candidates_eval = 0
        total_candidates_sel = 0
        total_spec_avoided = 0
        total_spec_performed = 0
        total_llm_saved = 0
        latencies: List[float] = []

        all_selected_symbols: Set[str] = set()

        # Step 1: Scan timeline to select qualified candidates
        for current_time in timeline:
            scan_res = self.scanner.scan_universe(self.universe, historical_datasets, as_of=current_time)
            scan_results.append(scan_res)

            eff = scan_res.efficiency
            total_screened_universe += eff.universe_size
            total_candidates_eval += eff.prefilter_screened
            total_candidates_sel += eff.selected_candidates_count
            total_spec_avoided += eff.specialist_executions_avoided
            total_spec_performed += eff.specialist_executions_performed
            total_llm_saved += eff.llm_calls_saved
            latencies.append(eff.scan_latency_ms)

            for cand in scan_res.ranking_result.selected_candidates:
                all_selected_symbols.add(cand.symbol)

        # Step 2: Configure replay engine with the universe of selected candidates
        if all_selected_symbols:
            self.replay_engine.config.symbols = list(all_selected_symbols)
        else:
            self.replay_engine.config.symbols = list(historical_datasets.keys())[:1]

        self.replay_engine.config.start_date = effective_start
        self.replay_engine.config.end_date = effective_end

        # Step 3: Run Stage B full replay on historical dataset
        sim_report = await self.replay_engine.run(historical_datasets)

        avg_lat = sum(latencies) / len(latencies) if latencies else 0.0

        batch_efficiency = BatchReplayEfficiency(
            total_replays_count=len(timeline),
            total_screened_universe_size=total_screened_universe,
            total_candidates_evaluated=total_candidates_eval,
            total_candidates_selected=total_candidates_sel,
            total_specialist_executions_avoided=total_spec_avoided,
            total_specialist_executions_performed=total_spec_performed,
            total_llm_calls_saved=total_llm_saved,
            average_scan_latency_ms=round(avg_lat, 2),
        )

        return BatchReplayResult(
            batch_run_id=batch_run_id,
            universe_type=self.universe.universe_type.value,
            start_date=effective_start,
            end_date=effective_end,
            simulation_report=sim_report,
            batch_efficiency=batch_efficiency,
            scan_results=scan_results,
        )
