import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from backend.domain.schemas import MarketContext, EvidenceSummary, DataQualityStatus
from backend.domain.debate_schemas import DebateResult
from backend.domain.research_synthesis_schemas import (
    ResearchSynthesisResult, SpecialistView, ResearchConflict
)
from backend.infrastructure.llm import LLMClient, LLMClientError

logger = logging.getLogger(__name__)

class AIResearchSynthesisEngine:
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    async def synthesize(self, 
                   market_context: MarketContext, 
                   evidence_summary: EvidenceSummary, 
                   debate_result: DebateResult) -> ResearchSynthesisResult:
        
        if not market_context or getattr(market_context, "quality_status", None) == DataQualityStatus.CRITICAL_FAILURE:
            return ResearchSynthesisResult(
                symbol=market_context.symbol if market_context else "UNKNOWN",
                context_id=market_context.context_id if market_context else "UNKNOWN",
                is_unavailable=True,
                data_limitations=["MarketContext UNAVAILABLE"]
            )
            
        try:
            # Prepare payload for LLM to synthesize
            bull_case = debate_result.bull_case.core_thesis if getattr(debate_result, "bull_case", None) else ""
            bear_case = debate_result.bear_case.attack_summary if getattr(debate_result, "bear_case", None) else ""
            risk_case = debate_result.risk_assessment.risk_reward_assessment if getattr(debate_result, "risk_assessment", None) else ""
            
            ev_len = len(getattr(evidence_summary, 'evidence_records', getattr(evidence_summary, 'records', [])))
            conf_len = len(getattr(evidence_summary, 'conflict_summary', []))
            
            user_prompt = (
                f"Synthesize the following research for {market_context.symbol}:\n"
                f"Bull Case: {bull_case}\n"
                f"Bear Case: {bear_case}\n"
                f"Risk: {risk_case}\n"
                f"Evidence items: {ev_len}\n"
                f"Conflicts: {conf_len}\n"
                "Return a coherent structured research summary, highlighting conflicts and data limitations."
            )
            
            response = await self.llm_client.generate_structured(
                user_prompt=user_prompt,
                response_model=ResearchSynthesisResult,
                system_prompt="You are an expert financial research synthesizer. Do not fabricate data or evidence IDs. Base everything entirely on the provided text."
            )
            
            # Post-process to ensure we don't hallucinate context info
            response.symbol = market_context.symbol
            response.context_id = market_context.context_id
            
            return response
            
        except LLMClientError as e:
            logger.error(f"LLM failure in Research Synthesis: {e}")
            return ResearchSynthesisResult(
                symbol=market_context.symbol,
                context_id=market_context.context_id,
                is_unavailable=True,
                data_limitations=[f"LLM synthesis failed: {str(e)}"]
            )
        except Exception as e:
            logger.error(f"Unexpected error in Research Synthesis: {e}")
            return ResearchSynthesisResult(
                symbol=market_context.symbol,
                context_id=market_context.context_id,
                is_unavailable=True,
                data_limitations=["Internal exception during synthesis"]
            )
