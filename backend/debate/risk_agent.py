import json
from typing import Dict, Any, Optional
from datetime import datetime
import uuid

from backend.domain.agents import BaseAgent
from backend.domain.schemas import AgentInput, AgentOutput, AgentState, AgentError
from backend.infrastructure.llm import LLMClient, LLMParseError, LLMClientError
from backend.domain.schemas import UnifiedEvidencePackage
from backend.domain.debate_schemas import RiskAssessment, BullCase, BearCase

class RiskAgent(BaseAgent):
    """
    RiskAgent evaluates downside risk and uncertainty based on the Debate cases and UnifiedEvidencePackage.
    """
    def __init__(self, llm: LLMClient):
        self._llm = llm

    @property
    def name(self) -> str:
        return "RiskAgent"

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
        
        # 1. Extract inputs
        unified_evidence_dict = input_data.additional_data.get("unified_evidence")
        bull_case_dict = input_data.additional_data.get("bull_case")
        bear_case_dict = input_data.additional_data.get("bear_case")
        
        if not unified_evidence_dict:
            return self._failure_output(ctx_id, symbol, "INVALID_INPUT", "UnifiedEvidencePackage is missing.", ts)
        if not bull_case_dict:
            return self._failure_output(ctx_id, symbol, "INVALID_INPUT", "BullCase is missing.", ts)
        if not bear_case_dict:
            return self._failure_output(ctx_id, symbol, "INVALID_INPUT", "BearCase is missing.", ts)
            
        unified_evidence = UnifiedEvidencePackage.model_validate(unified_evidence_dict)
        bull_case = BullCase.model_validate(bull_case_dict)
        bear_case = BearCase.model_validate(bear_case_dict)
        
        evidence_json = unified_evidence.model_dump_json(include={'evidence_items', 'missing_data_records', 'pit_inconsistent_count', 'data_quality_summary'})
        
        system_prompt = (
            "You are the risk control analyst.\n"
            "Evaluate whether the thesis survives downside, uncertainty, conflicting evidence and missing data.\n"
            "Do not manufacture numbers.\n"
            "Identify concentration, volatility, liquidity, drawdown, stop-loss and position-sizing concerns."
        )
        
        schema_json = json.dumps(RiskAssessment.model_json_schema(), indent=2)
        
        user_prompt = (
            f"Symbol: {symbol}\nContext ID: {ctx_id}\n\n"
            f"Bull Case:\n{bull_case.model_dump_json()}\n\n"
            f"Bear Case:\n{bear_case.model_dump_json()}\n\n"
            f"Evidence Package (Risk Focus):\n{evidence_json}\n\n"
            "Construct a RiskAssessment. Evaluate downside risk, missing info, and determine if there's a risk veto. "
            "You MUST return ONLY valid JSON matching this exact schema:\n"
            f"{schema_json}"
        )
        
        try:
            risk_case: RiskAssessment = await self._llm.generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=RiskAssessment
            )
            
            risk_case.context_id = ctx_id
            risk_case.symbol = symbol
            
            return AgentOutput(
                agent_name=self.name,
                version=self.version,
                model=self._llm.model_name,
                status=AgentState.SUCCESS,
                data_timestamp=ts,
                confidence=risk_case.confidence,
                conclusion=f"Risk Level: {risk_case.risk_level}. {risk_case.risk_reward_assessment}",
                evidence=[{"source": ref.source, "content": ref.claim} for ref in risk_case.evidence_references],
                risks=risk_case.primary_risks + risk_case.secondary_risks,
                invalidation_conditions=risk_case.thesis_invalidation,
                raw_data=risk_case.model_dump()
            )
            
        except LLMParseError as e:
            return self._failure_output(ctx_id, symbol, "LLM_PARSE_ERROR", str(e), ts)
        except LLMClientError as e:
            return self._failure_output(ctx_id, symbol, "LLM_CLIENT_ERROR", str(e), ts)
