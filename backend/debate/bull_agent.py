import json
from typing import Dict, Any, Optional
from datetime import datetime
import uuid

from backend.domain.agents import BaseAgent
from backend.domain.schemas import AgentInput, AgentOutput, AgentState, AgentError
from backend.infrastructure.llm import LLMClient, LLMParseError, LLMClientError
from backend.domain.schemas import UnifiedEvidencePackage
from backend.domain.debate_schemas import BullCase

class BullAgent(BaseAgent):
    """
    BullAgent constructs the strongest evidence-backed long thesis based on the UnifiedEvidencePackage.
    """
    def __init__(self, llm: LLMClient):
        self._llm = llm

    @property
    def name(self) -> str:
        return "BullAgent"

    @property
    def version(self) -> str:
        return "1.0.0"
        
    def _failure_output(self, ctx_id: str, symbol: str, code: str, message: str, ts: datetime) -> AgentOutput:
        return AgentOutput(
            agent_name=self.name,
            version=self.version,
            model=self._llm.model_name,
            status=AgentState.FAILED,
            data_timestamp=ts,
            confidence=0.0,
            conclusion="Failed",
            error=AgentError(code=code, message=message)
        )

    async def execute(self, input_data: AgentInput) -> AgentOutput:
        ctx_id = input_data.market_context.context_id
        symbol = input_data.symbol
        ts = input_data.market_context.data_timestamp
        
        # 1. Extract UnifiedEvidencePackage
        unified_evidence_dict = input_data.additional_data.get("unified_evidence")
        if not unified_evidence_dict:
            return self._failure_output(ctx_id, symbol, "INVALID_INPUT", "UnifiedEvidencePackage is missing.", ts)
            
        unified_evidence = UnifiedEvidencePackage.model_validate(unified_evidence_dict)
        
        if not unified_evidence.evidence_items:
            # Degraded if no evidence
            return AgentOutput(
                agent_name=self.name,
                version=self.version,
                model=self._llm.model_name,
                status=AgentState.DEGRADED,
                data_timestamp=ts,
                confidence=0.0,
                conclusion="Insufficient evidence to construct a Bull thesis.",
                raw_data={"reason": "No evidence items found"}
            )
        
        # Format evidence for LLM (only bullish or neutral/facts)
        # To avoid context limits, we might pass a summary, but the prompt says "Use ONLY evidence contained in UnifiedEvidencePackage".
        evidence_json = unified_evidence.model_dump_json(include={'evidence_items', 'agreement_summary', 'conflict_summary', 'bull_signals', 'high_confidence_signals'})
        
        system_prompt = (
            "You are the strongest possible long thesis builder.\n"
            "Use only supplied evidence.\n"
            "Do not invent facts or numerical values.\n"
            "Every material claim must reference evidence by evidence_id.\n"
            "You must acknowledge weaknesses.\n"
            "Distinguish facts from interpretation."
        )
        
        schema_json = json.dumps(BullCase.model_json_schema(), indent=2)
        
        user_prompt = (
            f"Symbol: {symbol}\nContext ID: {ctx_id}\n\n"
            f"Evidence Package:\n{evidence_json}\n\n"
            "Construct a coherent long thesis (BullCase). Focus on the strongest bullish evidence. "
            "You MUST return ONLY valid JSON matching this exact schema:\n"
            f"{schema_json}"
        )
        
        try:
            bull_case: BullCase = await self._llm.generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=BullCase
            )
            
            # Add missing IDs
            bull_case.thesis_id = bull_case.thesis_id or f"bull-{uuid.uuid4().hex[:8]}"
            bull_case.context_id = ctx_id
            bull_case.symbol = symbol
            
            return AgentOutput(
                agent_name=self.name,
                version=self.version,
                model=self._llm.model_name,
                status=AgentState.SUCCESS,
                data_timestamp=ts,
                confidence=bull_case.confidence,
                conclusion=bull_case.core_thesis,
                evidence=[{"source": ref.source, "content": ref.claim} for ref in bull_case.evidence_references],
                risks=bull_case.risks,
                assumptions=bull_case.assumptions,
                invalidation_conditions=bull_case.invalidation_conditions,
                raw_data=bull_case.model_dump()
            )
            
        except LLMParseError as e:
            return self._failure_output(ctx_id, symbol, "LLM_PARSE_ERROR", str(e), ts)
        except LLMClientError as e:
            return self._failure_output(ctx_id, symbol, "LLM_CLIENT_ERROR", str(e), ts)
