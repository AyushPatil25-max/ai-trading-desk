"""
SectorSpecialist — Phase 3.7

Production sector and relative performance specialist following the Golden Specialist Pattern.

Separation of concerns
-----------------------
DETERMINISTIC (Python — sector_calculator.py):
  - Company return (%)              — ((last_close - first_close) / first_close) * 100
  - Sector return (%)               — Extracted from sector_data['sector_return_pct']
  - Benchmark return (%)            — Extracted from sector_data['benchmark_return_pct']
  - Relative performance vs Sector  — Company Return - Sector Return (% points)
  - Relative performance vs Benchmark — Company Return - Benchmark Return (% points)
  - Sector vs Benchmark spread      — Sector Return - Benchmark Return (% points)
  - Metadata: sector, industry, benchmark symbol
  - Full provenance: metric name, value, unit, period, source, formula, context_id, data_timestamp

AI INTERPRETATION (LLM — _SectorLLMResponse):
  - Sector performance regime classification (STRONG_OUTPERFORMING, MODERATE_OUTPERFORMING, NEUTRAL, UNDERPERFORMING, LAGGING, INDETERMINATE)
  - Sector environment attractiveness (HIGHLY_ATTRACTIVE, ATTRACTIVE, NEUTRAL, UNATTRACTIVE, HIGHLY_UNATTRACTIVE, INDETERMINATE)
  - Cyclicality classification (CYCLICAL, DEFENSIVE, GROWTH, SENSITIVE, INDETERMINATE)
  - Relative strength ranking (LEADER, OUTPERFORMER, IN_LINE, UNDERPERFORMER, LAGGARD, INDETERMINATE)
  - Sector favorability score (0.0–1.0)
  - Sector-wide tailwinds and headwinds
  - One-sentence sector thesis, risks, assumptions, invalidation conditions
  - Does NOT compute, alter, or invent any numeric return or spread

Golden Specialist Pattern (5-stage pipeline)
---------------------------------------------
1. _validate_context(ctx)        — check current_price > 0
2. _build_metrics(ctx)           — calls sector_calculator.compute_all_sector_metrics()
3. _build_prompt(ctx, metrics)   — compact evidence block + JSON schema
4. llm.generate_structured()     — LLM qualitative synthesis
5. _build_output(input, resp, m) — typed SectorPayload in AgentOutput.raw_data

DEGRADED condition: when sector metadata is missing or unknown and < 1 sector-level metric is available.
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
    CyclicalityCategory,
    MarketContext,
    RelativeStrengthRank,
    SectorAttractiveness,
    SectorMetricRecord,
    SectorPayload,
    SectorRegime,
    _SectorLLMResponse,
)
from backend.infrastructure.llm import LLMClient, LLMClientError, LLMParseError
from backend.specialists.sector_calculator import (
    SectorMetric,
    compute_all_sector_metrics,
    extract_sector_metadata,
)

logger = logging.getLogger(__name__)

# Minimum available sector metrics/metadata required to proceed to full LLM analysis
MIN_AVAILABLE_SECTOR_METRICS = 1

_SYSTEM_PROMPT = """\
You are a specialist sector analyst operating within a systematic trading research system.

