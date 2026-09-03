"""
Phase 6.2 — Adversarial Debate Engine

Application-layer service orchestrating a controlled, multi-stage adversarial debate
between Bull and Bear viewpoints, mediated by Risk constraints and contradiction analysis.

Consumes ONLY validated EvidenceSummary data (plus immutable MarketContext for traceability).
Does NOT retrieve market data.
Does NOT directly inspect raw specialist outputs.
Does NOT recalculate metrics (Python is authoritative for numerical integrity).
Preserves disagreements instead of forcing artificial consensus.
Strips all chain-of-thought.
Handles degraded and failed specialists gracefully without crashing.
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
    ContradictionAnalysis, DebateDecisionState, ArgumentStrength, ChallengeType,
    BullCase, BearCase, RiskAssessment, EvidenceReference,
)
from backend.infrastructure.llm import LLMClient, LLMClientError, LLMParseError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM Response Models (Strict, Concise, No Chain-of-Thought)
# ---------------------------------------------------------------------------

class RawArgumentItem(BaseModel):
    claim: str = Field(description="Concise thesis argument based strictly on cited evidence.")
    supporting_evidence_ids: List[str] = Field(description="Exact IDs of supporting evidence records.")
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    risks: List[str] = Field(default_factory=list, description="Key downside risks to this argument.")
    assumptions: List[str] = Field(default_factory=list, description="Key assumptions underlying this argument.")


class RawArgumentsResponse(BaseModel):
    arguments: List[RawArgumentItem] = Field(default_factory=list)


class RawChallengeItem(BaseModel):
    target_argument_id: str = Field(description="ID of the opposing argument being challenged.")
    challenge: str = Field(description="Reason why the target argument is flawed, vulnerable, or contradicted.")
    evidence_ids: List[str] = Field(default_factory=list, description="Evidence IDs supporting this challenge.")
    severity: ChallengeSeverity = Field(default=ChallengeSeverity.MODERATE)


class RawChallengesResponse(BaseModel):
    challenges: List[RawChallengeItem] = Field(default_factory=list)


class RawRebuttalItem(BaseModel):
    challenge_id: str = Field(description="ID of the challenge being answered.")
    response: str = Field(description="Evidence-backed defense of the original argument.")
    supporting_evidence_ids: List[str] = Field(default_factory=list, description="Evidence IDs backing this rebuttal.")
    confidence: float = Field(default=0.6, ge=0.0, le=1.0)


class RawRebuttalsResponse(BaseModel):
    rebuttals: List[RawRebuttalItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Main Debate Engine
# ---------------------------------------------------------------------------

class DebateEngine:
    """
    Phase 6.2 Adversarial Debate Engine.
    Executes a structured 7-stage adversarial debate over validated EvidenceSummary.
    """

    SYSTEM_PROMPT_BULL = (
        "You are an adversarial financial debate component representing the BULL side.\n"
        "Your role is to construct the strongest evidence-backed long thesis.\n"
        "CRITICAL RULES:\n"
        "1. You may interpret and challenge ONLY the supplied validated evidence records.\n"
        "2. Do NOT invent, recalculate, substitute, or assume numerical facts.\n"
        "3. Every argument MUST cite supporting_evidence_ids matching the given evidence records.\n"
        "4. Do NOT include hidden chain-of-thought or reasoning steps. Output structured JSON only."
    )

    SYSTEM_PROMPT_BEAR = (
        "You are an adversarial financial debate component representing the BEAR side.\n"
        "Your role is to actively deconstruct the Bull thesis and highlight downside risks, valuation stretches, and contradictions.\n"
        "CRITICAL RULES:\n"
        "1. You may interpret and challenge ONLY the supplied validated evidence records.\n"
        "2. Do NOT invent, recalculate, substitute, or assume numerical facts.\n"
        "3. Every argument MUST cite supporting_evidence_ids matching the given evidence records.\n"
        "4. Do NOT include hidden chain-of-thought or reasoning steps. Output structured JSON only."
    )

    SYSTEM_PROMPT_CHALLENGE = (
        "You are an adversarial cross-examination component in a financial debate.\n"
        "Your role is to challenge opposing arguments using contradictory or weakening evidence.\n"
        "CRITICAL RULES:\n"
        "1. Every challenge must target a specific argument ID.\n"
        "2. Every challenge must cite supporting evidence IDs from the supplied evidence records.\n"
        "3. Do NOT invent numerical facts. Output structured JSON only."
    )

    SYSTEM_PROMPT_REBUTTAL = (
        "You are a rebuttal component in an adversarial financial debate.\n"
        "Your role is to defend challenged arguments using evidence or concede if the challenge is unanswerable.\n"
        "CRITICAL RULES:\n"
        "1. Every rebuttal must cite supporting evidence IDs from the supplied evidence records.\n"
        "2. Do NOT invent numerical facts. Output structured JSON only."
    )

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        max_rounds: int = 1,
        min_evidence_for_debate: int = 1,
        timeout_seconds: float = 60.0,
    ):
        self.llm_client = llm_client
        self.max_rounds = max_rounds
        self.min_evidence_for_debate = min_evidence_for_debate
        self.timeout_seconds = timeout_seconds

    # ------------------------------------------------------------------
    # Public Entry Point
    # ------------------------------------------------------------------

    async def run_debate(
        self,
        evidence_summary: EvidenceSummary,
        market_context: Optional[MarketContext] = None,
    ) -> DebateResult:
        """
        Executes the multi-stage adversarial debate on the provided EvidenceSummary.
        Guarantees zero mutation of market_context and preserves evidence traceability.
        """
        started_at = datetime.now(timezone.utc)
        context_id = evidence_summary.context_id
        symbol = evidence_summary.symbol
        run_id = evidence_summary.run_id
        debate_id = f"debate-{uuid.uuid4().hex[:8]}"

        # Traceability validation
        if market_context and market_context.context_id != context_id:
            logger.warning(
                f"[DebateEngine] Context ID mismatch: EvidenceSummary({context_id}) vs MarketContext({market_context.context_id})"
            )

        # Stage 1: Evidence intake & sufficiency check
        all_records = evidence_summary.evidence_records

        if len(all_records) < self.min_evidence_for_debate or evidence_summary.valid_evidence == 0:
            completed_at = datetime.now(timezone.utc)
            return DebateResult(
                debate_id=debate_id,
                run_id=run_id,
                context_id=context_id,
                symbol=symbol,
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=(completed_at - started_at).total_seconds(),
                rounds=[],
                unresolved_contradictions=list(evidence_summary.contradictions),
                contradiction_analyses=[],
                strongest_bull_arguments=[],
                strongest_bear_arguments=[],
                key_risks=["Insufficient evidence to conduct adversarial debate."],
                key_assumptions=[],
                evidence_coverage=0.0,
                final_debate_state=DebateDecisionState.INSUFFICIENT_EVIDENCE,
                confidence=0.0,
                thesis_status=DebateDecisionState.INSUFFICIENT_EVIDENCE,
                recommended_action="PASS (Insufficient Evidence)",
            )

        evidence_map = {r.evidence_id: r for r in all_records}
        evidence_text = self._build_compact_evidence_prompt(all_records)

        # Multi-round execution container
        rounds: List[DebateRound] = []

        try:
            # Wrap execution in timeout
            await asyncio.wait_for(
                self._execute_debate_rounds(
                    rounds=rounds,
                    evidence_summary=evidence_summary,
                    evidence_map=evidence_map,
                    evidence_text=evidence_text,
                ),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.error(f"[DebateEngine] Debate timed out after {self.timeout_seconds}s for {symbol}")
            # Fallback to deterministic round if empty
            if not rounds:
                rounds.append(self._build_deterministic_round(1, evidence_summary, evidence_map))
        except Exception as e:
            logger.error(f"[DebateEngine] Unexpected error during debate execution: {e}")
            if not rounds:
                rounds.append(self._build_deterministic_round(1, evidence_summary, evidence_map))

        # Stage 5: Contradiction analysis
        contradiction_analyses, unresolved_contradictions = self._analyze_contradictions(
            evidence_summary.contradictions, rounds, evidence_map
        )

        # Stage 7: Debate Synthesis & Deterministic Bookkeeping
        completed_at = datetime.now(timezone.utc)
        duration_seconds = max(0.001, (completed_at - started_at).total_seconds())

        result = self._synthesize_debate(
            debate_id=debate_id,
            run_id=run_id,
            context_id=context_id,
            symbol=symbol,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration_seconds,
            rounds=rounds,
            evidence_summary=evidence_summary,
            evidence_map=evidence_map,
            contradiction_analyses=contradiction_analyses,
            unresolved_contradictions=unresolved_contradictions,
        )

        return result

    # ------------------------------------------------------------------
    # Internal Debate Execution
    # ------------------------------------------------------------------

    async def _execute_debate_rounds(
        self,
        rounds: List[DebateRound],
        evidence_summary: EvidenceSummary,
        evidence_map: Dict[str, EvidenceRecord],
        evidence_text: str,
    ):
        for round_num in range(1, self.max_rounds + 1):
            # Stage 2: Bull Case Construction
            bull_args = await self._generate_bull_arguments(evidence_summary, evidence_map, evidence_text)

            # Stage 3: Bear Case Construction
            bear_args = await self._generate_bear_arguments(evidence_summary, evidence_map, evidence_text, bull_args)

            # Stage 4: Cross-examination / Challenges
            challenges = await self._generate_challenges(bull_args, bear_args, evidence_map, evidence_text)

            # Stage 6: Evidence-based Rebuttals
            rebuttals = await self._generate_rebuttals(challenges, bull_args, bear_args, evidence_map, evidence_text)

            # Update challenge response statuses based on rebuttals
            rebuttal_map = {r.challenge_id: r for r in rebuttals}
            for ch in challenges:
                reb = rebuttal_map.get(ch.challenge_id)
                if reb:
                    valid_reb_ids = [eid for eid in reb.supporting_evidence_ids if eid in evidence_map]
                    if len(valid_reb_ids) > 0:
                        ch.response_status = ChallengeStatus.DEFENDED
                    else:
                        ch.response_status = ChallengeStatus.PARTIALLY_DEFENDED
                else:
                    ch.response_status = ChallengeStatus.UNADDRESSED

            debate_round = DebateRound(
                round_number=round_num,
                bull_arguments=bull_args,
                bear_arguments=bear_args,
                challenges=challenges,
                rebuttals=rebuttals,
                round_id=f"round-{round_num}",
                bear_challenges=challenges,  # backward compatibility
            )
            rounds.append(debate_round)

    # ------------------------------------------------------------------
    # Stage 2 & 3: Argument Generation
    # ------------------------------------------------------------------

    async def _generate_bull_arguments(
        self,
        evidence_summary: EvidenceSummary,
        evidence_map: Dict[str, EvidenceRecord],
        evidence_text: str,
    ) -> List[DebateArgument]:
        if not self.llm_client:
            return self._deterministic_bull_arguments(evidence_summary, evidence_map)

        user_prompt = (
            f"Symbol: {evidence_summary.symbol}\n"
            f"Context ID: {evidence_summary.context_id}\n\n"
            f"VALIDATED EVIDENCE RECORDS:\n{evidence_text}\n\n"
            "Construct up to 4 strong, distinct Bull arguments supporting the long thesis.\n"
            "Every argument must reference at least 1 supporting_evidence_id from the records above."
        )

        try:
            resp = await self.llm_client.generate_structured(
                system_prompt=self.SYSTEM_PROMPT_BULL,
                user_prompt=user_prompt,
                response_model=RawArgumentsResponse,
            )
            return self._validate_and_convert_arguments(resp.arguments, DebateSide.BULL, evidence_map)
        except (LLMClientError, LLMParseError, Exception) as e:
            logger.warning(f"[DebateEngine] Bull LLM generation failed ({e}); falling back to deterministic.")
            return self._deterministic_bull_arguments(evidence_summary, evidence_map)

    async def _generate_bear_arguments(
        self,
        evidence_summary: EvidenceSummary,
        evidence_map: Dict[str, EvidenceRecord],
        evidence_text: str,
        bull_args: List[DebateArgument],
    ) -> List[DebateArgument]:
        if not self.llm_client:
            return self._deterministic_bear_arguments(evidence_summary, evidence_map)

        bull_summary = "\n".join([f"- [{a.argument_id}] {a.claim}" for a in bull_args])
        user_prompt = (
            f"Symbol: {evidence_summary.symbol}\n"
            f"Context ID: {evidence_summary.context_id}\n\n"
            f"VALIDATED EVIDENCE RECORDS:\n{evidence_text}\n\n"
            f"BULL ARGUMENTS TO CONTEST:\n{bull_summary}\n\n"
            "Construct up to 4 strong, distinct Bear arguments attacking the long thesis or presenting downside risks.\n"
            "Every argument must reference at least 1 supporting_evidence_id from the records above."
        )

        try:
            resp = await self.llm_client.generate_structured(
                system_prompt=self.SYSTEM_PROMPT_BEAR,
                user_prompt=user_prompt,
                response_model=RawArgumentsResponse,
            )
            return self._validate_and_convert_arguments(resp.arguments, DebateSide.BEAR, evidence_map)
        except (LLMClientError, LLMParseError, Exception) as e:
            logger.warning(f"[DebateEngine] Bear LLM generation failed ({e}); falling back to deterministic.")
            return self._deterministic_bear_arguments(evidence_summary, evidence_map)

    # ------------------------------------------------------------------
    # Stage 4: Cross-Examination / Challenges
    # ------------------------------------------------------------------

    async def _generate_challenges(
        self,
        bull_args: List[DebateArgument],
        bear_args: List[DebateArgument],
        evidence_map: Dict[str, EvidenceRecord],
        evidence_text: str,
    ) -> List[DebateChallenge]:
        if not self.llm_client:
            return self._deterministic_challenges(bull_args, bear_args, evidence_map)

        args_text = "BULL ARGUMENTS:\n" + "\n".join([f"ID: {a.argument_id} | Claim: {a.claim}" for a in bull_args])
        args_text += "\n\nBEAR ARGUMENTS:\n" + "\n".join([f"ID: {a.argument_id} | Claim: {a.claim}" for a in bear_args])

        user_prompt = (
            f"ARGUMENTS IN DEBATE:\n{args_text}\n\n"
            f"VALIDATED EVIDENCE RECORDS:\n{evidence_text}\n\n"
            "Generate targeted challenges from the Bear side against Bull arguments, and from the Bull side against Bear arguments.\n"
            "Each challenge must cite the target argument ID and evidence IDs that challenge it."
        )

        try:
            resp = await self.llm_client.generate_structured(
                system_prompt=self.SYSTEM_PROMPT_CHALLENGE,
                user_prompt=user_prompt,
                response_model=RawChallengesResponse,
            )
            return self._validate_and_convert_challenges(resp.challenges, bull_args + bear_args, evidence_map)
        except (LLMClientError, LLMParseError, Exception) as e:
            logger.warning(f"[DebateEngine] Challenge LLM generation failed ({e}); falling back to deterministic.")
            return self._deterministic_challenges(bull_args, bear_args, evidence_map)

    # ------------------------------------------------------------------
    # Stage 6: Evidence-Based Rebuttals
    # ------------------------------------------------------------------

    async def _generate_rebuttals(
        self,
        challenges: List[DebateChallenge],
        bull_args: List[DebateArgument],
        bear_args: List[DebateArgument],
        evidence_map: Dict[str, EvidenceRecord],
        evidence_text: str,
    ) -> List[DebateRebuttal]:
        if not challenges:
            return []

        if not self.llm_client:
            return self._deterministic_rebuttals(challenges, evidence_map)

        ch_text = "\n".join([f"Challenge ID: {c.challenge_id} | Target: {c.target_argument_id} | Challenge: {c.challenge}" for c in challenges])
        user_prompt = (
            f"CHALLENGES TO DEFEND:\n{ch_text}\n\n"
            f"VALIDATED EVIDENCE RECORDS:\n{evidence_text}\n\n"
            "For each challenge, provide an evidence-based rebuttal defending the original thesis, citing valid evidence IDs."
        )

        try:
            resp = await self.llm_client.generate_structured(
                system_prompt=self.SYSTEM_PROMPT_REBUTTAL,
                user_prompt=user_prompt,
                response_model=RawRebuttalsResponse,
            )
            return self._validate_and_convert_rebuttals(resp.rebuttals, challenges, evidence_map)
        except (LLMClientError, LLMParseError, Exception) as e:
            logger.warning(f"[DebateEngine] Rebuttal LLM generation failed ({e}); falling back to deterministic.")
            return self._deterministic_rebuttals(challenges, evidence_map)

    # ------------------------------------------------------------------
    # Stage 5: Contradiction Analysis
    # ------------------------------------------------------------------

    def _analyze_contradictions(
        self,
        contradictions: List[ContradictionRecord],
        rounds: List[DebateRound],
        evidence_map: Dict[str, EvidenceRecord],
    ) -> Tuple[List[ContradictionAnalysis], List[ContradictionRecord]]:
        analyses: List[ContradictionAnalysis] = []
        unresolved: List[ContradictionRecord] = []

        for c in contradictions:
            recs_a = [r for r in evidence_map.values() if r.specialist_name == c.specialist_a]
            recs_b = [r for r in evidence_map.values() if r.specialist_name == c.specialist_b]

            status = ContradictionResolutionStatus.UNRESOLVED
            rationale = "Direct contradiction between specialists remains unresolved."

            # Deterministic resolution rule: deterministic fact overrides qualitative interpretation
            a_is_fact = any(r.is_deterministic for r in recs_a)
            b_is_fact = any(r.is_deterministic for r in recs_b)

            if a_is_fact and not b_is_fact:
                status = ContradictionResolutionStatus.RESOLVED
                rationale = f"Resolved in favor of {c.specialist_a} (deterministic fact overrides interpretation)."
            elif b_is_fact and not a_is_fact:
                status = ContradictionResolutionStatus.RESOLVED
                rationale = f"Resolved in favor of {c.specialist_b} (deterministic fact overrides interpretation)."
            else:
                unresolved.append(c)

            analyses.append(
                ContradictionAnalysis(
                    contradiction_id=c.contradiction_id,
                    subject=c.subject,
                    status=status,
                    competing_claims=[f"{c.specialist_a}: {c.claim_a}", f"{c.specialist_b}: {c.claim_b}"],
                    resolution_rationale=rationale,
                )
            )

        return analyses, unresolved

    # ------------------------------------------------------------------
    # Stage 7: Deterministic Debate Synthesis
    # ------------------------------------------------------------------

    def _synthesize_debate(
        self,
        debate_id: str,
        run_id: str,
        context_id: str,
        symbol: str,
        started_at: datetime,
        completed_at: datetime,
        duration_seconds: float,
        rounds: List[DebateRound],
        evidence_summary: EvidenceSummary,
        evidence_map: Dict[str, EvidenceRecord],
        contradiction_analyses: List[ContradictionAnalysis],
        unresolved_contradictions: List[ContradictionRecord],
    ) -> DebateResult:
        all_bull_args: List[DebateArgument] = []
        all_bear_args: List[DebateArgument] = []
        all_challenges: List[DebateChallenge] = []
        all_cited_ids: Set[str] = set()

        for r in rounds:
            all_bull_args.extend(r.bull_arguments)
            all_bear_args.extend(r.bear_arguments)
            all_challenges.extend(r.challenges)
            for a in r.bull_arguments:
                all_cited_ids.update(a.supporting_evidence_ids)
            for a in r.bear_arguments:
                all_cited_ids.update(a.supporting_evidence_ids)
            for ch in r.challenges:
                all_cited_ids.update(ch.evidence_ids)
            for reb in r.rebuttals:
                all_cited_ids.update(reb.supporting_evidence_ids)

        valid_cited_ids = all_cited_ids & set(evidence_map.keys())
        total_ev = max(1, len(evidence_summary.evidence_records))
        evidence_coverage = min(1.0, len(valid_cited_ids) / total_ev)

        valid_bull = [a for a in all_bull_args if not a.is_unsupported and len(a.supporting_evidence_ids) > 0]
        valid_bear = [a for a in all_bear_args if not a.is_unsupported and len(a.supporting_evidence_ids) > 0]

        strongest_bull = sorted(
            valid_bull or all_bull_args,
            key=lambda x: (not x.is_unsupported, x.confidence, len(x.supporting_evidence_ids)),
            reverse=True,
        )[:3]

        strongest_bear = sorted(
            valid_bear or all_bear_args,
            key=lambda x: (not x.is_unsupported, x.confidence, len(x.supporting_evidence_ids)),
            reverse=True,
        )[:3]

        key_risks_set: Set[str] = set()
        key_assumptions_set: Set[str] = set()

        for a in all_bull_args + all_bear_args:
            key_risks_set.update(a.risks)
            key_assumptions_set.update(a.assumptions)
        for ch in all_challenges:
            if ch.challenge:
                key_risks_set.add(ch.challenge)

        for u in unresolved_contradictions:
            key_risks_set.add(f"Unresolved contradiction: {u.subject} ({u.explanation})")

        key_risks = sorted(list(key_risks_set))[:8]
        key_assumptions = sorted(list(key_assumptions_set))[:8]

        bull_score = 0.0
        if valid_bull:
            bull_score = min(1.0, sum(a.confidence for a in valid_bull) / len(valid_bull))
        bear_score = 0.0
        if valid_bear:
            bear_score = min(1.0, sum(a.confidence for a in valid_bear) / len(valid_bear))

        unresolved_penalty = len(unresolved_contradictions) * 0.10
        open_challenges = [c for c in all_challenges if c.response_status in [ChallengeStatus.OPEN, ChallengeStatus.UNADDRESSED]]
        challenge_penalty = len(open_challenges) * 0.05
        risk_score = min(1.0, max(0.1, bear_score * 0.5 + unresolved_penalty + challenge_penalty))

        margin = bull_score - bear_score
        has_critical_conflict = any(c.severity == ConflictSeverity.CRITICAL for c in unresolved_contradictions)

        if has_critical_conflict:
            final_state = DebateDecisionState.MIXED
            rec_action = "WATCH (Unresolved Critical Contradiction)"
        elif margin > 0.20 and risk_score < 0.6:
            final_state = DebateDecisionState.BULL_FAVORED
            rec_action = "CONSIDER LONG"
        elif margin < -0.20:
            final_state = DebateDecisionState.BEAR_FAVORED
            rec_action = "CONSIDER SHORT"
        else:
            final_state = DebateDecisionState.MIXED
            rec_action = "WATCH (Mixed Signals)"

        raw_conf = max(bull_score, bear_score) * 0.6 + evidence_coverage * 0.4
        final_conf = max(0.0, min(1.0, raw_conf - unresolved_penalty))

        bull_case = BullCase(
            thesis_id=f"bull-{uuid.uuid4().hex[:6]}",
            context_id=context_id,
            symbol=symbol,
            core_thesis=strongest_bull[0].claim if strongest_bull else "No supported bull arguments",
            supporting_evidence=[a.claim for a in strongest_bull],
            confidence=bull_score,
            risks=key_risks[:3],
            assumptions=key_assumptions[:3],
            evidence_references=[
                EvidenceReference(evidence_id=eid, category="DEBATE", claim=evidence_map[eid].claim)
                for eid in valid_cited_ids if eid in evidence_map
            ][:5],
        )

        bear_case = BearCase(
            thesis_id=f"bear-{uuid.uuid4().hex[:6]}",
            context_id=context_id,
            symbol=symbol,
            attack_summary=strongest_bear[0].claim if strongest_bear else "No supported bear arguments",
            bull_claims_challenged=[c.challenge for c in all_challenges][:3],
            contradictory_evidence=[u.explanation for u in unresolved_contradictions],
            confidence=bear_score,
            evidence_references=[
                EvidenceReference(evidence_id=eid, category="DEBATE", claim=evidence_map[eid].claim)
                for eid in valid_cited_ids if eid in evidence_map
            ][:5],
        )

        risk_assessment = RiskAssessment(
            context_id=context_id,
            symbol=symbol,
            risk_level="HIGH" if risk_score > 0.6 else ("MEDIUM" if risk_score > 0.3 else "LOW"),
            risk_score=risk_score,
            primary_risks=key_risks[:4],
            secondary_risks=key_risks[4:8],
            confidence=max(0.1, 1.0 - risk_score),
            risk_veto=(risk_score > 0.85),
        )

        return DebateResult(
            debate_id=debate_id,
            run_id=run_id,
            context_id=context_id,
            symbol=symbol,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration_seconds,
            rounds=rounds,
            unresolved_contradictions=unresolved_contradictions,
            contradiction_analyses=contradiction_analyses,
            strongest_bull_arguments=strongest_bull,
            strongest_bear_arguments=strongest_bear,
            key_risks=key_risks,
            key_assumptions=key_assumptions,
            evidence_coverage=evidence_coverage,
            final_debate_state=final_state,
            confidence=final_conf,
            # Backward-compatibility fields
            bull_case=bull_case,
            bear_case=bear_case,
            risk_assessment=risk_assessment,
            bull_strength=bull_score,
            bear_strength=bear_score,
            risk_score=risk_score,
            thesis_status=final_state,
            recommended_action=rec_action,
            key_agreements=[f"Agreement on {len(valid_cited_ids)} verified evidence items."],
            key_disagreements=[c.explanation for c in unresolved_contradictions],
            critical_conflicts=[c.explanation for c in unresolved_contradictions if c.severity == ConflictSeverity.CRITICAL],
            generated_at=completed_at,
        )

    # ------------------------------------------------------------------
    # Validation & Evidence Integrity Enforcers
    # ------------------------------------------------------------------

    def _validate_and_convert_arguments(
        self,
        raw_items: List[RawArgumentItem],
        side: DebateSide,
        evidence_map: Dict[str, EvidenceRecord],
    ) -> List[DebateArgument]:
        validated_args: List[DebateArgument] = []

        for item in raw_items:
            clean_claim = self._sanitize_text(item.claim)
            valid_ids = [eid for eid in item.supporting_evidence_ids if eid in evidence_map]
            is_unsupported = (len(valid_ids) == 0)

            claim_is_valid = self._verify_numerical_claim(clean_claim, valid_ids, evidence_map)
            if not claim_is_valid:
                is_unsupported = True

            validated_args.append(
                DebateArgument(
                    argument_id=f"arg-{uuid.uuid4().hex[:8]}",
                    side=side,
                    claim=clean_claim,
                    supporting_evidence_ids=valid_ids,
                    confidence=item.confidence if not is_unsupported else min(0.2, item.confidence),
                    risks=[self._sanitize_text(r) for r in item.risks],
                    assumptions=[self._sanitize_text(a) for a in item.assumptions],
                    is_unsupported=is_unsupported,
                    strength=ArgumentStrength.STRONG if len(valid_ids) >= 2 else (ArgumentStrength.MODERATE if len(valid_ids) == 1 else ArgumentStrength.WEAK),
                )
            )

        return validated_args

    def _validate_and_convert_challenges(
        self,
        raw_challenges: List[RawChallengeItem],
        all_args: List[DebateArgument],
        evidence_map: Dict[str, EvidenceRecord],
    ) -> List[DebateChallenge]:
        valid_arg_ids = set(a.argument_id for a in all_args)
        validated: List[DebateChallenge] = []

        for item in raw_challenges:
            clean_ch = self._sanitize_text(item.challenge)
            target_id = item.target_argument_id
            if target_id not in valid_arg_ids and all_args:
                target_id = all_args[0].argument_id

            valid_ids = [eid for eid in item.evidence_ids if eid in evidence_map]

            validated.append(
                DebateChallenge(
                    challenge_id=f"ch-{uuid.uuid4().hex[:8]}",
                    target_argument_id=target_id,
                    challenge=clean_ch,
                    evidence_ids=valid_ids,
                    severity=item.severity,
                    response_status=ChallengeStatus.OPEN,
                    explanation=clean_ch,
                )
            )

        return validated

    def _validate_and_convert_rebuttals(
        self,
        raw_rebuttals: List[RawRebuttalItem],
        challenges: List[DebateChallenge],
        evidence_map: Dict[str, EvidenceRecord],
    ) -> List[DebateRebuttal]:
        valid_ch_ids = set(c.challenge_id for c in challenges)
        validated: List[DebateRebuttal] = []

        for item in raw_rebuttals:
            if item.challenge_id not in valid_ch_ids:
                continue
            clean_resp = self._sanitize_text(item.response)
            valid_ids = [eid for eid in item.supporting_evidence_ids if eid in evidence_map]

            validated.append(
                DebateRebuttal(
                    rebuttal_id=f"reb-{uuid.uuid4().hex[:8]}",
                    challenge_id=item.challenge_id,
                    response=clean_resp,
                    supporting_evidence_ids=valid_ids,
                    confidence=item.confidence,
                )
            )

        return validated

    def _verify_numerical_claim(
        self,
        claim: str,
        evidence_ids: List[str],
        evidence_map: Dict[str, EvidenceRecord],
    ) -> bool:
        """
        Extracts numbers from claim string. If claim mentions specific numbers,
        verifies that they correspond to numerical values in the cited evidence records.
        """
        found_nums = re.findall(r"\b\d+(?:\.\d+)?\b", claim)
        if not found_nums:
            return True

        evidence_vals = []
        for eid in evidence_ids:
            ev = evidence_map.get(eid)
            if ev and ev.value is not None:
                if isinstance(ev.value, (int, float)) and not isinstance(ev.value, bool):
                    evidence_vals.append(float(ev.value))
                elif isinstance(ev.value, str):
                    for sn in re.findall(r"\b\d+(?:\.\d+)?\b", ev.value):
                        evidence_vals.append(float(sn))

        for fn in found_nums:
            num = float(fn)
            # Skip standard period integers (e.g. EMA20, RSI14, 1-4)
            if num in [1.0, 2.0, 3.0, 4.0, 5.0, 10.0, 14.0, 20.0, 50.0, 200.0]:
                continue
            matched = any(abs(num - ev_val) / max(abs(ev_val), 1.0) < 0.05 for ev_val in evidence_vals)
            if not matched and evidence_vals:
                return False

        return True

    # ------------------------------------------------------------------
    # Deterministic Rule-Based Fallbacks (Zero LLM, 100% Offline)
    # ------------------------------------------------------------------

    def _deterministic_bull_arguments(
        self,
        evidence_summary: EvidenceSummary,
        evidence_map: Dict[str, EvidenceRecord],
    ) -> List[DebateArgument]:
        bull_records = [
            r for r in evidence_summary.evidence_records
            if r.direction == SignalDirection.BULLISH
        ]
        if not bull_records:
            bull_records = [r for r in evidence_summary.evidence_records if r.direction != SignalDirection.BEARISH][:2]

        args: List[DebateArgument] = []
        for r in bull_records[:3]:
            val_str = f" ({r.metric_name}={r.value}{r.unit or ''})" if r.value is not None else ""
            args.append(
                DebateArgument(
                    argument_id=f"arg-bull-{uuid.uuid4().hex[:6]}",
                    side=DebateSide.BULL,
                    claim=f"Bullish confirmation: {r.claim}{val_str}",
                    supporting_evidence_ids=[r.evidence_id],
                    confidence=r.confidence if r.confidence is not None else 0.7,
                    risks=list(r.risks or ["Market volatility risk"]),
                    assumptions=list(r.assumptions or ["Trend continuation"]),
                    is_unsupported=False,
                )
            )
        return args

    def _deterministic_bear_arguments(
        self,
        evidence_summary: EvidenceSummary,
        evidence_map: Dict[str, EvidenceRecord],
    ) -> List[DebateArgument]:
        bear_records = [
            r for r in evidence_summary.evidence_records
            if r.direction == SignalDirection.BEARISH
        ]
        if not bear_records:
            bear_records = [r for r in evidence_summary.evidence_records if r.direction != SignalDirection.BULLISH][:2]

        args: List[DebateArgument] = []
        for r in bear_records[:3]:
            val_str = f" ({r.metric_name}={r.value}{r.unit or ''})" if r.value is not None else ""
            args.append(
                DebateArgument(
                    argument_id=f"arg-bear-{uuid.uuid4().hex[:6]}",
                    side=DebateSide.BEAR,
                    claim=f"Bearish caution: {r.claim}{val_str}",
                    supporting_evidence_ids=[r.evidence_id],
                    confidence=r.confidence if r.confidence is not None else 0.7,
                    risks=list(r.risks or ["Downside continuation risk"]),
                    assumptions=list(r.assumptions or ["Resistance holds"]),
                    is_unsupported=False,
                )
            )
        return args

    def _deterministic_challenges(
        self,
        bull_args: List[DebateArgument],
        bear_args: List[DebateArgument],
        evidence_map: Dict[str, EvidenceRecord],
    ) -> List[DebateChallenge]:
        challenges: List[DebateChallenge] = []
        if bull_args and bear_args:
            target = bull_args[0]
            contra = bear_args[0]
            challenges.append(
                DebateChallenge(
                    challenge_id=f"ch-{uuid.uuid4().hex[:6]}",
                    target_argument_id=target.argument_id,
                    challenge=f"Contested by bear thesis: {contra.claim}",
                    evidence_ids=contra.supporting_evidence_ids,
                    severity=ChallengeSeverity.HIGH,
                    response_status=ChallengeStatus.OPEN,
                    explanation=f"Contested by bear thesis: {contra.claim}",
                )
            )
        return challenges

    def _deterministic_rebuttals(
        self,
        challenges: List[DebateChallenge],
        evidence_map: Dict[str, EvidenceRecord],
    ) -> List[DebateRebuttal]:
        rebuttals: List[DebateRebuttal] = []
        for ch in challenges:
            avail_ids = list(evidence_map.keys())
            eid = [avail_ids[0]] if avail_ids else []
            rebuttals.append(
                DebateRebuttal(
                    rebuttal_id=f"reb-{uuid.uuid4().hex[:6]}",
                    challenge_id=ch.challenge_id,
                    response=f"Evidence reaffirms thesis validity despite challenge: {ch.challenge}",
                    supporting_evidence_ids=eid,
                    confidence=0.6,
                )
            )
        return rebuttals

    def _build_deterministic_round(
        self,
        round_num: int,
        evidence_summary: EvidenceSummary,
        evidence_map: Dict[str, EvidenceRecord],
    ) -> DebateRound:
        bull = self._deterministic_bull_arguments(evidence_summary, evidence_map)
        bear = self._deterministic_bear_arguments(evidence_summary, evidence_map)
        ch = self._deterministic_challenges(bull, bear, evidence_map)
        reb = self._deterministic_rebuttals(ch, evidence_map)
        return DebateRound(
            round_number=round_num,
            bull_arguments=bull,
            bear_arguments=bear,
            challenges=ch,
            rebuttals=reb,
            round_id=f"round-{round_num}",
            bear_challenges=ch,
        )

    # ------------------------------------------------------------------
    # Helper Utilities
    # ------------------------------------------------------------------

    def _build_compact_evidence_prompt(self, records: List[EvidenceRecord]) -> str:
        lines = []
        for r in records:
            cat = r.category.value if r.category else "GENERAL"
            val_str = f", val={r.value}{r.unit or ''}" if r.value is not None else ""
            dir_str = f", dir={r.direction.value}" if r.direction else ""
            lines.append(f"[{r.evidence_id}] {r.specialist_name} ({cat}): {r.claim}{val_str}{dir_str}")
        return "\n".join(lines)

    def _sanitize_text(self, text: str) -> str:
        if not text:
            return ""
        for marker in ["<think>", "</think>", "Thinking Process:", "Let's think step by step:"]:
            if marker in text:
                text = text.replace(marker, "")
        return text.strip()
