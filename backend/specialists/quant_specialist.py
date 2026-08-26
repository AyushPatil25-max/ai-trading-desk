"""
QuantSpecialist — Phase 3.4

Implements the first genuinely quantitative specialist.

Separation of concerns
-----------------------
DETERMINISTIC (Python — quant_calculator.py):
  - Daily returns, 5-day cumulative return, 5-day realized volatility
  - 5-day price range %, 5-day avg volume
  - Price z-score (5-day window), EMA spread %, RSI extremity score
  - Trend consistency score
  - All metrics carry full provenance (formula, window, source, timestamp)
  - Unavailable metrics (requiring full history) are explicitly documented

AI INTERPRETATION (LLM — _QuantLLMResponse):
  - Statistical regime classification
  - Risk characterization
  - Anomaly detection judgment
  - Statistical evidence strength
  - Conclusion, risks, assumptions, invalidation conditions
  - Does NOT alter or compute any numeric value

Golden Specialist Pattern (Stage 5)
-------------------------------------
1. _validate_context(ctx)
2. _build_metrics(ctx)          — calls quant_calculator.compute_all_metrics()
3. _build_prompt(ctx, metrics)
4. llm.generate_structured()
5. _build_output(input, llm_resp, metrics)

Data Availability (Phase 3.4 baseline)
---------------------------------------
AVAILABLE:
  - 5-day cumulative return          [≥2 OHLCV rows]
  - 5-day realized volatility        [≥3 OHLCV rows]
  - 5-day price range %              [≥2 OHLCV rows]
  - 5-day avg daily volume           [≥1 OHLCV row]
  - 5-day price z-score              [≥2 OHLCV rows]
  - 5-day return mean                [≥2 OHLCV rows]
  - 5-day trend consistency          [≥2 OHLCV rows]
  - EMA spread %                     [technical_indicators]
  - RSI extremity score              [technical_indicators]

NOT AVAILABLE (documented):
  - 20-day realized volatility       [needs full history]
  - 20-day max drawdown              [needs full history]
  - 60-day Sharpe ratio              [needs full history + Rf]
  - 60-day Sortino ratio             [needs full history]
  - 20-day rolling volatility        [needs full history]

FUTURE (requires new data fields):
  - Correlation to index
  - Factor exposures
  - Order book imbalance
"""

import json
import logging
from typing import List, Tuple

from backend.domain.agents import BaseAgent
from backend.domain.schemas import (
    AgentError,
    AgentInput,
    AgentOutput,
    AgentState,
    MarketContext,
    QuantMetricRecord,
    QuantPayload,
    QuantRiskCharacterization,
    QuantStatisticalRegime,
    _QuantLLMResponse,
)
from backend.infrastructure.llm import LLMClient, LLMClientError, LLMParseError
from backend.specialists.quant_calculator import QuantMetric, compute_all_metrics

logger = logging.getLogger(__name__)

# Minimum number of useful (available) metrics to proceed to LLM.
# If fewer than this are available, the context is too sparse for useful analysis.
MIN_AVAILABLE_METRICS = 2

_SYSTEM_PROMPT = """\
You are a quantitative analyst operating within a systematic trading research system.

Mandate:
- Interpret ONLY the quantitative evidence supplied to you.
- The numerical values are AUTHORITATIVE — computed by Python from raw market data.
- You MUST NOT modify, recalculate, or contradict any supplied numerical value.
- Do NOT produce hidden chain-of-thought reasoning.
- Explicitly state uncertainty when the evidence is statistically limited (e.g., 5-day window).
- Distinguish evidence (what the numbers show) from interpretation (what they imply statistically).
- Always provide at least one concrete invalidation condition.
- Return ONLY valid JSON matching the required schema — no prose, no markdown fencing.
"""


