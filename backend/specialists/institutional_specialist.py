"""
InstitutionalSpecialist — Phase 3.10

Production institutional flow and ownership specialist following the Golden Specialist Pattern.
Calculations are deterministic via institutional_calculator.py.
LLM provides only qualitative synthesis.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from backend.domain.agents import BaseAgent
from backend.domain.schemas import (
    AgentInput,
    AgentOutput,
    AgentState,
    MarketContext,
    AgentError,
    AgentEvidence,
    InstitutionalMetricRecord,
    InstitutionalPayload,
    InstitutionalRegime,
    FIIRegime,
    DIIRegime,
    OwnershipRegime,
    PromoterRisk,
    InstitutionalStrength,
    SourceTier,
    VerificationStatus,
    DataQuality
)
from backend.infrastructure.llm import LLMClient, LLMClientError, LLMParseError
from backend.specialists.institutional_calculator import (
    calc_net_flow, calc_ownership_change, calc_delivery_percentage
)
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Private LLM Schema
class _InstitutionalLLMResponse(BaseModel):
    institutional_regime: InstitutionalRegime = Field(description="Overall institutional direction")
    institutional_strength: InstitutionalStrength = Field(description="Conviction in institutional trend")
    fii_regime: FIIRegime = Field(description="FII/FPI direction")
    dii_regime: DIIRegime = Field(description="DII direction")
    ownership_regime: OwnershipRegime = Field(description="Direction of promoter and smart money holdings")
    promoter_risk: PromoterRisk = Field(description="Risk level inferred from promoter holding or pledge")
    
    catalysts: List[str] = Field(description="Positive institutional catalysts", default_factory=list)
    headwinds: List[str] = Field(description="Institutional headwinds/red flags", default_factory=list)
    risks: List[str] = Field(description="Risks to the institutional thesis", default_factory=list)
    assumptions: List[str] = Field(description="Key assumptions in this analysis", default_factory=list)
    invalidation_conditions: List[str] = Field(description="Conditions that would invalidate thesis", default_factory=list)
    
    conclusion: str = Field(description="One-sentence institutional thesis")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in the institutional thesis (0-1)")

_SYSTEM_PROMPT = """\
You are a specialist institutional ownership and flow analyst operating within a systematic trading research system.

