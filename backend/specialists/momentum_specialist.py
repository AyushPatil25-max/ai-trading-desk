"""
MomentumSpecialist — Phase 3.3

Follows the Golden Specialist Pattern established by TechnicalSpecialist.

Separation of concerns
-----------------------
DETERMINISTIC (Python):
  - Extracts EMA20, EMA50, RSI, 20-day high, current price from MarketContext.
  - Computes exact mathematical momentum relationships (price vs EMA distance %,
    EMA20/50 spread %, RSI regime, distance from 20-day high).
  - Explicitly marks unavailable indicators as available=False.
  - These values are authoritative; the LLM does NOT calculate or alter numbers.

AI INTERPRETATION (LLM):
  - Interprets momentum direction, momentum strength, acceleration/persistence,
    confirmation, risks, assumptions, invalidation conditions, and confidence.
  - Does NOT invent missing numerical data or change supplied values.

Five-stage execution pipeline:
1. _validate_context(ctx)      → checks required data presence
2. _build_evidence(ctx)        → builds deterministic MomentumIndicatorEvidence list
3. _build_prompt(ctx, ev)      → builds system & user prompts injecting evidence
4. llm.generate_structured()   → generates _MomentumLLMResponse
5. _build_output(...)          → composes final AgentOutput with MomentumPayload
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
    MomentumIndicatorEvidence,
    MomentumPayload,
    _MomentumLLMResponse,
)
from backend.infrastructure.llm import LLMClient, LLMClientError, LLMParseError

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a specialist momentum and trend velocity analyst operating within a systematic trading research system.

Rules you MUST follow:
1. Analyze ONLY the momentum indicator values and market context supplied to you.
2. Do NOT invent, recalculate, or substitute numerical momentum values.
3. Do NOT produce hidden chain-of-thought reasoning.
4. Clearly separate evidence (what the numbers show) from interpretation (what the velocity implies).
5. Explicitly state uncertainty when momentum signals conflict (e.g., strong RSI but negative moving average spread).
6. Always provide at least one concrete invalidation condition.
7. Return ONLY valid JSON matching the required schema — no markdown, no conversational text.
"""