Rules you MUST follow:
1. Analyze ONLY the sector environment, relative performance metrics, and market context supplied to you.
2. All numeric returns and performance spreads are AUTHORITATIVE — computed deterministically in Python.
3. You MUST NOT modify, recalculate, or contradict any supplied numeric value.
4. You MUST NOT invent, guess, or estimate missing sector returns, benchmark data, or market share numbers.
5. Clearly distinguish facts (what the returns and spreads show) from qualitative interpretation (what they mean for sector favorability).
6. Evaluate sector cyclicality and relative strength strictly from verified evidence or explicit assumptions.
7. Identify specific sector-wide tailwinds, headwinds, and structural risks.
8. Always provide at least one concrete invalidation condition.
9. Return ONLY valid JSON matching the required schema — no markdown, no prose wrapper.
10. Do NOT produce hidden chain-of-thought reasoning.
"""


class SectorSpecialist(BaseAgent):
    """
    Production sector analysis specialist.

    Depends on LLMClient for qualitative sector synthesis;
    deterministic calculations originate strictly from MarketContext / sector_calculator.py.

    Parameters
    ----------
    llm_client : LLMClient
        Injected LLM provider. Use MockLLMClient in tests.
    """

    AGENT_NAME = "SectorSpecialist"
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
        Execute the sector analysis specialist.

        Stage 1 — Validate basic context validity (current_price > 0).
        Stage 2 — Compute deterministic sector metrics from MarketContext.
        Stage 3 — Check data sufficiency (return DEGRADED if sector data is missing).
        Stage 4 — Build LLM prompt embedding verified returns & spreads.
        Stage 5 — Call LLM for qualitative synthesis.
        Stage 6 — Assemble typed AgentOutput with SectorPayload.
        """
        ctx = input_data.market_context
        logger.info(
            "[SectorSpecialist] executing symbol=%s context_id=%s",
            ctx.symbol, ctx.context_id,
        )

        # Stage 1 — Context validation
        validation_error = self._validate_context(ctx)
        if validation_error:
            return self._failure_output(
                ctx, code="INVALID_INPUT", message=validation_error
            )

        # Resolve sector data (checking both MarketContext and additional_data)
        sector_data: Dict[str, Any] = ctx.sector_data
        if not sector_data and input_data.additional_data:
            sector_data = input_data.additional_data.get("sector_data", {})

        # Extract metadata and compute deterministic metrics
        sector, industry, benchmark_symbol = extract_sector_metadata(sector_data)
        period_str = str(getattr(ctx.historical_window, "value", ctx.historical_window) or "RECENT")

        raw_metrics = compute_all_sector_metrics(
            sector_data=sector_data,
            ohlcv_historical=ctx.ohlcv_historical,
            context_id=ctx.context_id,
            data_timestamp=ctx.data_timestamp,
            period=period_str,
        )

        # Stage 3 — Data sufficiency check
        available_count = sum(1 for m in raw_metrics if m.available)
        has_sector_info = (sector != "UNKNOWN") or (industry != "UNKNOWN")

        if not has_sector_info and available_count < 2:
            logger.warning(
                "[SectorSpecialist] DEGRADED symbol=%s context_id=%s: "
                "sector metadata missing and only %d metric(s) available",
                ctx.symbol, ctx.context_id, available_count,
            )
            reason = (
                f"Sector and industry classification is unavailable in MarketContext for {ctx.symbol}. "
                "Sector return, benchmark comparison, and industry categorization require a sector data provider."
            )
            return self._degraded_output(
                ctx=ctx,
                raw_metrics=raw_metrics,
                sector=sector,
                industry=industry,
                reason=reason,
            )

        # Stage 4 — Prompt construction
        system_prompt, user_prompt = self._build_prompt(
            ctx=ctx,
            raw_metrics=raw_metrics,
            sector=sector,
            industry=industry,
            benchmark_symbol=benchmark_symbol,
            period_str=period_str,
        )

        # Stage 5 — LLM qualitative synthesis
        try:
            llm_response: _SectorLLMResponse = await self._llm.generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=_SectorLLMResponse,
            )
        except LLMParseError as exc:
            logger.warning(
                "[SectorSpecialist] LLM parse error context_id=%s: %s",
                ctx.context_id, exc,
            )
            return self._failure_output(
                ctx, code="LLM_PARSE_ERROR", message=str(exc)
            )
        except LLMClientError as exc:
            logger.error(
                "[SectorSpecialist] LLM client error context_id=%s: %s",
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
            sector=sector,
            industry=industry,
        )

    # ── Stage 1: Validation ───────────────────────────────────────────────────

    def _validate_context(self, ctx: MarketContext) -> Optional[str]:
        """Check minimal context validity."""
        if ctx.current_price <= 0:
            return f"Invalid current_price={ctx.current_price} in MarketContext."
        return None

    # ── Stage 2: Metric Conversion ────────────────────────────────────────────

    @staticmethod
    def _metrics_to_records(raw_metrics: List[SectorMetric]) -> List[SectorMetricRecord]:
        """Convert SectorMetric dataclasses to Pydantic SectorMetricRecord models."""
        return [
            SectorMetricRecord(
                metric_name=m.metric_name,
                value=m.value,
                unit=m.unit,
                period=m.period,
                source=m.source,
                calculation_method=m.calculation_method,
                inputs=m.inputs,
                available=m.available,
                unavailable_reason=m.unavailable_reason,
                context_id=m.context_id,
                data_timestamp=m.data_timestamp,
            )
            for m in raw_metrics
        ]

    # ── Stage 4: Prompt Construction ──────────────────────────────────────────

    def _build_prompt(
        self,
        ctx: MarketContext,
        raw_metrics: List[SectorMetric],
        sector: str,
        industry: str,
        benchmark_symbol: str,
        period_str: str,
    ) -> Tuple[str, str]:
        """
        Build LLM prompt embedding verified sector returns and spreads.
        Available metrics are presented with exact values and formulas.
        Unavailable metrics are explicitly listed so the LLM does not hallucinate them.
        """
        avail_lines: List[str] = []
        unavail_lines: List[str] = []

        for m in raw_metrics:
            if m.available and m.value is not None:
                avail_lines.append(
                    f"  - {m.metric_name}: {m.value:+.2f}%  "
                    f"[source={m.source}, method={m.calculation_method}]"
                )
            else:
                unavail_lines.append(
                    f"  - {m.metric_name}: [UNAVAILABLE — {m.unavailable_reason}]"
                )

        schema_json = json.dumps(_SectorLLMResponse.model_json_schema(), indent=2)

        user_prompt = f"""
Perform a sector and industry analysis for {ctx.symbol}.

Market context generated at: {ctx.generated_at.isoformat()}
Market data timestamp: {ctx.data_timestamp.isoformat()}
Current share price: {ctx.current_price:.2f}
Observation period: {period_str}

=== SECTOR & INDUSTRY METADATA ===
Sector: {sector}
Industry: {industry}
Benchmark: {benchmark_symbol}

=== AUTHORITATIVE SECTOR PERFORMANCE METRICS (Python-calculated — do NOT alter or recalculate) ===
{chr(10).join(avail_lines) if avail_lines else "  [None available]"}

=== EXPLICITLY UNAVAILABLE METRICS (do NOT invent or guess values) ===
{chr(10).join(unavail_lines) if unavail_lines else "  [None]"}

Instructions:
1. Classify sector performance regime (STRONG_OUTPERFORMING, MODERATE_OUTPERFORMING, NEUTRAL, UNDERPERFORMING, LAGGING, or INDETERMINATE).
2. Assess sector attractiveness (HIGHLY_ATTRACTIVE, ATTRACTIVE, NEUTRAL, UNATTRACTIVE, HIGHLY_UNATTRACTIVE, or INDETERMINATE).
3. Classify sector cyclicality (CYCLICAL, DEFENSIVE, GROWTH, SENSITIVE, or INDETERMINATE).
4. Classify company relative strength positioning (LEADER, OUTPERFORMER, IN_LINE, UNDERPERFORMER, LAGGARD, or INDETERMINATE).
5. Assign a composite sector score from 0.0 to 1.0.
6. Provide a concise one-sentence sector investment thesis.
7. Identify specific sector tailwinds (structural drivers, regulatory support, demand expansion).
8. Identify specific sector headwinds (cost pressures, margin squeeze, macro drag).
9. List sector-specific risks.
10. List underlying assumptions.
11. List invalidation conditions for this sector thesis.

Required JSON output schema:
{schema_json}
"""
        return _SYSTEM_PROMPT, user_prompt

    # ── Stage 6: Output Assembly ──────────────────────────────────────────────

    def _build_output(
        self,
        input_data: AgentInput,
        llm_response: _SectorLLMResponse,
        raw_metrics: List[SectorMetric],
        sector: str,
        industry: str,
    ) -> AgentOutput:
        """Assemble the final SUCCESS AgentOutput with typed SectorPayload."""
        ctx = input_data.market_context
        metric_records = self._metrics_to_records(raw_metrics)

        # Build relative performance dictionary from calculated metrics
        relative_perf: Dict[str, Any] = {}
        for m in raw_metrics:
            if m.available and m.value is not None:
                relative_perf[m.metric_name] = m.value

        payload = SectorPayload(
            sector=sector,
            industry=industry,
            sector_regime=llm_response.sector_regime,
            sector_attractiveness=llm_response.sector_attractiveness,
            cyclicality=llm_response.cyclicality,
            relative_strength_rank=llm_response.relative_strength_rank,
            sector_score=llm_response.sector_score,
            relative_performance=relative_perf,
            tailwinds=llm_response.tailwinds,
            headwinds=llm_response.headwinds,
            evidence=metric_records,
            invalidation_conditions=llm_response.invalidation_conditions,
            risks=llm_response.risks,
            assumptions=llm_response.assumptions,
            conclusion=llm_response.conclusion,
            confidence=llm_response.confidence,
        )

        logger.info(
            "[SectorSpecialist] SUCCESS context_id=%s sector=%s regime=%s score=%.2f confidence=%.2f",
            ctx.context_id,
            sector,
            llm_response.sector_regime.value,
            llm_response.sector_score,
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
        raw_metrics: List[SectorMetric],
        sector: str,
        industry: str,
        reason: str,
    ) -> AgentOutput:
        """Produce a structured DEGRADED AgentOutput when sector data is missing."""
        metric_records = self._metrics_to_records(raw_metrics)

        payload = SectorPayload(
            sector=sector,
            industry=industry,
            sector_regime=SectorRegime.INDETERMINATE,
            sector_attractiveness=SectorAttractiveness.INDETERMINATE,
            cyclicality=CyclicalityCategory.INDETERMINATE,
            relative_strength_rank=RelativeStrengthRank.INDETERMINATE,
            sector_score=0.0,
            relative_performance={},
            tailwinds=[],
            headwinds=[],
            evidence=metric_records,
            invalidation_conditions=["Sector and benchmark performance data becomes available"],
            risks=["Cannot assess industry tailwinds, sector rotation, or relative strength without sector data"],
            assumptions=["Sector analysis deferred until sector reference provider is integrated"],
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
            conclusion="Sector analysis failed.",
            error=AgentError(code=code, message=message),
        )
