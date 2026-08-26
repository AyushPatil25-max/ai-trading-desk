"""
TechnicalSpecialist — Phase 3.2

First production-style specialist following the Golden Specialist Pattern.

Separation of concerns
-----------------------
DETERMINISTIC (Python):
  - Reads EMA20, EMA50, RSI, 20-day high, current price from MarketContext.
  - Builds TechnicalIndicatorEvidence items with exact numeric values.
  - These values are the source of truth; the LLM does NOT recalculate them.

AI INTERPRETATION (LLM):
  - Receives the indicator values in the prompt.
  - Returns trend direction, setup type, conviction score, confirmation,
    conclusion, risks, assumptions, and invalidation conditions.
  - Must NOT claim different numeric values than what was supplied.

Golden Specialist Pattern (for future agents to follow)
--------------------------------------------------------
1. _build_evidence(ctx)     → List[TechnicalIndicatorEvidence]
2. _build_prompt(ctx, ev)   → (system_prompt, user_prompt)
3. llm.generate_structured(system, user, _TechnicalLLMResponse)
4. _build_output(input, llm_resp, evidence) → AgentOutput
"""

import json
import logging
from datetime import datetime
from typing import List, Tuple

from backend.domain.agents import BaseAgent
from backend.domain.schemas import (
    AgentError,
    AgentInput,
    AgentOutput,
    AgentState,
    MarketContext,
    TechnicalIndicatorEvidence,
    TechnicalPayload,
    _TechnicalLLMResponse,
)
from backend.infrastructure.llm import LLMClient, LLMClientError, LLMParseError

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a specialist technical analyst operating within a systematic trading research system.

