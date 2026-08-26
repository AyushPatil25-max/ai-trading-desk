"""
Opportunity Scanner Engine — Phase 5.3

Orchestrates Stage A (deterministic pre-filtering and availability-aware ranking)
over Point-In-Time universe constituents and tracks compute efficiency gains.
"""

from datetime import datetime
import time
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field

from backend.scanner.prefilter import DeterministicPrefilter, PrefilterResult
from backend.scanner.ranking import CandidateRankingEngine, CandidateScore, ScannerRankingResult
from backend.scanner.scanner_config import ScannerConfig
from backend.scanner.universe import StockUniverse, UniverseSnapshot, UniverseType
from backend.simulation.pit_filter import PointInTimeFilter


class ScannerEfficiencyReport(BaseModel):
    universe_size: int = 0
    prefilter_screened: int = 0
    prefilter_passed: int = 0
    prefilter_rejected: int = 0
    ranked_candidates_count: int = 0
    selected_candidates_count: int = 0
    specialist_executions_avoided: int = 0
    specialist_executions_performed: int = 0
    llm_calls_saved: int = 0
    scan_latency_ms: float = 0.0


class ScannerResult(BaseModel):
    run_id: str
    as_of: datetime
    universe_type: UniverseType
    config: ScannerConfig
    ranking_result: ScannerRankingResult
    efficiency: ScannerEfficiencyReport
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class OpportunityScanner:
    """
    High-throughput, deterministic equity scanner for Indian stock universes.
    """

    def __init__(
        self,
        config: Optional[ScannerConfig] = None,
        prefilter: Optional[DeterministicPrefilter] = None,
        ranking_engine: Optional[CandidateRankingEngine] = None,
    ) -> None:
        self.config = config or ScannerConfig()
        self.prefilter = prefilter or DeterministicPrefilter(self.config)
        self.ranking_engine = ranking_engine or CandidateRankingEngine(self.config)

    def scan_universe(
        self,
        universe: StockUniverse,
        datasets: Dict[str, Dict[str, Any]],
        as_of: datetime,
    ) -> ScannerResult:
        start_time = time.perf_counter()
        run_id = f"scan-{uuid.uuid4().hex[:8]}"

        snapshot: UniverseSnapshot = universe.get_snapshot(as_of)
        universe_size = len(snapshot.constituents)

        prefilter_screened = 0
        prefilter_passed = 0
        prefilter_rejected = 0
        passed_candidate_scores: List[CandidateScore] = []

        # Map symbol -> sector from universe constituent metadata
        sector_map = {c.symbol: c.sector for c in snapshot.constituents}

        for constituent in snapshot.constituents:
            symbol = constituent.symbol
            raw_data = datasets.get(symbol)
            if not raw_data:
                prefilter_rejected += 1
                continue

            prefilter_screened += 1

            # 1. Strict Point-in-Time Data Filtering
            pit_ohlcv = PointInTimeFilter.filter_ohlcv(raw_data.get("ohlcv_historical", []), as_of=as_of)
            pit_fundamentals = PointInTimeFilter.filter_fundamentals(raw_data.get("fundamental_data", {}), as_of=as_of)
            pit_news = PointInTimeFilter.filter_news(raw_data.get("news_data", {}), as_of=as_of)
            pit_institutional = PointInTimeFilter.filter_institutional(raw_data.get("institutional_data", []), as_of=as_of)

            pit_data = {
                "current_price": pit_ohlcv[-1].get("close", 0.0) if pit_ohlcv else raw_data.get("current_price", 0.0),
                "ohlcv_historical": pit_ohlcv,
                "technical_indicators": raw_data.get("technical_indicators", {}),
                "fundamental_data": pit_fundamentals,
                "news_data": pit_news,
                "institutional_data": pit_institutional,
            }

            # 2. Stage A: Inexpensive Deterministic Prefilter
            pref_res: PrefilterResult = self.prefilter.filter_candidate(symbol, pit_data)

            if pref_res.passed:
                prefilter_passed += 1
                sector = sector_map.get(symbol, "Unassigned")
                # 3. Candidate Scoring
                candidate_score = self.ranking_engine.score_candidate(symbol, sector, pit_data)
                passed_candidate_scores.append(candidate_score)
            else:
                prefilter_rejected += 1

        # 4. Rank and Select Top-K
        ranking_result = self.ranking_engine.rank_and_select(passed_candidate_scores)
        selected_count = len(ranking_result.selected_candidates)

        end_time = time.perf_counter()
        scan_latency_ms = round((end_time - start_time) * 1000.0, 2)

        # Efficiency calculation: 9 specialists per stock avoided
        specialist_avoided = (universe_size - selected_count) * 9
        specialist_performed = selected_count * 9
        # Assuming ~12 LLM calls per full pipeline evaluation (9 specialists + 3 debate/committee)
        llm_calls_saved = (universe_size - selected_count) * 12

        efficiency = ScannerEfficiencyReport(
            universe_size=universe_size,
            prefilter_screened=prefilter_screened,
            prefilter_passed=prefilter_passed,
            prefilter_rejected=prefilter_rejected,
            ranked_candidates_count=len(passed_candidate_scores),
            selected_candidates_count=selected_count,
            specialist_executions_avoided=specialist_avoided,
            specialist_executions_performed=specialist_performed,
            llm_calls_saved=llm_calls_saved,
            scan_latency_ms=scan_latency_ms,
        )

        return ScannerResult(
            run_id=run_id,
            as_of=as_of,
            universe_type=universe.universe_type,
            config=self.config,
            ranking_result=ranking_result,
            efficiency=efficiency,
        )
