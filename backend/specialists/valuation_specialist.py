"""
ValuationSpecialist — Phase 3.6

Production valuation analysis specialist following the Golden Specialist Pattern.

Separation of concerns
-----------------------
DETERMINISTIC (Python — valuation_calculator.py):
  - P/E Ratio          — current_price / eps
  - P/S Ratio          — current_price / (revenue / shares_outstanding)
  - P/B Ratio          — current_price / (total_equity / shares_outstanding)
  - EV/EBITDA          — (market_cap + debt - cash) / ebitda
  - FCF Yield          — (fcf_per_share / current_price) * 100
  - PEG Ratio          — pe_ratio / eps_growth_rate_pct
  - All guards: EPS=0, EPS<0, negative EBITDA, missing inputs, NaN/Inf
  - Full provenance: method, formula, inputs, assumptions, context_id, data_timestamp

AI INTERPRETATION (LLM — _ValuationLLMResponse):
  - Valuation status classification (UNDERVALUED / FAIRLY_VALUED / OVERVALUED / INDETERMINATE)
  - Premium/discount assessment
  - Valuation strength score (0.0–1.0)
  - One-sentence investment thesis
  - Risks, assumptions, invalidation conditions
  - Does NOT compute, alter, or invent any numeric valuation multiple

Constraint
----------
THE LLM MUST NOT BE THE VALUATION CALCULATOR.
Every numeric value in the output originates exclusively from valuation_calculator.py.

Golden Specialist Pattern (5-stage pipeline)
---------------------------------------------
1. _validate_context(ctx)        — check current_price > 0
2. _build_metrics(ctx)           — calls valuation_calculator.compute_all_valuation_metrics()
3. _build_prompt(ctx, metrics)   — compact evidence block + JSON schema
4. llm.generate_structured()     — LLM qualitative synthesis
5. _build_output(input, resp, m) — typed ValuationPayload in AgentOutput.raw_data

DEGRADED condition: fewer than 1 available valuation metric
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
    MarketContext,
    ValuationMetricRecord,
    ValuationPayload,
    ValuationPremiumDiscount,
    ValuationStatus,
    _ValuationLLMResponse,
)
from backend.infrastructure.llm import LLMClient, LLMClientError, LLMParseError
from backend.specialists.valuation_calculator import (
    ValuationMetric,
    compute_all_valuation_metrics,
    summarize_available,
)

logger = logging.getLogger(__name__)

# Minimum available valuation metrics required to proceed to LLM analysis.
# With < 1 available metric there is nothing meaningful to assess.
MIN_AVAILABLE_VALUATION_METRICS = 1

_SYSTEM_PROMPT = """\
You are a specialist valuation analyst operating within a systematic trading research system.

Rules you MUST follow:
1. Analyze ONLY the valuation multiples and evidence supplied to you.
2. All numeric multiples (P/E, P/S, P/B, EV/EBITDA, FCF Yield, PEG) are AUTHORITATIVE —
   computed deterministically from verified financial data and the current share price.
