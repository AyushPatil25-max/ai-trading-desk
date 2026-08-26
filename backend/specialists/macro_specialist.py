import json
from typing import Dict, Any, List

from backend.domain.schemas import (
    MarketContext,
    AgentInput,
    AgentOutput,
    AgentState,
    AgentError,
    MacroPayload,
    _MacroLLMResponse,
    MacroRegime,
    MacroRisk,
    RateRegime,
    InflationRegime,
    MacroMetricRecord
)
from backend.domain.agents import BaseAgent
from backend.infrastructure.llm import LLMClientError, LLMParseError
from backend.specialists.macro_calculator import MacroCalculator

class MacroSpecialist(BaseAgent):
    """
    Analyzes macroeconomic data and interprets the current macro regime.
    Complies with the Golden Specialist Pattern.
    """

    AGENT_NAME = "MacroSpecialist"
    AGENT_VERSION = "1.0.0"

    def __init__(self, llm_client=None):
        self._llm = llm_client

    @property
    def name(self) -> str:
        return self.AGENT_NAME

    @property
    def version(self) -> str:
        return self.AGENT_VERSION

    async def execute(self, input_data: AgentInput) -> AgentOutput:
        market_context = input_data.market_context
        try:
            # 1. Validate Context
            if not self._validate_context(market_context):
                return self._build_degraded_output("Invalid market context.", market_context.data_timestamp)

            # 2. Build Metrics (Deterministic)
            metrics = self._build_metrics(market_context)
            available_metrics = [m for m in metrics if m.available]

            if len(available_metrics) < 1:
                return self._build_degraded_output("Insufficient macro data available.", market_context.data_timestamp)

            # 3. Build Prompt
            system_prompt = "You are a Macroeconomic Specialist. Analyze the provided macro metrics and deduce the macroeconomic regime, rate regime, inflation regime, and impact on the asset."
            user_prompt = self._build_prompt(market_context, available_metrics)

            # 4. Generate LLM Output
            llm_response = await self._llm.generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=_MacroLLMResponse,
            )

            # 5. Build Output Payload
            return self._build_output(llm_response, metrics, market_context.data_timestamp)

        except LLMParseError as exc:
            return self._build_failed_output("LLM_PARSE_ERROR", str(exc), market_context.data_timestamp)
        except LLMClientError as exc:
            return self._build_failed_output("LLM_CLIENT_ERROR", str(exc), market_context.data_timestamp)
        except Exception as e:
            return self._build_degraded_output(f"Exception during analysis: {str(e)}", market_context.data_timestamp)

    def _validate_context(self, context: MarketContext) -> bool:
        if not context:
            return False
        if not hasattr(context, 'macro_data'):
            return False
        return True

    def _build_metrics(self, context: MarketContext) -> List[MacroMetricRecord]:
        return MacroCalculator.calculate_macro_metrics(context)

    def _build_prompt(self, context: MarketContext, metrics: List[MacroMetricRecord]) -> str:
        metrics_dict = {m.metric_name: m.value for m in metrics}
        
        prompt = f"""
        Analyze the following macroeconomic data for the symbol {context.symbol}.
        
        Macro Metrics:
        {json.dumps(metrics_dict, indent=2)}
        
        Synthesize this data to determine:
        1. Macro Regime (EXPANSIONARY, NEUTRAL, CONTRACTIONARY, RESTRICTIVE, TRANSITIONAL)
        2. Macro Risk (LOW, MODERATE, HIGH, SEVERE)
        3. Rate Regime (HIKING, CUTTING, HOLDING)
        4. Inflation Regime (ACCELERATING, DECELERATING, STABLE, DEFLATIONARY)
        5. Specific asset impact and company sensitivity.
        
        Provide headwinds, tailwinds, invalidation conditions, risks, assumptions, and a one-sentence conclusion.
        """
        return prompt

    def _build_degraded_output(self, reason: str, timestamp: datetime) -> AgentOutput:
        payload = MacroPayload(
            macro_regime=MacroRegime.INDETERMINATE,
            macro_risk=MacroRisk.INDETERMINATE,
            rate_regime=RateRegime.INDETERMINATE,
            inflation_regime=InflationRegime.INDETERMINATE,
            asset_impact="Indeterminate due to insufficient data.",
            company_sensitivity="Indeterminate due to insufficient data.",
            evidence=[],
            tailwinds=[],
            headwinds=[],
            invalidation_conditions=[],
            risks=[],
            assumptions=[],
            conclusion=reason,
            confidence=0.0
        )
        return AgentOutput(
            agent_name=self.name,
            version=self.version,
            model=self._llm.model_name if self._llm else "unknown",
            status=AgentState.DEGRADED,
            data_timestamp=timestamp,
            conclusion=reason,
            confidence=0.0,
            raw_data=payload.model_dump(),
            evidence=[]
        )

    def _build_output(self, llm_response: _MacroLLMResponse, metrics: List[MacroMetricRecord], timestamp: datetime) -> AgentOutput:
        payload = MacroPayload(
            macro_regime=llm_response.macro_regime,
            macro_risk=llm_response.macro_risk,
            rate_regime=llm_response.rate_regime,
            inflation_regime=llm_response.inflation_regime,
            asset_impact=llm_response.asset_impact,
            company_sensitivity=llm_response.company_sensitivity,
            evidence=metrics,
            tailwinds=llm_response.tailwinds,
            headwinds=llm_response.headwinds,
            invalidation_conditions=llm_response.invalidation_conditions,
            risks=llm_response.risks,
            assumptions=llm_response.assumptions,
            conclusion=llm_response.conclusion,
            confidence=llm_response.confidence
        )

        from backend.domain.schemas import AgentEvidence
        evidence_recs = [
            AgentEvidence(source=m.source, content=f"{m.metric_name}: {m.value} {m.unit}")
            for m in metrics if m.available
        ]

        return AgentOutput(
            agent_name=self.name,
            version=self.version,
            model=self._llm.model_name if self._llm else "unknown",
            status=AgentState.SUCCESS,
            data_timestamp=timestamp,
            conclusion=llm_response.conclusion,
            confidence=llm_response.confidence,
            raw_data=payload.model_dump(),
            evidence=evidence_recs
        )

    def _build_failed_output(self, error_code: str, error_message: str, timestamp: datetime) -> AgentOutput:
        return AgentOutput(
            agent_name=self.name,
            version=self.version,
            model=self._llm.model_name if self._llm else "unknown",
            status=AgentState.FAILED,
            data_timestamp=timestamp,
            confidence=0.0,
            conclusion=f"Macro specialist failed: {error_message}",
            error=AgentError(code=error_code, message=error_message),
            evidence=[],
            raw_data=None,
        )
