"""
Candidate Ranking & Scoring Engine — Phase 5.3

Computes availability-aware opportunity scores, data quality metrics,
and enforces sector diversification limits across candidate equities.
"""

from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from backend.scanner.scanner_config import ScannerConfig


class CandidateScore(BaseModel):
    symbol: str
    sector: str = "Unassigned"
    technical_score: Optional[float] = None
    momentum_score: Optional[float] = None
    quant_score: Optional[float] = None
    fundamental_score: Optional[float] = None
    valuation_score: Optional[float] = None
    sector_score: Optional[float] = None
    macro_score: Optional[float] = None
    news_score: Optional[float] = None
    institutional_score: Optional[float] = None
    available_domains_count: int = 0
    data_quality_score: float = 0.0
    raw_weighted_score: float = 0.0
    effective_opportunity_score: float = 0.0
    passed_thresholds: bool = True
    selection_status: str = "PENDING"
    rejection_reason: Optional[str] = None


class ScannerRankingResult(BaseModel):
    selected_candidates: List[CandidateScore] = Field(default_factory=list)
    rejected_candidates: List[CandidateScore] = Field(default_factory=list)
    all_scored_candidates: List[CandidateScore] = Field(default_factory=list)
    sector_distribution: Dict[str, int] = Field(default_factory=dict)
    total_screened: int = 0
    total_selected: int = 0


