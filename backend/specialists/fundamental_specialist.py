"""
FundamentalSpecialist — Phase 3.5

Production fundamental analysis specialist following the Golden Specialist Pattern.

Separation of concerns
-----------------------
DETERMINISTIC (Python — fundamental_calculator.py):
  - Margins: Gross Margin %, Operating Margin %, Net Profit Margin %
  - Growth: Revenue Growth YoY %, EPS Growth YoY %
  - Solvency & Health: Debt to Equity, Current Ratio, ROE %, Free Cash Flow
  - Valuation ratios (P/E) computed strictly from verifiable current price and EPS
  - Period tracking and data freshness / staleness evaluation
  - Full provenance (formula, period, source, timestamps)

AI INTERPRETATION (LLM — _FundamentalLLMResponse):
  - Business quality assessment (FundamentalQuality)
  - Top-line & bottom-line growth assessment (GrowthAssessment)
  - Profitability and earnings efficiency assessment (ProfitabilityAssessment)
  - Balance sheet and leverage assessment (BalanceSheetAssessment)
  - Financial strength score (0.0–1.0)
  - Qualitative conclusion, invalidation conditions, risks, and assumptions
  - Does NOT alter, calculate, or invent any numerical financial facts

Golden Specialist Pattern (Stage 5)
-------------------------------------
1. _validate_context(ctx)
2. _build_metrics(ctx)          — calls fundamental_calculator.compute_all_fundamental_metrics()
3. _build_prompt(ctx, metrics)
4. llm.generate_structured()
5. _build_output(input, llm_resp, metrics)
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from backend.domain.agents import BaseAgent
from backend.domain.schemas import (
    AgentError,
    AgentInput,
    AgentOutput,
    AgentState,
    BalanceSheetAssessment,
    FundamentalMetricRecord,
    FundamentalPayload,
    FundamentalQuality,
    GrowthAssessment,
    MarketContext,
    ProfitabilityAssessment,
    _FundamentalLLMResponse,
)
from backend.infrastructure.llm import LLMClient, LLMClientError, LLMParseError
from backend.specialists.fundamental_calculator import (
    FundamentalMetric,
    assess_data_freshness,
    compute_all_fundamental_metrics,
)

logger = logging.getLogger(__name__)

# Minimum available metrics required to perform meaningful LLM analysis
MIN_AVAILABLE_FUNDAMENTAL_METRICS = 2

_SYSTEM_PROMPT = """\
You are a fundamental financial analyst operating within a systematic trading research system.