class MomentumSpecialist(BaseAgent):
    """
    Production momentum analysis specialist.

    Depends on LLMClient for qualitative interpretation and thesis synthesis;
    deterministic momentum computations originate strictly from MarketContext.

    Parameters
    ----------
    llm_client : LLMClient
        Injected LLM provider.
    """

    AGENT_NAME = "MomentumSpecialist"
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
        Execute the momentum analysis specialist.
        """
        ctx = input_data.market_context
        logger.info(
            "[MomentumSpecialist] executing symbol=%s context_id=%s",
            ctx.symbol, ctx.context_id,
        )

        # Stage 1 — Input validation
        validation_error = self._validate_context(ctx)
        if validation_error:
            return self._failure_output(
                ctx, code="INVALID_INPUT", message=validation_error
            )

        # Stage 2 — Deterministic evidence assembly (Python only)
        evidence = self._build_evidence(ctx)

        # Stage 3 — Prompt construction
        system_prompt, user_prompt = self._build_prompt(ctx, evidence)

        # Stage 4 — LLM interpretation
        try:
            llm_response: _MomentumLLMResponse = await self._llm.generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=_MomentumLLMResponse,
            )
        except LLMParseError as exc:
            logger.warning(
                "[MomentumSpecialist] LLM parse error context_id=%s: %s",
                ctx.context_id, exc,
            )
            return self._failure_output(
                ctx, code="LLM_PARSE_ERROR", message=str(exc)
            )
        except LLMClientError as exc:
            logger.error(
                "[MomentumSpecialist] LLM client error context_id=%s: %s",
                ctx.context_id, exc,
            )
            return self._failure_output(
                ctx, code="LLM_CLIENT_ERROR", message=str(exc)
            )

        # Stage 5 — Output assembly
        return self._build_output(input_data, llm_response, evidence)

    # ── Stage 1: Validation ───────────────────────────────────────────────────

    def _validate_context(self, ctx: MarketContext) -> str | None:
        """Validate that context contains minimal technical data required for momentum."""
        indicators = ctx.technical_indicators
        if not indicators:
            return "MarketContext.technical_indicators is empty — cannot compute momentum evidence."
        if ctx.current_price <= 0:
            return f"Invalid current_price={ctx.current_price} in MarketContext."
        return None

    # ── Stage 2: Deterministic Evidence Assembly ─────────────────────────────

    def _build_evidence(self, ctx: MarketContext) -> List[MomentumIndicatorEvidence]:
        """
        Build deterministic momentum evidence from MarketContext.
        Values are calculated precisely using Python and cannot be overridden by the LLM.
        """
        ind = ctx.technical_indicators
        price = ctx.current_price
        evidence: List[MomentumIndicatorEvidence] = []

        # 1. Price vs EMA20 Momentum Velocity
        ema20 = ind.get("ema20")
        if ema20 is not None:
            ema20_f = float(ema20)
            dist_pct = ((price - ema20_f) / ema20_f) * 100.0
            pos = "above" if dist_pct >= 0 else "below"
            evidence.append(MomentumIndicatorEvidence(
                name="Price_vs_EMA20",
                value=round(dist_pct, 2),
                available=True,
                interpretation=f"Price is {abs(dist_pct):.2f}% {pos} short-term momentum baseline (EMA20={ema20_f:.2f})"
            ))
        else:
            evidence.append(MomentumIndicatorEvidence(
                name="Price_vs_EMA20",
                value=None,
                available=False,
                interpretation="EMA20 not available in MarketContext"
            ))

        # 2. Price vs EMA50 Trend Baseline
        ema50 = ind.get("ema50")
        if ema50 is not None:
            ema50_f = float(ema50)
            dist_pct = ((price - ema50_f) / ema50_f) * 100.0
            pos = "above" if dist_pct >= 0 else "below"
            evidence.append(MomentumIndicatorEvidence(
                name="Price_vs_EMA50",
                value=round(dist_pct, 2),
                available=True,
                interpretation=f"Price is {abs(dist_pct):.2f}% {pos} medium-term momentum baseline (EMA50={ema50_f:.2f})"
            ))
        else:
            evidence.append(MomentumIndicatorEvidence(
                name="Price_vs_EMA50",
                value=None,
                available=False,
                interpretation="EMA50 not available in MarketContext"
            ))

        # 3. Moving Average Velocity Spread (EMA20 vs EMA50)
        if ema20 is not None and ema50 is not None:
            ema20_f = float(ema20)
            ema50_f = float(ema50)
            spread_pct = ((ema20_f - ema50_f) / ema50_f) * 100.0
            state = "bullish expansion" if spread_pct > 0 else "bearish contraction"
            evidence.append(MomentumIndicatorEvidence(
                name="EMA_Spread_20_50",
                value=round(spread_pct, 2),
                available=True,
                interpretation=f"EMA 20/50 spread is {spread_pct:+.2f}% indicating {state}"
            ))

        # 4. RSI14 Momentum Oscillator
        rsi = ind.get("rsi")
        if rsi is not None:
            rsi_f = float(rsi)
            if rsi_f >= 70.0:
                regime = "strong positive momentum (overbought zone)"
            elif rsi_f >= 50.0:
                regime = "constructive positive momentum (bullish zone)"
            elif rsi_f >= 30.0:
                regime = "negative momentum (bearish zone)"
            else:
                regime = "strong negative momentum (oversold zone)"
            evidence.append(MomentumIndicatorEvidence(
                name="RSI14",
                value=round(rsi_f, 2),
                available=True,
                interpretation=f"RSI={rsi_f:.2f} — {regime}"
            ))
        else:
            evidence.append(MomentumIndicatorEvidence(
                name="RSI14",
                value=None,
                available=False,
                interpretation="RSI14 not available in MarketContext"
            ))

        # 5. Distance from 20-day High (High Proximity Momentum)
        high_20d = ind.get("20_day_high")
        if high_20d is not None:
            high_20d_f = float(high_20d)
            pct_from_high = ((price - high_20d_f) / high_20d_f) * 100.0
            evidence.append(MomentumIndicatorEvidence(
                name="Distance_From_20D_High",
                value=round(pct_from_high, 2),
                available=True,
                interpretation=f"Price is {pct_from_high:+.2f}% relative to 20-day high ({high_20d_f:.2f})"
            ))
        else:
            evidence.append(MomentumIndicatorEvidence(
                name="Distance_From_20D_High",
                value=None,
                available=False,
                interpretation="20-day high not available in MarketContext"
            ))

        # 6. Explicitly report uncalculated advanced momentum indicators as unavailable
        evidence.append(MomentumIndicatorEvidence(
            name="MACD_Histogram",
            value=None,
            available=False,
            interpretation="MACD not provided in baseline MarketContext"
        ))

        return evidence

    # ── Stage 3: Prompt Construction ──────────────────────────────────────────

    def _build_prompt(
        self,
        ctx: MarketContext,
        evidence: List[MomentumIndicatorEvidence],
    ) -> Tuple[str, str]:
        """
        Build system and user prompts injecting deterministic momentum evidence.
        """
        evidence_lines = []
        for ev in evidence:
            if ev.available and ev.value is not None:
                evidence_lines.append(f"  - {ev.name}: {ev.value} ({ev.interpretation})")
            else:
                evidence_lines.append(f"  - {ev.name}: [UNAVAILABLE] ({ev.interpretation})")

        evidence_block = "\n".join(evidence_lines)
        schema_json = json.dumps(_MomentumLLMResponse.model_json_schema(), indent=2)

        user_prompt = f"""