class QuantSpecialist(BaseAgent):
    """
    Production quantitative analysis specialist.

    Computes deterministic statistical metrics from MarketContext via
    quant_calculator.compute_all_metrics(), then uses the LLM for
    statistical interpretation only.

    Parameters
    ----------
    llm_client : LLMClient
        Injected LLM provider. Use MockLLMClient in tests.
    """

    AGENT_NAME = "QuantSpecialist"
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
        Execute the quantitative analysis specialist.

        Stage 1 — Validate context has minimal required data.
        Stage 2 — Compute deterministic quant metrics (Python only).
        Stage 3 — Build prompt embedding computed metrics.
        Stage 4 — Call LLM for statistical interpretation.
        Stage 5 — Assemble typed AgentOutput with QuantPayload.
        """
        ctx = input_data.market_context
        logger.info(
            "[QuantSpecialist] executing symbol=%s context_id=%s",
            ctx.symbol, ctx.context_id,
        )

        # Stage 1 — Validation
        validation_error = self._validate_context(ctx)
        if validation_error:
            return self._failure_output(
                ctx, code="INVALID_INPUT", message=validation_error
            )

        # Stage 2 — Deterministic calculation (no LLM)
        raw_metrics = compute_all_metrics(
            current_price=ctx.current_price,
            ohlcv=ctx.ohlcv_historical,
            technical_indicators=ctx.technical_indicators,
        )

        # Check we have enough available metrics to be meaningful
        available_count = sum(1 for m in raw_metrics if m.available)
        if available_count < MIN_AVAILABLE_METRICS:
            return self._failure_output(
                ctx,
                code="INSUFFICIENT_QUANT_DATA",
                message=(
                    f"Only {available_count} quantitative metric(s) available "
                    f"(minimum {MIN_AVAILABLE_METRICS} required). "
                    "Ensure MarketContext contains ohlcv_historical and/or "
                    "technical_indicators with valid numeric data."
                ),
            )

        # Stage 3 — Prompt construction
        system_prompt, user_prompt = self._build_prompt(ctx, raw_metrics)

        # Stage 4 — LLM interpretation
        try:
            llm_response: _QuantLLMResponse = await self._llm.generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=_QuantLLMResponse,
            )
        except LLMParseError as exc:
            logger.warning(
                "[QuantSpecialist] LLM parse error context_id=%s: %s",
                ctx.context_id, exc,
            )
            return self._failure_output(
                ctx, code="LLM_PARSE_ERROR", message=str(exc)
            )
        except LLMClientError as exc:
            logger.error(
                "[QuantSpecialist] LLM client error context_id=%s: %s",
                ctx.context_id, exc,
            )
            return self._failure_output(
                ctx, code="LLM_CLIENT_ERROR", message=str(exc)
            )

        # Stage 5 — Output assembly
        return self._build_output(input_data, llm_response, raw_metrics)

    # ── Stage 1: Validation ───────────────────────────────────────────────────

    def _validate_context(self, ctx: MarketContext) -> str | None:
        """
        Check that MarketContext has at least one usable data source.

        We don't fail if OHLCV is missing — technical_indicators alone can
        supply RSI extremity and EMA spread. But if both are empty, there's
        nothing to analyze.
        """
        if ctx.current_price <= 0:
            return f"Invalid current_price={ctx.current_price} in MarketContext."
        has_ohlcv = bool(ctx.ohlcv_historical)
        has_indicators = bool(ctx.technical_indicators)
        if not has_ohlcv and not has_indicators:
            return (
                "MarketContext has no ohlcv_historical and no technical_indicators — "
                "cannot compute any quantitative evidence."
            )
        return None

    # ── Stage 2: Deterministic calculation ──────────────────────────────────

    @staticmethod
    def _metrics_to_records(raw_metrics: List[QuantMetric]) -> List[QuantMetricRecord]:
        """Convert QuantMetric dataclasses to Pydantic QuantMetricRecord models."""
        return [
            QuantMetricRecord(
                metric_name=m.metric_name,
                value=m.value,
                unit=m.unit,
                window=m.window,
                available=m.available,
                unavailable_reason=m.unavailable_reason,
                source=m.source,
                calculation_method=m.calculation_method,
                data_timestamp=m.data_timestamp,
            )
            for m in raw_metrics
        ]

    # ── Stage 3: Prompt construction ──────────────────────────────────────────

    def _build_prompt(
        self,
        ctx: MarketContext,
        raw_metrics: List[QuantMetric],
    ) -> Tuple[str, str]:
        """
        Build LLM prompt with full metric evidence block.

        Available metrics are presented with their computed values.
        Unavailable metrics are presented with their reason so the LLM
        does not fabricate them.
        """
        avail_lines: List[str] = []
        unavail_lines: List[str] = []

        for m in raw_metrics:
            if m.available and m.value is not None:
                avail_lines.append(
                    f"  - {m.metric_name}: {m.value} {m.unit}  "
                    f"[window={m.window}, method={m.calculation_method}]"
                )
            else:
                unavail_lines.append(
                    f"  - {m.metric_name}: [UNAVAILABLE — {m.unavailable_reason}]"
                )

        schema_json = json.dumps(_QuantLLMResponse.model_json_schema(), indent=2)

        user_prompt = f"""