Rules you MUST follow:
1. Analyze ONLY the indicator values and market context supplied to you.
2. Do NOT invent, recalculate, or substitute numerical indicator values.
3. Do NOT produce hidden chain-of-thought reasoning.
4. Clearly separate evidence (what the data shows) from interpretation (what it means).
5. Explicitly state uncertainty where indicators are conflicting.
6. Always provide at least one invalidation condition.
7. Return ONLY valid JSON matching the required schema — no prose, no markdown.
"""


class TechnicalSpecialist(BaseAgent):
    """
    Production technical analysis specialist.

    Depends on LLMClient for interpretation; deterministic calculations
    are supplied via MarketContext.

    Parameters
    ----------
    llm_client : LLMClient
        Injected LLM provider. Use MockLLMClient in tests.
    model_version : str
        Reported in AgentOutput.version for traceability.
    """

    AGENT_NAME = "TechnicalSpecialist"
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
        Execute the technical analysis specialist.

        Step 1 — Validate input has required technical data.
        Step 2 — Build deterministic evidence from MarketContext.
        Step 3 — Build LLM prompt embedding those values.
        Step 4 — Call LLM for interpretation.
        Step 5 — Assemble and return structured AgentOutput.
        """
        ctx = input_data.market_context
        logger.info(
            "[TechnicalSpecialist] executing symbol=%s context_id=%s",
            ctx.symbol, ctx.context_id,
        )

        # Step 1 — Input validation
        validation_error = self._validate_context(ctx)
        if validation_error:
            return self._failure_output(
                ctx, code="INVALID_INPUT", message=validation_error
            )

        # Step 2 — Deterministic evidence assembly (no LLM involved)
        evidence = self._build_evidence(ctx)

        # Step 3 — Prompt construction
        system_prompt, user_prompt = self._build_prompt(ctx, evidence)

        # Step 4 — LLM interpretation
        try:
            llm_response: _TechnicalLLMResponse = await self._llm.generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=_TechnicalLLMResponse,
            )
        except LLMParseError as exc:
            logger.warning(
                "[TechnicalSpecialist] LLM parse error context_id=%s: %s",
                ctx.context_id, exc,
            )
            return self._failure_output(
                ctx, code="LLM_PARSE_ERROR", message=str(exc)
            )
        except LLMClientError as exc:
            logger.error(
                "[TechnicalSpecialist] LLM client error context_id=%s: %s",
                ctx.context_id, exc,
            )
            return self._failure_output(
                ctx, code="LLM_CLIENT_ERROR", message=str(exc)
            )

        # Step 5 — Build structured output
        return self._build_output(input_data, llm_response, evidence)

    # ── Step 2: Deterministic evidence assembly ───────────────────────────────

    def _validate_context(self, ctx: MarketContext) -> str | None:
        """Return an error string if required data is missing, else None."""
        indicators = ctx.technical_indicators
        if not indicators:
            return "MarketContext.technical_indicators is empty — cannot perform technical analysis."
        if ctx.current_price <= 0:
            return f"Invalid current_price={ctx.current_price} in MarketContext."
        return None

    def _build_evidence(self, ctx: MarketContext) -> List[TechnicalIndicatorEvidence]:
        """
        Extract exact numeric indicator values from MarketContext.

        These become the AUTHORITATIVE source of truth.
        The LLM will interpret them — it will not recalculate or replace them.
        """
        ind = ctx.technical_indicators
        price = ctx.current_price
        evidence: List[TechnicalIndicatorEvidence] = []

        # Current price
        evidence.append(TechnicalIndicatorEvidence(
            name="CurrentPrice",
            value=price,
            interpretation="placeholder",  # replaced post-LLM; value is authoritative
        ))

        # EMA20
        ema20 = ind.get("ema20")
        if ema20 is not None:
            rel = "above" if price > ema20 else "below"
            evidence.append(TechnicalIndicatorEvidence(
                name="EMA20",
                value=float(ema20),
                interpretation=f"Price is {rel} EMA20 ({ema20:.2f})",
            ))

        # EMA50
        ema50 = ind.get("ema50")
        if ema50 is not None:
            rel = "above" if price > ema50 else "below"
            evidence.append(TechnicalIndicatorEvidence(
                name="EMA50",
                value=float(ema50),
                interpretation=f"Price is {rel} EMA50 ({ema50:.2f})",
            ))

        # RSI
        rsi = ind.get("rsi")
        if rsi is not None:
            rsi_f = float(rsi)
            if rsi_f >= 70:
                regime = "overbought"
            elif rsi_f <= 30:
                regime = "oversold"
            else:
                regime = "neutral"
            evidence.append(TechnicalIndicatorEvidence(
                name="RSI14",
                value=rsi_f,
                interpretation=f"RSI={rsi_f:.1f} — {regime} territory",
            ))

        # 20-day high
        high_20d = ind.get("20_day_high")
        if high_20d is not None:
            pct_from_high = ((price - float(high_20d)) / float(high_20d)) * 100
            proximity = f"{pct_from_high:+.1f}% from 20-day high"
            evidence.append(TechnicalIndicatorEvidence(
                name="20DayHigh",
                value=float(high_20d),
                interpretation=proximity,
            ))

        return evidence

    # ── Step 3: Prompt construction ───────────────────────────────────────────

    def _build_prompt(
        self,
        ctx: MarketContext,
        evidence: List[TechnicalIndicatorEvidence],
    ) -> Tuple[str, str]:
        """
        Build system + user prompts.

        The prompt embeds exact numeric values from the deterministic evidence.
        The LLM is asked to interpret — not compute — those values.
        """
        indicators_block = "\n".join(
            f"  - {ev.name}: {ev.value}  ({ev.interpretation})"
            for ev in evidence
        )
        schema_json = json.dumps(_TechnicalLLMResponse.model_json_schema(), indent=2)

        user_prompt = f"""
Perform a technical analysis of {ctx.symbol}.

Market context generated at: {ctx.generated_at.isoformat()}
Data timestamp: {ctx.data_timestamp.isoformat()}

Confirmed indicator values (do NOT recalculate or substitute these):
{indicators_block}

Instructions:
- Interpret the trend based on EMA20/EMA50 crossover and price position.
- Identify the trading setup based on the confirmed data.
- Assign a conviction score 1.0–10.0 reflecting indicator alignment.
- Set confirmation=true only if multiple indicators agree on direction.
- Provide a concise one-sentence conclusion.
- List at least one invalidation condition.
- State uncertainty if indicators are conflicting.
- Do NOT invent values not present in the supplied data.

Required JSON output schema:
{schema_json}
"""
        return _SYSTEM_PROMPT, user_prompt

    # ── Step 5: Output assembly ───────────────────────────────────────────────

    def _build_output(
        self,
        input_data: AgentInput,
        llm_response: _TechnicalLLMResponse,
        evidence: List[TechnicalIndicatorEvidence],
    ) -> AgentOutput:
        """
        Assemble the final AgentOutput.

        Numeric values in the payload originate from the deterministic evidence;
        trend/setup/conclusion/risks come from the LLM response.
        """
        ctx = input_data.market_context

        payload = TechnicalPayload(
            trend=llm_response.trend,
            setup=llm_response.setup,
            technical_score=llm_response.technical_score,
            confirmation=llm_response.confirmation,
            evidence=evidence,
            invalidation_conditions=llm_response.invalidation_conditions,
            risks=llm_response.risks,
            assumptions=llm_response.assumptions,
        )

        logger.info(
            "[TechnicalSpecialist] SUCCESS context_id=%s trend=%s score=%.1f confidence=%.2f",
            ctx.context_id,
            llm_response.trend.value,
            llm_response.technical_score,
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
            evidence=[],          # AgentEvidence list kept empty; full detail in raw_data
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
            conclusion="Technical analysis failed.",
            error=AgentError(code=code, message=message),
        )