Rules you MUST follow:
1. Analyze and interpret ONLY the fundamental financial evidence supplied to you.
2. Numerical values and accounting ratios are AUTHORITATIVE — computed deterministically from verified financial data.
3. You MUST NOT modify, recalculate, or contradict any supplied numerical value.
4. You MUST NOT invent, guess, or estimate missing financial figures or statements.
5. Clearly distinguish facts (what the numbers show) from qualitative interpretation (what they imply for business quality).
6. Respect reporting periods (TTM, MRQ, Annual, Quarterly).
7. Explicitly state uncertainty when financial data is limited, missing, or historical.
8. Identify business risks, balance-sheet risks, and key operational assumptions.
9. Always provide at least one concrete invalidation condition.
10. Return ONLY valid JSON matching the required schema — no markdown, no prose wrapper.
11. Do NOT produce hidden chain-of-thought reasoning.
"""


class FundamentalSpecialist(BaseAgent):
    """
    Production fundamental analysis specialist.

    Depends on LLMClient for qualitative financial synthesis;
    deterministic financial calculations originate strictly from MarketContext / Python calculator.

    Parameters
    ----------
    llm_client : LLMClient
        Injected LLM provider. Use MockLLMClient in tests.
    """

    AGENT_NAME = "FundamentalSpecialist"
    AGENT_VERSION = "1.0"

    def __init__(self, llm_client: LLMClient) -> None:
        self._llm = llm_client

    @property
    def name(self) -> str:
        return self.AGENT_NAME

    @property
    def version(self) -> str:
        return self.AGENT_VERSION

    # ── Public entry point ────────────────────────────────────────────────────

    async def execute(self, input_data: AgentInput) -> AgentOutput:
        """
        Execute the fundamental analysis specialist.

        Stage 1 — Validate basic context validity.
        Stage 2 — Compute deterministic fundamental metrics and evaluate freshness.
        Stage 3 — Check data sufficiency (handle DEGRADED state if data is missing).
        Stage 4 — Build prompt embedding verified metrics.
        Stage 5 — Call LLM for qualitative synthesis.
        Stage 6 — Assemble typed AgentOutput with FundamentalPayload.
        """
        ctx = input_data.market_context
        logger.info(
            "[FundamentalSpecialist] executing symbol=%s context_id=%s",
            ctx.symbol, ctx.context_id,
        )

        # Stage 1 — Context validation
        validation_error = self._validate_context(ctx)
        if validation_error:
            return self._failure_output(
                ctx, code="INVALID_INPUT", message=validation_error
            )

        # Extract fundamental data (checking both MarketContext and additional_data)
        fundamental_data = ctx.fundamental_data
        if not fundamental_data and input_data.additional_data:
            fundamental_data = input_data.additional_data.get("fundamental_data", {})

        # Stage 2 — Deterministic calculation & freshness check
        raw_metrics = compute_all_fundamental_metrics(
            fundamental_data=fundamental_data,
            current_price=ctx.current_price,
            data_timestamp=ctx.data_timestamp,
        )
        freshness_status, age_days = assess_data_freshness(
            data=fundamental_data,
            market_timestamp=ctx.data_timestamp,
        )

        # Stage 3 — Data sufficiency check
        available_count = sum(1 for m in raw_metrics if m.available)
        if available_count < MIN_AVAILABLE_FUNDAMENTAL_METRICS:
            logger.warning(
                "[FundamentalSpecialist] DEGRADED symbol=%s context_id=%s: only %d fundamental metrics available",
                ctx.symbol, ctx.context_id, available_count,
            )
            reason = (
                f"Fundamental data is unavailable in MarketContext for {ctx.symbol}. "
                f"Only {available_count} metric(s) available (minimum {MIN_AVAILABLE_FUNDAMENTAL_METRICS} required). "
                "Corporate financial statements (income statement, balance sheet, cash flows) require a fundamental data provider."
            )
            return self._degraded_output(
                ctx=ctx,
                raw_metrics=raw_metrics,
                freshness_status=freshness_status,
                reason=reason,
            )

        # Stage 4 — Prompt construction
        system_prompt, user_prompt = self._build_prompt(
            ctx=ctx,
            raw_metrics=raw_metrics,
            fundamental_data=fundamental_data,
            freshness_status=freshness_status,
            age_days=age_days,
        )

        # Stage 5 — LLM qualitative synthesis
        try:
            llm_response: _FundamentalLLMResponse = await self._llm.generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=_FundamentalLLMResponse,
            )
        except LLMParseError as exc:
            logger.warning(
                "[FundamentalSpecialist] LLM parse error context_id=%s: %s",
                ctx.context_id, exc,
            )
            return self._failure_output(
                ctx, code="LLM_PARSE_ERROR", message=str(exc)
            )
        except LLMClientError as exc:
            logger.error(
                "[FundamentalSpecialist] LLM client error context_id=%s: %s",
                ctx.context_id, exc,
            )
            return self._failure_output(
                ctx, code="LLM_CLIENT_ERROR", message=str(exc)
            )

        # Stage 6 — Output assembly
        return self._build_output(
            input_data=input_data,
            llm_response=llm_response,
            raw_metrics=raw_metrics,
            fundamental_data=fundamental_data,
            freshness_status=freshness_status,
        )

    # ── Stage 1: Validation ───────────────────────────────────────────────────

    def _validate_context(self, ctx: MarketContext) -> Optional[str]:
        """Check minimal context validity."""
        if ctx.current_price <= 0:
            return f"Invalid current_price={ctx.current_price} in MarketContext."
        return None

    # ── Stage 2: Helper to convert records ────────────────────────────────────

    @staticmethod
    def _metrics_to_records(raw_metrics: List[FundamentalMetric]) -> List[FundamentalMetricRecord]:
        """Convert FundamentalMetric dataclasses to Pydantic FundamentalMetricRecord models."""
        return [
            FundamentalMetricRecord(
                metric_name=m.metric_name,
                value=m.value,
                unit=m.unit,
                period=m.period,
                report_date=m.report_date,
                available=m.available,
                unavailable_reason=m.unavailable_reason,
                source=m.source,
                calculation_method=m.calculation_method,
                data_timestamp=m.data_timestamp,
            )
            for m in raw_metrics
        ]

    # ── Stage 4: Prompt Construction ──────────────────────────────────────────

    def _build_prompt(
        self,
        ctx: MarketContext,
        raw_metrics: List[FundamentalMetric],
        fundamental_data: Dict[str, Any],
        freshness_status: str,
        age_days: Optional[int],
    ) -> Tuple[str, str]:
        """
        Build LLM prompt embedding verified fundamental metrics.
        Available metrics are presented with exact values and period.
        Unavailable metrics are explicitly listed so the LLM does not hallucinate them.
        """
        avail_lines: List[str] = []
        unavail_lines: List[str] = []

        for m in raw_metrics:
            if m.available and m.value is not None:
                avail_lines.append(
                    f"  - {m.metric_name}: {m.value} {m.unit}  "
                    f"[period={m.period}, method={m.calculation_method}, source={m.source}]"
                )
            else:
                unavail_lines.append(
                    f"  - {m.metric_name}: [UNAVAILABLE — {m.unavailable_reason}]"
                )

        period = fundamental_data.get("period", "TTM")
        report_date = fundamental_data.get("report_date", "Unspecified")
        freshness_info = f"{freshness_status}"
        if age_days is not None:
            freshness_info += f" ({age_days} days old relative to market timestamp)"

        schema_json = json.dumps(_FundamentalLLMResponse.model_json_schema(), indent=2)

        user_prompt = f"""
