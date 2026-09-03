"""
Phase 6.3 — Investment Committee / Decision Synthesis

Application-layer service synthesizing validated EvidenceSummary and DebateResult into a structured,
auditable CommitteeDecision with deterministic conviction scoring, data quality auditing,
contradiction preservation, numerical integrity enforcement, and robust failure fallbacks.

Consumes ONLY EvidenceSummary, DebateResult, and immutable MarketContext metadata.
Does NOT retrieve market data.
Does NOT inspect raw specialist outputs.
Does NOT recalculate metrics (Python remains authoritative).
Zero numerical fabrication.
Strict CoT stripping.
"""

import re
import uuid
import math
import asyncio
import logging
from typing import List, Dict, Optional, Any, Set, Tuple
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from backend.domain.schemas import (
    MarketContext, EvidenceSummary, EvidenceRecord, ContradictionRecord,
    SignalDirection, EvidenceCategory, ConflictSeverity,
)
from backend.domain.debate_schemas import (
    DebateArgument, DebateChallenge, DebateRebuttal, DebateRound, DebateResult,
    DebateSide, ChallengeSeverity, ChallengeStatus, ContradictionResolutionStatus,
    DebateDecisionState, EvidenceReference,
)
from backend.domain.investment_committee_schemas import (
    CommitteeRecommendation, DataQualityStatus, CommitteeDecision,
    InvestmentDecisionState, InvestmentAction, ExecutionPlan, PositionSizing, DecisionAudit,
)
from backend.infrastructure.llm import LLMClient, LLMClientError, LLMParseError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM Response Model (Strict, Qualitative Only, No Chain-of-Thought)
# ---------------------------------------------------------------------------

class RawCommitteeSynthesis(BaseModel):
    investment_thesis: str = Field(description="Concise synthesis of the investment view based strictly on evidence.")
    decision_summary: str = Field(description="Summary of why this recommendation was reached.")
    why_bull_case_wins: str = Field(description="Evaluation of bull arguments and supporting catalysts.")
    why_bear_case_wins: str = Field(description="Evaluation of bear arguments and downside risks.")
    what_would_change_the_decision: str = Field(description="Specific triggers or invalidations that would alter this decision.")
    key_risks: List[str] = Field(default_factory=list, description="Primary risks to this position.")
    invalidation_conditions: List[str] = Field(default_factory=list, description="Explicit conditions that invalidate the thesis.")
    assumptions: List[str] = Field(default_factory=list, description="Key assumptions underlying the decision.")


# ---------------------------------------------------------------------------
# Investment Committee Application Service
# ---------------------------------------------------------------------------

