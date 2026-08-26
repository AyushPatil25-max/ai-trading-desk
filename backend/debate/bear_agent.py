import json
from typing import Dict, Any, Optional
from datetime import datetime
import uuid

from backend.domain.agents import BaseAgent
from backend.domain.schemas import AgentInput, AgentOutput, AgentState, AgentError
from backend.infrastructure.llm import LLMClient, LLMParseError, LLMClientError
from backend.domain.schemas import UnifiedEvidencePackage
from backend.domain.debate_schemas import BearCase, BullCase

class BearAgent(BaseAgent):
    """
    BearAgent attacks the BullCase and constructs a short thesis based on the UnifiedEvidencePackage.
    """
    def __init__(self, llm: LLMClient):
        self._llm = llm

    @property
    def name(self) -> str:
        return "BearAgent"

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
        
        # 1. Extract UnifiedEvidencePackage and BullCase
        unified_evidence_dict = input_data.additional_data.get("unified_evidence")
        bull_case_dict = input_data.additional_data.get("bull_case")
        
        if not unified_evidence_dict:
            return self._failure_output(ctx_id, symbol, "INVALID_INPUT", "UnifiedEvidencePackage is missing.", ts)
        if not bull_case_dict:
            return self._failure_output(ctx_id, symbol, "INVALID_INPUT", "BullCase is missing.", ts)
            
        unified_evidence = UnifiedEvidencePackage.model_validate(unified_evidence_dict)
        bull_case = BullCase.model_validate(bull_case_dict)
        
        if not unified_evidence.evidence_items:
            return AgentOutput(
                agent_name=self.name,
                version=self.version,
                model=self._llm.model_name,
                status=AgentState.DEGRADED,
                data_timestamp=ts,
                confidence=0.0,
                conclusion="Insufficient evidence to construct a Bear thesis.",
                raw_data={"reason": "No evidence items found"}
            )
            
        evidence_json = unified_evidence.model_dump_json(include={'evidence_items', 'agreement_summary', 'conflict_summary', 'bear_signals', 'low_confidence_signals', 'missing_data_records'})
        bull_case_json = bull_case.model_dump_json()
        
        system_prompt = (
            "You are an adversarial short-side analyst.\n"
            "Your job is to destroy the Bull thesis.\n"
            "Do not produce generic bearish commentary.\n"
            "Attack specific Bull claims using supplied evidence.\n"
            "Do not invent numerical values or evidence. Reference evidence by evidence_id."
        )
        
        schema_json = json.dumps(BearCase.model_json_schema(), indent=2)
        
        user_prompt = (
            f"Symbol: {symbol}\nContext ID: {ctx_id}\n\n"
            f"Bull Case to Attack:\n{bull_case_json}\n\n"
            f"Evidence Package:\n{evidence_json}\n\n"
            "Construct a BearCase targeting the weaknesses, assumptions, and contradictory evidence in the Bull Case. "
            "You MUST return ONLY valid JSON matching this exact schema:\n"
            f"{schema_json}"
        )
        
        try:
            bear_case: BearCase = await self._llm.generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=BearCase
            )
            
            # Add missing IDs
            bear_case.thesis_id = bear_case.thesis_id or f"bear-{uuid.uuid4().hex[:8]}"
            bear_case.context_id = ctx_id
            bear_case.symbol = symbol
            
            return AgentOutput(
                agent_name=self.name,
                version=self.version,
                model=self._llm.model_name,
                status=AgentState.SUCCESS,
                data_timestamp=ts,
                confidence=bear_case.confidence,
                conclusion=bear_case.attack_summary,
                evidence=[{"source": ref.source, "content": ref.claim} for ref in bear_case.evidence_references],
                risks=bear_case.key_downside_risks,
                invalidation_conditions=bear_case.invalidation_conditions,
                raw_data=bear_case.model_dump()
            )
            
        except LLMParseError as e:
            return self._failure_output(ctx_id, symbol, "LLM_PARSE_ERROR", str(e), ts)
        except LLMClientError as e:
            return self._failure_output(ctx_id, symbol, "LLM_CLIENT_ERROR", str(e), ts)
