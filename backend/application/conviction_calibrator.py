"""
Phase 6.5 — Conviction & Decision Calibration Engine

Production-grade, deterministic conviction calibration service.
Calibrates upstream conviction into a reproducible score in [0.0, 1.0],
de-correlating overlapping evidence pillars, evaluating specialist agreement,
penalizing unresolved contradictions and data quality issues, and auditing
logical consistency with committee recommendations.
All numerical calculations are executed in pure Python — zero LLM math.
"""

from datetime import datetime, timezone
import logging
import math
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from backend.domain.investment_committee_schemas import (
    CommitteeRecommendation,
    DataQualityStatus,
    CommitteeDecision,
)
from backend.domain.debate_schemas import (
    DebateResult,
    DebateSide,
    DebateDecisionState,
)
from backend.domain.schemas import (
    MarketContext,
    EvidenceSummary,
    EvidenceCategory,
    SignalDirection,
    ConflictSeverity,
    ContradictionRecord,
)
from backend.domain.calibration_schemas import (
    CALIBRATION_VERSION,
    ConvictionBand,
    SpecialistAgreementLevel,
    RecommendationConsistency,
    PillarBreakdown,
    ConvictionCalibrationResult,
)

logger = logging.getLogger(__name__)


class ConvictionCalibrator:
    """
    Authoritative deterministic conviction calibration service.

    Responsibilities:
    1. Multi-pillar de-correlation (dampening collinear signals like Tech+Mom).
    2. Specialist agreement classification (Consensus, Mixed, Conflicting, Insufficient).
    3. Debate edge integration and coverage scaling.
    4. Deterministic contradiction penalties (factual vs qualitative).
    5. Data quality haircuts and hard caps (Stale, Insufficient, Degraded, Partial).
    6. Recommendation consistency auditing (ensuring BUY/SELL aligns with conviction).
    7. Absolute risk decoupling (conviction score != risk score; risk veto immutability).
    8. Guaranteed bounds [0.0, 1.0] and version tracking.
    """

    def __init__(self, version: str = CALIBRATION_VERSION) -> None:
        self.version = version

    def calibrate(
        self,
        committee_decision: CommitteeDecision,
        debate_result: Optional[DebateResult] = None,
        evidence_summary: Optional[EvidenceSummary] = None,
        market_context: Optional[MarketContext] = None,
    ) -> ConvictionCalibrationResult:
        """
        Calibrate upstream conviction deterministically.

        Parameters
        ----------
        committee_decision : CommitteeDecision
            Upstream synthesis from Phase 6.3 Investment Committee.
        debate_result : Optional[DebateResult]
            Phase 6.2 debate result with bull/bear strength and contradictions.
        evidence_summary : Optional[EvidenceSummary]
            Phase 6.1 evidence store summary.
        market_context : Optional[MarketContext]
            Immutable market context for identity and provenance.

        Returns
        -------
        ConvictionCalibrationResult
            Calibrated result with bounded score, factor breakdowns, and audit trace.
        """
        calibration_id = f"calib-{uuid.uuid4().hex[:12]}"
        context_id = committee_decision.context_id
        decision_id = committee_decision.decision_id
        symbol = committee_decision.symbol
        recommendation = committee_decision.recommendation
        confidence = float(getattr(committee_decision, "confidence", 0.5))
        risk_score = float(getattr(committee_decision, "risk_score", 0.0))
        risk_veto_applied = bool(getattr(committee_decision, "risk_veto_applied", False))
        risk_veto_reason = getattr(committee_decision, "risk_veto_reason", None)
        data_quality = committee_decision.data_quality

        warnings: List[str] = []
        assumptions: List[str] = []

        # ── 1. Sanitize Raw Conviction ─────────────────────────────────────────
        raw_conviction = float(committee_decision.conviction_score)
        if math.isnan(raw_conviction) or math.isinf(raw_conviction):
            warnings.append(f"NON_FINITE_CONVICTION: Upstream conviction was {raw_conviction}; reset to 0.0.")
            raw_conviction = 0.0
        else:
            raw_conviction = max(0.0, min(1.0, raw_conviction))

        # ── 2. Multi-Pillar De-correlation & Analysis ─────────────────────────
        pillar_details, correlation_discount, evidence_strength, evidence_coverage = self._evaluate_pillars(
            evidence_summary=evidence_summary,
            debate_result=debate_result,
            committee_decision=committee_decision,
            raw_conviction=raw_conviction,
        )
        pillar_scores = {p.pillar_name: p.raw_score for p in pillar_details}

        # ── 3. Specialist Agreement Evaluation ─────────────────────────────────
        specialist_agreement, agreement_adjustment = self._evaluate_specialist_agreement(pillar_details)

        # ── 4. Debate Edge & Spread Evaluation ────────────────────────────────
        debate_strength, debate_adjustment = self._evaluate_debate_edge(
            debate_result=debate_result,
            recommendation=recommendation,
        )

        # ── 5. Contradiction Penalties ────────────────────────────────────────
        contradiction_penalty, contradiction_warnings = self._calculate_contradiction_penalties(
            committee_decision=committee_decision,
            debate_result=debate_result,
            evidence_summary=evidence_summary,
        )
        warnings.extend(contradiction_warnings)

        # ── 6. Data Quality Adjustments & Hard Caps ───────────────────────────
        dq_adjustment, dq_cap, missing_data_penalty, dq_warnings = self._calculate_data_quality_adjustments(
            committee_decision=committee_decision,
            evidence_summary=evidence_summary,
        )
        warnings.extend(dq_warnings)

        # ── 7. Calculate Calibrated Conviction ─────────────────────────────────
        if raw_conviction <= 1e-6:
            calibrated_conviction = 0.0
            conviction_band = ConvictionBand.VERY_LOW
        else:
            if len(pillar_details) > 0:
                pillar_composite = sum(p.weight * p.raw_score * p.correlation_discount_applied for p in pillar_details)
                total_weight = sum(p.weight for p in pillar_details)
                normalized_composite = (pillar_composite / total_weight) if total_weight > 0 else raw_conviction
                base_score = 0.55 * raw_conviction + 0.45 * normalized_composite
            else:
                base_score = raw_conviction

            # Positive adjustments scale proportionally with base_score
            positive_boost = max(0.0, agreement_adjustment) + max(0.0, debate_adjustment)
            negative_drag = (
                abs(min(0.0, agreement_adjustment))
                + abs(min(0.0, debate_adjustment))
                + contradiction_penalty
                + dq_adjustment
                + missing_data_penalty
                + (correlation_discount * 0.05)
            )

            adjusted_score = (base_score * (1.0 + positive_boost)) - negative_drag

            # Enforce coverage damping if expected core pillars are missing
            expected_pillars = ["technical_momentum", "fundamental_valuation", "quant_statistical"]
            active_core_pillars = [
                p for p in pillar_details
                if p.pillar_name in expected_pillars and len(p.specialists_included) > 0
            ]
            pillar_coverage = len(active_core_pillars) / len(expected_pillars) if expected_pillars else 1.0

            if pillar_coverage < 0.67:
                adjusted_score *= (0.50 + 0.50 * pillar_coverage)

            # Enforce hard upper cap based on data quality and specialist status
            capped_score = min(adjusted_score, dq_cap)

            # Enforce strict bounds [0.0, 1.0] and rounding
            calibrated_conviction = round(max(0.0, min(1.0, capped_score)), 4)
            conviction_band = ConvictionBand.from_score(calibrated_conviction)

        # ── 8. Recommendation Consistency Audit ───────────────────────────────
        consistency, consistency_notes = self._audit_recommendation_consistency(
            recommendation=recommendation,
            calibrated_conviction=calibrated_conviction,
            conviction_band=conviction_band,
            risk_score=risk_score,
            risk_veto_applied=risk_veto_applied,
            contradiction_penalty=contradiction_penalty,
        )
        if consistency == RecommendationConsistency.INCONSISTENT:
            warnings.append(f"RECOMMENDATION_INCONSISTENCY: {consistency_notes}")

        # ── 9. Risk Separation & Upstream Veto Warning ────────────────────────
        if risk_veto_applied:
            warnings.append(
                f"UPSTREAM_RISK_VETO: Risk veto was applied upstream ('{risk_veto_reason or 'UNKNOWN'}'). "
                f"Calibrated conviction ({calibrated_conviction:.2f}) does NOT override risk veto. Position size will be 0."
            )

        # ── 10. Provenance Extraction ─────────────────────────────────────────
        provenance: List[Dict[str, Any]] = []
        if market_context and hasattr(market_context, "provenance") and market_context.provenance:
            for p in market_context.provenance:
                if hasattr(p, "model_dump"):
                    provenance.append(p.model_dump())
                elif isinstance(p, dict):
                    provenance.append(p)
        elif hasattr(committee_decision, "provenance") and committee_decision.provenance:
            provenance.extend(committee_decision.provenance)

        return ConvictionCalibrationResult(
            calibration_id=calibration_id,
            context_id=context_id,
            decision_id=decision_id,
            symbol=symbol,
            raw_conviction=raw_conviction,
            calibrated_conviction=calibrated_conviction,
            conviction_band=conviction_band,
            evidence_strength=round(evidence_strength, 4),
            evidence_coverage=round(evidence_coverage, 4),
            specialist_agreement=specialist_agreement,
            debate_strength=round(debate_strength, 4),
            pillar_scores={k: round(v, 4) for k, v in pillar_scores.items()},
            pillar_details=pillar_details,
            correlation_discount=round(correlation_discount, 4),
            contradiction_penalty=round(contradiction_penalty, 4),
            data_quality_adjustment=round(dq_adjustment, 4),
            missing_data_penalty=round(missing_data_penalty, 4),
            calibration_method="MULTI_PILLAR_UNCORRELATED_COMPOSITE",
            calibration_version=self.version,
            confidence=round(confidence, 4),
            recommendation=recommendation,
            recommendation_consistency=consistency,
            consistency_notes=consistency_notes,
            risk_score=round(risk_score, 4),
            risk_veto_applied=risk_veto_applied,
            risk_veto_reason=risk_veto_reason,
            warnings=warnings,
            assumptions=assumptions,
            provenance=provenance,
            timestamp=datetime.now(timezone.utc),
        )

    def calibrate_decision(
        self,
        committee_decision: CommitteeDecision,
        debate_result: Optional[DebateResult] = None,
        evidence_summary: Optional[EvidenceSummary] = None,
        market_context: Optional[MarketContext] = None,
    ) -> CommitteeDecision:
        """
        Calibrate conviction and return an updated copy of CommitteeDecision.

        Parameters
        ----------
        committee_decision : CommitteeDecision
            Original decision to calibrate.
        debate_result : Optional[DebateResult]
            Phase 6.2 debate outcome.
        evidence_summary : Optional[EvidenceSummary]
            Phase 6.1 evidence records.
        market_context : Optional[MarketContext]
            Context information.

        Returns
        -------
        CommitteeDecision
            Updated CommitteeDecision with calibrated_conviction set and
            conviction_score updated to match the calibrated value.
        """
        res = self.calibrate(
            committee_decision=committee_decision,
            debate_result=debate_result,
            evidence_summary=evidence_summary,
            market_context=market_context,
        )
        return committee_decision.model_copy(update={
            "conviction_score": res.calibrated_conviction,
            "calibrated_conviction": res.calibrated_conviction,
            "calibration_id": res.calibration_id,
        })

    # -------------------------------------------------------------------------
    # Internal Helpers
    # -------------------------------------------------------------------------

    def _evaluate_pillars(
        self,
        evidence_summary: Optional[EvidenceSummary],
        debate_result: Optional[DebateResult],
        committee_decision: CommitteeDecision,
        raw_conviction: float = 0.5,
    ) -> Tuple[List[PillarBreakdown], float, float, float]:
        """
        Group evidence into independent pillars and apply correlation discounting
        between collinear specialists (Technical + Momentum).
        """
        pillars: List[PillarBreakdown] = []
        correlation_discount = 0.0
        safe_conviction = max(0.0, min(1.0, raw_conviction))
        evidence_strength = safe_conviction
        evidence_coverage = 0.50

        if debate_result:
            evidence_coverage = float(getattr(debate_result, "evidence_coverage", 0.50))

        if not evidence_summary or not evidence_summary.evidence_records:
            # Fallback to default pillars inferred from committee & debate
            pillars = [
                PillarBreakdown(
                    pillar_name="technical_momentum",
                    weight=0.30,
                    raw_score=safe_conviction,
                    direction="BULLISH" if committee_decision.recommendation in (CommitteeRecommendation.STRONG_BUY, CommitteeRecommendation.BUY) else "NEUTRAL",
                    specialists_included=["TechnicalSpecialist", "MomentumSpecialist"],
                    correlation_discount_applied=0.85,
                ),
                PillarBreakdown(
                    pillar_name="fundamental_valuation",
                    weight=0.35,
                    raw_score=safe_conviction,
                    direction="BULLISH" if committee_decision.recommendation in (CommitteeRecommendation.STRONG_BUY, CommitteeRecommendation.BUY) else "NEUTRAL",
                    specialists_included=["FundamentalSpecialist"],
                    correlation_discount_applied=1.0,
                ),
                PillarBreakdown(
                    pillar_name="quant_statistical",
                    weight=0.25,
                    raw_score=safe_conviction,
                    direction="BULLISH" if committee_decision.recommendation in (CommitteeRecommendation.STRONG_BUY, CommitteeRecommendation.BUY) else "NEUTRAL",
                    specialists_included=["QuantSpecialist"],
                    correlation_discount_applied=1.0,
                ),
            ]
            return pillars, 0.15, safe_conviction, evidence_coverage

        records = evidence_summary.evidence_records
        scores_by_cat: Dict[EvidenceCategory, List[float]] = {}
        dirs_by_cat: Dict[EvidenceCategory, List[SignalDirection]] = {}

        for r in records:
            cat = r.category or EvidenceCategory.QUANT
            score = getattr(r, "strength", None)
            if score is None:
                score = getattr(r, "confidence", None)
            if score is None:
                score = safe_conviction
            scores_by_cat.setdefault(cat, []).append(float(score))
            dirs_by_cat.setdefault(cat, []).append(r.direction if hasattr(r, "direction") else SignalDirection.NEUTRAL)

        # Calculate overall evidence strength
        all_strengths = [s for lst in scores_by_cat.values() for s in lst]
        if all_strengths:
            evidence_strength = sum(all_strengths) / len(all_strengths)

        # 1. Technical & Momentum Pillar (Collinear Price Trend)
        tech_scores = scores_by_cat.get(EvidenceCategory.TECHNICAL, [])
        mom_scores = scores_by_cat.get(EvidenceCategory.MOMENTUM, [])
        tech_dirs = dirs_by_cat.get(EvidenceCategory.TECHNICAL, [])
        mom_dirs = dirs_by_cat.get(EvidenceCategory.MOMENTUM, [])

        tm_scores = tech_scores + mom_scores
        tm_raw = (sum(tm_scores) / len(tm_scores)) if tm_scores else safe_conviction
        tm_dir = self._majority_direction(tech_dirs + mom_dirs)

        # If both Technical and Momentum are present and agree directionally, apply correlation discount rho=0.85
        has_both_tm = len(tech_scores) > 0 and len(mom_scores) > 0
        tm_agree = has_both_tm and (self._majority_direction(tech_dirs) == self._majority_direction(mom_dirs))
        tm_discount = 0.85 if tm_agree else 1.0
        if tm_agree:
            correlation_discount = 0.15

        tm_specs: List[str] = []
        if tech_scores:
            tm_specs.append("TechnicalSpecialist")
        if mom_scores:
            tm_specs.append("MomentumSpecialist")

        pillars.append(PillarBreakdown(
            pillar_name="technical_momentum",
            weight=0.30,
            raw_score=max(0.0, min(1.0, tm_raw)),
            direction=tm_dir,
            specialists_included=tm_specs,
            correlation_discount_applied=tm_discount,
        ))

        # 2. Fundamental & Valuation Pillar
        fund_scores = scores_by_cat.get(EvidenceCategory.FUNDAMENTAL, []) + scores_by_cat.get(EvidenceCategory.VALUATION, [])
        fund_dirs = dirs_by_cat.get(EvidenceCategory.FUNDAMENTAL, []) + dirs_by_cat.get(EvidenceCategory.VALUATION, [])
        fund_raw = (sum(fund_scores) / len(fund_scores)) if fund_scores else safe_conviction
        fund_dir = self._majority_direction(fund_dirs)
        pillars.append(PillarBreakdown(
            pillar_name="fundamental_valuation",
            weight=0.35,
            raw_score=max(0.0, min(1.0, fund_raw)),
            direction=fund_dir,
            specialists_included=["FundamentalSpecialist"] if fund_scores else [],
            correlation_discount_applied=1.0,
        ))

        # 3. Quantitative & Statistical Pillar
        quant_scores = scores_by_cat.get(EvidenceCategory.QUANT, [])
        quant_dirs = dirs_by_cat.get(EvidenceCategory.QUANT, [])
        quant_raw = (sum(quant_scores) / len(quant_scores)) if quant_scores else safe_conviction
        quant_dir = self._majority_direction(quant_dirs)
        pillars.append(PillarBreakdown(
            pillar_name="quant_statistical",
            weight=0.25,
            raw_score=max(0.0, min(1.0, quant_raw)),
            direction=quant_dir,
            specialists_included=["QuantSpecialist"] if quant_scores else [],
            correlation_discount_applied=1.0,
        ))

        # 4. News / Macro Pillar (if present)
        macro_scores = scores_by_cat.get(EvidenceCategory.MACRO, []) + scores_by_cat.get(EvidenceCategory.NEWS, [])
        if macro_scores:
            macro_dirs = dirs_by_cat.get(EvidenceCategory.MACRO, []) + dirs_by_cat.get(EvidenceCategory.NEWS, [])
            macro_raw = sum(macro_scores) / len(macro_scores)
            macro_dir = self._majority_direction(macro_dirs)
            pillars.append(PillarBreakdown(
                pillar_name="macro_news",
                weight=0.10,
                raw_score=max(0.0, min(1.0, macro_raw)),
                direction=macro_dir,
                specialists_included=["NewsSpecialist"],
                correlation_discount_applied=1.0,
            ))

        return pillars, correlation_discount, evidence_strength, evidence_coverage

    def _majority_direction(self, dirs: List[SignalDirection]) -> str:
        """Compute dominant direction for a list of directions."""
        if not dirs:
            return "UNKNOWN"
        bulls = sum(1 for d in dirs if d == SignalDirection.BULLISH)
        bears = sum(1 for d in dirs if d == SignalDirection.BEARISH)
        if bulls > bears:
            return "BULLISH"
        elif bears > bulls:
            return "BEARISH"
        elif bulls == 0 and bears == 0:
            return "NEUTRAL"
        else:
            return "MIXED"

    def _evaluate_specialist_agreement(
        self,
        pillar_details: List[PillarBreakdown],
    ) -> Tuple[SpecialistAgreementLevel, float]:
        """
        Determine agreement across independent pillars.
        Returns (AgreementLevel, score_adjustment).
        """
        active_pillars = [p for p in pillar_details if p.direction in ("BULLISH", "BEARISH")]
        if len(active_pillars) < 2:
            return SpecialistAgreementLevel.INSUFFICIENT, -0.15

        bull_count = sum(1 for p in active_pillars if p.direction == "BULLISH")
        bear_count = sum(1 for p in active_pillars if p.direction == "BEARISH")

        if bull_count >= 3 and bear_count == 0:
            return SpecialistAgreementLevel.STRONG_CONSENSUS, +0.10
        elif bear_count >= 3 and bull_count == 0:
            return SpecialistAgreementLevel.STRONG_CONSENSUS, +0.10
        elif (bull_count == 2 and bear_count == 0) or (bear_count == 2 and bull_count == 0):
            return SpecialistAgreementLevel.MODERATE_CONSENSUS, +0.05
        elif bull_count >= 1 and bear_count >= 1:
            return SpecialistAgreementLevel.CONFLICTING, -0.15
        else:
            return SpecialistAgreementLevel.MIXED, 0.00

    def _evaluate_debate_edge(
        self,
        debate_result: Optional[DebateResult],
        recommendation: CommitteeRecommendation,
    ) -> Tuple[float, float]:
        """
        Evaluate debate outcome.
        Returns (debate_strength, debate_adjustment).
        """
        if not debate_result:
            return 0.50, 0.00

        bull = getattr(debate_result, "bull_strength", 0.50)
        bear = getattr(debate_result, "bear_strength", 0.50)
        spread = bull - bear
        dominant = max(bull, bear)
        abs_spread = abs(spread)

        # Narrow / balanced debate penalizes conviction
        if abs_spread < 0.15:
            return dominant, -0.10

        # Decisive debate aligned with recommendation
        if recommendation in (CommitteeRecommendation.STRONG_BUY, CommitteeRecommendation.BUY) and spread >= 0.25:
            return dominant, +0.08
        elif recommendation == CommitteeRecommendation.SELL and spread <= -0.25:
            return dominant, +0.08
        elif abs_spread >= 0.30:
            return dominant, +0.05

        return dominant, 0.00

    def _calculate_contradiction_penalties(
        self,
        committee_decision: CommitteeDecision,
        debate_result: Optional[DebateResult],
        evidence_summary: Optional[EvidenceSummary],
    ) -> Tuple[float, List[str]]:
        """Calculate penalty for unresolved contradictions."""
        contradictions: List[ContradictionRecord] = []
        warnings: List[str] = []

        if committee_decision.unresolved_contradictions:
            contradictions = committee_decision.unresolved_contradictions
        elif debate_result and getattr(debate_result, "unresolved_contradictions", None):
            contradictions = debate_result.unresolved_contradictions
        elif evidence_summary and getattr(evidence_summary, "contradictions", None):
            contradictions = evidence_summary.contradictions

        if not contradictions:
            return 0.0, warnings

        penalty = 0.0
        for c in contradictions:
            sev = getattr(c, "severity", ConflictSeverity.MODERATE)
            if sev == ConflictSeverity.CRITICAL:
                penalty += 0.20
                warnings.append(f"CRITICAL_CONTRADICTION: {getattr(c, 'description', 'Critical factual conflict.')}")
            elif sev == ConflictSeverity.MODERATE:
                penalty += 0.10
                warnings.append(f"MODERATE_CONTRADICTION: {getattr(c, 'description', 'Moderate conflict.')}")
            else:
                penalty += 0.05

        return min(0.45, penalty), warnings

    def _calculate_data_quality_adjustments(
        self,
        committee_decision: CommitteeDecision,
        evidence_summary: Optional[EvidenceSummary],
    ) -> Tuple[float, float, float, List[str]]:
        """
        Calculate haircut, upper bound cap, and missing data penalty.
        Returns (dq_adjustment, dq_cap, missing_data_penalty, warnings).
        """
        dq = committee_decision.data_quality
        missing = list(committee_decision.missing_critical_data or [])
        warnings: List[str] = []

        adjustment = 0.0
        cap = 1.0
        missing_penalty = len(missing) * 0.08

        if dq == DataQualityStatus.STALE:
            adjustment = 0.40
            cap = 0.10
            warnings.append("DATA_QUALITY_STALE: Stale data limits maximum conviction to 0.10.")
        elif dq == DataQualityStatus.INSUFFICIENT:
            adjustment = 0.35
            cap = 0.15
            warnings.append("DATA_QUALITY_INSUFFICIENT: Insufficient data limits maximum conviction to 0.15.")
        elif dq == DataQualityStatus.DEGRADED:
            adjustment = 0.20
            cap = 0.50
            warnings.append("DATA_QUALITY_DEGRADED: Degraded specialist data caps conviction at 0.50.")
        elif dq == DataQualityStatus.PARTIAL:
            adjustment = 0.10
            cap = 0.75
            warnings.append("DATA_QUALITY_PARTIAL: Partial evidence coverage caps conviction at 0.75.")

        if missing:
            cap = min(cap, 0.60)
            warnings.append(f"MISSING_CRITICAL_DATA: Missing {', '.join(missing)} caps conviction at 0.60.")

        # Check degraded specialists
        degraded = committee_decision.degraded_specialists or []
        if degraded:
            adjustment += len(degraded) * 0.05
            cap = min(cap, 0.55)

        # Check failed specialists
        failed = committee_decision.failed_specialists or []
        if failed:
            adjustment += len(failed) * 0.10
            cap = min(cap, 0.40)
            warnings.append(f"FAILED_SPECIALISTS: Specialists {failed} failed execution.")

        return adjustment, cap, missing_penalty, warnings

    def _audit_recommendation_consistency(
        self,
        recommendation: CommitteeRecommendation,
        calibrated_conviction: float,
        conviction_band: ConvictionBand,
        risk_score: float,
        risk_veto_applied: bool,
        contradiction_penalty: float,
    ) -> Tuple[RecommendationConsistency, str]:
        """Audit the logical consistency of recommendation vs calibrated conviction."""
        # 1. Buy recommendations require positive conviction
        if recommendation in (CommitteeRecommendation.STRONG_BUY, CommitteeRecommendation.BUY):
            if calibrated_conviction < 0.35:
                return (
                    RecommendationConsistency.INCONSISTENT,
                    f"Recommendation '{recommendation.value}' contradicts low conviction {calibrated_conviction:.2f} ({conviction_band.value}).",
                )
            elif recommendation == CommitteeRecommendation.STRONG_BUY and calibrated_conviction < 0.60:
                return (
                    RecommendationConsistency.CAUTIONARY,
                    f"Recommendation 'STRONG_BUY' has moderate conviction {calibrated_conviction:.2f} (typically requires >= 0.60).",
                )
            return (
                RecommendationConsistency.CONSISTENT,
                f"Recommendation '{recommendation.value}' aligns with {conviction_band.value} conviction ({calibrated_conviction:.2f}).",
            )

        # 2. Sell recommendations with high conviction are consistent bearish theses
        elif recommendation == CommitteeRecommendation.SELL:
            if calibrated_conviction >= 0.50:
                return (
                    RecommendationConsistency.CONSISTENT,
                    f"High thesis conviction ({calibrated_conviction:.2f}) validates active SELL recommendation.",
                )
            return (
                RecommendationConsistency.CONSISTENT,
                f"SELL recommendation aligns with conviction score {calibrated_conviction:.2f}.",
            )

        # 3. Hold / Watch recommendations
        elif recommendation in (CommitteeRecommendation.HOLD, CommitteeRecommendation.WATCH):
            if calibrated_conviction >= 0.65:
                if risk_veto_applied or risk_score >= 0.65 or contradiction_penalty >= 0.15:
                    return (
                        RecommendationConsistency.CONSISTENT,
                        f"High conviction ({calibrated_conviction:.2f}) held in '{recommendation.value}' due to elevated risk/contradictions.",
                    )
                else:
                    return (
                        RecommendationConsistency.CAUTIONARY,
                        f"High conviction ({calibrated_conviction:.2f}) in '{recommendation.value}' without active risk veto or high risk score.",
                    )
            return (
                RecommendationConsistency.CONSISTENT,
                f"Moderate/low conviction ({calibrated_conviction:.2f}) logically supports '{recommendation.value}'.",
            )

        # 4. Avoid / Indeterminate
        else:
            return (
                RecommendationConsistency.CONSISTENT,
                f"Defensive recommendation '{recommendation.value}' is consistent with evidence profile ({calibrated_conviction:.2f}).",
            )
