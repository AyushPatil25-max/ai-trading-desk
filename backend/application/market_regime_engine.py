"""
Phase 6.6 — Market Regime Engine

Production-grade deterministic market regime detector.
Evaluates broader market environment across multiple dimensions (trend, volatility,
breadth, momentum, liquidity, stress) and computes stock-vs-market alignment
without fabricating unavailable data.
"""

from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional, Tuple

from backend.domain.schemas import MarketContext
from backend.domain.regime_schemas import (
    REGIME_ENGINE_VERSION,
    MarketTrendRegime,
    MarketVolatilityRegime,
    MarketBreadthRegime,
    MarketMomentumRegime,
    MarketLiquidityRegime,
    MarketStressLevel,
    OverallMarketRegime,
    RegimeAlignment,
    RelativeStrengthStatus,
    RegimeMetric,
    RegimeTransition,
    MarketRegime,
)


class MarketRegimeEngine:
    """
    Deterministic Market Regime detection service.
    Zero LLM numerical calculations. Operates safely under partial data conditions.
    """

    def __init__(self, default_benchmark: str = "^NSEI"):
        self.default_benchmark = default_benchmark

    def evaluate_regime(
        self,
        market_context: MarketContext,
        benchmark_ohlcv: Optional[List[Dict[str, Any]]] = None,
        previous_regime: Optional[OverallMarketRegime] = None,
    ) -> MarketRegime:
        """
        Evaluate multi-dimensional market regime and compare candidate stock
        against broader market environment.
        """
        context_id = getattr(market_context, "context_id", "ctx-unknown")
        symbol = getattr(market_context, "symbol", "UNKNOWN")
        data_ts = getattr(market_context, "data_timestamp", datetime.now(timezone.utc))

        metrics: List[RegimeMetric] = []
        warnings: List[str] = []
        provenance: List[Dict[str, Any]] = list(getattr(market_context, "provenance", []) or [])

        # ── 1. Benchmark Return & Availability ─────────────────────────────────
        bm_symbol = self.default_benchmark
        if hasattr(market_context, "sector_data") and isinstance(market_context.sector_data, dict):
            bm_symbol = market_context.sector_data.get("benchmark_symbol", self.default_benchmark)

        benchmark_return, bm_metric = self._extract_benchmark_return(
            market_context=market_context,
            benchmark_ohlcv=benchmark_ohlcv,
            benchmark_symbol=bm_symbol,
            context_id=context_id,
            timestamp=data_ts,
        )
        metrics.append(bm_metric)
        if not bm_metric.available:
            warnings.append("BENCHMARK_UNAVAILABLE: Benchmark return could not be deterministically determined.")

        # ── 2. Candidate Return & Availability ─────────────────────────────────
        candidate_return, cand_metric = self._calculate_candidate_return(
            market_context=market_context,
            context_id=context_id,
            timestamp=data_ts,
        )
        metrics.append(cand_metric)

        # ── 3. Relative Strength vs Benchmark ──────────────────────────────────
        relative_return: Optional[float] = None
        relative_strength_status = RelativeStrengthStatus.UNKNOWN

        if benchmark_return is not None and candidate_return is not None:
            relative_return = round(candidate_return - benchmark_return, 4)
            metrics.append(RegimeMetric(
                metric_name="relative_return_vs_benchmark",
                value=relative_return,
                unit="%",
                period="RECENT",
                source="CALCULATED",
                calculation_method=f"candidate_return ({candidate_return}%) - benchmark_return ({benchmark_return}%)",
                timestamp=data_ts,
                available=True,
                context_id=context_id,
            ))

            if relative_return >= 2.0:
                relative_strength_status = RelativeStrengthStatus.OUTPERFORMING
            elif relative_return <= -2.0:
                relative_strength_status = RelativeStrengthStatus.UNDERPERFORMING
            else:
                relative_strength_status = RelativeStrengthStatus.IN_LINE
        else:
            metrics.append(RegimeMetric(
                metric_name="relative_return_vs_benchmark",
                available=False,
                unavailable_reason="Either candidate return or benchmark return is unavailable",
                timestamp=data_ts,
                context_id=context_id,
            ))

        # ── 4. Multi-Dimensional Regime Dimensions ─────────────────────────────
        trend_regime, trend_metric = self._detect_trend_regime(
            market_context=market_context,
            benchmark_ohlcv=benchmark_ohlcv,
            benchmark_return=benchmark_return,
            context_id=context_id,
            timestamp=data_ts,
        )
        metrics.append(trend_metric)

        vol_regime, vol_metric = self._detect_volatility_regime(
            market_context=market_context,
            benchmark_ohlcv=benchmark_ohlcv,
            context_id=context_id,
            timestamp=data_ts,
        )
        metrics.append(vol_metric)

        breadth_regime, breadth_metric = self._detect_breadth_regime(
            market_context=market_context,
            context_id=context_id,
            timestamp=data_ts,
        )
        metrics.append(breadth_metric)

        momentum_regime, mom_metric = self._detect_momentum_regime(
            market_context=market_context,
            benchmark_return=benchmark_return,
            context_id=context_id,
            timestamp=data_ts,
        )
        metrics.append(mom_metric)

        liquidity_regime, liq_metric = self._detect_liquidity_regime(
            market_context=market_context,
            context_id=context_id,
            timestamp=data_ts,
        )
        metrics.append(liq_metric)

        stress_level, stress_metric = self._detect_market_stress(
            market_context=market_context,
            benchmark_return=benchmark_return,
            vol_regime=vol_regime,
            context_id=context_id,
            timestamp=data_ts,
        )
        metrics.append(stress_metric)

        # ── 5. Overall Regime Synthesis ────────────────────────────────────────
        overall_regime = self._synthesize_overall_regime(
            trend=trend_regime,
            volatility=vol_regime,
            breadth=breadth_regime,
            momentum=momentum_regime,
            stress=stress_level,
        )

        # ── 6. Regime Confidence Score ─────────────────────────────────────────
        # Based on completeness and consistency of available regime dimensions
        regime_confidence = self._calculate_regime_confidence(metrics=metrics)

        # ── 7. Transition Detection ───────────────────────────────────────────
        transition = RegimeTransition(
            transition_detected=False,
            previous_regime=previous_regime,
            current_regime=overall_regime,
            transition_direction="",
            confidence=0.0,
            detected_at=data_ts,
        )
        if previous_regime is not None and previous_regime != OverallMarketRegime.UNKNOWN:
            if previous_regime != overall_regime:
                transition.transition_detected = True
                transition.transition_direction = f"{previous_regime.value} -> {overall_regime.value}"
                transition.confidence = round(regime_confidence, 4)
                warnings.append(f"REGIME_TRANSITION_DETECTED: Market shifted from {previous_regime.value} to {overall_regime.value}.")

        # ── 8. Stock vs Market Alignment ──────────────────────────────────────
        stock_alignment = self._evaluate_stock_alignment(
            market_context=market_context,
            overall_regime=overall_regime,
            vol_regime=vol_regime,
            relative_strength=relative_strength_status,
            candidate_return=candidate_return,
        )

        provenance.append({
            "source": "MarketRegimeEngine",
            "version": REGIME_ENGINE_VERSION,
            "timestamp": str(datetime.now(timezone.utc)),
            "overall_regime": overall_regime.value,
            "regime_confidence": regime_confidence,
            "stock_alignment": stock_alignment.value,
        })

        return MarketRegime(
            context_id=context_id,
            symbol=symbol,
            benchmark_symbol=bm_symbol,
            evaluated_at=data_ts,
            trend=trend_regime,
            volatility=vol_regime,
            breadth=breadth_regime,
            momentum=momentum_regime,
            liquidity=liquidity_regime,
            stress_level=stress_level,
            overall_regime=overall_regime,
            market_regime_confidence=regime_confidence,
            regime_transition=transition,
            stock_alignment=stock_alignment,
            relative_strength_status=relative_strength_status,
            relative_return=relative_return,
            benchmark_return=benchmark_return,
            candidate_return=candidate_return,
            metrics=metrics,
            provenance=provenance,
            warnings=warnings,
            engine_version=REGIME_ENGINE_VERSION,
        )

    # ── Calculation Helpers ───────────────────────────────────────────────────

    def _extract_benchmark_return(
        self,
        market_context: MarketContext,
        benchmark_ohlcv: Optional[List[Dict[str, Any]]],
        benchmark_symbol: str,
        context_id: str,
        timestamp: datetime,
    ) -> Tuple[Optional[float], RegimeMetric]:
        """Extract or calculate benchmark return deterministically."""
        # 1. From sector_data
        if hasattr(market_context, "sector_data") and isinstance(market_context.sector_data, dict):
            val = market_context.sector_data.get("benchmark_return_pct")
            if val is not None and not math.isnan(float(val)) and not math.isinf(float(val)):
                ret = round(float(val), 4)
                return ret, RegimeMetric(
                    metric_name="benchmark_return",
                    value=ret,
                    unit="%",
                    period="RECENT",
                    source=f"sector_data[{benchmark_symbol}]",
                    calculation_method="Extracted from sector_data.benchmark_return_pct",
                    timestamp=timestamp,
                    available=True,
                    context_id=context_id,
                )

        # 2. From benchmark_ohlcv
        if benchmark_ohlcv and len(benchmark_ohlcv) >= 2:
            first_bar = benchmark_ohlcv[0]
            last_bar = benchmark_ohlcv[-1]
            first_c = float(first_bar.get("close", 0.0))
            last_c = float(last_bar.get("close", 0.0))
            if first_c > 0 and not math.isnan(first_c) and not math.isnan(last_c):
                ret = round(((last_c - first_c) / first_c) * 100.0, 4)
                return ret, RegimeMetric(
                    metric_name="benchmark_return",
                    value=ret,
                    unit="%",
                    period=f"{len(benchmark_ohlcv)}_bars",
                    source=benchmark_symbol,
                    calculation_method="((last_close - first_close) / first_close) * 100",
                    timestamp=timestamp,
                    available=True,
                    context_id=context_id,
                )

        return None, RegimeMetric(
            metric_name="benchmark_return",
            unit="%",
            period="RECENT",
            source=benchmark_symbol,
            calculation_method="Extraction/Calculation",
            timestamp=timestamp,
            available=False,
            unavailable_reason="Benchmark return missing in sector_data and benchmark_ohlcv not supplied",
            context_id=context_id,
        )

    def _calculate_candidate_return(
        self,
        market_context: MarketContext,
        context_id: str,
        timestamp: datetime,
    ) -> Tuple[Optional[float], RegimeMetric]:
        """Calculate candidate return from historical OHLCV."""
        ohlcv = getattr(market_context, "ohlcv_historical", []) or []
        if len(ohlcv) >= 2:
            first_c = float(ohlcv[0].get("close", 0.0))
            last_c = float(ohlcv[-1].get("close", 0.0))
            if first_c > 0 and not math.isnan(first_c) and not math.isnan(last_c):
                ret = round(((last_c - first_c) / first_c) * 100.0, 4)
                return ret, RegimeMetric(
                    metric_name="candidate_return",
                    value=ret,
                    unit="%",
                    period=f"{len(ohlcv)}_bars",
                    source=market_context.symbol,
                    calculation_method="((last_close - first_close) / first_close) * 100",
                    timestamp=timestamp,
                    available=True,
                    context_id=context_id,
                )

        return None, RegimeMetric(
            metric_name="candidate_return",
            unit="%",
            period="RECENT",
            source=getattr(market_context, "symbol", "CANDIDATE"),
            calculation_method="((last_close - first_close) / first_close) * 100",
            timestamp=timestamp,
            available=False,
            unavailable_reason="Insufficient OHLCV bars (<2) to compute candidate return",
            context_id=context_id,
        )

    def _detect_trend_regime(
        self,
        market_context: MarketContext,
        benchmark_ohlcv: Optional[List[Dict[str, Any]]],
        benchmark_return: Optional[float],
        context_id: str,
        timestamp: datetime,
    ) -> Tuple[MarketTrendRegime, RegimeMetric]:
        """Classify trend regime from benchmark returns and moving average structure."""
        if benchmark_return is not None:
            if benchmark_return >= 2.5:
                regime = MarketTrendRegime.BULL
            elif benchmark_return <= -2.5:
                regime = MarketTrendRegime.BEAR
            else:
                regime = MarketTrendRegime.SIDEWAYS

            return regime, RegimeMetric(
                metric_name="market_trend_regime",
                value=benchmark_return,
                unit="%",
                period="RECENT",
                source="BENCHMARK",
                calculation_method="Threshold evaluation on benchmark_return",
                timestamp=timestamp,
                available=True,
                context_id=context_id,
            )

        # Fallback to technical indicators if available
        indicators = getattr(market_context, "technical_indicators", {}) or {}
        ema20 = indicators.get("ema20")
        ema50 = indicators.get("ema50")
        cur_price = getattr(market_context, "current_price", None)

        if ema20 is not None and ema50 is not None and cur_price is not None:
            if cur_price > ema20 > ema50:
                return MarketTrendRegime.BULL, RegimeMetric(
                    metric_name="market_trend_regime",
                    unit="state",
                    source="technical_indicators",
                    calculation_method="price > ema20 > ema50",
                    timestamp=timestamp,
                    available=True,
                    context_id=context_id,
                )
            elif cur_price < ema20 < ema50:
                return MarketTrendRegime.BEAR, RegimeMetric(
                    metric_name="market_trend_regime",
                    unit="state",
                    source="technical_indicators",
                    calculation_method="price < ema20 < ema50",
                    timestamp=timestamp,
                    available=True,
                    context_id=context_id,
                )
            else:
                return MarketTrendRegime.SIDEWAYS, RegimeMetric(
                    metric_name="market_trend_regime",
                    unit="state",
                    source="technical_indicators",
                    calculation_method="Moving average consolidation",
                    timestamp=timestamp,
                    available=True,
                    context_id=context_id,
                )

        return MarketTrendRegime.UNKNOWN, RegimeMetric(
            metric_name="market_trend_regime",
            available=False,
            unavailable_reason="Insufficient data for trend regime classification",
            timestamp=timestamp,
            context_id=context_id,
        )

    def _detect_volatility_regime(
        self,
        market_context: MarketContext,
        benchmark_ohlcv: Optional[List[Dict[str, Any]]],
        context_id: str,
        timestamp: datetime,
    ) -> Tuple[MarketVolatilityRegime, RegimeMetric]:
        """Calculate realized volatility and classify volatility regime."""
        # Calculate from benchmark OHLCV if available, else candidate OHLCV
        series = benchmark_ohlcv if benchmark_ohlcv and len(benchmark_ohlcv) >= 3 else getattr(market_context, "ohlcv_historical", [])
        if series and len(series) >= 3:
            closes = [float(b.get("close", 0.0)) for b in series if b.get("close") is not None]
            closes = [c for c in closes if c > 0 and not math.isnan(c)]
            if len(closes) >= 3:
                returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
                mean_ret = sum(returns) / len(returns)
                var = sum((r - mean_ret) ** 2 for r in returns) / max(1, len(returns) - 1)
                daily_std = math.sqrt(var)
                annualized_vol = round(daily_std * math.sqrt(252) * 100.0, 2)

                if annualized_vol < 12.0:
                    regime = MarketVolatilityRegime.LOW
                elif annualized_vol <= 22.0:
                    regime = MarketVolatilityRegime.NORMAL
                elif annualized_vol <= 35.0:
                    regime = MarketVolatilityRegime.HIGH
                else:
                    regime = MarketVolatilityRegime.EXTREME

                return regime, RegimeMetric(
                    metric_name="realized_volatility",
                    value=annualized_vol,
                    unit="%",
                    period=f"{len(closes)}_bars_annualized",
                    source="OHLCV",
                    calculation_method="Sample standard deviation of log/discrete returns * sqrt(252)",
                    timestamp=timestamp,
                    available=True,
                    context_id=context_id,
                )

        return MarketVolatilityRegime.UNKNOWN, RegimeMetric(
            metric_name="realized_volatility",
            available=False,
            unavailable_reason="Insufficient OHLCV history (<3 bars) to compute realized volatility",
            timestamp=timestamp,
            context_id=context_id,
        )

    def _detect_breadth_regime(
        self,
        market_context: MarketContext,
        context_id: str,
        timestamp: datetime,
    ) -> Tuple[MarketBreadthRegime, RegimeMetric]:
        """Detect market breadth participation from sector or macro data."""
        sec_data = getattr(market_context, "sector_data", {}) or {}
        breadth_ratio = sec_data.get("advance_decline_ratio") or sec_data.get("market_breadth_pct")

        if breadth_ratio is not None and not math.isnan(float(breadth_ratio)):
            br = float(breadth_ratio)
            if br >= 65.0 or (br > 1.5 and br < 20.0):
                regime = MarketBreadthRegime.STRONG
            elif br <= 35.0 or (br < 0.67 and br > 0.0):
                regime = MarketBreadthRegime.WEAK
            else:
                regime = MarketBreadthRegime.NEUTRAL

            return regime, RegimeMetric(
                metric_name="market_breadth",
                value=round(br, 2),
                unit="ratio_or_pct",
                source="sector_data",
                calculation_method="Advance/decline or participating sector ratio",
                timestamp=timestamp,
                available=True,
                context_id=context_id,
            )

        return MarketBreadthRegime.UNKNOWN, RegimeMetric(
            metric_name="market_breadth",
            available=False,
            unavailable_reason="Breadth metrics unavailable in market context",
            timestamp=timestamp,
            context_id=context_id,
        )

    def _detect_momentum_regime(
        self,
        market_context: MarketContext,
        benchmark_return: Optional[float],
        context_id: str,
        timestamp: datetime,
    ) -> Tuple[MarketMomentumRegime, RegimeMetric]:
        """Detect market momentum state from benchmark returns and technical indicators."""
        if benchmark_return is not None:
            if benchmark_return >= 1.0:
                regime = MarketMomentumRegime.POSITIVE
            elif benchmark_return <= -1.0:
                regime = MarketMomentumRegime.NEGATIVE
            else:
                regime = MarketMomentumRegime.NEUTRAL

            return regime, RegimeMetric(
                metric_name="market_momentum",
                value=benchmark_return,
                unit="%",
                source="BENCHMARK",
                calculation_method="Rate of change over observation window",
                timestamp=timestamp,
                available=True,
                context_id=context_id,
            )

        return MarketMomentumRegime.UNKNOWN, RegimeMetric(
            metric_name="market_momentum",
            available=False,
            unavailable_reason="Benchmark return unavailable for momentum evaluation",
            timestamp=timestamp,
            context_id=context_id,
        )

    def _detect_liquidity_regime(
        self,
        market_context: MarketContext,
        context_id: str,
        timestamp: datetime,
    ) -> Tuple[MarketLiquidityRegime, RegimeMetric]:
        """Detect market liquidity regime from volume characteristics."""
        ohlcv = getattr(market_context, "ohlcv_historical", []) or []
        if len(ohlcv) >= 3:
            vols = [float(b.get("volume", 0.0)) for b in ohlcv if b.get("volume") is not None]
            vols = [v for v in vols if v > 0 and not math.isnan(v)]
            if len(vols) >= 3:
                last_vol = vols[-1]
                avg_vol = sum(vols[:-1]) / (len(vols) - 1)
                if avg_vol > 0:
                    vol_ratio = round(last_vol / avg_vol, 2)
                    if vol_ratio >= 1.25:
                        regime = MarketLiquidityRegime.HIGH
                    elif vol_ratio <= 0.75:
                        regime = MarketLiquidityRegime.LOW
                    else:
                        regime = MarketLiquidityRegime.NORMAL

                    return regime, RegimeMetric(
                        metric_name="volume_liquidity_ratio",
                        value=vol_ratio,
                        unit="ratio",
                        source="OHLCV",
                        calculation_method="latest_volume / historical_average_volume",
                        timestamp=timestamp,
                        available=True,
                        context_id=context_id,
                    )

        return MarketLiquidityRegime.UNKNOWN, RegimeMetric(
            metric_name="volume_liquidity_ratio",
            available=False,
            unavailable_reason="Insufficient volume history for liquidity evaluation",
            timestamp=timestamp,
            context_id=context_id,
        )

    def _detect_market_stress(
        self,
        market_context: MarketContext,
        benchmark_return: Optional[float],
        vol_regime: MarketVolatilityRegime,
        context_id: str,
        timestamp: datetime,
    ) -> Tuple[MarketStressLevel, RegimeMetric]:
        """Detect systemic market stress conditions."""
        if benchmark_return is not None:
            if benchmark_return <= -5.0 or vol_regime == MarketVolatilityRegime.EXTREME:
                stress = MarketStressLevel.SEVERE
            elif benchmark_return <= -2.5 or vol_regime == MarketVolatilityRegime.HIGH:
                stress = MarketStressLevel.ELEVATED
            else:
                stress = MarketStressLevel.NORMAL

            return stress, RegimeMetric(
                metric_name="market_stress_level",
                unit="state",
                source="BENCHMARK",
                calculation_method="Combined drawdown and volatility stress thresholds",
                timestamp=timestamp,
                available=True,
                context_id=context_id,
            )

        if vol_regime == MarketVolatilityRegime.HIGH:
            return MarketStressLevel.ELEVATED, RegimeMetric(
                metric_name="market_stress_level",
                unit="state",
                source="VOLATILITY",
                calculation_method="Volatility regime inference",
                timestamp=timestamp,
                available=True,
                context_id=context_id,
            )

        return MarketStressLevel.UNKNOWN, RegimeMetric(
            metric_name="market_stress_level",
            available=False,
            unavailable_reason="Insufficient return and volatility data for stress detection",
            timestamp=timestamp,
            context_id=context_id,
        )

    def _synthesize_overall_regime(
        self,
        trend: MarketTrendRegime,
        volatility: MarketVolatilityRegime,
        breadth: MarketBreadthRegime,
        momentum: MarketMomentumRegime,
        stress: MarketStressLevel,
    ) -> OverallMarketRegime:
        """Synthesize multi-dimensional dimensions into an overall regime classification."""
        if stress == MarketStressLevel.SEVERE:
            return OverallMarketRegime.STRESSED

        if trend == MarketTrendRegime.BULL:
            if volatility in (MarketVolatilityRegime.LOW, MarketVolatilityRegime.NORMAL):
                return OverallMarketRegime.BULL
            elif volatility in (MarketVolatilityRegime.HIGH, MarketVolatilityRegime.EXTREME):
                return OverallMarketRegime.TRANSITION

        if trend == MarketTrendRegime.BEAR:
            if volatility in (MarketVolatilityRegime.HIGH, MarketVolatilityRegime.EXTREME):
                return OverallMarketRegime.STRESSED
            return OverallMarketRegime.BEAR

        if trend == MarketTrendRegime.SIDEWAYS:
            if volatility == MarketVolatilityRegime.HIGH:
                return OverallMarketRegime.HIGH_VOLATILITY
            elif volatility == MarketVolatilityRegime.LOW:
                return OverallMarketRegime.LOW_VOLATILITY
            return OverallMarketRegime.SIDEWAYS

        if volatility == MarketVolatilityRegime.HIGH:
            return OverallMarketRegime.HIGH_VOLATILITY
        if volatility == MarketVolatilityRegime.LOW:
            return OverallMarketRegime.LOW_VOLATILITY

        return OverallMarketRegime.UNKNOWN

    def _calculate_regime_confidence(self, metrics: List[RegimeMetric]) -> float:
        """Calculate confidence in regime classification based on metric availability."""
        total = len(metrics)
        if total == 0:
            return 0.0
        available = sum(1 for m in metrics if m.available)
        base_confidence = available / total
        return round(max(0.10, min(1.0, base_confidence)), 4)

    def _evaluate_stock_alignment(
        self,
        market_context: MarketContext,
        overall_regime: OverallMarketRegime,
        vol_regime: MarketVolatilityRegime,
        relative_strength: RelativeStrengthStatus,
        candidate_return: Optional[float],
    ) -> RegimeAlignment:
        """Contextually compare candidate security with market regime."""
        cand_bullish = candidate_return is not None and candidate_return > 1.5
        cand_bearish = candidate_return is not None and candidate_return < -1.5

        if overall_regime in (OverallMarketRegime.STRESSED, OverallMarketRegime.HIGH_VOLATILITY):
            if vol_regime in (MarketVolatilityRegime.HIGH, MarketVolatilityRegime.EXTREME):
                return RegimeAlignment.ELEVATED_VOLATILITY_RISK

        if overall_regime == OverallMarketRegime.BULL:
            if cand_bullish:
                return RegimeAlignment.ALIGNED_BULL
            elif cand_bearish:
                return RegimeAlignment.DIVERGENT

        if overall_regime == OverallMarketRegime.BEAR:
            if cand_bearish:
                return RegimeAlignment.ALIGNED_BEAR
            elif cand_bullish and relative_strength == RelativeStrengthStatus.OUTPERFORMING:
                return RegimeAlignment.RELATIVE_STRENGTH_EXCEPTION

        if overall_regime == OverallMarketRegime.UNKNOWN:
            return RegimeAlignment.UNKNOWN

        return RegimeAlignment.NEUTRAL
