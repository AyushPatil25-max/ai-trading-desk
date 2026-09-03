"""
Phase 6.7 — Scenario & Stress Testing Engine

Production-grade deterministic scenario and stress testing service for Trading OS.
Evaluates how candidate decisions and portfolio states withstand controlled,
hypothetical market shocks without mutating actual live or baseline state.
"""

from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional, Tuple, Union
import uuid

from backend.domain.schemas import MarketContext
from backend.domain.risk_schemas import (
    PositionDirection,
    PositionSizingPlan,
    RiskConfiguration,
)
from backend.domain.regime_schemas import (
    OverallMarketRegime,
    MarketRegime,
)
from backend.domain.portfolio_schemas import (
    PortfolioIntelligence,
)
from backend.domain.scenario_schemas import (
    SCENARIO_ENGINE_VERSION,
    ScenarioType,
    ScenarioSeverity,
    ScenarioResilience,
    ScenarioDataQuality,
    ScenarioDefinition,
    PositionImpact,
    PortfolioImpact,
    StopLossInteraction,
    ConvictionScenarioContext,
    ScenarioResult,
    ScenarioComparison,
    ScenarioMatrixRow,
    ScenarioMatrix,
)
from backend.application.risk_engine import RiskEngine


class ScenarioEngine:
    """
    Deterministic Scenario & Stress Testing service.
    Zero LLM numerical calculations. Operates exclusively on derived scenario copies.
    """

    def __init__(self, default_risk_engine: Optional[RiskEngine] = None):
        self.risk_engine = default_risk_engine or RiskEngine()

    # ── Pre-configured Standard Scenarios ─────────────────────────────────────

    @classmethod
    def get_standard_scenarios(cls) -> Dict[str, ScenarioDefinition]:
        """Returns standard pre-configured deterministic stress scenarios."""
        return {
            "MARKET_CRASH_10": ScenarioDefinition(
                scenario_type=ScenarioType.MARKET_CRASH,
                name="Market Crash -10%",
                description="Broad market index decline of 10%",
                market_return_shock=-0.10,
                assumptions={"beta_applied": True, "type": "SYSTEMIC"},
            ),
            "MARKET_CRASH_20": ScenarioDefinition(
                scenario_type=ScenarioType.MARKET_CRASH,
                name="Market Crash -20%",
                description="Severe systemic market crash of 20%",
                market_return_shock=-0.20,
                assumptions={"beta_applied": True, "type": "SYSTEMIC_EXTREME"},
            ),
            "MARKET_RALLY_10": ScenarioDefinition(
                scenario_type=ScenarioType.MARKET_RALLY,
                name="Market Rally +10%",
                description="Broad market index rally of 10%",
                market_return_shock=0.10,
                assumptions={"beta_applied": True, "type": "EXPANSION"},
            ),
            "VOLATILITY_SPIKE_50": ScenarioDefinition(
                scenario_type=ScenarioType.VOLATILITY_SPIKE,
                name="Volatility Spike +50%",
                description="Realized and implied volatility expands by 50%",
                volatility_multiplier=1.50,
                assumptions={"adverse_range_factor": 1.5, "type": "VOLATILITY"},
            ),
            "SECTOR_SHOCK_15": ScenarioDefinition(
                scenario_type=ScenarioType.SECTOR_SHOCK,
                name="Sector Shock -15%",
                description="Adverse 15% shock isolated to the candidate's sector",
                sector_return_shock=-0.15,
                assumptions={"sector_specific": True, "type": "INDUSTRY"},
            ),
            "STOCK_SHOCK_12": ScenarioDefinition(
                scenario_type=ScenarioType.STOCK_SHOCK,
                name="Idiosyncratic Stock Shock -12%",
                description="Earnings miss or adverse event triggering -12% shock",
                stock_return_shock=-0.12,
                assumptions={"idiosyncratic": True, "type": "STOCK"},
            ),
            "GAP_DOWN_8": ScenarioDefinition(
                scenario_type=ScenarioType.GAP_DOWN,
                name="Overnight Gap Down -8%",
                description="Overnight opening price gap down of 8%",
                opening_price_shock=-0.08,
                assumptions={"gap_execution": "NEXT_OPEN", "type": "GAP"},
            ),
            "GAP_UP_8": ScenarioDefinition(
                scenario_type=ScenarioType.GAP_UP,
                name="Overnight Gap Up +8%",
                description="Overnight opening price gap up of 8%",
                opening_price_shock=0.08,
                assumptions={"gap_execution": "NEXT_OPEN", "type": "GAP"},
            ),
            "REGIME_CHANGE_STRESSED": ScenarioDefinition(
                scenario_type=ScenarioType.REGIME_CHANGE,
                name="Regime Shift to Stressed",
                description="Market regime shifts from current state to STRESSED",
                target_regime=OverallMarketRegime.STRESSED,
                assumptions={"alignment_reevaluation": True, "type": "REGIME"},
            ),
            "PORTFOLIO_DRAWDOWN_15": ScenarioDefinition(
                scenario_type=ScenarioType.PORTFOLIO_DRAWDOWN,
                name="Portfolio Broad Drawdown -15%",
                description="Uniform 15% drawdown across all active holdings",
                market_return_shock=-0.15,
                assumptions={"portfolio_wide": True, "type": "DRAWDOWN"},
            ),
            "LIQUIDITY_STRESS_50": ScenarioDefinition(
                scenario_type=ScenarioType.LIQUIDITY_STRESS,
                name="Liquidity Deterioration -50%",
                description="50% collapse in liquidity with widened slippage",
                liquidity_multiplier=0.50,
                assumptions={"slippage_penalty_pct": 1.5, "type": "LIQUIDITY"},
            ),
        }

    # ── Core Scenario Execution ───────────────────────────────────────────────

    def run_scenario(
        self,
        candidate_context: MarketContext,
        candidate_plan: Optional[PositionSizingPlan] = None,
        portfolio_state: Optional[Any] = None,
        scenario_def: Optional[ScenarioDefinition] = None,
        market_regime: Optional[MarketRegime] = None,
        risk_engine: Optional[RiskEngine] = None,
    ) -> ScenarioResult:
        """
        Evaluate a single hypothetical stress scenario deterministically.
        Operates exclusively on derived scenario state without mutating baseline.
        """
        now = datetime.now(timezone.utc)
        context_id = getattr(candidate_context, "context_id", "ctx-unknown")
        symbol = getattr(candidate_context, "symbol", "UNKNOWN")

        # Fallback to standard market crash if not provided
        scenario = scenario_def or self.get_standard_scenarios()["MARKET_CRASH_10"]

        warnings: List[str] = []
        provenance: List[Dict[str, Any]] = []

        # ── 1. Determine Baseline State ─────────────────────────────────────────
        baseline_price = self._clean_number(getattr(candidate_context, "current_price", 0.0))
        if baseline_price <= 0.0:
            warnings.append("INVALID_PRICE: Candidate current price is non-positive; degrading scenario.")

        qty = float(getattr(candidate_plan, "position_quantity", 0.0) or 0.0) if candidate_plan else 0.0
        baseline_notional = qty * baseline_price
        baseline_stop = float(getattr(candidate_plan, "stop_loss_price", 0.0) or 0.0) if candidate_plan else None
        baseline_conviction = float(getattr(candidate_plan, "conviction_score", 0.5) or 0.5) if candidate_plan else 0.5

        port_id, base_equity, base_cash, base_positions, dq = self._extract_portfolio_baseline(
            portfolio_state=portfolio_state,
            warnings=warnings,
        )

        baseline_state = {
            "symbol": symbol,
            "current_price": baseline_price,
            "position_quantity": qty,
            "position_notional": baseline_notional,
            "stop_loss_price": baseline_stop,
            "conviction_score": baseline_conviction,
            "portfolio_equity": base_equity,
            "portfolio_cash": base_cash,
            "position_count": len(base_positions),
        }

        # ── 2. Determine Candidate Shock Percentage ─────────────────────────────
        cand_shock = self._resolve_candidate_shock(
            scenario=scenario,
            candidate_context=candidate_context,
            warnings=warnings,
        )

        # ── 3. Calculate Stressed Candidate Position Impact ────────────────────
        stressed_price = max(0.0, round(baseline_price * (1.0 + cand_shock), 4))
        stressed_notional = round(qty * stressed_price, 2)
        abs_pnl = round(stressed_notional - baseline_notional, 2)
        pct_change = round(cand_shock * 100.0, 2)

        # ── 4. Calculate Portfolio Stress Impact ───────────────────────────────
        stressed_equity, affected_pos, sector_impact = self._calculate_portfolio_stress(
            base_cash=base_cash,
            base_positions=base_positions,
            scenario=scenario,
            candidate_symbol=symbol,
            stressed_notional=stressed_notional,
            baseline_notional=baseline_notional,
            candidate_context=candidate_context,
        )

        equity_diff = round(stressed_equity - base_equity, 2)
        pct_drawdown = round(max(0.0, ((base_equity - stressed_equity) / base_equity) * 100.0), 2) if base_equity > 0 else 0.0
        exp_after = round((stressed_notional / stressed_equity), 4) if stressed_equity > 0 else 0.0

        pos_impact = PositionImpact(
            symbol=symbol,
            baseline_price=baseline_price,
            stressed_price=stressed_price,
            quantity=qty,
            baseline_value=baseline_notional,
            stressed_value=stressed_notional,
            absolute_pnl_change=abs_pnl,
            pct_change=pct_change,
            exposure_after=exp_after,
        )

        port_impact = PortfolioImpact(
            baseline_equity=base_equity,
            stressed_equity=stressed_equity,
            absolute_loss_gain=equity_diff,
            pct_drawdown=pct_drawdown,
            affected_positions=affected_pos,
            sector_impact=sector_impact,
            concentration_impact={"exposure_after": exp_after},
        )

        # ── 5. Evaluate Stop-Loss Interaction ──────────────────────────────────
        stop_interaction = self._evaluate_stop_loss(
            candidate_plan=candidate_plan,
            stressed_price=stressed_price,
            baseline_price=baseline_price,
            scenario=scenario,
        )

        # ── 6. Evaluate Risk Limits Under Stress (Dry-Run) ──────────────────────
        risk_breaches = self._audit_risk_limits(
            scenario=scenario,
            stressed_price=stressed_price,
            stressed_equity=stressed_equity,
            stressed_notional=stressed_notional,
            stop_interaction=stop_interaction,
            candidate_plan=candidate_plan,
            risk_engine=risk_engine or self.risk_engine,
        )

        # ── 7. Evaluate Resilience, Severity, and Stress Score ─────────────────
        stress_score = self._compute_stress_score(
            cand_shock=cand_shock,
            pct_drawdown=pct_drawdown,
            stop_interaction=stop_interaction,
            risk_breaches=risk_breaches,
        )
        severity = self._classify_severity(stress_score, scenario)
        resilience = self._classify_resilience(
            cand_shock=cand_shock,
            pct_drawdown=pct_drawdown,
            stop_interaction=stop_interaction,
            risk_breaches=risk_breaches,
        )

        # ── 8. Conviction Context (Separated from Baseline) ─────────────────────
        adjusted_conv = self._calculate_scenario_conviction(
            baseline_conviction=baseline_conviction,
            resilience=resilience,
        )
        conv_context = ConvictionScenarioContext(
            baseline_conviction=baseline_conviction,
            scenario_resilience=resilience,
            scenario_adjusted_conviction=adjusted_conv,
            explanation=f"Scenario resilience evaluated as {resilience.value}; baseline conviction remains {baseline_conviction:.2f}.",
        )

        stressed_state = {
            "stressed_price": stressed_price,
            "stressed_value": stressed_notional,
            "stressed_equity": stressed_equity,
            "pct_drawdown": pct_drawdown,
            "stop_triggered": stop_interaction.stop_triggered,
            "risk_breaches_count": len(risk_breaches),
        }

        provenance.append({
            "source": "ScenarioEngine",
            "version": SCENARIO_ENGINE_VERSION,
            "scenario_name": scenario.name,
            "scenario_type": scenario.scenario_type.value,
            "timestamp": str(now),
            "cand_shock_pct": pct_change,
            "portfolio_drawdown_pct": pct_drawdown,
            "stress_score": stress_score,
        })

        return ScenarioResult(
            scenario_type=scenario.scenario_type,
            scenario_version=SCENARIO_ENGINE_VERSION,
            context_id=context_id,
            portfolio_id=port_id,
            candidate_symbol=symbol,
            baseline_state=baseline_state,
            stressed_state=stressed_state,
            market_impact={"scenario_name": scenario.name, "shock_pct": cand_shock * 100.0},
            position_impact=pos_impact,
            portfolio_impact=port_impact,
            risk_limit_breaches=risk_breaches,
            stop_loss_interaction=stop_interaction,
            conviction_context=conv_context,
            regime_context={"baseline_regime": market_regime.overall_regime.value if market_regime else "UNKNOWN", "target_regime": scenario.target_regime.value if scenario.target_regime else None},
            severity=severity,
            stress_score=stress_score,
            resilience=resilience,
            data_quality=dq,
            warnings=warnings,
            provenance=provenance,
            timestamp=now,
        )

    # ── Multi-Scenario Suite & Comparison ─────────────────────────────────────

    def run_scenario_suite(
        self,
        candidate_context: MarketContext,
        candidate_plan: Optional[PositionSizingPlan] = None,
        portfolio_state: Optional[Any] = None,
        scenarios: Optional[List[ScenarioDefinition]] = None,
        market_regime: Optional[MarketRegime] = None,
        risk_engine: Optional[RiskEngine] = None,
    ) -> ScenarioComparison:
        """
        Execute a complete battery of stress scenarios and synthesize a comparative report.
        """
        scen_list = scenarios or list(self.get_standard_scenarios().values())
        results: Dict[str, ScenarioResult] = {}

        for sc in scen_list:
            res = self.run_scenario(
                candidate_context=candidate_context,
                candidate_plan=candidate_plan,
                portfolio_state=portfolio_state,
                scenario_def=sc,
                market_regime=market_regime,
                risk_engine=risk_engine,
            )
            results[sc.name] = res

        # Determine worst-case (highest stress score) and most resilient (lowest stress score)
        worst_sc = max(results.keys(), key=lambda k: results[k].stress_score) if results else None
        best_sc = min(results.keys(), key=lambda k: results[k].stress_score) if results else None

        avg_score = sum(r.stress_score for r in results.values()) / max(1, len(results))
        if avg_score < 0.25:
            overall_res = ScenarioResilience.STRONG
        elif avg_score < 0.50:
            overall_res = ScenarioResilience.MODERATE
        elif avg_score < 0.75:
            overall_res = ScenarioResilience.WEAK
        else:
            overall_res = ScenarioResilience.FRAGILE

        summary = (
            f"Evaluated {len(results)} stress scenarios for {candidate_context.symbol}. "
            f"Defined stress maximum: '{worst_sc}' (Score: {results[worst_sc].stress_score:.2f}). "
            f"Overall resilience: {overall_res.value}."
        ) if worst_sc else "No scenarios evaluated."

        return ScenarioComparison(
            candidate_symbol=candidate_context.symbol,
            context_id=candidate_context.context_id,
            portfolio_id=getattr(portfolio_state, "portfolio_id", None) if portfolio_state else None,
            scenarios=results,
            worst_case_scenario=worst_sc,
            most_resilient_scenario=best_sc,
            overall_resilience=overall_res,
            summary=summary,
            generated_at=datetime.now(timezone.utc),
        )

    def generate_scenario_matrix(
        self,
        candidate_context: MarketContext,
        candidate_plan: Optional[PositionSizingPlan] = None,
        portfolio_state: Optional[Any] = None,
        scenarios: Optional[List[ScenarioDefinition]] = None,
    ) -> ScenarioMatrix:
        """Generate a structured tabular matrix of scenario stress impacts."""
        scen_list = scenarios or [
            self.get_standard_scenarios()["MARKET_CRASH_10"],
            self.get_standard_scenarios()["MARKET_CRASH_20"],
            self.get_standard_scenarios()["VOLATILITY_SPIKE_50"],
            self.get_standard_scenarios()["SECTOR_SHOCK_15"],
            self.get_standard_scenarios()["GAP_DOWN_8"],
        ]

        rows: List[ScenarioMatrixRow] = []
        for sc in scen_list:
            res = self.run_scenario(
                candidate_context=candidate_context,
                candidate_plan=candidate_plan,
                portfolio_state=portfolio_state,
                scenario_def=sc,
            )
            rows.append(ScenarioMatrixRow(
                scenario_name=sc.name,
                scenario_type=sc.scenario_type,
                candidate_pnl_pct=res.position_impact.pct_change,
                portfolio_drawdown_pct=res.portfolio_impact.pct_drawdown,
                stop_breached=res.stop_loss_interaction.stop_triggered,
                risk_breaches=len(res.risk_limit_breaches),
                severity=res.severity,
                resilience=res.resilience,
            ))

        return ScenarioMatrix(
            candidate_symbol=candidate_context.symbol,
            context_id=candidate_context.context_id,
            rows=rows,
            generated_at=datetime.now(timezone.utc),
        )

    # ── Dry-Run Risk Evaluation ───────────────────────────────────────────────

    def dry_run_risk(
        self,
        candidate_context: MarketContext,
        candidate_plan: PositionSizingPlan,
        scenario_result: ScenarioResult,
        portfolio_state: Optional[Any] = None,
    ) -> PositionSizingPlan:
        """
        Ask 'What would RiskEngine do under this hypothetical scenario?'
        Evaluates risk constraints against the stressed state without modifying
        actual baseline sizing.
        """
        # Create hypothetical context with stressed price
        stressed_ctx = candidate_context.model_copy(update={
            "current_price": scenario_result.position_impact.stressed_price,
            "warnings": list(candidate_context.warnings) + ["HYPOTHETICAL_STRESS_STATE"],
        })

        # Create hypothetical decision
        from backend.domain.investment_committee_schemas import (
            CommitteeDecision,
            CommitteeRecommendation,
        )
        hypothetical_decision = CommitteeDecision(
            decision_id=f"dry-{uuid.uuid4().hex[:8]}",
            context_id=candidate_context.context_id,
            symbol=candidate_context.symbol,
            recommendation=CommitteeRecommendation.BUY,
            conviction_score=scenario_result.conviction_context.scenario_adjusted_conviction,
            risk_score=min(1.0, 0.20 + (scenario_result.stress_score * 0.5)),
            risk_veto_applied=candidate_plan.veto_applied,  # Preserves real veto
            risk_veto_reason=candidate_plan.veto_reasons[0] if candidate_plan.veto_reasons else "",
        )

        return self.risk_engine.evaluate_and_size(
            committee_decision=hypothetical_decision,
            market_context=stressed_ctx,
            portfolio_state=portfolio_state,
        )

    # ── Private Calculation Helpers ───────────────────────────────────────────

    def _resolve_candidate_shock(
        self,
        scenario: ScenarioDefinition,
        candidate_context: MarketContext,
        warnings: List[str],
    ) -> float:
        """Determine discrete candidate return shock fraction deterministically."""
        st = scenario.scenario_type

        # 1. Direct Stock Shock
        if scenario.stock_return_shock is not None:
            return scenario.stock_return_shock

        # 2. Opening Price Shock (Gap)
        if scenario.opening_price_shock is not None:
            return scenario.opening_price_shock

        # 3. Sector Shock
        if scenario.sector_return_shock is not None:
            cand_sec = "UNKNOWN"
            if hasattr(candidate_context, "sector_data") and isinstance(candidate_context.sector_data, dict):
                cand_sec = candidate_context.sector_data.get("sector", "UNKNOWN")

            if cand_sec != "UNKNOWN":
                return scenario.sector_return_shock
            else:
                warnings.append("SECTOR_UNKNOWN: Candidate sector metadata missing; applying 50% beta shock.")
                return scenario.sector_return_shock * 0.50

        # 4. Market Return Shock (Crash / Rally / Drawdown)
        if scenario.market_return_shock is not None:
            # Check beta if available, default to 1.0
            beta = 1.0
            sec_data = getattr(candidate_context, "sector_data", {}) or {}
            if "beta" in sec_data and sec_data["beta"] is not None:
                beta = self._clean_number(sec_data["beta"])
                if beta <= 0:
                    beta = 1.0

            return scenario.market_return_shock * beta

        # 5. Volatility Spike
        if scenario.volatility_multiplier is not None:
            # Under a volatility spike, model adverse deviation: - (ATR or standard 4% * (mult - 1))
            mult = max(1.0, scenario.volatility_multiplier)
            return -round(0.04 * (mult - 1.0), 4)

        # 6. Regime Change
        if scenario.target_regime is not None:
            if scenario.target_regime == OverallMarketRegime.STRESSED:
                return -0.075
            elif scenario.target_regime == OverallMarketRegime.BEAR:
                return -0.05
            elif scenario.target_regime == OverallMarketRegime.BULL:
                return 0.05
            return 0.0

        # 7. Liquidity Stress
        if scenario.liquidity_multiplier is not None:
            # Liquidity collapse implies execution penalty of ~2%
            return -0.02

        return 0.0

    def _calculate_portfolio_stress(
        self,
        base_cash: float,
        base_positions: Dict[str, Any],
        scenario: ScenarioDefinition,
        candidate_symbol: str,
        stressed_notional: float,
        baseline_notional: float,
        candidate_context: MarketContext,
    ) -> Tuple[float, List[str], Dict[str, float]]:
        """Calculate stressed portfolio equity, affected holdings, and sector impacts."""
        stressed_positions_val = 0.0
        affected: List[str] = []
        sector_impacts: Dict[str, float] = {}

        # Determine broad holding shock
        holding_shock = scenario.market_return_shock if scenario.market_return_shock is not None else 0.0
        if scenario.sector_return_shock is not None:
            holding_shock = 0.0  # Sector shock applies only to that sector

        cand_sec = "UNKNOWN"
        if hasattr(candidate_context, "sector_data") and isinstance(candidate_context.sector_data, dict):
            cand_sec = candidate_context.sector_data.get("sector", "UNKNOWN")

        for sym, pos_data in base_positions.items():
            mv = self._clean_number(getattr(pos_data, "market_value", 0.0) if not isinstance(pos_data, dict) else pos_data.get("market_value", 0.0))
            sec = str(getattr(pos_data, "sector", "UNKNOWN") if not isinstance(pos_data, dict) else pos_data.get("sector", "UNKNOWN"))

            # Determine specific shock for this holding
            shock = holding_shock
            if scenario.sector_return_shock is not None and sec == cand_sec and sec != "UNKNOWN":
                shock = scenario.sector_return_shock

            stressed_mv = max(0.0, round(mv * (1.0 + shock), 2))
            stressed_positions_val += stressed_mv

            if shock != 0.0 and mv > 0.0:
                affected.append(sym)
                sector_impacts[sec] = round(sector_impacts.get(sec, 0.0) + (stressed_mv - mv), 2)

        # Include candidate if it was not already in portfolio
        total_stressed_eq = base_cash + stressed_positions_val
        return round(total_stressed_eq, 2), affected, sector_impacts

    def _evaluate_stop_loss(
        self,
        candidate_plan: Optional[PositionSizingPlan],
        stressed_price: float,
        baseline_price: float,
        scenario: ScenarioDefinition,
    ) -> StopLossInteraction:
        """Evaluate stop-loss trigger and gap-through slippage mechanics."""
        if not candidate_plan or not candidate_plan.stop_loss_price:
            return StopLossInteraction(
                stop_loss_price=None,
                scenario_price=stressed_price,
                stop_triggered=False,
                gap_through=False,
                potential_slippage=0.0,
                execution_price_estimate=stressed_price,
                description="No active stop-loss defined on candidate plan.",
            )

        stop_p = float(candidate_plan.stop_loss_price)
        direction = getattr(candidate_plan, "direction", PositionDirection.LONG)

        if direction == PositionDirection.LONG:
            stop_triggered = stressed_price <= stop_p
            gap_through = stressed_price < stop_p
            slippage = max(0.0, round(stop_p - stressed_price, 4)) if gap_through else 0.0
            exec_p = stressed_price if gap_through else stop_p if stop_triggered else baseline_price
        else:
            stop_triggered = stressed_price >= stop_p
            gap_through = stressed_price > stop_p
            slippage = max(0.0, round(stressed_price - stop_p, 4)) if gap_through else 0.0
            exec_p = stressed_price if gap_through else stop_p if stop_triggered else baseline_price

        desc_parts = []
        if stop_triggered:
            desc_parts.append(f"Stop level {stop_p} triggered.")
            if gap_through:
                desc_parts.append(f"Price gapped through stop to {stressed_price}; estimated slippage: {slippage:.2f}.")
            else:
                desc_parts.append("Clean stop exit at trigger price.")
        else:
            desc_parts.append(f"Price {stressed_price} remains above stop {stop_p}.")

        return StopLossInteraction(
            stop_loss_price=stop_p,
            scenario_price=stressed_price,
            stop_triggered=stop_triggered,
            gap_through=gap_through,
            potential_slippage=slippage,
            execution_price_estimate=exec_p,
            description=" ".join(desc_parts),
        )

    def _audit_risk_limits(
        self,
        scenario: ScenarioDefinition,
        stressed_price: float,
        stressed_equity: float,
        stressed_notional: float,
        stop_interaction: StopLossInteraction,
        candidate_plan: Optional[PositionSizingPlan],
        risk_engine: RiskEngine,
    ) -> List[str]:
        """Audit risk limit breaches under hypothetical stress."""
        breaches: List[str] = []
        cfg = risk_engine.config

        if stressed_equity > 0:
            stressed_exp = stressed_notional / stressed_equity
            if stressed_exp > cfg.max_position_pct:
                breaches.append(f"POSITION_EXPOSURE_BREACH: Stressed exposure {stressed_exp*100:.1f}% exceeds limit {cfg.max_position_pct*100:.0f}%.")

        if stop_interaction.gap_through and stop_interaction.potential_slippage > 0:
            breaches.append(f"STOP_LOSS_OVERSHOOT: Price gapped past stop loss by {stop_interaction.potential_slippage:.2f}.")

        if candidate_plan and candidate_plan.veto_applied:
            breaches.append(f"BASELINE_RISK_VETO: Real risk veto is active: {candidate_plan.veto_reasons[0] if candidate_plan.veto_reasons else 'Vetoed'}.")

        return breaches

    def _compute_stress_score(
        self,
        cand_shock: float,
        pct_drawdown: float,
        stop_interaction: StopLossInteraction,
        risk_breaches: List[str],
    ) -> float:
        """Compute normalized deterministic stress score in [0.0, 1.0]."""
        loss_component = min(1.0, abs(min(0.0, cand_shock)) / 0.20)
        drawdown_component = min(1.0, pct_drawdown / 25.0)
        stop_component = 0.5 if stop_interaction.stop_triggered else 0.0
        if stop_interaction.gap_through:
            stop_component = 1.0
        breach_component = min(1.0, len(risk_breaches) * 0.35)

        raw_score = (0.35 * loss_component) + (0.35 * drawdown_component) + (0.15 * stop_component) + (0.15 * breach_component)
        return round(max(0.0, min(1.0, raw_score)), 4)

    def _classify_severity(self, stress_score: float, scenario: ScenarioDefinition) -> ScenarioSeverity:
        """Classify scenario condition severity."""
        if stress_score < 0.20:
            return ScenarioSeverity.LOW
        elif stress_score < 0.45:
            return ScenarioSeverity.MODERATE
        elif stress_score < 0.70:
            return ScenarioSeverity.HIGH
        elif stress_score < 0.85:
            return ScenarioSeverity.SEVERE
        return ScenarioSeverity.EXTREME

    def _classify_resilience(
        self,
        cand_shock: float,
        pct_drawdown: float,
        stop_interaction: StopLossInteraction,
        risk_breaches: List[str],
    ) -> ScenarioResilience:
        """Classify resilience of the decision / portfolio under stress."""
        if pct_drawdown > 20.0 or stop_interaction.gap_through or len(risk_breaches) >= 2:
            return ScenarioResilience.FRAGILE
        elif stop_interaction.stop_triggered or pct_drawdown > 10.0 or len(risk_breaches) >= 1:
            return ScenarioResilience.WEAK
        elif pct_drawdown > 4.0 or abs(cand_shock) > 0.05:
            return ScenarioResilience.MODERATE
        return ScenarioResilience.STRONG

    def _calculate_scenario_conviction(
        self,
        baseline_conviction: float,
        resilience: ScenarioResilience,
    ) -> float:
        """Compute scenario-adjusted conviction without mutating baseline."""
        if resilience == ScenarioResilience.STRONG:
            return round(baseline_conviction, 4)
        elif resilience == ScenarioResilience.MODERATE:
            return round(baseline_conviction * 0.90, 4)
        elif resilience == ScenarioResilience.WEAK:
            return round(baseline_conviction * 0.70, 4)
        elif resilience == ScenarioResilience.FRAGILE:
            return round(baseline_conviction * 0.40, 4)
        return round(baseline_conviction * 0.50, 4)

    def _extract_portfolio_baseline(
        self,
        portfolio_state: Any,
        warnings: List[str],
    ) -> Tuple[Optional[str], float, float, Dict[str, Any], ScenarioDataQuality]:
        """Safely extract active portfolio baseline values."""
        if portfolio_state is None:
            return None, 100000.0, 100000.0, {}, ScenarioDataQuality.PARTIAL

        def _get(attr: str, default: Any = None) -> Any:
            if isinstance(portfolio_state, dict):
                return portfolio_state.get(attr, default)
            return getattr(portfolio_state, attr, default)

        port_id = _get("portfolio_id", None)
        eq = self._clean_number(_get("total_equity", 100000.0))
        cash = self._clean_number(_get("cash", eq))
        positions = _get("positions", {}) or {}

        dq = ScenarioDataQuality.FRESH
        updated_at = _get("updated_at", None)
        if isinstance(updated_at, datetime):
            up_tz = updated_at if updated_at.tzinfo else updated_at.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            age_hours = (now - up_tz).total_seconds() / 3600.0
            if age_hours > 24.0:
                dq = ScenarioDataQuality.STALE
                warnings.append("STALE_PORTFOLIO: Portfolio data is older than 24 hours.")

        if not positions and eq == 0.0:
            dq = ScenarioDataQuality.UNAVAILABLE

        return port_id, eq, cash, positions, dq

    def _clean_number(self, val: Any) -> float:
        """Sanitize numerical input, converting NaN/Inf/None to 0.0."""
        if val is None:
            return 0.0
        try:
            f = float(val)
            if math.isnan(f) or math.isinf(f):
                return 0.0
            return f
        except (ValueError, TypeError):
            return 0.0