Rules you MUST follow:
1. Analyze ONLY the supplied institutional net flows, ownership changes, and delivery statistics.
2. All numbers (FII net, DII net, ownership %, delivery %) are AUTHORITATIVE facts computed in Python.
3. Do NOT invent, hallucinate, or calculate any numeric values. Use the provided metrics exactly.
4. Synthesize the regimes (Institutional, FII, DII, Ownership, Promoter Risk) strictly based on the provided evidence.
5. If flow data is entirely missing, output UNKNOWN regimes.
6. Clearly separate facts from your qualitative interpretation.
7. Return ONLY valid JSON matching the required schema.
"""


class InstitutionalSpecialist(BaseAgent):
    AGENT_NAME = "InstitutionalSpecialist"
    AGENT_VERSION = "1.0.0"

    def __init__(self, llm_client: Optional[LLMClient] = None) -> None:
        self._llm = llm_client

    @property
    def name(self) -> str:
        return self.AGENT_NAME

    @property
    def version(self) -> str:
        return self.AGENT_VERSION

    async def execute(self, input_data: AgentInput) -> AgentOutput:
        market_context = input_data.market_context
        context_id = market_context.context_id
        symbol = market_context.symbol
        data_ts = market_context.data_timestamp

        if not self._validate_context(market_context):
            return self._build_failed_output(
                error_code="INVALID_INPUT",
                error_message="Invalid market context.",
                data_timestamp=data_ts,
            )

        # 2. Build Evidence
        try:
            metrics_dict, evidence_records = self._build_evidence(market_context)
        except Exception as exc:
            logger.exception("[%s] Calculation error: %s", self.name, exc)
            return self._build_failed_output("CALCULATION_ERROR", str(exc), data_ts)

        # Degraded Check
        if not evidence_records:
            logger.info("[%s] DEGRADED symbol=%s context_id=%s: 0 institutional metrics available", self.name, symbol, context_id)
            return self._build_degraded_output(
                reason="No institutional/ownership data available in MarketContext.",
                data_timestamp=data_ts,
                metrics_dict=metrics_dict,
                evidence=evidence_records
            )

        # 3. Build Prompt
        system_prompt, user_prompt = self._build_prompt(market_context, metrics_dict)

        # 4. LLM qualitative
        if not self._llm:
            return self._build_failed_output("LLM_CLIENT_MISSING", "No LLMClient configured.", data_ts)

        try:
            llm_response: _InstitutionalLLMResponse = await self._llm.generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=_InstitutionalLLMResponse,
            )
        except LLMParseError as exc:
            return self._build_failed_output("LLM_PARSE_ERROR", str(exc), data_ts)
        except LLMClientError as exc:
            return self._build_failed_output("LLM_CLIENT_ERROR", str(exc), data_ts)
        except Exception as exc:
            return self._build_failed_output("LLM_ERROR", str(exc), data_ts)

        # 5. Build Output
        return self._build_output(input_data, llm_response, metrics_dict, evidence_records)


    def _validate_context(self, context: MarketContext) -> bool:
        if not context or not hasattr(context, "current_price") or context.current_price <= 0:
            return False
        return True

    def _build_evidence(self, context: MarketContext) -> Tuple[Dict[str, Any], List[InstitutionalMetricRecord]]:
        metrics_dict = {
            "fii_net_flow": None,
            "dii_net_flow": None,
            "combined_net_flow": None,
            "promoter_ownership": None,
            "promoter_ownership_change": None,
            "promoter_pledge_percentage": None,
            "delivery_percentage": None,
            "bulk_deal_count": 0,
            "block_deal_count": 0
        }
        evidence_list = []

        context_id = context.context_id
        timestamp_str = context.data_timestamp.isoformat()

        # Flows
        if hasattr(context, "institutional_data") and context.institutional_data:
            fii_net = sum([f.net_value for f in context.institutional_data if f.investor_type in ["FII", "FPI"] and f.net_value is not None])
            dii_net = sum([f.net_value for f in context.institutional_data if f.investor_type in ["DII", "MUTUAL_FUND", "INSURANCE", "BANK"] and f.net_value is not None])
            
            # Count how many records exist for FII/DII to verify it's not actually just zero sum but present
            fii_records = [f for f in context.institutional_data if f.investor_type in ["FII", "FPI"] and f.net_value is not None]
            dii_records = [f for f in context.institutional_data if f.investor_type in ["DII", "MUTUAL_FUND", "INSURANCE", "BANK"] and f.net_value is not None]
            
            if fii_records:
                metrics_dict["fii_net_flow"] = fii_net
                evidence_list.append(InstitutionalMetricRecord(
                    metric_name="fii_net_flow",
                    value=fii_net,
                    unit="currency",
                    period=fii_records[0].period,
                    source=fii_records[0].source,
                    source_tier=fii_records[0].source_tier,
                    verification_status=fii_records[0].verification_status,
                    calculation_method="Sum of FII/FPI net_value",
                    inputs={"record_count": len(fii_records)},
                    context_id=context_id,
                    data_timestamp=timestamp_str
                ))
            if dii_records:
                metrics_dict["dii_net_flow"] = dii_net
                evidence_list.append(InstitutionalMetricRecord(
                    metric_name="dii_net_flow",
                    value=dii_net,
                    unit="currency",
                    period=dii_records[0].period,
                    source=dii_records[0].source,
                    source_tier=dii_records[0].source_tier,
                    verification_status=dii_records[0].verification_status,
                    calculation_method="Sum of DII net_value",
                    inputs={"record_count": len(dii_records)},
                    context_id=context_id,
                    data_timestamp=timestamp_str
                ))
            if fii_records or dii_records:
                c_fii = metrics_dict["fii_net_flow"] or 0.0
                c_dii = metrics_dict["dii_net_flow"] or 0.0
                metrics_dict["combined_net_flow"] = c_fii + c_dii
                
        # Ownership
        if hasattr(context, "ownership_data") and context.ownership_data:
            promoter_records = [o for o in context.ownership_data if o.holder_type in ["PROMOTER", "PROMOTER_GROUP"]]
            if promoter_records:
                latest = sorted(promoter_records, key=lambda r: getattr(r, "report_date", None) or getattr(r, "observed_at", None) or context.data_timestamp, reverse=True)[0]
                metrics_dict["promoter_ownership"] = latest.ownership_percentage
                metrics_dict["promoter_pledge_percentage"] = latest.pledged_percentage
                evidence_list.append(InstitutionalMetricRecord(
                    metric_name="promoter_ownership",
                    value=latest.ownership_percentage,
                    unit="%",
                    period=latest.period,
                    source=latest.source,
                    source_tier=latest.source_tier,
                    verification_status=latest.verification_status,
                    calculation_method="Latest PROMOTER ownership_percentage",
                    inputs={"pledge_percentage": latest.pledged_percentage},
                    context_id=context_id,
                    data_timestamp=timestamp_str
                ))
                if len(promoter_records) > 1:
                    sorted_records = sorted(promoter_records, key=lambda r: getattr(r, "report_date", None) or getattr(r, "observed_at", None) or context.data_timestamp, reverse=True)
                    prev = sorted_records[1]
                    chg = calc_ownership_change(latest.ownership_percentage, prev.ownership_percentage)
                    metrics_dict["promoter_ownership_change"] = chg

        # Delivery
        if hasattr(context, "delivery_data") and context.delivery_data:
            latest = sorted(context.delivery_data, key=lambda d: d.trade_date, reverse=True)[0]
            metrics_dict["delivery_percentage"] = latest.delivery_percentage
            evidence_list.append(InstitutionalMetricRecord(
                metric_name="delivery_percentage",
                value=latest.delivery_percentage,
                unit="%",
                period="1D",
                source=latest.source,
                source_tier=latest.source_tier,
                verification_status=latest.verification_status,
                calculation_method="Delivery / Traded",
                inputs={"delivery": latest.delivery_quantity, "traded": latest.traded_quantity},
                context_id=context_id,
                data_timestamp=timestamp_str
            ))

        # Deals
        if hasattr(context, "deal_data") and context.deal_data:
            metrics_dict["bulk_deal_count"] = len([d for d in context.deal_data if d.deal_type == "BULK"])
            metrics_dict["block_deal_count"] = len([d for d in context.deal_data if d.deal_type == "BLOCK"])

        return metrics_dict, evidence_list

    def _build_prompt(self, context: MarketContext, metrics: Dict[str, Any]) -> Tuple[str, str]:
        user_data = {
            "symbol": context.symbol,
            "data_timestamp": context.data_timestamp.isoformat(),
            "metrics": metrics
        }
        return _SYSTEM_PROMPT, json.dumps(user_data, indent=2)


    def _build_output(self, input_data: AgentInput, llm_response: _InstitutionalLLMResponse, metrics: Dict[str, Any], evidence: List[InstitutionalMetricRecord]) -> AgentOutput:
        
        payload = InstitutionalPayload(
            fii_net_flow=metrics["fii_net_flow"] or 0.0,
            dii_net_flow=metrics["dii_net_flow"] or 0.0,
            combined_net_flow=metrics["combined_net_flow"] or 0.0,
            promoter_ownership=metrics["promoter_ownership"] or 0.0,
            promoter_ownership_change=metrics["promoter_ownership_change"] or 0.0,
            promoter_pledge_percentage=metrics["promoter_pledge_percentage"] or 0.0,
            delivery_percentage=metrics["delivery_percentage"] or 0.0,
            delivery_trend="UNKNOWN",
            bulk_deal_count=metrics["bulk_deal_count"],
            block_deal_count=metrics["block_deal_count"],
            
            institutional_regime=llm_response.institutional_regime,
            institutional_strength=llm_response.institutional_strength,
            fii_regime=llm_response.fii_regime,
            dii_regime=llm_response.dii_regime,
            ownership_regime=llm_response.ownership_regime,
            promoter_risk=llm_response.promoter_risk,
            
            catalysts=llm_response.catalysts,
            headwinds=llm_response.headwinds,
            risks=llm_response.risks,
            assumptions=llm_response.assumptions,
            invalidation_conditions=llm_response.invalidation_conditions,
            conclusion=llm_response.conclusion,
            confidence=llm_response.confidence,
            
            evidence=evidence
        )
        
        agent_evidence_list = []
        for e in evidence:
            agent_evidence_list.append(AgentEvidence(source=self.name, content=e.model_dump_json()))
            
        return AgentOutput(
            agent_name=self.name,
            version=self.version,
            model=self._llm.model_name if self._llm else "unknown",
            status=AgentState.SUCCESS,
            context=input_data.market_context,
            raw_data=payload.model_dump(),
            agent_outputs=[],
            summary=llm_response.conclusion,
            evidence=agent_evidence_list,
            error=None,
            data_timestamp=input_data.market_context.data_timestamp,
            confidence=llm_response.confidence,
            conclusion=llm_response.conclusion
        )

    def _build_failed_output(self, error_code: str, error_message: str, data_timestamp: datetime) -> AgentOutput:
        return AgentOutput(
            agent_name=self.name,
            version=self.version,
            model=self._llm.model_name if self._llm else "unknown",
            status=AgentState.FAILED,
            context=MarketContext(
                context_id="unknown", symbol="unknown", data_timestamp=data_timestamp, current_price=0.0, provider="unknown"
            ),
            raw_data={},
            agent_outputs=[],
            summary="Institutional specialist failed.",
            evidence=[],
            error=AgentError(code=error_code, message=error_message),
            data_timestamp=data_timestamp,
            confidence=0.0,
            conclusion="Failed to execute"
        )

    def _build_degraded_output(self, reason: str, data_timestamp: datetime, metrics_dict: Dict[str, Any], evidence: List[InstitutionalMetricRecord]) -> AgentOutput:
        payload = InstitutionalPayload(
            institutional_regime=InstitutionalRegime.UNKNOWN,
            institutional_strength=InstitutionalStrength.UNKNOWN,
            fii_regime=FIIRegime.UNKNOWN,
            dii_regime=DIIRegime.UNKNOWN,
            ownership_regime=OwnershipRegime.UNKNOWN,
            promoter_risk=PromoterRisk.UNKNOWN,
            
            fii_net_flow=metrics_dict.get("fii_net_flow"),
            dii_net_flow=metrics_dict.get("dii_net_flow"),
            combined_net_flow=metrics_dict.get("combined_net_flow"),
            
            promoter_ownership=metrics_dict.get("promoter_ownership"),
            promoter_ownership_change=metrics_dict.get("promoter_ownership_change"),
            promoter_pledge_percentage=metrics_dict.get("promoter_pledge_percentage"),
            
            delivery_percentage=metrics_dict.get("delivery_percentage"),
            delivery_trend=None,
            
            bulk_deal_count=metrics_dict.get("bulk_deal_count", 0),
            block_deal_count=metrics_dict.get("block_deal_count", 0),
            
            institutional_confirmation=False,
            evidence=evidence,
            
            catalysts=[],
            headwinds=[],
            risks=[],
            assumptions=[],
            invalidation_conditions=[],
            
            conclusion=reason,
            confidence=0.0
        )

        return AgentOutput(
            agent_name=self.name,
            version=self.version,
            model=self._llm.model_name if self._llm else "unknown",
            status=AgentState.DEGRADED,
            context=MarketContext(
                context_id="unknown", symbol="unknown", data_timestamp=data_timestamp, current_price=0.0, provider="unknown"
            ),
            raw_data=payload.model_dump(),
            agent_outputs=[],
            summary=reason,
            evidence=[],
            error=None,
            data_timestamp=data_timestamp,
            confidence=0.0,
            conclusion="Degraded execution"
        )