Perform a fundamental investment analysis of {ctx.symbol}.

Market context generated at: {ctx.generated_at.isoformat()}
Market data timestamp: {ctx.data_timestamp.isoformat()}
Current share price: {ctx.current_price:.2f}
Reporting period: {period}
Filing / Report date: {report_date}
Data freshness: {freshness_info}

=== AUTHORITATIVE FUNDAMENTAL METRICS (Python-calculated — do NOT alter or recalculate) ===
{chr(10).join(avail_lines) if avail_lines else "  [None available]"}

=== EXPLICITLY UNAVAILABLE METRICS (do NOT invent or guess values) ===
{chr(10).join(unavail_lines) if unavail_lines else "  [None]"}

Instructions:
1. Assess overall fundamental quality (STRONG, MODERATE, WEAK, DISTRESSED, or INDETERMINATE).
2. Assess growth trajectory (HIGH_GROWTH, MODERATE_GROWTH, STAGNANT, CONTRACTING, or INDETERMINATE).
3. Assess profitability and margin efficiency (HIGHLY_PROFITABLE, MODERATE_PROFITABILITY, LOW_PROFITABILITY, UNPROFITABLE, or INDETERMINATE).
4. Assess balance sheet leverage and solvency (PRISTINE, HEALTHY, LEVERAGED, DISTRESSED, or INDETERMINATE).
5. Assign a composite financial strength score from 0.0 to 1.0.
6. Provide a concise one-sentence fundamental conclusion.
7. List specific invalidation conditions (e.g. margin contraction, debt covenant breach, revenue deceleration).
8. List fundamental business and solvency risks.
9. List key operational and macro assumptions.
10. Note any limitations resulting from reporting period age or missing statements.

