import asyncio
from datetime import datetime
from typing import Optional, List
import uuid

from backend.domain.schemas import MarketContext, AgentInput, AgentState, UnifiedEvidencePackage
from backend.domain.debate_schemas import (
    DebateResult, BullCase, BearCase, RiskAssessment, DebateDecisionState
)
from backend.debate.bull_agent import BullAgent
from backend.debate.bear_agent import BearAgent
from backend.debate.risk_agent import RiskAgent

class DebateOrchestrator:
    """
    Orchestrates the sequential adversarial debate process:
    Bull -> Bear -> Risk -> Deterministic Resolution.
    """
    def __init__(self, bull_agent: BullAgent, bear_agent: BearAgent, risk_agent: RiskAgent):
        self.bull_agent = bull_agent
        self.bear_agent = bear_agent
        self.risk_agent = risk_agent

    async def run_debate(self, market_context: MarketContext, unified_evidence: UnifiedEvidencePackage) -> DebateResult:
        debate_id = f"debate-{uuid.uuid4().hex[:8]}"
        symbol = market_context.symbol
        ctx_id = market_context.context_id
        
        # Base result
        result = DebateResult(
            debate_id=debate_id,
            context_id=ctx_id,
            symbol=symbol,
            generated_at=datetime.utcnow()
        )
        
        # 1. Execute Bull Agent
        bull_input = AgentInput(
            symbol=symbol,
            market_context=market_context,
            additional_data={"unified_evidence": unified_evidence.model_dump()}
        )
        bull_output = await self.bull_agent.execute(bull_input)
        
        if bull_output.status != AgentState.SUCCESS:
            result.thesis_status = DebateDecisionState.INSUFFICIENT_EVIDENCE
            result.recommended_action = "PASS (Bull Agent failed or degraded)"
            return result
            
        bull_case = BullCase.model_validate(bull_output.raw_data)
        result.bull_case = bull_case
        
        # 2. Execute Bear Agent
        bear_input = AgentInput(
            symbol=symbol,
            market_context=market_context,
            additional_data={
                "unified_evidence": unified_evidence.model_dump(),
                "bull_case": bull_case.model_dump()
            }
        )
        bear_output = await self.bear_agent.execute(bear_input)
        
        if bear_output.status != AgentState.SUCCESS:
            result.thesis_status = DebateDecisionState.INSUFFICIENT_EVIDENCE
            result.recommended_action = "PASS (Bear Agent failed or degraded)"
            return result
            
        bear_case = BearCase.model_validate(bear_output.raw_data)
        result.bear_case = bear_case
        
        # 3. Execute Risk Agent
        risk_input = AgentInput(
            symbol=symbol,
            market_context=market_context,
            additional_data={
                "unified_evidence": unified_evidence.model_dump(),
                "bull_case": bull_case.model_dump(),
                "bear_case": bear_case.model_dump()
            }
        )
        risk_output = await self.risk_agent.execute(risk_input)
        
        if risk_output.status != AgentState.SUCCESS:
            result.thesis_status = DebateDecisionState.INSUFFICIENT_EVIDENCE
            result.recommended_action = "PASS (Risk Agent failed or degraded)"
            return result
            
        risk_assessment = RiskAssessment.model_validate(risk_output.raw_data)
        result.risk_assessment = risk_assessment
        
        # 4. Deterministic Resolution
        self._resolve_debate(result, unified_evidence)
        
        return result

    def _resolve_debate(self, result: DebateResult, evidence: UnifiedEvidencePackage):
        """
        Deterministic logic for debate resolution based on the structural outputs.
        """
        # Calculate coverage (1 point for each evidence referenced)
        bull_refs = len(result.bull_case.evidence_references) if result.bull_case else 0
        bear_refs = len(result.bear_case.evidence_references) if result.bear_case else 0
        risk_refs = len(result.risk_assessment.evidence_references) if result.risk_assessment else 0
        
        total_extracted = evidence.total_evidence_extracted or len(evidence.evidence_items)
        coverage = min(1.0, (bull_refs + bear_refs) / max(1, total_extracted))
        
        bull_score = min(1.0, bull_refs * 0.1 + result.bull_case.confidence * 0.5)
        bear_score = min(1.0, bear_refs * 0.1 + result.bear_case.confidence * 0.5)
        
        if result.risk_assessment:
            # risk score is derived from RiskAssessment
            risk_score = min(1.0, risk_refs * 0.1 + result.risk_assessment.risk_score * 0.5)
        else:
            risk_score = 1.0
            
        result.bull_strength = bull_score
        result.bear_strength = bear_score
        result.risk_score = risk_score
        
        # Check risk veto
        if result.risk_assessment and result.risk_assessment.risk_veto:
            result.thesis_status = DebateDecisionState.RISK_VETO
            result.recommended_action = "PASS (Risk Veto)"
            result.overall_debate_quality = "HIGH" if coverage > 0.5 else "LOW"
            return
            
        # Check for insufficient coverage or conflicts
        if coverage < 0.2:
            result.thesis_status = DebateDecisionState.INSUFFICIENT_EVIDENCE
            result.recommended_action = "PASS (Low Evidence Coverage)"
            result.overall_debate_quality = "LOW"
            return
            
        # Calculate status
        margin = bull_score - bear_score
        if margin > 0.2 and risk_score < 0.5:
            result.thesis_status = DebateDecisionState.BULL_FAVORED
            result.recommended_action = "CONSIDER LONG"
        elif margin < -0.2:
            result.thesis_status = DebateDecisionState.BEAR_FAVORED
            result.recommended_action = "CONSIDER SHORT"
        else:
            result.thesis_status = DebateDecisionState.MIXED
            result.recommended_action = "WATCH (Mixed Signals)"
            
        result.overall_debate_quality = "HIGH" if (bull_refs >= 3 and bear_refs >= 2 and risk_refs >= 1) else "LOW"
        
        # Build unresolved questions based on contradictions
        if len(evidence.conflict_summary) > 0:
            result.unresolved_questions.append(f"Contains {len(evidence.conflict_summary)} critical data/domain conflicts.")
            
        # Ensure confidence reflects evidence coverage and risk
        result.confidence = max(0.0, min(1.0, coverage * 0.5 + (1.0 - risk_score) * 0.5))