class CandidateRankingEngine:
    """
    Ranks screened candidates deterministically using evidence-availability weighting.
    """

    def __init__(self, config: Optional[ScannerConfig] = None) -> None:
        self.config = config or ScannerConfig()

    def calculate_technical_score(self, data: Dict[str, Any]) -> Optional[float]:
        ohlcv = data.get("ohlcv_historical", [])
        tech = data.get("technical_indicators", {})
        if not ohlcv:
            return None

        current_price = float(data.get("current_price") or ohlcv[-1].get("close", 0.0))
        score = 50.0  # Base neutral

        ema_20 = tech.get("ema_20")
        ema_50 = tech.get("ema_50")
        rsi = tech.get("rsi_14")

        # Trend alignment
        if ema_20 and current_price > ema_20:
            score += 15.0
        elif ema_20 and current_price < ema_20:
            score -= 15.0

        if ema_20 and ema_50:
            if ema_20 > ema_50:
                score += 15.0
            else:
                score -= 15.0

        # RSI regime
        if rsi is not None:
            if 50.0 <= rsi <= 70.0:
                score += 20.0  # Bullish momentum zone
            elif rsi > 70.0:
                score += 5.0   # Overbought caution
            elif 40.0 <= rsi < 50.0:
                score -= 5.0
            else:
                score -= 20.0  # Oversold / Downtrend

        return max(0.0, min(100.0, score))

    def calculate_momentum_score(self, data: Dict[str, Any]) -> Optional[float]:
        ohlcv = data.get("ohlcv_historical", [])
        if len(ohlcv) < 5:
            return None

        closes = [float(b.get("close", 0.0)) for b in ohlcv if b.get("close")]
        if len(closes) < 5:
            return None

        p_current = closes[-1]
        p_prev = closes[-5]
        if p_prev <= 0:
            return None

        ret_5d = ((p_current - p_prev) / p_prev) * 100.0
        # Score mapped to 50 + return factor
        score = 50.0 + (ret_5d * 5.0)
        return max(0.0, min(100.0, score))

    def calculate_quant_score(self, data: Dict[str, Any]) -> Optional[float]:
        ohlcv = data.get("ohlcv_historical", [])
        if len(ohlcv) < 10:
            return None

        closes = [float(b.get("close", 0.0)) for b in ohlcv]
        # Volatility & drawdown proxy
        peak = max(closes)
        current = closes[-1]
        drawdown_pct = ((peak - current) / peak) * 100.0 if peak > 0 else 0.0

        score = 80.0 - (drawdown_pct * 2.0)
        return max(0.0, min(100.0, score))

    def calculate_fundamental_score(self, data: Dict[str, Any]) -> Optional[float]:
        fund = data.get("fundamental_data", {})
        if not fund:
            return None

        score = 50.0
        # Positive indicators
        if fund.get("net_profit", 0) > 0:
            score += 15.0
        if fund.get("revenue_growth", 0) > 0.10:  # > 10% YoY
            score += 20.0
        if fund.get("roe", 0) > 0.15:            # > 15% ROE
            score += 15.0

        return max(0.0, min(100.0, score))

    def calculate_valuation_score(self, data: Dict[str, Any]) -> Optional[float]:
        fund = data.get("fundamental_data", {})
        if not fund or "pe_ratio" not in fund:
            return None

        pe = float(fund["pe_ratio"])
        if pe <= 0:
            return None

        if pe < 15.0:
            score = 85.0
        elif pe < 25.0:
            score = 70.0
        elif pe < 40.0:
            score = 50.0
        else:
            score = 30.0

        return max(0.0, min(100.0, score))

    def calculate_institutional_score(self, data: Dict[str, Any]) -> Optional[float]:
        inst = data.get("institutional_data", [])
        if not inst:
            return None

        net_flow = sum(getattr(obs, "net_value", 0.0) for obs in inst)
        if net_flow > 0:
            return 75.0
        elif net_flow < 0:
            return 25.0
        return 50.0

    def calculate_news_score(self, data: Dict[str, Any]) -> Optional[float]:
        news = data.get("news_data", {})
        if not news:
            return None

        articles = news if isinstance(news, list) else news.get("articles", [])
        if not articles:
            return None

        # Neutral baseline if articles exist
        return 60.0

    def calculate_data_quality_score(self, data: Dict[str, Any]) -> float:
        quality_score = 0.0
        # Technical/OHLCV presence
        if data.get("ohlcv_historical"):
            quality_score += 25.0
        if data.get("technical_indicators"):
            quality_score += 15.0
        if data.get("fundamental_data"):
            quality_score += 25.0
        if data.get("news_data"):
            quality_score += 15.0
        if data.get("institutional_data"):
            quality_score += 20.0

        return min(100.0, quality_score)

    def score_candidate(
        self,
        symbol: str,
        sector: str,
        data: Dict[str, Any],
    ) -> CandidateScore:
        s_tech = self.calculate_technical_score(data)
        s_mom = self.calculate_momentum_score(data)
        s_quant = self.calculate_quant_score(data)
        s_fund = self.calculate_fundamental_score(data)
        s_val = self.calculate_valuation_score(data)
        s_inst = self.calculate_institutional_score(data)
        s_news = self.calculate_news_score(data)
        s_sector = 50.0  # Baseline
        s_macro = 50.0   # Baseline

        w = self.config.weights
        available_pairs: List[Tuple[float, float]] = []

        if s_tech is not None:
            available_pairs.append((w.technical, s_tech))
        if s_mom is not None:
            available_pairs.append((w.momentum, s_mom))
        if s_quant is not None:
            available_pairs.append((w.quant, s_quant))
        if s_fund is not None:
            available_pairs.append((w.fundamental, s_fund))
        if s_val is not None:
            available_pairs.append((w.valuation, s_val))
        if s_inst is not None:
            available_pairs.append((w.institutional, s_inst))
        if s_news is not None:
            available_pairs.append((w.news, s_news))

        # Always include baseline sector/macro
        available_pairs.append((w.sector, s_sector))
        available_pairs.append((w.macro, s_macro))

        available_weight_sum = sum(weight for weight, _ in available_pairs)
        if available_weight_sum > 0:
            raw_weighted_score = sum(weight * score for weight, score in available_pairs) / available_weight_sum
        else:
            raw_weighted_score = 0.0

        dq_score = self.calculate_data_quality_score(data)
        dq_penalty_weight = self.config.data_quality_penalty_weight
        dq_factor = (1.0 - dq_penalty_weight) + (dq_penalty_weight * (dq_score / 100.0))

        effective_score = round(raw_weighted_score * dq_factor, 2)

        return CandidateScore(
            symbol=symbol,
            sector=sector,
            technical_score=s_tech,
            momentum_score=s_mom,
            quant_score=s_quant,
            fundamental_score=s_fund,
            valuation_score=s_val,
            sector_score=s_sector,
            macro_score=s_macro,
            news_score=s_news,
            institutional_score=s_inst,
            available_domains_count=len(available_pairs),
            data_quality_score=dq_score,
            raw_weighted_score=round(raw_weighted_score, 2),
            effective_opportunity_score=effective_score,
        )

    def rank_and_select(
        self,
        candidate_scores: List[CandidateScore],
    ) -> ScannerRankingResult:
        # Sort descending by effective opportunity score
        sorted_candidates = sorted(
            candidate_scores,
            key=lambda c: c.effective_opportunity_score,
            reverse=True,
        )

        selected: List[CandidateScore] = []
        rejected: List[CandidateScore] = []
        sector_counts: Dict[str, int] = defaultdict(int)

        for c in sorted_candidates:
            # Check minimum score threshold
            if c.effective_opportunity_score < self.config.min_opportunity_score:
                c.passed_thresholds = False
                c.selection_status = "REJECTED_LOW_SCORE"
                c.rejection_reason = f"Score {c.effective_opportunity_score:.1f} < min {self.config.min_opportunity_score:.1f}"
                rejected.append(c)
                continue

            # Check minimum data quality threshold
            if c.data_quality_score < self.config.min_data_quality_score:
                c.passed_thresholds = False
                c.selection_status = "REJECTED_LOW_DATA_QUALITY"
                c.rejection_reason = f"Data quality {c.data_quality_score:.1f} < min {self.config.min_data_quality_score:.1f}"
                rejected.append(c)
                continue

            # Check sector concentration limit
            if sector_counts[c.sector] >= self.config.max_candidates_per_sector:
                c.selection_status = "REJECTED_SECTOR_CONCENTRATION"
                c.rejection_reason = f"Sector '{c.sector}' limit of {self.config.max_candidates_per_sector} reached"
                rejected.append(c)
                continue

            # Check top_k capacity
            if len(selected) < self.config.top_k:
                c.selection_status = "SELECTED"
                selected.append(c)
                sector_counts[c.sector] += 1
            else:
                c.selection_status = "REJECTED_TOP_K_LIMIT"
                c.rejection_reason = f"Top-{self.config.top_k} limit reached"
                rejected.append(c)

        return ScannerRankingResult(
            selected_candidates=selected,
            rejected_candidates=rejected,
            all_scored_candidates=sorted_candidates,
            sector_distribution=dict(sector_counts),
            total_screened=len(candidate_scores),
            total_selected=len(selected),
        )