Perform a quantitative statistical analysis of {ctx.symbol}.

Market context generated at: {ctx.generated_at.isoformat()}
Data timestamp: {ctx.data_timestamp.isoformat()}
Current price: {ctx.current_price:.2f}

=== AUTHORITATIVE COMPUTED METRICS (Python-calculated — do NOT alter) ===
{chr(10).join(avail_lines) if avail_lines else "  [None available]"}

=== EXPLICITLY UNAVAILABLE METRICS (do NOT invent values) ===
{chr(10).join(unavail_lines) if unavail_lines else "  [None]"}

Instructions:
1. Classify the statistical regime based on available volatility and return evidence.
2. Characterize the risk profile (ELEVATED / MODERATE / SUBDUED / INDETERMINATE).
3. Set anomaly_detected=true if any metric is statistically extreme (e.g., vol spike, z-score > 2.0).
4. Assign statistical_strength based on quantity and consistency of available evidence.
5. Provide a concise one-sentence conclusion.
6. List specific invalidation conditions.
7. Acknowledge limitations caused by the 5-day observation window.
8. Do NOT calculate or alter any numerical value from the AUTHORITATIVE section.
9. For UNAVAILABLE metrics, do not invent values or estimates.

Required JSON output schema:
{schema_json}
"""
        return _SYSTEM_PROMPT, user_prompt

    # ── Stage 5: Output assembly ──────────────────────────────────────────────

    def _build_output(
        self,
        input_data: AgentInput,
        llm_response: _QuantLLMResponse,
        raw_metrics: List[QuantMetric],
    ) -> AgentOutput:
        """
        Assemble the final AgentOutput with typed QuantPayload.

        Numeric metric values come from Python calculation (authoritative).
        Regime, risk, anomaly classification come from the LLM response.
        """
        ctx = input_data.market_context
        metric_records = self._metrics_to_records(raw_metrics)

        payload = QuantPayload(
            statistical_regime=llm_response.statistical_regime,
            risk_characterization=llm_response.risk_characterization,
            anomaly_detected=llm_response.anomaly_detected,
            statistical_strength=llm_response.statistical_strength,
            metrics=metric_records,
            invalidation_conditions=llm_response.invalidation_conditions,
            risks=llm_response.risks,
            assumptions=llm_response.assumptions,
        )

        logger.info(
            "[QuantSpecialist] SUCCESS context_id=%s regime=%s risk=%s anomaly=%s confidence=%.2f",
            ctx.context_id,
            llm_response.statistical_regime.value,
            llm_response.risk_characterization.value,
            llm_response.anomaly_detected,
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
            conclusion="Quantitative analysis failed.",
            error=AgentError(code=code, message=message),
        )