Required JSON output schema:
{schema_json}
"""
        return _SYSTEM_PROMPT, user_prompt

    # ── Stage 6: Output Assembly ──────────────────────────────────────────────

    def _build_output(
        self,
        input_data: AgentInput,
        llm_response: _FundamentalLLMResponse,
        raw_metrics: List[FundamentalMetric],
        fundamental_data: Dict[str, Any],
        freshness_status: str,
    ) -> AgentOutput:
        """Assemble the final SUCCESS AgentOutput with typed FundamentalPayload."""
        ctx = input_data.market_context
        metric_records = self._metrics_to_records(raw_metrics)
        period = str(fundamental_data.get("period", "TTM"))

        payload = FundamentalPayload(
            fundamental_quality=llm_response.fundamental_quality,
            growth_assessment=llm_response.growth_assessment,
            profitability_assessment=llm_response.profitability_assessment,
            balance_sheet_assessment=llm_response.balance_sheet_assessment,
            financial_strength=llm_response.financial_strength,
            reporting_period=period,
            data_freshness_status=freshness_status,
            metrics=metric_records,
            invalidation_conditions=llm_response.invalidation_conditions,
            risks=llm_response.risks,
            assumptions=llm_response.assumptions,
        )

        logger.info(
            "[FundamentalSpecialist] SUCCESS context_id=%s quality=%s strength=%.2f confidence=%.2f",
            ctx.context_id,
            llm_response.fundamental_quality.value,
            llm_response.financial_strength,
            llm_response.confidence,
        )

        return AgentOutput(
            agent_name=self.name,
            version=self.version,
            model=self._llm.model_name,
            status=AgentState.SUCCESS,
            data_timestamp=ctx.data_timestamp,
            confidence=llm_response.confidence,
            conclusion=llm_response.conclusion,
            evidence=[],
            risks=llm_response.risks,
            assumptions=llm_response.assumptions,
            invalidation_conditions=llm_response.invalidation_conditions,
            raw_data=payload.model_dump(),
        )

    def _degraded_output(
        self,
        ctx: MarketContext,
        raw_metrics: List[FundamentalMetric],
        freshness_status: str,
        reason: str,
    ) -> AgentOutput:
        """Produce a structured DEGRADED AgentOutput when fundamental data is missing."""
        metric_records = self._metrics_to_records(raw_metrics)
        period = "N/A"

        payload = FundamentalPayload(
            fundamental_quality=FundamentalQuality.INDETERMINATE,
            growth_assessment=GrowthAssessment.INDETERMINATE,
            profitability_assessment=ProfitabilityAssessment.INDETERMINATE,
            balance_sheet_assessment=BalanceSheetAssessment.INDETERMINATE,
            financial_strength=0.0,
            reporting_period=period,
            data_freshness_status="UNAVAILABLE",
            metrics=metric_records,
            invalidation_conditions=["Corporate financial statement data becomes available"],
            risks=["Cannot verify business solvency, margins, or growth without financial statements"],
            assumptions=["Fundamental analysis deferred until data provider is integrated"],
        )

        return AgentOutput(
            agent_name=self.name,
            version=self.version,
            model=self._llm.model_name,
            status=AgentState.DEGRADED,
            data_timestamp=ctx.data_timestamp,
            confidence=0.0,
            conclusion=reason,
            evidence=[],
            risks=payload.risks,
            assumptions=payload.assumptions,
            invalidation_conditions=payload.invalidation_conditions,
            raw_data=payload.model_dump(),
        )

    def _failure_output(
        self,
        ctx: MarketContext,
        code: str,
        message: str,
    ) -> AgentOutput:
        """Produce a well-formed FAILED AgentOutput without raising."""
        return AgentOutput(
            agent_name=self.name,
            version=self.version,
            model=self._llm.model_name,
            status=AgentState.FAILED,
            data_timestamp=ctx.data_timestamp,
            confidence=0.0,
            conclusion="Fundamental analysis failed.",
            error=AgentError(code=code, message=message),
        )