Perform a momentum and trend velocity analysis of {ctx.symbol}.

Market context generated at: {ctx.generated_at.isoformat()}
Data timestamp: {ctx.data_timestamp.isoformat()}
Current Price: {ctx.current_price:.2f}

Deterministic Momentum Evidence (do NOT alter, invent, or recalculate these values):
{evidence_block}

Instructions:
- Evaluate momentum direction (BULLISH, BEARISH, or NEUTRAL).
- Evaluate momentum strength (STRONG, MODERATE, or WEAK).
- Set confirmation=true if velocity and trend baseline indicators agree.
- Provide a concise one-sentence conclusion summarizing the momentum thesis.
- List specific invalidation conditions where momentum would break down.
- State potential momentum risks (e.g. overextension, mean reversion, negative divergence).
- State key assumptions.
- If an indicator is marked [UNAVAILABLE], do not invent its numerical value.

Required JSON output schema:
{schema_json}
"""
        return _SYSTEM_PROMPT, user_prompt

    # ── Stage 5: Output Assembly ──────────────────────────────────────────────

    def _build_output(
        self,
        input_data: AgentInput,
        llm_response: _MomentumLLMResponse,
        evidence: List[MomentumIndicatorEvidence],
    ) -> AgentOutput:
        """
        Assemble the final AgentOutput with typed MomentumPayload.
        """
        ctx = input_data.market_context

        payload = MomentumPayload(
            momentum_direction=llm_response.momentum_direction,
            momentum_strength=llm_response.momentum_strength,
            confirmation=llm_response.confirmation,
            evidence=evidence,
            invalidation_conditions=llm_response.invalidation_conditions,
            risks=llm_response.risks,
            assumptions=llm_response.assumptions,
        )

        logger.info(
            "[MomentumSpecialist] SUCCESS context_id=%s direction=%s strength=%s confidence=%.2f",
            ctx.context_id,
            llm_response.momentum_direction.value,
            llm_response.momentum_strength.value,
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
            conclusion="Momentum analysis failed.",
            error=AgentError(code=code, message=message),
        )