class InvestmentCommittee:
    """
    Phase 6.3 Investment Committee Decision Synthesis.
    Combines EvidenceSummary and DebateResult into a definitive CommitteeDecision.
    """

    SYSTEM_PROMPT_SYNTHESIS = (
        "You are an investment committee decision-synthesis component.\n"
        "Your role is to formulate a clear, qualitative investment thesis based strictly on the provided validated evidence and debate results.\n"
        "CRITICAL RULES:\n"
        "1. You may interpret ONLY the supplied validated evidence records and debate outputs.\n"
        "2. Do NOT invent, recalculate, substitute, or assume numerical financial facts.\n"
        "3. Every material claim must be grounded in the supplied records.\n"
        "4. Do NOT include hidden chain-of-thought or reasoning steps. Output structured JSON only."
    )

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        timeout_seconds: float = 60.0,
        min_evidence_threshold: int = 2,
    ):
        self.llm_client = llm_client
        self.timeout_seconds = timeout_seconds
        self.min_evidence_threshold = min_evidence_threshold

    # ------------------------------------------------------------------
    # Public Entry Point
    # ------------------------------------------------------------------

    async def synthesize_decision(
        self,
        evidence_summary: EvidenceSummary,
        debate_result: DebateResult,
        market_context: Optional[MarketContext] = None,
    ) -> CommitteeDecision:
        """
        Synthesizes a structured CommitteeDecision from EvidenceSummary and DebateResult.
        Preserves MarketContext immutability and enforces end-to-end evidence traceability.
        """
        started_at = datetime.now(timezone.utc)
        context_id = evidence_summary.context_id or debate_result.context_id
        symbol = evidence_summary.symbol or debate_result.symbol
        run_id = evidence_summary.run_id or debate_result.run_id
        decision_id = f"ic-dec-{uuid.uuid4().hex[:8]}"

        # Context validation
        if market_context and market_context.context_id != context_id:
            logger.warning(
                f"[InvestmentCommittee] Context ID mismatch: EvidenceSummary({context_id}) vs MarketContext({market_context.context_id})"
            )

        # 1. Evaluate Data Quality & Missing Critical Data
        data_quality, missing_critical_data = self._assess_data_quality(evidence_summary)

        # 2. Sufficiency Check
        if (
            data_quality == DataQualityStatus.INSUFFICIENT
            or len(evidence_summary.evidence_records) < self.min_evidence_threshold
            or debate_result.final_debate_state == DebateDecisionState.INSUFFICIENT_EVIDENCE
        ):
            completed_at = datetime.now(timezone.utc)
            return CommitteeDecision(
                decision_id=decision_id,
                run_id=run_id,
                context_id=context_id,
                symbol=symbol,
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=(completed_at - started_at).total_seconds(),
                recommendation=CommitteeRecommendation.INDETERMINATE,
                conviction_score=0.0,
                confidence=0.0,
                supporting_evidence_ids=[],
                opposing_evidence_ids=[],
                strongest_bull_arguments=[],
                strongest_bear_arguments=[],
                unresolved_contradictions=list(evidence_summary.contradictions),
                key_risks=["Insufficient evidence: data density below required threshold."],
                invalidation_conditions=["Availability of sufficient validated market and specialist data."],
                assumptions=[],
                evidence_coverage=0.0,
                data_quality=data_quality,
                degraded_specialists=list(evidence_summary.degraded_specialists),
                failed_specialists=list(evidence_summary.failed_specialists),
                missing_critical_data=missing_critical_data,
                investment_thesis="No viable investment thesis due to lack of validated evidence.",
                decision_summary="Decision INDETERMINATE: Insufficient evidence available to synthesize a reliable investment view.",
                why_bull_case_wins="N/A (Insufficient evidence)",
                why_bear_case_wins="N/A (Insufficient evidence)",
                what_would_change_the_decision="Acquisition of primary market and specialist evidence.",
                evidence_references=[],
                provenance=[],
                state=InvestmentDecisionState.INSUFFICIENT_EVIDENCE,
            )

        # 3. Deterministic Conviction Calculation
        contradictions = debate_result.unresolved_contradictions or evidence_summary.contradictions
        conviction_score = self._calculate_conviction_score(
            evidence_summary=evidence_summary,
            debate_result=debate_result,
            data_quality=data_quality,
            missing_critical_data=missing_critical_data,
            unresolved_contradictions=contradictions,
        )

        # 4. Deterministic Recommendation Mapping
        recommendation = self._determine_recommendation(
            debate_result=debate_result,
            conviction_score=conviction_score,
            unresolved_contradictions=contradictions,
        )

        # 5. Deterministic Confidence Score
        dq_multiplier = 1.0 if data_quality == DataQualityStatus.AVAILABLE else (0.85 if data_quality == DataQualityStatus.PARTIAL else 0.70)
        contra_penalty = len(contradictions) * 0.08
        confidence = round(max(0.0, min(1.0, debate_result.confidence * dq_multiplier - contra_penalty)), 4)

        # 6. Evidence Traceability & Supporting/Opposing Separation
        supporting_ids, opposing_ids, valid_references = self._extract_traceable_evidence(
            evidence_summary=evidence_summary,
            debate_result=debate_result,
        )

        # 7. LLM Qualitative Synthesis with Fallback
        synthesis = await self._generate_qualitative_synthesis(
            symbol=symbol,
            context_id=context_id,
            recommendation=recommendation,
            conviction_score=conviction_score,
            evidence_summary=evidence_summary,
            debate_result=debate_result,
            supporting_ids=supporting_ids,
            opposing_ids=opposing_ids,
            unresolved_contradictions=contradictions,
            missing_critical_data=missing_critical_data,
        )

        completed_at = datetime.now(timezone.utc)
        duration_seconds = max(0.001, (completed_at - started_at).total_seconds())

        # Map to legacy state for backward compatibility
        legacy_state = self._map_to_legacy_state(recommendation)

        return CommitteeDecision(
            decision_id=decision_id,
            run_id=run_id,
            context_id=context_id,
            symbol=symbol,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration_seconds,
            decision_timestamp=completed_at,
            time_horizon="MEDIUM_TERM",
            recommendation=recommendation,
            conviction_score=conviction_score,
            confidence=confidence,
            risk_score=float(debate_result.risk_score),
            risk_level=str(getattr(debate_result.risk_assessment, "risk_level", "LOW") if debate_result.risk_assessment else "LOW"),
            risk_veto_applied=bool(getattr(debate_result.risk_assessment, "risk_veto", False) if debate_result.risk_assessment else False),
            risk_veto_reason=None,
            supporting_evidence_ids=supporting_ids,
            opposing_evidence_ids=opposing_ids,
            strongest_bull_arguments=debate_result.strongest_bull_arguments,
            strongest_bear_arguments=debate_result.strongest_bear_arguments,
            unresolved_contradictions=list(contradictions),
            key_risks=synthesis.key_risks,
            invalidation_conditions=synthesis.invalidation_conditions,
            assumptions=synthesis.assumptions,
            evidence_coverage=debate_result.evidence_coverage,
            data_quality=data_quality,
            degraded_specialists=list(evidence_summary.degraded_specialists),
            failed_specialists=list(evidence_summary.failed_specialists),
            missing_critical_data=missing_critical_data,
            investment_thesis=synthesis.investment_thesis,
            decision_summary=synthesis.decision_summary,
            why_bull_case_wins=synthesis.why_bull_case_wins,
            why_bear_case_wins=synthesis.why_bear_case_wins,
            what_would_change_the_decision=synthesis.what_would_change_the_decision,
            evidence_references=valid_references,
            provenance=list(market_context.provenance) if market_context and hasattr(market_context, "provenance") else [],
            state=legacy_state,
        )

    # ------------------------------------------------------------------
    # Data Quality Assessment
    # ------------------------------------------------------------------

    def _assess_data_quality(self, evidence_summary: EvidenceSummary) -> Tuple[DataQualityStatus, List[str]]:
        missing_critical: List[str] = []
        records = evidence_summary.evidence_records

        if len(records) == 0 or evidence_summary.valid_evidence == 0:
            return DataQualityStatus.INSUFFICIENT, ["All primary specialist evidence missing"]

        present_categories = set(r.category for r in records if r.category)

        # Check for presence of fundamental data
        if EvidenceCategory.FUNDAMENTAL not in present_categories and EvidenceCategory.VALUATION not in present_categories:
            missing_critical.append("Missing Fundamental Data")

        # Check for presence of quantitative data
        if EvidenceCategory.QUANT not in present_categories:
            missing_critical.append("Missing Quant Data")

        # Check for presence of technical data
        if EvidenceCategory.TECHNICAL not in present_categories and EvidenceCategory.MOMENTUM not in present_categories:
            missing_critical.append("Missing Technical Data")

        if len(evidence_summary.degraded_specialists) > 0:
            return DataQualityStatus.DEGRADED, missing_critical

        if len(evidence_summary.failed_specialists) > 0 or len(missing_critical) > 0:
            return DataQualityStatus.PARTIAL, missing_critical

        return DataQualityStatus.AVAILABLE, missing_critical

    # ------------------------------------------------------------------
    # Deterministic Conviction Scoring
    # ------------------------------------------------------------------

    def _calculate_conviction_score(
        self,
        evidence_summary: EvidenceSummary,
        debate_result: DebateResult,
        data_quality: DataQualityStatus,
        missing_critical_data: List[str],
        unresolved_contradictions: List[ContradictionRecord],
    ) -> float:
        """
        Pure deterministic calculation in Python.
        Enforces 0.0 <= conviction_score <= 1.0.
        """
        bull_score = debate_result.bull_strength
        bear_score = debate_result.bear_strength
        spread = bull_score - bear_score
        dominant_score = max(bull_score, bear_score)
        directional_edge = abs(spread)

        # Base conviction from debate dominance, spread, and systemic confidence
        base_conviction = dominant_score * 0.50 + directional_edge * 0.30 + debate_result.confidence * 0.20

        # Coverage factor
        coverage = debate_result.evidence_coverage
        coverage_factor = min(1.0, max(0.35, coverage))

        # Data quality factor
        dq_factor = 1.0
        if data_quality == DataQualityStatus.PARTIAL:
            dq_factor = 0.85
        elif data_quality == DataQualityStatus.DEGRADED:
            dq_factor = 0.70
        elif data_quality == DataQualityStatus.INSUFFICIENT:
            dq_factor = 0.20

        # Penalties
        # 1. Unresolved contradictions
        has_critical = any(c.severity == ConflictSeverity.CRITICAL for c in unresolved_contradictions)
        contra_penalty = len(unresolved_contradictions) * 0.10 + (0.15 if has_critical else 0.0)

        # 2. Degraded specialists
        degraded_penalty = len(evidence_summary.degraded_specialists) * 0.08

        # 3. Failed specialists
        failed_penalty = len(evidence_summary.failed_specialists) * 0.12

        # 4. Missing critical data
        missing_penalty = len(missing_critical_data) * 0.08

        # 5. Risk score penalty
        risk_penalty = debate_result.risk_score * 0.20

        total_penalties = contra_penalty + degraded_penalty + failed_penalty + missing_penalty + risk_penalty

        raw_conviction = (base_conviction * coverage_factor * dq_factor) - total_penalties

        return round(max(0.0, min(1.0, raw_conviction)), 4)

    # ------------------------------------------------------------------
    # Deterministic Recommendation Logic
    # ------------------------------------------------------------------

    def _determine_recommendation(
        self,
        debate_result: DebateResult,
        conviction_score: float,
        unresolved_contradictions: List[ContradictionRecord],
    ) -> CommitteeRecommendation:
        # Hard Risk Veto
        if debate_result.risk_assessment and debate_result.risk_assessment.risk_veto:
            return CommitteeRecommendation.AVOID

        if debate_result.risk_score >= 0.85:
            return CommitteeRecommendation.AVOID

        # Critical Contradictions -> WATCH (no artificial consensus)
        has_critical = any(c.severity == ConflictSeverity.CRITICAL for c in unresolved_contradictions)
        if has_critical:
            return CommitteeRecommendation.WATCH

        bull_score = debate_result.bull_strength
        bear_score = debate_result.bear_strength
        spread = bull_score - bear_score

        # Decisive Bull
        if spread >= 0.30 and conviction_score >= 0.60 and bull_score >= 0.70:
            return CommitteeRecommendation.STRONG_BUY
        elif spread >= 0.15 and conviction_score >= 0.35 and bull_score > bear_score:
            return CommitteeRecommendation.BUY

        # Decisive Bear
        if spread <= -0.30 and bear_score >= 0.70:
            return CommitteeRecommendation.SELL
        elif spread <= -0.15 or debate_result.risk_score >= 0.65:
            return CommitteeRecommendation.AVOID

        # Indeterminate / Conflicting
        if conviction_score < 0.25 or debate_result.confidence < 0.35:
            return CommitteeRecommendation.WATCH

        return CommitteeRecommendation.HOLD

    # ------------------------------------------------------------------
    # Traceability Extraction
    # ------------------------------------------------------------------

    def _extract_traceable_evidence(
        self,
        evidence_summary: EvidenceSummary,
        debate_result: DebateResult,
    ) -> Tuple[List[str], List[str], List[EvidenceReference]]:
        evidence_map = {r.evidence_id: r for r in evidence_summary.evidence_records}

        supporting_ids: Set[str] = set()
        opposing_ids: Set[str] = set()

        for a in debate_result.strongest_bull_arguments:
            for eid in a.supporting_evidence_ids:
                if eid in evidence_map:
                    supporting_ids.add(eid)

        for a in debate_result.strongest_bear_arguments:
            for eid in a.supporting_evidence_ids:
                if eid in evidence_map:
                    opposing_ids.add(eid)

        # Fallback to evidence directions if debate did not cite specific IDs
        if not supporting_ids:
            for r in evidence_summary.evidence_records:
                if r.direction == SignalDirection.BULLISH:
                    supporting_ids.add(r.evidence_id)

        if not opposing_ids:
            for r in evidence_summary.evidence_records:
                if r.direction == SignalDirection.BEARISH:
                    opposing_ids.add(r.evidence_id)

        all_cited_ids = supporting_ids | opposing_ids
        evidence_references = [
            EvidenceReference(
                evidence_id=eid,
                category=evidence_map[eid].category.value if evidence_map[eid].category else "GENERAL",
                claim=evidence_map[eid].claim,
                supporting_value=float(evidence_map[eid].value) if isinstance(evidence_map[eid].value, (int, float)) and not isinstance(evidence_map[eid].value, bool) else None,
                source=evidence_map[eid].specialist_name,
                confidence=evidence_map[eid].confidence or 0.5,
            )
            for eid in sorted(list(all_cited_ids))
            if eid in evidence_map
        ]

        return sorted(list(supporting_ids)), sorted(list(opposing_ids)), evidence_references

    # ------------------------------------------------------------------
    # Qualitative LLM Synthesis & Fallback
    # ------------------------------------------------------------------

    async def _generate_qualitative_synthesis(
        self,
        symbol: str,
        context_id: str,
        recommendation: CommitteeRecommendation,
        conviction_score: float,
        evidence_summary: EvidenceSummary,
        debate_result: DebateResult,
        supporting_ids: List[str],
        opposing_ids: List[str],
        unresolved_contradictions: List[ContradictionRecord],
        missing_critical_data: List[str],
    ) -> RawCommitteeSynthesis:
        if not self.llm_client:
            return self._deterministic_fallback_synthesis(
                symbol, recommendation, conviction_score, debate_result, unresolved_contradictions, missing_critical_data
            )

        # Build compact context (Anti-Prompt-Bloat)
        evidence_map = {r.evidence_id: r for r in evidence_summary.evidence_records}
        sup_text = "\n".join([f"- [{eid}] {evidence_map[eid].claim}" for eid in supporting_ids[:4] if eid in evidence_map]) or "None"
        opp_text = "\n".join([f"- [{eid}] {evidence_map[eid].claim}" for eid in opposing_ids[:4] if eid in evidence_map]) or "None"

        bull_text = "\n".join([f"- {a.claim}" for a in debate_result.strongest_bull_arguments[:3]]) or "None"
        bear_text = "\n".join([f"- {a.claim}" for a in debate_result.strongest_bear_arguments[:3]]) or "None"
        contra_text = "\n".join([f"- {c.subject}: {c.explanation}" for c in unresolved_contradictions[:3]]) or "None"

        user_prompt = (
            f"Symbol: {symbol}\n"
            f"Context ID: {context_id}\n"
            f"Deterministic Recommendation: {recommendation.value}\n"
            f"Conviction Score: {conviction_score:.4f}\n\n"
            f"SUPPORTING EVIDENCE:\n{sup_text}\n\n"
            f"OPPOSING EVIDENCE:\n{opp_text}\n\n"
            f"STRONGEST BULL ARGUMENTS:\n{bull_text}\n\n"
            f"STRONGEST BEAR ARGUMENTS:\n{bear_text}\n\n"
            f"UNRESOLVED CONTRADICTIONS:\n{contra_text}\n\n"
            "Formulate the final investment thesis and decision summary.\n"
            "Return valid JSON matching the schema."
        )

        try:
            resp: RawCommitteeSynthesis = await asyncio.wait_for(
                self.llm_client.generate_structured(
                    system_prompt=self.SYSTEM_PROMPT_SYNTHESIS,
                    user_prompt=user_prompt,
                    response_model=RawCommitteeSynthesis,
                ),
                timeout=self.timeout_seconds,
            )
            # Verify numerical claim integrity and strip CoT
            clean_synthesis = self._sanitize_and_verify_synthesis(resp, evidence_map)
            return clean_synthesis
        except (LLMClientError, LLMParseError, asyncio.TimeoutError, Exception) as e:
            logger.warning(f"[InvestmentCommittee] LLM synthesis failed ({e}); using deterministic fallback.")
            return self._deterministic_fallback_synthesis(
                symbol, recommendation, conviction_score, debate_result, unresolved_contradictions, missing_critical_data
            )

    def _deterministic_fallback_synthesis(
        self,
        symbol: str,
        recommendation: CommitteeRecommendation,
        conviction_score: float,
        debate_result: DebateResult,
        unresolved_contradictions: List[ContradictionRecord],
        missing_critical_data: List[str],
    ) -> RawCommitteeSynthesis:
        bull_claim = debate_result.strongest_bull_arguments[0].claim if debate_result.strongest_bull_arguments else "No verified bull argument."
        bear_claim = debate_result.strongest_bear_arguments[0].claim if debate_result.strongest_bear_arguments else "No verified bear argument."

        thesis = (
            f"Investment Committee adopts a {recommendation.value} posture on {symbol} "
            f"with conviction {conviction_score:.2f}."
        )

        summary = (
            f"Deterministic evaluation concluded {recommendation.value}. "
            f"Bull strength: {debate_result.bull_strength:.2f}, Bear strength: {debate_result.bear_strength:.2f}, "
            f"Risk score: {debate_result.risk_score:.2f}."
        )
        if unresolved_contradictions:
            summary += f" Preserved {len(unresolved_contradictions)} unresolved contradiction(s)."
        if missing_critical_data:
            summary += f" Data quality impacted by: {', '.join(missing_critical_data)}."

        return RawCommitteeSynthesis(
            investment_thesis=thesis,
            decision_summary=summary,
            why_bull_case_wins=bull_claim,
            why_bear_case_wins=bear_claim,
            what_would_change_the_decision="Resolution of key directional contradictions or violation of risk stop boundaries.",
            key_risks=list(debate_result.key_risks or ["Market volatility risk"]),
            invalidation_conditions=list(debate_result.key_assumptions or ["Break of key technical support"]),
            assumptions=list(debate_result.key_assumptions or ["Established trend continuation"]),
        )

    def _sanitize_and_verify_synthesis(
        self,
        synthesis: RawCommitteeSynthesis,
        evidence_map: Dict[str, EvidenceRecord],
    ) -> RawCommitteeSynthesis:
        """
        Strips CoT markers and verifies that cited numbers in the LLM text are grounded in evidence.
        """
        def clean(t: str) -> str:
            if not t:
                return ""
            for m in ["<think>", "</think>", "Thinking Process:", "Let's think step by step:"]:
                t = t.replace(m, "")
            return t.strip()

        # Collect all valid numbers in evidence records
        valid_numbers: Set[float] = set()
        for ev in evidence_map.values():
            if ev.value is not None and isinstance(ev.value, (int, float)) and not isinstance(ev.value, bool):
                valid_numbers.add(float(ev.value))
            elif isinstance(ev.value, str):
                for sn in re.findall(r"\b\d+(?:\.\d+)?\b", ev.value):
                    valid_numbers.add(float(sn))

        def check_and_clean_numbers(t: str) -> str:
            cleaned = clean(t)
            nums = re.findall(r"\b\d+(?:\.\d+)?\b", cleaned)
            for n in nums:
                val = float(n)
                # Ignore standard integer indicators/thresholds
                if val in [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 10.0, 14.0, 20.0, 50.0, 100.0, 200.0]:
                    continue
                # Check proximity to known numbers
                if valid_numbers and not any(abs(val - vn) / max(abs(vn), 1.0) < 0.05 for vn in valid_numbers):
                    # Mask ungrounded fabricated numbers
                    cleaned = re.sub(r"\b" + re.escape(n) + r"\b", "[unverified metric]", cleaned)
            return cleaned

        return RawCommitteeSynthesis(
            investment_thesis=check_and_clean_numbers(synthesis.investment_thesis),
            decision_summary=check_and_clean_numbers(synthesis.decision_summary),
            why_bull_case_wins=check_and_clean_numbers(synthesis.why_bull_case_wins),
            why_bear_case_wins=check_and_clean_numbers(synthesis.why_bear_case_wins),
            what_would_change_the_decision=clean(synthesis.what_would_change_the_decision),
            key_risks=[clean(r) for r in synthesis.key_risks],
            invalidation_conditions=[clean(ic) for ic in synthesis.invalidation_conditions],
            assumptions=[clean(a) for a in synthesis.assumptions],
        )

    def _map_to_legacy_state(self, recommendation: CommitteeRecommendation) -> InvestmentDecisionState:
        if recommendation in [CommitteeRecommendation.STRONG_BUY, CommitteeRecommendation.BUY]:
            return InvestmentDecisionState.APPROVE
        elif recommendation == CommitteeRecommendation.SELL:
            return InvestmentDecisionState.REJECT
        elif recommendation == CommitteeRecommendation.AVOID:
            return InvestmentDecisionState.RISK_VETO
        elif recommendation == CommitteeRecommendation.INDETERMINATE:
            return InvestmentDecisionState.INSUFFICIENT_EVIDENCE
        else:
            return InvestmentDecisionState.HOLD
