"""
Phase 6.6 — Portfolio Intelligence Engine

Production-grade deterministic portfolio intelligence service.
Performs sector exposure aggregation, concentration analysis (HHI),
Pearson correlation calculation, marginal risk evaluation, diversification scoring,
and configurable portfolio constraint auditing without fabricating data.
"""

from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional, Tuple, Union

from backend.domain.schemas import MarketContext
from backend.domain.portfolio_schemas import (
    PORTFOLIO_ENGINE_VERSION,
    PortfolioDataQuality,
    PortfolioPosition,
    SectorExposure,
    ConcentrationMetric,
    CorrelationMetric,
    MarginalExposure,
    DiversificationStatus,
    PortfolioConstraintConfig,
    PortfolioConstraintEvaluation,
    PortfolioIntelligence,
    MarketPortfolioIntelligence,
)
from backend.domain.regime_schemas import MarketRegime


class PortfolioIntelligenceEngine:
    """
    Deterministic Portfolio Intelligence service.
    Zero LLM numerical calculations. Operates safely with empty or partial portfolios.
    """

    def __init__(self, default_config: Optional[PortfolioConstraintConfig] = None):
        self.config = default_config or PortfolioConstraintConfig()

    def analyze_portfolio(
        self,
        portfolio_state: Any,
        candidate_context: Optional[MarketContext] = None,
        candidate_plan: Optional[Any] = None,
        historical_prices: Optional[Dict[str, List[float]]] = None,
        constraint_config: Optional[PortfolioConstraintConfig] = None,
        portfolio_contexts: Optional[Dict[str, MarketContext]] = None,
    ) -> PortfolioIntelligence:
        """
        Analyze current portfolio state and evaluate the marginal risk impact
        of a candidate trade.
        """
        cfg = constraint_config or self.config
        context_id = getattr(candidate_context, "context_id", "ctx-portfolio-001") if candidate_context else "ctx-portfolio-001"
        now = datetime.now(timezone.utc)

        warnings: List[str] = []
        provenance: List[Dict[str, Any]] = []

        # ── 1. Ingest & Sanitize Portfolio State ────────────────────────────────
        port_id, equity, cash, avail_cash, raw_positions, updated_at, dq_status = self._ingest_portfolio_state(
            portfolio_state=portfolio_state,
            warnings=warnings,
        )

        # ── 2. Process Positions & Weights ─────────────────────────────────────
        positions: Dict[str, PortfolioPosition] = {}
        total_market_val = 0.0

        for sym, pos_data in raw_positions.items():
            pos = self._parse_position(sym, pos_data, equity, candidate_context)
            positions[sym] = pos
            total_market_val += pos.market_value

        # Re-verify equity
        if equity <= 0.0:
            equity = cash + total_market_val
            if equity <= 0.0:
                equity = 1.0  # Guard against zero division

        # Re-compute exact normalized weights
        for p in positions.values():
            p.weight = round(p.market_value / equity, 4) if equity > 0 else 0.0

        total_exposure_pct = round((total_market_val / equity) * 100.0, 2) if equity > 0 else 0.0

        # ── 3. Sector Exposures ───────────────────────────────────────────────
        sector_exposures = self._aggregate_sector_exposures(positions, equity)

        # ── 4. Concentration Analysis (HHI) ───────────────────────────────────
        concentration = self._evaluate_concentration(positions, equity, cfg, warnings)

        # ── 5. Correlation Analysis ───────────────────────────────────────────
        candidate_symbol = getattr(candidate_context, "symbol", "") if candidate_context else ""
        correlation = self._evaluate_correlation(
            candidate_symbol=candidate_symbol,
            positions=positions,
            historical_prices=historical_prices,
        )

        # ── 6. Marginal Exposure Analysis ─────────────────────────────────────
        marginal = self._evaluate_marginal_exposure(
            candidate_context=candidate_context,
            candidate_plan=candidate_plan,
            equity=equity,
            total_market_val=total_market_val,
            sector_exposures=sector_exposures,
            concentration=concentration,
        )

        # ── 7. Diversification Assessment ─────────────────────────────────────
        diversification = self._evaluate_diversification(
            candidate_context=candidate_context,
            positions=positions,
            sector_exposures=sector_exposures,
            correlation=correlation,
            marginal=marginal,
        )

        # ── 8. Portfolio Constraint Evaluations ───────────────────────────────
        constraints_eval = self._evaluate_constraints(
            equity=equity,
            cash=cash,
            total_exposure_pct=total_exposure_pct,
            positions=positions,
            sector_exposures=sector_exposures,
            marginal=marginal,
            cfg=cfg,
            warnings=warnings,
        )

        # ── 9. Bull/Bear Risk Aggregation (Phase 17) ──────────────────────────
        agg_bullish = 0.0
        agg_bearish = 0.0
        agg_risk_state = "UNKNOWN"
        agg_risk_factors = []
        valid_contexts = 0
        
        if portfolio_contexts:
            total_weight = sum([p.weight for p in positions.values() if p.symbol in portfolio_contexts])
            
            for sym, pos in positions.items():
                ctx = portfolio_contexts.get(sym)
                if ctx and hasattr(ctx, "bull_bear_risk") and ctx.bull_bear_risk:
                    bb = ctx.bull_bear_risk
                    normalized_weight = (pos.weight / total_weight) if total_weight > 0 else 0
                    
                    agg_bullish += getattr(bb, "bullish_score", 0.0) * normalized_weight
                    agg_bearish += getattr(bb, "bearish_score", 0.0) * normalized_weight
                    
                    if hasattr(bb, "risk_factors") and bb.risk_factors:
                        for rf in bb.risk_factors:
                            # Avoid duplicates loosely
                            if not any(existing.get("factor_type") == rf.factor_type for existing in agg_risk_factors):
                                agg_risk_factors.append({
                                    "symbol": sym,
                                    "factor_type": rf.factor_type,
                                    "severity": rf.severity.value if hasattr(rf.severity, "value") else str(rf.severity),
                                    "description": rf.description
                                })
                    valid_contexts += 1
            
            if valid_contexts > 0:
                diff = agg_bullish - agg_bearish
                if diff > 10:
                    agg_risk_state = "LOW"
                elif diff < -10:
                    agg_risk_state = "HIGH"
                else:
                    agg_risk_state = "MODERATE"

        provenance.append({
            "source": "PortfolioIntelligenceEngine",
            "version": PORTFOLIO_ENGINE_VERSION,
            "portfolio_id": port_id,
            "total_equity": equity,
            "position_count": len(positions),
            "hhi_index": concentration.hhi_index,
            "data_quality": dq_status.value,
        })

        return PortfolioIntelligence(
            portfolio_id=port_id,
            context_id=context_id,
            total_equity=round(equity, 2),
            cash=round(cash, 2),
            available_cash=round(avail_cash, 2),
            total_market_value=round(total_market_val, 2),
            total_exposure_pct=total_exposure_pct,
            position_count=len(positions),
            positions=positions,
            sector_exposures=sector_exposures,
            concentration=concentration,
            correlation=correlation,
            marginal_exposure=marginal,
            diversification=diversification,
            constraints_evaluated=constraints_eval,
            data_quality=dq_status,
            warnings=warnings,
            provenance=provenance,
            evaluated_at=now,
            engine_version=PORTFOLIO_ENGINE_VERSION,
            aggregated_bullish_score=round(agg_bullish, 2),
            aggregated_bearish_score=round(agg_bearish, 2),
            overall_portfolio_risk_state=agg_risk_state,
            aggregated_risk_factors=agg_risk_factors,
        )

    def create_unified_intelligence(
        self,
        market_regime: MarketRegime,
        portfolio_intelligence: Optional[PortfolioIntelligence] = None,
    ) -> MarketPortfolioIntelligence:
        """
        Combine market regime assessment and portfolio intelligence into a single
        unified envelope with contextual summaries and warnings.
        """
        context_id = market_regime.context_id
        symbol = market_regime.symbol
        port_id = portfolio_intelligence.portfolio_id if portfolio_intelligence else None

        summaries: List[str] = [
            f"Market Regime: {market_regime.overall_regime.value} (Confidence: {market_regime.market_regime_confidence:.2f}).",
            f"Stock Alignment: {market_regime.stock_alignment.value}."
        ]
        warnings: List[str] = list(market_regime.warnings)

        if portfolio_intelligence:
            summaries.append(
                f"Portfolio Exposure: {portfolio_intelligence.total_exposure_pct:.1f}% across {portfolio_intelligence.position_count} positions (HHI: {portfolio_intelligence.concentration.hhi_index:.0f})."
            )
            warnings.extend(portfolio_intelligence.warnings)

            if portfolio_intelligence.marginal_exposure:
                summaries.append(portfolio_intelligence.marginal_exposure.risk_impact_summary)

        return MarketPortfolioIntelligence(
            context_id=context_id,
            symbol=symbol,
            portfolio_id=port_id,
            market_regime=market_regime,
            portfolio_intelligence=portfolio_intelligence,
            contextual_summary=" ".join(summaries),
            contextual_warnings=warnings,
            created_at=datetime.now(timezone.utc),
        )

    # ── Private Implementation Helpers ───────────────────────────────────────

    def _ingest_portfolio_state(
        self,
        portfolio_state: Any,
        warnings: List[str],
    ) -> Tuple[str, float, float, float, Dict[str, Any], datetime, PortfolioDataQuality]:
        """Safely extract raw portfolio data, sanitizing types and detecting quality."""
        if portfolio_state is None:
            return "port-empty", 0.0, 0.0, 0.0, {}, datetime.now(timezone.utc), PortfolioDataQuality.UNAVAILABLE

        # Extract fields from dict or model
        def _get(attr: str, default: Any = None) -> Any:
            if isinstance(portfolio_state, dict):
                return portfolio_state.get(attr, default)
            return getattr(portfolio_state, attr, default)

        port_id = str(_get("portfolio_id", "port-default"))
        raw_eq = self._clean_number(_get("total_equity", 0.0))
        raw_cash = self._clean_number(_get("cash", 0.0))
        raw_avail = self._clean_number(_get("available_cash", raw_cash))
        raw_positions = _get("positions", {}) or {}
        updated_at = _get("updated_at", datetime.now(timezone.utc))

        # Check freshness
        dq = PortfolioDataQuality.FRESH
        if isinstance(updated_at, datetime):
            up_tz = updated_at if updated_at.tzinfo else updated_at.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            age_hours = (now - up_tz).total_seconds() / 3600.0
            if age_hours > 24.0:
                dq = PortfolioDataQuality.STALE
                warnings.append("STALE_PORTFOLIO: Portfolio state is older than 24 hours.")
        elif isinstance(updated_at, str):
            dq = PortfolioDataQuality.RECENT

        if not raw_positions and raw_eq == 0.0 and raw_cash == 0.0:
            dq = PortfolioDataQuality.UNAVAILABLE

        return port_id, raw_eq, raw_cash, raw_avail, raw_positions, datetime.now(timezone.utc), dq

    def _parse_position(
        self,
        symbol: str,
        pos_data: Any,
        total_equity: float,
        candidate_context: Optional[MarketContext],
    ) -> PortfolioPosition:
        """Parse raw position record into strongly typed PortfolioPosition."""
        def _get(attr: str, default: Any = None) -> Any:
            if isinstance(pos_data, dict):
                return pos_data.get(attr, default)
            return getattr(pos_data, attr, default)

        qty = max(0.0, self._clean_number(_get("quantity", 0.0)))
        avg_p = max(0.0, self._clean_number(_get("average_price", 0.0)))
        cur_p = max(0.0, self._clean_number(_get("current_price", avg_p)))
        mkt_val = max(0.0, self._clean_number(_get("market_value", qty * cur_p)))
        unreal_pnl = self._clean_number(_get("unrealized_pnl", (cur_p - avg_p) * qty))
        real_pnl = self._clean_number(_get("realized_pnl", 0.0))
        sec = str(_get("sector", "UNKNOWN"))

        # If sector is unknown, check candidate context if symbol matches
        if sec == "UNKNOWN" and candidate_context and candidate_context.symbol == symbol:
            sec_data = getattr(candidate_context, "sector_data", {}) or {}
            sec = sec_data.get("sector", "UNKNOWN")

        weight = round(mkt_val / total_equity, 4) if total_equity > 0 else 0.0

        return PortfolioPosition(
            symbol=symbol,
            quantity=qty,
            average_price=avg_p,
            current_price=cur_p,
            market_value=mkt_val,
            weight=weight,
            sector=sec,
            asset_class=str(_get("asset_class", "EQUITY")),
            unrealized_pnl=unreal_pnl,
            realized_pnl=real_pnl,
            volatility=self._clean_number(_get("volatility", None)),
            beta=self._clean_number(_get("beta", None)),
            updated_at=datetime.now(timezone.utc),
        )

    def _aggregate_sector_exposures(
        self,
        positions: Dict[str, PortfolioPosition],
        total_equity: float,
    ) -> Dict[str, SectorExposure]:
        """Group positions by sector and calculate aggregate weights."""
        sectors: Dict[str, Dict[str, Any]] = {}
        for pos in positions.values():
            sec = pos.sector or "UNKNOWN"
            if sec not in sectors:
                sectors[sec] = {"market_value": 0.0, "count": 0, "symbols": []}
            sectors[sec]["market_value"] += pos.market_value
            sectors[sec]["count"] += 1
            sectors[sec]["symbols"].append(pos.symbol)

        result: Dict[str, SectorExposure] = {}
        for sec, d in sectors.items():
            mv = d["market_value"]
            pct = round((mv / total_equity) * 100.0, 2) if total_equity > 0 else 0.0
            result[sec] = SectorExposure(
                sector=sec,
                market_value=round(mv, 2),
                weight_pct=pct,
                position_count=d["count"],
                symbols=d["symbols"],
            )
        return result

    def _evaluate_concentration(
        self,
        positions: Dict[str, PortfolioPosition],
        total_equity: float,
        config: PortfolioConstraintConfig,
        warnings: List[str],
    ) -> ConcentrationMetric:
        """Calculate Herfindahl-Hirschman Index and top holding weights."""
        if not positions or total_equity <= 0.0:
            return ConcentrationMetric(
                top_position_weight=0.0,
                top_3_weight=0.0,
                top_5_weight=0.0,
                hhi_index=0.0,
                concentration_risk_level="LOW",
                max_position_limit=config.max_position_weight,
                max_sector_limit=config.max_sector_weight,
                passed=True,
                warnings=[],
            )

        weights = sorted([p.weight for p in positions.values()], reverse=True)
        top_1 = round(weights[0], 4) if len(weights) >= 1 else 0.0
        top_3 = round(sum(weights[:3]), 4) if len(weights) >= 3 else round(sum(weights), 4)
        top_5 = round(sum(weights[:5]), 4) if len(weights) >= 5 else round(sum(weights), 4)

        # HHI is sum of (weight_pct)^2
        hhi = round(sum(((w * 100.0) ** 2) for w in weights), 2)

        if hhi > 2500.0 or top_1 > 0.25:
            level = "HIGH"
        elif hhi > 1500.0 or top_1 > 0.15:
            level = "MODERATE"
        else:
            level = "LOW"

        passed = top_1 <= config.max_position_weight
        c_warnings: List[str] = []
        if not passed:
            msg = f"CONCENTRATION_BREACH: Top position weight {top_1*100:.1f}% exceeds limit {config.max_position_weight*100:.1f}%."
            c_warnings.append(msg)
            warnings.append(msg)

        return ConcentrationMetric(
            top_position_weight=top_1,
            top_3_weight=top_3,
            top_5_weight=top_5,
            hhi_index=hhi,
            concentration_risk_level=level,
            max_position_limit=config.max_position_weight,
            max_sector_limit=config.max_sector_weight,
            passed=passed,
            warnings=c_warnings,
        )

    def _evaluate_correlation(
        self,
        candidate_symbol: str,
        positions: Dict[str, PortfolioPosition],
        historical_prices: Optional[Dict[str, List[float]]],
    ) -> CorrelationMetric:
        """
        Compute deterministic Pearson correlation across portfolio holdings and candidate stock.
        """
        if not historical_prices or not candidate_symbol or not positions:
            return CorrelationMetric(
                candidate_symbol=candidate_symbol,
                available=False,
                unavailable_reason="Historical price series missing or portfolio empty",
            )

        cand_prices = historical_prices.get(candidate_symbol)
        if not cand_prices or len(cand_prices) < 5:
            return CorrelationMetric(
                candidate_symbol=candidate_symbol,
                available=False,
                unavailable_reason=f"Insufficient history (<5 bars) for candidate {candidate_symbol}",
            )

        cand_returns = self._compute_returns(cand_prices)
        if len(cand_returns) < 4:
            return CorrelationMetric(
                candidate_symbol=candidate_symbol,
                available=False,
                unavailable_reason="Insufficient valid return periods (<4) for correlation",
            )

        matrix: Dict[str, Dict[str, float]] = {}
        cand_corrs: Dict[str, float] = {}

        for sym in positions.keys():
            pos_prices = historical_prices.get(sym)
            if pos_prices and len(pos_prices) >= 5:
                pos_ret = self._compute_returns(pos_prices)
                # Align lengths
                min_len = min(len(cand_returns), len(pos_ret))
                r = self._pearson(cand_returns[-min_len:], pos_ret[-min_len:])
                if r is not None:
                    cand_corrs[sym] = round(r, 4)
                    matrix.setdefault(candidate_symbol, {})[sym] = round(r, 4)
                    matrix.setdefault(sym, {})[candidate_symbol] = round(r, 4)

        if not cand_corrs:
            return CorrelationMetric(
                candidate_symbol=candidate_symbol,
                available=False,
                unavailable_reason="No overlapping historical price series available with existing positions",
            )

        avg_corr = round(sum(cand_corrs.values()) / len(cand_corrs), 4)
        max_sym = max(cand_corrs, key=lambda k: cand_corrs[k])
        max_corr = cand_corrs[max_sym]

        return CorrelationMetric(
            candidate_symbol=candidate_symbol,
            avg_correlation_to_portfolio=avg_corr,
            max_correlated_symbol=max_sym,
            max_correlation=max_corr,
            correlation_matrix=matrix,
            available=True,
            unavailable_reason="",
        )

    def _evaluate_marginal_exposure(
        self,
        candidate_context: Optional[MarketContext],
        candidate_plan: Optional[Any],
        equity: float,
        total_market_val: float,
        sector_exposures: Dict[str, SectorExposure],
        concentration: ConcentrationMetric,
    ) -> Optional[MarginalExposure]:
        """Simulate incremental impact of adding candidate position."""
        if not candidate_context or not candidate_plan:
            return None

        cand_symbol = getattr(candidate_context, "symbol", "CANDIDATE")
        qty = float(getattr(candidate_plan, "position_quantity", 0.0) or 0.0)
        notional = float(getattr(candidate_plan, "position_notional", 0.0) or 0.0)
        if notional <= 0.0 and qty > 0:
            price = float(getattr(candidate_plan, "entry_price", candidate_context.current_price) or 0.0)
            notional = qty * price

        curr_exp = round((total_market_val / equity) * 100.0, 2) if equity > 0 else 0.0
        prop_exp = round(((total_market_val + notional) / equity) * 100.0, 2) if equity > 0 else 0.0
        incr_exp = round((notional / equity) * 100.0, 2) if equity > 0 else 0.0

        cand_sector = "UNKNOWN"
        if hasattr(candidate_context, "sector_data") and isinstance(candidate_context.sector_data, dict):
            cand_sector = candidate_context.sector_data.get("sector", "UNKNOWN")

        sec_before = sector_exposures.get(cand_sector).weight_pct if cand_sector in sector_exposures else 0.0
        new_sec_mv = (sector_exposures.get(cand_sector).market_value + notional) if cand_sector in sector_exposures else notional
        sec_after = round((new_sec_mv / equity) * 100.0, 2) if equity > 0 else 0.0

        # Marginal HHI
        cand_weight_pct = incr_exp
        hhi_after = round(concentration.hhi_index + (cand_weight_pct ** 2), 2)

        summary = (
            f"Adding {cand_symbol} ({notional:.0f}) moves portfolio exposure from {curr_exp:.1f}% to {prop_exp:.1f}% "
            f"and sector '{cand_sector}' exposure from {sec_before:.1f}% to {sec_after:.1f}%."
        )

        return MarginalExposure(
            candidate_symbol=cand_symbol,
            proposed_quantity=qty,
            proposed_notional=round(notional, 2),
            current_portfolio_exposure_pct=curr_exp,
            proposed_portfolio_exposure_pct=prop_exp,
            incremental_exposure_pct=incr_exp,
            sector_exposure_before_pct=sec_before,
            sector_exposure_after_pct=sec_after,
            concentration_hhi_before=concentration.hhi_index,
            concentration_hhi_after=hhi_after,
            risk_impact_summary=summary,
        )

    def _evaluate_diversification(
        self,
        candidate_context: Optional[MarketContext],
        positions: Dict[str, PortfolioPosition],
        sector_exposures: Dict[str, SectorExposure],
        correlation: CorrelationMetric,
        marginal: Optional[MarginalExposure],
    ) -> Optional[DiversificationStatus]:
        """Assess diversification value added by candidate."""
        if not candidate_context:
            return None

        cand_sec = "UNKNOWN"
        if hasattr(candidate_context, "sector_data") and isinstance(candidate_context.sector_data, dict):
            cand_sec = candidate_context.sector_data.get("sector", "UNKNOWN")

        adds_new_sector = cand_sec != "UNKNOWN" and cand_sec not in sector_exposures
        adds_correlated = correlation.available and correlation.avg_correlation_to_portfolio is not None and correlation.avg_correlation_to_portfolio > 0.65
        increases_conc = marginal is not None and marginal.incremental_exposure_pct > 10.0

        score = 0.50
        if adds_new_sector:
            score += 0.25
        if correlation.available and correlation.avg_correlation_to_portfolio is not None:
            if correlation.avg_correlation_to_portfolio < 0.30:
                score += 0.20
            elif correlation.avg_correlation_to_portfolio > 0.70:
                score -= 0.20
        if increases_conc:
            score -= 0.15

        score = round(max(0.0, min(1.0, score)), 2)

        summary_parts: List[str] = []
        if adds_new_sector:
            summary_parts.append(f"Introduces new sector '{cand_sec}'.")
        else:
            summary_parts.append(f"Increases existing sector '{cand_sec}' allocation.")

        if adds_correlated:
            summary_parts.append("Elevated correlation with existing holdings.")
        elif correlation.available and correlation.avg_correlation_to_portfolio is not None:
            summary_parts.append(f"Low correlation ({correlation.avg_correlation_to_portfolio:.2f}) provides diversification.")

        return DiversificationStatus(
            increases_concentration=increases_conc,
            adds_new_sector=adds_new_sector,
            adds_correlated_exposure=adds_correlated,
            diversification_score=score,
            summary=" ".join(summary_parts),
        )

    def _evaluate_constraints(
        self,
        equity: float,
        cash: float,
        total_exposure_pct: float,
        positions: Dict[str, PortfolioPosition],
        sector_exposures: Dict[str, SectorExposure],
        marginal: Optional[MarginalExposure],
        cfg: PortfolioConstraintConfig,
        warnings: List[str],
    ) -> List[PortfolioConstraintEvaluation]:
        """Audit all configurable portfolio limits."""
        evals: List[PortfolioConstraintEvaluation] = []

        # 1. Max portfolio exposure
        proposed_exp = marginal.proposed_portfolio_exposure_pct if marginal else total_exposure_pct
        passed_exp = proposed_exp <= (cfg.max_portfolio_exposure * 100.0)
        evals.append(PortfolioConstraintEvaluation(
            constraint_name="MAX_PORTFOLIO_EXPOSURE",
            passed=passed_exp,
            limit_value=round(cfg.max_portfolio_exposure * 100.0, 2),
            actual_value=proposed_exp,
            description=f"Max total portfolio exposure limit ({cfg.max_portfolio_exposure*100:.0f}%).",
            action_suggested="ALLOW" if passed_exp else "SIZE_DOWN",
        ))
        if not passed_exp:
            warnings.append(f"PORTFOLIO_EXPOSURE_BREACH: Proposed exposure {proposed_exp:.1f}% exceeds limit {cfg.max_portfolio_exposure*100:.0f}%.")

        # 2. Max sector exposure
        max_sec_limit = cfg.max_sector_weight * 100.0
        sec_to_check = sector_exposures
        if marginal:
            sec_after = marginal.sector_exposure_after_pct
            cand_sec = getattr(marginal, "candidate_symbol", "")
            # Find candidate sector
            for s_name, s_exp in sector_exposures.items():
                if cand_sec in s_exp.symbols:
                    pass

        max_sec_val = max([s.weight_pct for s in sector_exposures.values()], default=0.0)
        if marginal and marginal.sector_exposure_after_pct > max_sec_val:
            max_sec_val = marginal.sector_exposure_after_pct

        passed_sec = max_sec_val <= max_sec_limit
        evals.append(PortfolioConstraintEvaluation(
            constraint_name="MAX_SECTOR_EXPOSURE",
            passed=passed_sec,
            limit_value=max_sec_limit,
            actual_value=max_sec_val,
            description=f"Max single sector exposure limit ({max_sec_limit:.0f}%).",
            action_suggested="ALLOW" if passed_sec else "VETO",
        ))
        if not passed_sec:
            warnings.append(f"SECTOR_EXPOSURE_BREACH: Sector exposure {max_sec_val:.1f}% exceeds limit {max_sec_limit:.0f}%.")

        # 3. Minimum cash reserve
        cash_pct = round((cash / equity) * 100.0, 2) if equity > 0 else 100.0
        passed_cash = cash_pct >= (cfg.min_cash_reserve_pct * 100.0)
        evals.append(PortfolioConstraintEvaluation(
            constraint_name="MIN_CASH_RESERVE",
            passed=passed_cash,
            limit_value=round(cfg.min_cash_reserve_pct * 100.0, 2),
            actual_value=cash_pct,
            description=f"Minimum cash reserve ratio ({cfg.min_cash_reserve_pct*100:.0f}%).",
            action_suggested="ALLOW" if passed_cash else "WARN",
        ))

        # 4. Max number of positions
        pos_count = len(positions) + (1 if marginal and marginal.proposed_quantity > 0 and marginal.candidate_symbol not in positions else 0)
        passed_count = pos_count <= cfg.max_positions
        evals.append(PortfolioConstraintEvaluation(
            constraint_name="MAX_POSITION_COUNT",
            passed=passed_count,
            limit_value=float(cfg.max_positions),
            actual_value=float(pos_count),
            description=f"Maximum simultaneous holdings limit ({cfg.max_positions}).",
            action_suggested="ALLOW" if passed_count else "VETO",
        ))

        return evals

    # ── Mathematical Math Utilities ──────────────────────────────────────────

    def _compute_returns(self, prices: List[float]) -> List[float]:
        """Compute simple discrete returns from price sequence."""
        clean = [p for p in prices if p is not None and not math.isnan(p) and not math.isinf(p) and p > 0]
        if len(clean) < 2:
            return []
        return [(clean[i] - clean[i-1]) / clean[i-1] for i in range(1, len(clean))]

    def _pearson(self, x: List[float], y: List[float]) -> Optional[float]:
        """Deterministic Pearson correlation between two float series."""
        n = min(len(x), len(y))
        if n < 3:
            return None
        x_sub = x[-n:]
        y_sub = y[-n:]
        x_mean = sum(x_sub) / n
        y_mean = sum(y_sub) / n
        num = sum((x_sub[i] - x_mean) * (y_sub[i] - y_mean) for i in range(n))
        den_x = math.sqrt(sum((val - x_mean) ** 2 for val in x_sub))
        den_y = math.sqrt(sum((val - y_mean) ** 2 for val in y_sub))
        if den_x == 0 or den_y == 0:
            return 0.0
        return max(-1.0, min(1.0, num / (den_x * den_y)))

    def _clean_number(self, val: Any) -> float:
        """Convert any number to valid float; replace NaN/Inf/None with 0.0."""
        if val is None:
            return 0.0
        try:
            f = float(val)
            if math.isnan(f) or math.isinf(f):
                return 0.0
            return f
        except (ValueError, TypeError):
            return 0.0