3. You MUST NOT modify, recalculate, or contradict any supplied numeric value.
4. You MUST NOT invent, guess, or estimate missing multiples or financial figures.
5. Clearly separate facts (what the numbers show) from interpretation (what they imply for valuation).
6. Use only the available multiples to form your assessment — explicitly acknowledge gaps.
7. Explicitly state uncertainty when valuation data is limited or missing.
8. Identify specific valuation risks (multiple compression/expansion, earnings miss, sector re-rating).
9. Always provide at least one concrete invalidation condition.
10. Return ONLY valid JSON matching the required schema — no markdown, no prose wrapper.
11. Do NOT produce hidden chain-of-thought reasoning.
"""


class ValuationSpecialist(BaseAgent):
    """
    Production valuation analysis specialist.

    Depends on LLMClient for qualitative valuation synthesis.
    Deterministic calculations originate strictly from MarketContext via valuation_calculator.py.

    Parameters
    ----------
    llm_client : LLMClient
        Injected LLM provider. Use MockLLMClient in tests.
    """

    AGENT_NAME = "ValuationSpecialist"
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
        Execute the valuation analysis specialist.

        Stage 1 — Validate basic context validity (current_price > 0).
        Stage 2 — Compute deterministic valuation metrics from MarketContext.
        Stage 3 — Check data sufficiency (return DEGRADED if no metrics available).
        Stage 4 — Build LLM prompt embedding verified multiples.
        Stage 5 — Call LLM for qualitative synthesis.
        Stage 6 — Assemble typed AgentOutput with ValuationPayload.
        """
        ctx = input_data.market_context
        logger.info(
            "[ValuationSpecialist] executing symbol=%s context_id=%s",
            ctx.symbol, ctx.context_id,
        )

        # Stage 1 — Context validation
        validation_error = self._validate_context(ctx)
        if validation_error:
            return self._failure_output(
                ctx, code="INVALID_INPUT", message=validation_error
            )

        # Resolve fundamental data (MarketContext takes priority; fallback to additional_data)
        fundamental_data: Dict[str, Any] = ctx.fundamental_data
        if not fundamental_data and input_data.additional_data:
            fundamental_data = input_data.additional_data.get("fundamental_data", {})

        # Stage 2 — Deterministic valuation calculations
        raw_metrics = compute_all_valuation_metrics(
            fundamental_data=fundamental_data,
            current_price=ctx.current_price,
            context_id=ctx.context_id,
            data_timestamp=ctx.data_timestamp,
        )
        available_methods, available_count = summarize_available(raw_metrics)

        # Stage 3 — Data sufficiency check
        if available_count < MIN_AVAILABLE_VALUATION_METRICS:
            logger.warning(
                "[ValuationSpecialist] DEGRADED symbol=%s context_id=%s: "
                "only %d valuation metrics available (minimum %d required)",
                ctx.symbol, ctx.context_id, available_count, MIN_AVAILABLE_VALUATION_METRICS,
            )
            reason = (
                f"Valuation data is unavailable in MarketContext for {ctx.symbol}. "
                f"Only {available_count} metric(s) available "
                f"(minimum {MIN_AVAILABLE_VALUATION_METRICS} required). "
                "Financial statement data (EPS, revenue, equity, shares_outstanding) requires "
                "a fundamental data provider."
            )
            return self._degraded_output(
                ctx=ctx,
                raw_metrics=raw_metrics,
                available_methods=available_methods,
                reason=reason,
            )

        # Stage 4 — Prompt construction
        system_prompt, user_prompt = self._build_prompt(
            ctx=ctx,
            raw_metrics=raw_metrics,
            available_methods=available_methods,
        )

        # Stage 5 — LLM qualitative synthesis
        try:
            llm_response: _ValuationLLMResponse = await self._llm.generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=_ValuationLLMResponse,
            )
        except LLMParseError as exc:
            logger.warning(
                "[ValuationSpecialist] LLM parse error context_id=%s: %s",
                ctx.context_id, exc,
            )
            return self._failure_output(
                ctx, code="LLM_PARSE_ERROR", message=str(exc)
            )
        except LLMClientError as exc:
            logger.error(
                "[ValuationSpecialist] LLM client error context_id=%s: %s",
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
            available_methods=available_methods,
        )

    # ── Stage 1: Validation ───────────────────────────────────────────────────

    def _validate_context(self, ctx: MarketContext) -> Optional[str]:
        """Check minimal context validity. Returns error message string or None."""
        if ctx.current_price <= 0:
            return f"Invalid current_price={ctx.current_price} in MarketContext."
        return None

    # ── Stage 2: Metric Conversion ────────────────────────────────────────────

    @staticmethod
    def _metrics_to_records(raw_metrics: List[ValuationMetric]) -> List[ValuationMetricRecord]:
        """Convert ValuationMetric dataclasses to Pydantic ValuationMetricRecord models."""
        return [
            ValuationMetricRecord(
                metric_name=m.metric_name,
                value=m.value,
                unit=m.unit,
                method=m.method,
                formula=m.formula,
                inputs=m.inputs,
                available=m.available,
                unavailable_reason=m.unavailable_reason,
                assumptions=list(m.assumptions),
                context_id=m.context_id,
                data_timestamp=m.data_timestamp,
            )
            for m in raw_metrics
        ]

    # ── Stage 4: Prompt Construction ──────────────────────────────────────────

    def _build_prompt(
        self,
        ctx: MarketContext,
        raw_metrics: List[ValuationMetric],
        available_methods: List[str],
    ) -> Tuple[str, str]:
        """
        Build LLM prompt embedding verified valuation multiples.
        Available metrics are presented with exact values, formulas, and inputs.
        Unavailable metrics are explicitly listed so the LLM does not hallucinate them.
        """
        avail_lines: List[str] = []
        unavail_lines: List[str] = []

        for m in raw_metrics:
            if m.available and m.value is not None:
                input_summary = ", ".join(
                    f"{k}={v}" for k, v in m.inputs.items()
                )
                avail_lines.append(
                    f"  - {m.metric_name}: {m.value:.4f} {m.unit}  "
                    f"[method={m.method}, formula={m.formula}, inputs: {input_summary}]"
                )
            else:
                unavail_lines.append(
                    f"  - {m.metric_name}: [UNAVAILABLE — {m.unavailable_reason}]"
                )

        schema_json = json.dumps(_ValuationLLMResponse.model_json_schema(), indent=2)

        user_prompt = f"""
Perform a valuation analysis for {ctx.symbol}.

Market context generated at: {ctx.generated_at.isoformat()}
Market data timestamp: {ctx.data_timestamp.isoformat()}
Current share price: {ctx.current_price:.2f}
Available valuation methods: {', '.join(available_methods) if available_methods else 'None'}

=== AUTHORITATIVE VALUATION MULTIPLES (Python-calculated — do NOT alter or recalculate) ===
{chr(10).join(avail_lines) if avail_lines else "  [None available]"}

=== EXPLICITLY UNAVAILABLE METRICS (do NOT invent or guess values) ===
{chr(10).join(unavail_lines) if unavail_lines else "  [None]"}

NOT IMPLEMENTED (by design):
  - DCF (Discounted Cash Flow): Omitted — requires long-range FCF forecast, discount rate,
    and terminal growth rate, which are not yet available from the data provider.

Instructions:
1. Classify overall valuation status (UNDERVALUED, FAIRLY_VALUED, OVERVALUED, or INDETERMINATE).
2. Assess premium/discount vs fair value (SIGNIFICANT_PREMIUM, MODERATE_PREMIUM, FAIR_VALUE,
   MODERATE_DISCOUNT, SIGNIFICANT_DISCOUNT, or INDETERMINATE).
3. Assign a valuation strength score from 0.0 to 1.0 (conviction level).
4. Provide a concise one-sentence valuation thesis.
5. List specific invalidation conditions (e.g., multiple expansion reverses, earnings miss).
6. List key valuation risks.
7. List key assumptions underlying this valuation assessment.
8. Note any limitations from missing multiples or data.

Required JSON output schema:
{schema_json}
"""
        return _SYSTEM_PROMPT, user_prompt

    # ── Stage 6: Output Assembly ──────────────────────────────────────────────

    def _build_output(
        self,
        input_data: AgentInput,
        llm_response: _ValuationLLMResponse,
        raw_metrics: List[ValuationMetric],
        available_methods: List[str],
    ) -> AgentOutput:
        """Assemble the final SUCCESS AgentOutput with typed ValuationPayload."""
        ctx = input_data.market_context
        metric_records = self._metrics_to_records(raw_metrics)

        # Separate relative (multiples) from absolute (yield) metrics for payload clarity
        relative_keys = {"pe_ratio", "ps_ratio", "pb_ratio", "ev_ebitda", "peg_ratio"}
        absolute_keys = {"fcf_yield"}

        relative_valuation: Dict[str, Any] = {}
        absolute_valuation: Dict[str, Any] = {}
        for m in raw_metrics:
            if m.available and m.value is not None:
                if m.metric_name in relative_keys:
                    relative_valuation[m.metric_name] = m.value
                elif m.metric_name in absolute_keys:
                    absolute_valuation[m.metric_name] = m.value

        payload = ValuationPayload(
            valuation_status=llm_response.valuation_status,
            premium_discount_assessment=llm_response.premium_discount_assessment,
            valuation_strength=llm_response.valuation_strength,
            methods_used=available_methods,
            relative_valuation=relative_valuation,
            absolute_valuation=absolute_valuation,
            evidence=metric_records,
            invalidation_conditions=llm_response.invalidation_conditions,
            risks=llm_response.risks,
            assumptions=llm_response.assumptions,
            conclusion=llm_response.conclusion,
            confidence=llm_response.confidence,
        )

        logger.info(
            "[ValuationSpecialist] SUCCESS context_id=%s status=%s strength=%.2f confidence=%.2f",
            ctx.context_id,
            llm_response.valuation_status.value,
            llm_response.valuation_strength,
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

    # ── DEGRADED output ───────────────────────────────────────────────────────

    def _degraded_output(
        self,
        ctx: MarketContext,
        raw_metrics: List[ValuationMetric],
        available_methods: List[str],
        reason: str,
    ) -> AgentOutput:
        """Produce a structured DEGRADED AgentOutput when valuation inputs are missing."""
        metric_records = self._metrics_to_records(raw_metrics)

        payload = ValuationPayload(
            valuation_status=ValuationStatus.INDETERMINATE,
            premium_discount_assessment=ValuationPremiumDiscount.INDETERMINATE,
            valuation_strength=0.0,
            methods_used=available_methods,
            relative_valuation={},
            absolute_valuation={},
            evidence=metric_records,
            invalidation_conditions=[
                "Fundamental financial statement data becomes available (EPS, revenue, equity)"
            ],
            risks=[
                "Cannot assess valuation without financial statement data "
                "(EPS, revenue, total equity, shares outstanding)"
            ],
            assumptions=["Valuation analysis deferred until fundamental data provider is integrated"],
            conclusion=reason,
            confidence=0.0,
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

    # ── FAILED output ─────────────────────────────────────────────────────────

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
            conclusion="Valuation analysis failed.",
            error=AgentError(code=code, message=message),
        )
