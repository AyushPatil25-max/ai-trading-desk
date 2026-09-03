"""
Phase 6.4 — Risk Management & Position Sizing Engine

Production-grade, deterministic risk evaluation and position sizing layer.
Consumes CommitteeDecision and MarketContext to produce a validated PositionSizingPlan.
All numerical calculations are executed in pure Python — zero LLM math.
"""

from datetime import datetime, timezone
import logging
import math
from typing import Any, Dict, List, Optional
import uuid

from backend.domain.investment_committee_schemas import (
    CommitteeRecommendation,
    DataQualityStatus,
    CommitteeDecision,
)
from backend.domain.risk_schemas import (
    PositionDirection,
    StopLossMethod,
    RiskConstraintType,
    RiskConstraintResult,
    RiskConfiguration,
    PositionSizingPlan,
    RiskAssessmentResult,
)
from backend.domain.schemas import MarketContext
from backend.infrastructure.llm import LLMClient

logger = logging.getLogger(__name__)


class RiskEngine:
    """
    Authoritative deterministic risk management and position sizing engine.

    Responsibilities:
    1. Account capital verification
    2. Numerical integrity & finite number checks
    3. Trade direction mapping from CommitteeDecision
    4. Stop-loss derivation (explicit, technical invalidation, percentage fallback)
    5. Take-profit & Risk/Reward evaluation
    6. Conviction and data-quality based sizing adjustments
    7. Hard risk constraints & risk veto overrides
    8. Deterministic share quantity flooring (math.floor)
    9. Auditable constraints trace and provenance propagation
    """

    def __init__(
        self,
        config: Optional[RiskConfiguration] = None,
        llm_client: Optional[LLMClient] = None,
    ) -> None:
        self.config = config or RiskConfiguration()
        self.llm_client = llm_client

    def evaluate_and_size(
        self,
        committee_decision: CommitteeDecision,
        market_context: Optional[MarketContext] = None,
        portfolio_state: Optional[Any] = None,
        explicit_stop_loss: Optional[float] = None,
        explicit_take_profit: Optional[float] = None,
        calibration: Optional[Any] = None,
        portfolio_intelligence: Optional[Any] = None,
        market_regime: Optional[Any] = None,
    ) -> PositionSizingPlan:
        """
        Evaluate risk constraints and calculate the exact position size deterministically.

        Parameters
        ----------
        committee_decision : CommitteeDecision
            Upstream synthesis from Phase 6.3 Investment Committee.
        market_context : Optional[MarketContext]
            Market context providing entry price, technical indicators, and provenance.
        portfolio_state : Optional[Any]
            Optional active portfolio tracking for exposure constraints.
        explicit_stop_loss : Optional[float]
            Optional user-specified or explicit stop-loss price.
        explicit_take_profit : Optional[float]
            Optional user-specified or explicit take-profit price.
        calibration : Optional[Any]
            Optional Phase 6.5 ConvictionCalibrationResult.

        Returns
        -------
        PositionSizingPlan
            Validated, auditable position sizing plan.
        """
        plan_id = f"plan-{uuid.uuid4().hex[:12]}"
        symbol = committee_decision.symbol
        context_id = committee_decision.context_id
        run_id = committee_decision.run_id
        decision_id = committee_decision.decision_id
        data_quality = committee_decision.data_quality
        conviction_score = (
            float(calibration.calibrated_conviction)
            if calibration is not None and hasattr(calibration, "calibrated_conviction")
            else committee_decision.conviction_score
        )

        constraints_applied: List[RiskConstraintResult] = []
        veto_reasons: List[str] = []
        veto_applied = False

        # ── 1. Capital Integrity ──────────────────────────────────────────────
        capital = self.config.account_capital
        if capital is None or math.isnan(capital) or math.isinf(capital) or capital <= 0:
            veto_applied = True
            veto_reasons.append(f"INVALID_CAPITAL: Account capital {capital} is non-positive or non-finite.")
            constraints_applied.append(RiskConstraintResult(
                constraint_type=RiskConstraintType.CAPITAL_INTEGRITY,
                passed=False,
                limit_value=0.0,
                actual_value=capital if (capital is not None and not math.isnan(capital) and not math.isinf(capital)) else None,
                action_taken="VETOED",
                description="Account capital must be a finite positive number.",
            ))
        else:
            constraints_applied.append(RiskConstraintResult(
                constraint_type=RiskConstraintType.CAPITAL_INTEGRITY,
                passed=True,
                actual_value=capital,
                description="Account capital is valid and positive.",
            ))

        # ── 2. Entry Price Determination & Integrity ──────────────────────────
        entry_price = 0.0
        if market_context and hasattr(market_context, "current_price"):
            entry_price = float(market_context.current_price)

        if math.isnan(entry_price) or math.isinf(entry_price) or entry_price <= 0:
            veto_applied = True
            veto_reasons.append(f"INVALID_PRICE: Entry price {entry_price} is non-positive or non-finite.")
            constraints_applied.append(RiskConstraintResult(
                constraint_type=RiskConstraintType.PRICE_INTEGRITY,
                passed=False,
                limit_value=0.0,
                actual_value=entry_price if (not math.isnan(entry_price) and not math.isinf(entry_price)) else None,
                action_taken="VETOED",
                description="Entry price must be a finite positive number.",
            ))
            entry_price = max(0.0, entry_price) if (not math.isnan(entry_price) and not math.isinf(entry_price)) else 0.0
        else:
            constraints_applied.append(RiskConstraintResult(
                constraint_type=RiskConstraintType.PRICE_INTEGRITY,
                passed=True,
                actual_value=entry_price,
                description="Entry price is verified positive and finite.",
            ))

        # ── 3. Recommendation & Direction Mapping ─────────────────────────────
        direction = PositionDirection.FLAT
        rec = committee_decision.recommendation

        if rec in (CommitteeRecommendation.STRONG_BUY, CommitteeRecommendation.BUY):
            direction = PositionDirection.LONG
            constraints_applied.append(RiskConstraintResult(
                constraint_type=RiskConstraintType.COMMITTEE_APPROVAL,
                passed=True,
                action_taken="ALLOWED",
                description=f"Approved for LONG sizing by recommendation '{rec.value}'.",
            ))
        elif rec == CommitteeRecommendation.SELL:
            if self.config.allow_short:
                direction = PositionDirection.SHORT
                constraints_applied.append(RiskConstraintResult(
                    constraint_type=RiskConstraintType.COMMITTEE_APPROVAL,
                    passed=True,
                    action_taken="ALLOWED",
                    description="Approved for SHORT sizing by recommendation 'SELL'.",
                ))
                constraints_applied.append(RiskConstraintResult(
                    constraint_type=RiskConstraintType.SHORT_POLICY,
                    passed=True,
                    action_taken="ALLOWED",
                    description="Short selling permitted by RiskConfiguration.",
                ))
            else:
                direction = PositionDirection.FLAT
                veto_applied = True
                veto_reasons.append("SHORT_SELLING_DISABLED: Short position requested by SELL recommendation, but short selling is disabled in RiskConfiguration.")
                constraints_applied.append(RiskConstraintResult(
                    constraint_type=RiskConstraintType.SHORT_POLICY,
                    passed=False,
                    action_taken="VETOED",
                    description="Short selling disabled in RiskConfiguration.",
                ))
        else:
            direction = PositionDirection.FLAT
            veto_applied = True
            veto_reasons.append(f"COMMITTEE_NON_ACTIONABLE: Recommendation '{rec.value}' is non-actionable.")
            constraints_applied.append(RiskConstraintResult(
                constraint_type=RiskConstraintType.COMMITTEE_APPROVAL,
                passed=False,
                action_taken="VETOED",
                description=f"Recommendation '{rec.value}' requires no capital commitment.",
            ))

        # ── 4. Upstream Risk Veto & Risk Score ────────────────────────────────
        if committee_decision.risk_veto_applied:
            veto_applied = True
            reason = committee_decision.risk_veto_reason or "Risk veto was applied upstream by Investment Committee."
            veto_reasons.append(f"UPSTREAM_RISK_VETO: {reason}")
            constraints_applied.append(RiskConstraintResult(
                constraint_type=RiskConstraintType.RISK_VETO,
                passed=False,
                action_taken="VETOED",
                description=f"Upstream risk veto: {reason}",
            ))

        if committee_decision.risk_score > self.config.max_allowed_risk_score:
            veto_applied = True
            veto_reasons.append(
                f"EXCESSIVE_RISK_SCORE: Risk score {committee_decision.risk_score:.2f} "
                f"exceeds threshold {self.config.max_allowed_risk_score:.2f}."
            )
            constraints_applied.append(RiskConstraintResult(
                constraint_type=RiskConstraintType.RISK_VETO,
                passed=False,
                limit_value=self.config.max_allowed_risk_score,
                actual_value=committee_decision.risk_score,
                action_taken="VETOED",
                description=f"Risk score {committee_decision.risk_score:.2f} exceeds threshold.",
            ))

        # ── 5. Conviction Threshold ───────────────────────────────────────────
        if conviction_score < self.config.minimum_conviction:
            veto_applied = True
            veto_reasons.append(
                f"INSUFFICIENT_CONVICTION: Conviction score {conviction_score:.2f} "
                f"is below minimum {self.config.minimum_conviction:.2f}."
            )
            constraints_applied.append(RiskConstraintResult(
                constraint_type=RiskConstraintType.CONVICTION_THRESHOLD,
                passed=False,
                limit_value=self.config.minimum_conviction,
                actual_value=conviction_score,
                action_taken="VETOED",
                description=f"Conviction {conviction_score:.2f} below threshold {self.config.minimum_conviction:.2f}.",
            ))
        else:
            constraints_applied.append(RiskConstraintResult(
                constraint_type=RiskConstraintType.CONVICTION_THRESHOLD,
                passed=True,
                limit_value=self.config.minimum_conviction,
                actual_value=conviction_score,
                description="Conviction score satisfies minimum requirement.",
            ))

        # ── 6. Data Quality & Sizing Restrictions ─────────────────────────────
        quality_multiplier = 1.0
        if data_quality == DataQualityStatus.INSUFFICIENT:
            veto_applied = True
            quality_multiplier = 0.0
            veto_reasons.append("DATA_QUALITY_INSUFFICIENT: Critical evidence is insufficient for capital commitment.")
            constraints_applied.append(RiskConstraintResult(
                constraint_type=RiskConstraintType.DATA_QUALITY,
                passed=False,
                action_taken="VETOED",
                description="Data quality INSUFFICIENT produces immediate zero position.",
            ))
        elif data_quality == DataQualityStatus.STALE:
            veto_applied = True
            quality_multiplier = 0.0
            veto_reasons.append("DATA_QUALITY_STALE: Data timestamp exceeds freshness limits.")
            constraints_applied.append(RiskConstraintResult(
                constraint_type=RiskConstraintType.DATA_QUALITY,
                passed=False,
                action_taken="VETOED",
                description="Data quality STALE produces immediate zero position.",
            ))
        elif data_quality == DataQualityStatus.DEGRADED:
            quality_multiplier = 0.50  # 50% risk sizing restriction
            constraints_applied.append(RiskConstraintResult(
                constraint_type=RiskConstraintType.DATA_QUALITY,
                passed=True,
                limit_value=0.50,
                actual_value=quality_multiplier,
                action_taken="SIZED_DOWN",
                description="Data quality DEGRADED imposes 50% sizing haircut.",
            ))
        elif data_quality == DataQualityStatus.PARTIAL:
            quality_multiplier = 0.70  # 70% risk sizing restriction
            constraints_applied.append(RiskConstraintResult(
                constraint_type=RiskConstraintType.DATA_QUALITY,
                passed=True,
                limit_value=0.70,
                actual_value=quality_multiplier,
                action_taken="SIZED_DOWN",
                description="Data quality PARTIAL imposes 30% sizing haircut.",
            ))
        else:
            constraints_applied.append(RiskConstraintResult(
                constraint_type=RiskConstraintType.DATA_QUALITY,
                passed=True,
                action_taken="ALLOWED",
                description="Data quality AVAILABLE allows full sizing.",
            ))

        # Check for failed specialists
        if committee_decision.failed_specialists:
            if len(committee_decision.failed_specialists) >= 2 or any(
                s in committee_decision.failed_specialists for s in ["TechnicalSpecialist", "FundamentalSpecialist"]
            ):
                veto_applied = True
                veto_reasons.append(f"FAILED_SPECIALISTS: Critical specialists failed: {committee_decision.failed_specialists}")
                constraints_applied.append(RiskConstraintResult(
                    constraint_type=RiskConstraintType.DATA_QUALITY,
                    passed=False,
                    action_taken="VETOED",
                    description=f"Specialist failures: {committee_decision.failed_specialists}",
                ))

        # ── 7. Stop-Loss Determination & Directional Sanity ────────────────────
        stop_loss_price, stop_loss_source, stop_loss_method = self._determine_stop_loss(
            direction=direction,
            entry_price=entry_price,
            market_context=market_context,
            explicit_stop_loss=explicit_stop_loss,
        )

        if math.isnan(stop_loss_price) or math.isinf(stop_loss_price) or stop_loss_price <= 0:
            veto_applied = True
            veto_reasons.append(f"INVALID_STOP_LOSS: Stop price {stop_loss_price} is non-positive or non-finite.")
            constraints_applied.append(RiskConstraintResult(
                constraint_type=RiskConstraintType.PRICE_INTEGRITY,
                passed=False,
                limit_value=0.0,
                actual_value=stop_loss_price if (not math.isnan(stop_loss_price) and not math.isinf(stop_loss_price)) else None,
                action_taken="VETOED",
                description="Stop-loss price must be a finite positive number.",
            ))
            stop_loss_price = max(0.0, stop_loss_price) if (not math.isnan(stop_loss_price) and not math.isinf(stop_loss_price)) else 0.0

        risk_distance = abs(entry_price - stop_loss_price) if entry_price > 0 and stop_loss_price > 0 else 0.0

        if entry_price > 0 and stop_loss_price > 0:
            if risk_distance <= 1e-6:
                veto_applied = True
                veto_reasons.append(f"ZERO_RISK_DISTANCE: Entry price ({entry_price}) and stop-loss price ({stop_loss_price}) are identical.")
                constraints_applied.append(RiskConstraintResult(
                    constraint_type=RiskConstraintType.PRICE_INTEGRITY,
                    passed=False,
                    actual_value=risk_distance,
                    action_taken="VETOED",
                    description="Zero risk distance between entry and stop.",
                ))

            if direction == PositionDirection.LONG and stop_loss_price >= entry_price:
                veto_applied = True
                veto_reasons.append(
                    f"INVALID_LONG_STOP: Stop-loss ({stop_loss_price}) must be strictly less than "
                    f"entry ({entry_price}) for a LONG trade."
                )
                constraints_applied.append(RiskConstraintResult(
                    constraint_type=RiskConstraintType.PRICE_INTEGRITY,
                    passed=False,
                    limit_value=entry_price,
                    actual_value=stop_loss_price,
                    action_taken="VETOED",
                    description="Long stop-loss must be strictly below entry price.",
                ))
            elif direction == PositionDirection.SHORT and stop_loss_price <= entry_price:
                veto_applied = True
                veto_reasons.append(
                    f"INVALID_SHORT_STOP: Stop-loss ({stop_loss_price}) must be strictly greater than "
                    f"entry ({entry_price}) for a SHORT trade."
                )
                constraints_applied.append(RiskConstraintResult(
                    constraint_type=RiskConstraintType.PRICE_INTEGRITY,
                    passed=False,
                    limit_value=entry_price,
                    actual_value=stop_loss_price,
                    action_taken="VETOED",
                    description="Short stop-loss must be strictly above entry price.",
                ))

        # ── 8. Take-Profit & Risk/Reward Calculation ───────────────────────────
        take_profit_price, risk_reward_ratio = self._calculate_risk_reward(
            direction=direction,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            risk_distance=risk_distance,
            market_context=market_context,
            explicit_take_profit=explicit_take_profit,
        )

        if direction in (PositionDirection.LONG, PositionDirection.SHORT) and risk_reward_ratio is not None:
            if risk_reward_ratio < self.config.minimum_risk_reward_ratio:
                veto_applied = True
                veto_reasons.append(
                    f"INSUFFICIENT_RISK_REWARD: Risk/reward ratio {risk_reward_ratio:.2f} "
                    f"is below minimum {self.config.minimum_risk_reward_ratio:.2f}."
                )
                constraints_applied.append(RiskConstraintResult(
                    constraint_type=RiskConstraintType.MIN_RISK_REWARD,
                    passed=False,
                    limit_value=self.config.minimum_risk_reward_ratio,
                    actual_value=risk_reward_ratio,
                    action_taken="VETOED",
                    description=f"R:R ratio {risk_reward_ratio:.2f} below required minimum.",
                ))
            else:
                constraints_applied.append(RiskConstraintResult(
                    constraint_type=RiskConstraintType.MIN_RISK_REWARD,
                    passed=True,
                    limit_value=self.config.minimum_risk_reward_ratio,
                    actual_value=risk_reward_ratio,
                    description="Risk/reward ratio satisfies minimum threshold.",
                ))

        # ── 9. Mathematical Position Sizing ───────────────────────────────────
        position_quantity = 0
        position_notional = 0.0
        exposure_pct = 0.0
        risk_budget = 0.0
        risk_per_trade_pct = 0.0
        risk_per_share = risk_distance

        if not veto_applied and entry_price > 0 and risk_per_share > 0 and capital > 0:
            # Scale trade risk by conviction and data quality
            conviction_multiplier = max(0.40, min(1.0, conviction_score))
            effective_trade_risk_pct = self.config.max_trade_risk_pct * conviction_multiplier * quality_multiplier
            risk_budget = capital * effective_trade_risk_pct

            # 1. Quantity by Risk Budget:
            qty_risk = math.floor(risk_budget / risk_per_share)
            constraints_applied.append(RiskConstraintResult(
                constraint_type=RiskConstraintType.MAX_TRADE_RISK,
                passed=True,
                limit_value=risk_budget,
                actual_value=float(qty_risk * risk_per_share),
                description=f"Risk budget constraint yields max {qty_risk} shares.",
            ))

            # 2. Quantity by Max Position Allocation Constraint:
            max_pos_budget = capital * self.config.max_position_pct
            qty_alloc = math.floor(max_pos_budget / entry_price)
            constraints_applied.append(RiskConstraintResult(
                constraint_type=RiskConstraintType.MAX_POSITION_ALLOCATION,
                passed=True,
                limit_value=max_pos_budget,
                actual_value=float(qty_alloc * entry_price),
                description=f"Max position allocation constraint ({int(self.config.max_position_pct*100)}%) yields max {qty_alloc} shares.",
            ))

            # 3. Portfolio-level Constraints:
            qty_portfolio = qty_alloc
            active_portfolio = portfolio_state or portfolio_intelligence
            if active_portfolio is not None:
                existing_symbol_val = 0.0
                if hasattr(active_portfolio, "positions") and isinstance(active_portfolio.positions, dict):
                    if symbol in active_portfolio.positions:
                        pos = active_portfolio.positions[symbol]
                        existing_symbol_val = getattr(pos, "market_value", 0.0) or 0.0

                rem_symbol_budget = max(0.0, (capital * self.config.max_single_asset_exposure_pct) - existing_symbol_val)
                qty_single_asset = math.floor(rem_symbol_budget / entry_price)
                qty_portfolio = min(qty_portfolio, qty_single_asset)
                constraints_applied.append(RiskConstraintResult(
                    constraint_type=RiskConstraintType.MAX_SINGLE_ASSET,
                    passed=True,
                    limit_value=rem_symbol_budget,
                    actual_value=float(qty_single_asset * entry_price),
                    description="Evaluated against active portfolio single-asset exposure limit.",
                ))

                total_invested = getattr(active_portfolio, "total_market_value", getattr(active_portfolio, "market_value", 0.0)) or 0.0
                rem_portfolio_budget = max(0.0, (capital * self.config.max_portfolio_risk_pct * 10) - total_invested)
                qty_total_exposure = math.floor(rem_portfolio_budget / entry_price)
                qty_portfolio = min(qty_portfolio, qty_total_exposure)
                constraints_applied.append(RiskConstraintResult(
                    constraint_type=RiskConstraintType.MAX_PORTFOLIO_EXPOSURE,
                    passed=True,
                    limit_value=rem_portfolio_budget,
                    actual_value=float(qty_total_exposure * entry_price),
                    description="Evaluated against active portfolio total exposure limit.",
                ))
                # Sector-level Constraints:
                active_sector_exposures = getattr(active_portfolio, "sector_exposures", None)

                if active_sector_exposures and market_context:
                    cand_sector = "UNKNOWN"
                    if hasattr(market_context, "sector_data") and isinstance(market_context.sector_data, dict):
                        cand_sector = market_context.sector_data.get("sector", "UNKNOWN")

                    if cand_sector != "UNKNOWN" and cand_sector in active_sector_exposures:
                        sec_info = active_sector_exposures[cand_sector]
                        curr_sec_mv = getattr(sec_info, "market_value", 0.0) or 0.0
                        max_sec_budget = capital * self.config.max_sector_exposure_pct
                        rem_sec_budget = max(0.0, max_sec_budget - curr_sec_mv)
                        qty_sector = math.floor(rem_sec_budget / entry_price)
                        qty_portfolio = min(qty_portfolio, qty_sector)
                        passed_sec = curr_sec_mv < max_sec_budget
                        constraints_applied.append(RiskConstraintResult(
                            constraint_type=RiskConstraintType.MAX_SECTOR_EXPOSURE,
                            passed=passed_sec,
                            limit_value=max_sec_budget,
                            actual_value=float(curr_sec_mv),
                            action_taken="ALLOWED" if passed_sec else "VETOED",
                            description=f"Evaluated against sector '{cand_sector}' exposure limit ({self.config.max_sector_exposure_pct*100:.0f}%).",
                        ))
                        if not passed_sec:
                            veto_applied = True
                            veto_reasons.append(f"SECTOR_EXPOSURE_EXCEEDED: Sector '{cand_sector}' allocation already exceeds maximum allowable threshold.")

            else:
                constraints_applied.append(RiskConstraintResult(
                    constraint_type=RiskConstraintType.MAX_PORTFOLIO_EXPOSURE,
                    passed=True,
                    description="Portfolio state not provided; evaluated against account capital.",
                ))

            # Sizing is the minimum across all constraints:
            position_quantity = int(max(0, min(qty_risk, qty_alloc, qty_portfolio)))
            position_notional = float(position_quantity * entry_price)
            exposure_pct = float(position_notional / capital) if capital > 0 else 0.0
            risk_per_trade_pct = float((position_quantity * risk_per_share) / capital) if capital > 0 else 0.0

            if position_quantity == 0:
                veto_applied = True
                veto_reasons.append("POSITION_SIZE_ZERO: Position sizing constraints resulted in zero whole shares.")
        else:
            position_quantity = 0
            position_notional = 0.0
            exposure_pct = 0.0
            risk_budget = 0.0
            risk_per_trade_pct = 0.0

        # Provenance preservation
        provenance: List[Dict[str, Any]] = []
        if market_context and hasattr(market_context, "provenance") and market_context.provenance:
            for p in market_context.provenance:
                if hasattr(p, "model_dump"):
                    provenance.append(p.model_dump())
                elif isinstance(p, dict):
                    provenance.append(p)
        elif hasattr(committee_decision, "provenance") and committee_decision.provenance:
            provenance.extend(committee_decision.provenance)

        notes = ""
        if veto_applied:
            notes = f"Position vetoed: {'; '.join(veto_reasons)}"
        else:
            notes = (
                f"Sized {position_quantity} shares of {symbol} ({direction.value}) "
                f"at {entry_price:.2f} with stop at {stop_loss_price:.2f}. "
                f"Notional: {position_notional:.2f} ({exposure_pct*100:.2f}% equity)."
            )

        return PositionSizingPlan(
            plan_id=plan_id,
            context_id=context_id,
            symbol=symbol,
            run_id=run_id,
            decision_id=decision_id,
            direction=direction,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            risk_per_share=risk_per_share,
            risk_budget=risk_budget,
            risk_per_trade_pct=risk_per_trade_pct,
            position_quantity=position_quantity,
            position_notional=position_notional,
            exposure_pct=exposure_pct,
            risk_reward_ratio=risk_reward_ratio,
            sizing_method="DETERMINISTIC_RISK_BUDGET",
            stop_loss_source=stop_loss_source,
            stop_loss_method=stop_loss_method,
            constraints_applied=constraints_applied,
            veto_applied=veto_applied,
            veto_reasons=veto_reasons,
            data_quality=data_quality,
            conviction_score=conviction_score,
            timestamp=datetime.now(timezone.utc),
            provenance=provenance,
            notes=notes,
        )

    def _determine_stop_loss(
        self,
        direction: PositionDirection,
        entry_price: float,
        market_context: Optional[MarketContext],
        explicit_stop_loss: Optional[float],
    ) -> tuple[float, str, StopLossMethod]:
        """Determine the stop-loss price and tracking metadata."""
        if explicit_stop_loss is not None and not math.isnan(explicit_stop_loss) and explicit_stop_loss > 0:
            return float(explicit_stop_loss), "EXPLICIT_SPECIFIED", StopLossMethod.EXPLICIT

        if entry_price <= 0 or math.isnan(entry_price) or math.isinf(entry_price):
            return 0.0, "INVALID_ENTRY", StopLossMethod.UNAVAILABLE

        ind: Dict[str, Any] = {}
        if market_context and hasattr(market_context, "technical_indicators") and market_context.technical_indicators:
            ind = market_context.technical_indicators

        if direction == PositionDirection.LONG:
            # Check technical support levels below entry
            ema50 = ind.get("ema50")
            if ema50 is not None and isinstance(ema50, (int, float)) and not math.isnan(ema50):
                if 0.85 * entry_price <= ema50 < entry_price:
                    return float(ema50), "TECHNICAL_EMA50", StopLossMethod.TECHNICAL_INVALIDATION

            ema20 = ind.get("ema20")
            if ema20 is not None and isinstance(ema20, (int, float)) and not math.isnan(ema20):
                if 0.85 * entry_price <= ema20 < entry_price:
                    return float(ema20), "TECHNICAL_EMA20", StopLossMethod.TECHNICAL_INVALIDATION

            stop_price = entry_price * (1.0 - self.config.default_stop_loss_pct)
            return stop_price, f"CONFIGURED_PERCENTAGE_{int(self.config.default_stop_loss_pct*100)}PCT", StopLossMethod.CONFIGURED_PERCENTAGE

        elif direction == PositionDirection.SHORT:
            # Check technical resistance levels above entry
            high20 = ind.get("20_day_high")
            if high20 is not None and isinstance(high20, (int, float)) and not math.isnan(high20):
                if entry_price < high20 <= 1.15 * entry_price:
                    return float(high20), "TECHNICAL_20_DAY_HIGH", StopLossMethod.TECHNICAL_INVALIDATION

            ema20 = ind.get("ema20")
            if ema20 is not None and isinstance(ema20, (int, float)) and not math.isnan(ema20):
                if entry_price < ema20 <= 1.15 * entry_price:
                    return float(ema20), "TECHNICAL_EMA20", StopLossMethod.TECHNICAL_INVALIDATION

            stop_price = entry_price * (1.0 + self.config.default_stop_loss_pct)
            return stop_price, f"CONFIGURED_PERCENTAGE_{int(self.config.default_stop_loss_pct*100)}PCT", StopLossMethod.CONFIGURED_PERCENTAGE

        else:
            stop_price = entry_price * (1.0 - self.config.default_stop_loss_pct)
            return stop_price, "DEFAULT_PERCENTAGE", StopLossMethod.CONFIGURED_PERCENTAGE

    def _calculate_risk_reward(
        self,
        direction: PositionDirection,
        entry_price: float,
        stop_loss_price: float,
        risk_distance: float,
        market_context: Optional[MarketContext],
        explicit_take_profit: Optional[float],
    ) -> tuple[Optional[float], Optional[float]]:
        """Calculate take-profit target and reward-to-risk ratio."""
        if entry_price <= 0 or risk_distance <= 0:
            return None, None

        take_profit_price: Optional[float] = None
        if explicit_take_profit is not None and not math.isnan(explicit_take_profit) and explicit_take_profit > 0:
            take_profit_price = float(explicit_take_profit)
        elif market_context and hasattr(market_context, "technical_indicators") and market_context.technical_indicators:
            ind = market_context.technical_indicators
            if direction == PositionDirection.LONG:
                high20 = ind.get("20_day_high")
                if high20 is not None and isinstance(high20, (int, float)) and high20 > entry_price:
                    take_profit_price = float(high20)
            elif direction == PositionDirection.SHORT:
                low20 = ind.get("20_day_low")
                if low20 is not None and isinstance(low20, (int, float)) and 0 < low20 < entry_price:
                    take_profit_price = float(low20)

        # If still None, generate default 2:1 target
        if take_profit_price is None:
            if direction == PositionDirection.LONG:
                take_profit_price = entry_price + (2.0 * risk_distance)
            elif direction == PositionDirection.SHORT:
                take_profit_price = max(0.01, entry_price - (2.0 * risk_distance))

        if take_profit_price is not None:
            if direction == PositionDirection.LONG:
                reward = take_profit_price - entry_price
            elif direction == PositionDirection.SHORT:
                reward = entry_price - take_profit_price
            else:
                reward = 0.0

            if reward > 0 and risk_distance > 0:
                ratio = reward / risk_distance
                return take_profit_price, float(ratio)
            else:
                return take_profit_price, 0.0

        return None, None
