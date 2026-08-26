"""
NewsSpecialist — Phase 3.9

Production news and sentiment specialist following the Golden Specialist Pattern.

Separation of concerns
-----------------------
DETERMINISTIC (Python — news_calculator.py):
  - Ingests articles from MarketContext.news_data
  - Normalizes timestamps and classifies recency (VERY_RECENT, RECENT, OLDER, STALE, UNKNOWN)
  - Classifies source credibility tier (OFFICIAL, REGULATORY, REPUTABLE_MEDIA, SECONDARY, UNKNOWN)
  - Classifies corporate/macro event types (EARNINGS, GUIDANCE, M&A, PRODUCT, etc.)
  - Evaluates rule-based importance (HIGH, MEDIUM, LOW)
  - Deduplicates repeated media coverage of the same underlying event
  - Calculates exact deterministic counts (total_articles, unique_events_count, high_importance_count, recent_count)
  - Full provenance tracking (context_id, data_timestamp, duplicate group IDs)

AI INTERPRETATION (LLM — _NewsLLMResponse):
  - Synthesizes news regime (BULLISH, BEARISH, NEUTRAL, MIXED, INDETERMINATE)
  - Assesses overall qualitative sentiment (POSITIVE, NEGATIVE, NEUTRAL, MIXED, UNCERTAIN, INDETERMINATE)
  - Identifies tangible catalysts and news headwinds
  - Synthesizes news-specific risks, assumptions, and invalidation conditions
  - Generates one-sentence news thesis
  - Does NOT invent headlines, dates, sources, or numerical counts

Golden Specialist Pattern (5-stage pipeline)
---------------------------------------------
1. _validate_context(ctx)        — check current_price > 0, context validity
2. _build_evidence(ctx)          — calls NewsCalculator.process_news_data()
3. _build_prompt(ctx, ev, stats) — compact structured evidence prompt
4. llm.generate_structured()     — LLM qualitative synthesis
5. _build_output(input, resp, ev)— typed NewsPayload in AgentOutput.raw_data

DEGRADED condition: when news_data is missing, empty, or contains 0 valid articles.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from backend.domain.agents import BaseAgent
from backend.domain.schemas import (
    AgentError,
    AgentEvidence,
    AgentInput,
    AgentOutput,
    AgentState,
    MarketContext,
    NewsArticleEvidence,
    NewsEventType,
    NewsImportance,
    NewsPayload,
    NewsRecency,
    NewsRegime,
    NewsSentiment,
    NewsSourceQuality,
    _NewsLLMResponse,
)
from backend.infrastructure.llm import LLMClient, LLMClientError, LLMParseError
from backend.specialists.news_calculator import NewsCalculator

logger = logging.getLogger(__name__)

# Minimum available articles required to proceed to full LLM analysis
MIN_REQUIRED_ARTICLES = 1

_SYSTEM_PROMPT = """\
You are a specialist news and sentiment analyst operating within a systematic trading research system.

Rules you MUST follow:
1. Analyze ONLY the supplied news events, recency, source quality, and market context.
2. All article headlines, sources, dates, and event counts are AUTHORITATIVE facts computed in Python.
3. Do NOT invent, hallucinate, or assume any unmentioned news stories, press releases, or earnings reports.
4. Distinguish primary/regulatory disclosures from secondary commentary.
5. Do NOT treat multiple duplicate articles covering the same event as independent positive/negative signals.
6. Clearly separate facts from your qualitative sentiment interpretation.
7. Always provide at least one concrete invalidation condition for your thesis.
8. Return ONLY valid JSON matching the required schema — no markdown, no conversational prose.
"""


class NewsSpecialist(BaseAgent):
    """
    Specialist agent that analyzes corporate news, filings, media coverage,
    and market sentiment for a specific ticker.
    """

    AGENT_NAME = "NewsSpecialist"
    AGENT_VERSION = "1.0.0"

    def __init__(self, llm_client: Optional[LLMClient] = None) -> None:
        self._llm = llm_client

    @property
    def name(self) -> str:
        return self.AGENT_NAME

    @property
    def version(self) -> str:
        return self.AGENT_VERSION

    # ── Public Entry Point ───────────────────────────────────────────────────

    async def execute(self, input_data: AgentInput) -> AgentOutput:
        """
        Execute the news & sentiment specialist workflow.
        """
        market_context = input_data.market_context
        context_id = market_context.context_id
        symbol = market_context.symbol
        data_ts = market_context.data_timestamp

        # Step 1 — Validate Input
        if not self._validate_context(market_context):
            logger.warning(
                "[%s] INVALID INPUT symbol=%s context_id=%s current_price=%s",
                self.name, symbol, context_id, getattr(market_context, "current_price", None),
            )
            return self._build_failed_output(
                error_code="INVALID_INPUT",
                error_message=f"Invalid market context: current_price must be > 0 (got {market_context.current_price})",
                data_timestamp=data_ts,
            )

        # Step 2 — Deterministic Evidence Computation
        try:
            articles, stats = self._build_evidence(market_context)
        except Exception as exc:
            logger.exception("[%s] Error in deterministic calculation: %s", self.name, exc)
            return self._build_failed_output(
                error_code="CALCULATION_ERROR",
                error_message=f"NewsCalculator failed: {str(exc)}",
                data_timestamp=data_ts,
            )

        # Degraded check: If no articles available
        if stats["total_articles"] < MIN_REQUIRED_ARTICLES:
            logger.info(
                "[%s] DEGRADED symbol=%s context_id=%s: 0 news articles available in MarketContext.news_data",
                self.name, symbol, context_id,
            )
            return self._build_degraded_output(
                reason=f"No news data or articles available in MarketContext for {symbol}.",
                data_timestamp=data_ts,
                articles=articles,
                stats=stats,
            )

        # Step 3 — Build Compact Prompt
        system_prompt, user_prompt = self._build_prompt(market_context, articles, stats)

        # Step 4 — LLM Qualitative Synthesis
        if not self._llm:
            return self._build_failed_output(
                error_code="LLM_CLIENT_MISSING",
                error_message="No LLMClient configured for NewsSpecialist.",
                data_timestamp=data_ts,
            )

        try:
            llm_response: _NewsLLMResponse = await self._llm.generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=_NewsLLMResponse,
            )
        except LLMParseError as exc:
            logger.warning("[%s] LLM parse error context_id=%s: %s", self.name, context_id, exc)
            return self._build_failed_output(
                error_code="LLM_PARSE_ERROR",
                error_message=f"Failed to parse LLM response into _NewsLLMResponse schema: {exc}",
                data_timestamp=data_ts,
            )
        except LLMClientError as exc:
            logger.warning("[%s] LLM client error context_id=%s: %s", self.name, context_id, exc)
            return self._build_failed_output(
                error_code="LLM_CLIENT_ERROR",
                error_message=f"LLM client error during news synthesis: {exc}",
                data_timestamp=data_ts,
            )
        except Exception as exc:
            logger.exception("[%s] Unexpected LLM failure context_id=%s: %s", self.name, context_id, exc)
            return self._build_failed_output(
                error_code="LLM_ERROR",
                error_message=f"Unexpected error during LLM generation: {exc}",
                data_timestamp=data_ts,
            )

        # Step 5 — Assemble Output
        return self._build_output(
            input_data=input_data,
            llm_data=llm_response,
            articles=articles,
            stats=stats,
        )

    # ── Pipeline Step Implementations ────────────────────────────────────────

    def _validate_context(self, context: MarketContext) -> bool:
        """Validate context meets minimum requirements for execution."""
        if context is None:
            return False
        if not hasattr(context, "current_price") or context.current_price is None or context.current_price <= 0:
            return False
        if not hasattr(context, "news_data"):
            return False
        return True

    def _build_evidence(self, context: MarketContext) -> Tuple[List[NewsArticleEvidence], Dict[str, int]]:
        """Run deterministic news calculator."""
        return NewsCalculator.process_news_data(context)

    def _build_prompt(
        self,
        context: MarketContext,
        articles: List[NewsArticleEvidence],
        stats: Dict[str, int],
    ) -> Tuple[str, str]:
        """Construct compact system and user prompts."""
        # Focus on unique (non-duplicate) articles to save tokens and preserve signal integrity
        unique_articles = [a for a in articles if not a.is_duplicate]
        
        # Sort by importance (HIGH -> MEDIUM -> LOW) and recency (VERY_RECENT -> RECENT)
        importance_rank = {NewsImportance.HIGH: 0, NewsImportance.MEDIUM: 1, NewsImportance.LOW: 2, NewsImportance.UNKNOWN: 3}
        recency_rank = {NewsRecency.VERY_RECENT: 0, NewsRecency.RECENT: 1, NewsRecency.OLDER: 2, NewsRecency.STALE: 3, NewsRecency.UNKNOWN: 4}
        
        sorted_articles = sorted(
            unique_articles,
            key=lambda a: (importance_rank.get(a.importance, 3), recency_rank.get(a.recency, 4))
        )

        compact_events = []
        for a in sorted_articles[:15]:  # limit to top 15 most material events
            item = {
                "headline": a.headline,
                "source": a.source,
                "source_quality": a.source_quality.value,
                "event_type": a.event_type.value,
                "importance": a.importance.value,
                "recency": a.recency.value,
                "published_at": a.published_at,
            }
            if a.summary:
                item["summary"] = a.summary[:200]
            compact_events.append(item)

        user_content = {
            "symbol": context.symbol,
            "current_price": context.current_price,
            "data_timestamp": context.data_timestamp.isoformat(),
            "summary_statistics": stats,
            "curated_events": compact_events,
        }

        user_prompt = f"""
Analyze the following corporate news, event disclosures, and media coverage for {context.symbol}:

```json
{json.dumps(user_content, indent=2)}
```

Synthesize the news evidence into:
1. Overall news regime: BULLISH, BEARISH, NEUTRAL, MIXED, or INDETERMINATE.
2. Overall sentiment: POSITIVE, NEGATIVE, NEUTRAL, MIXED, UNCERTAIN, or INDETERMINATE.
3. Catalysts: tangible positive news drivers.
4. Headwinds: tangible negative news drivers or risks.
5. Risks: news-specific operational, regulatory, or headline risks.
6. Assumptions: assumptions underlying your qualitative assessment.
7. Invalidation conditions: explicit events or disclosures that would invalidate this thesis.
8. Conclusion: concise one-sentence investment synthesis grounded strictly in the supplied events.
9. Confidence: confidence score (0.0 to 1.0) based on news materiality, recency, and source credibility.
"""
        return _SYSTEM_PROMPT, user_prompt.strip()

    def _build_output(
        self,
        input_data: AgentInput,
        llm_data: _NewsLLMResponse,
        articles: List[NewsArticleEvidence],
        stats: Dict[str, int],
    ) -> AgentOutput:
        """Assemble structured SUCCESS output."""
        market_context = input_data.market_context

        payload = NewsPayload(
            news_regime=llm_data.news_regime,
            overall_sentiment=llm_data.overall_sentiment,
            total_articles=stats["total_articles"],
            unique_events_count=stats["unique_events_count"],
            high_importance_count=stats["high_importance_count"],
            recent_count=stats["recent_count"],
            articles=articles,
            catalysts=llm_data.catalysts,
            headwinds=llm_data.headwinds,
            risks=llm_data.risks,
            assumptions=llm_data.assumptions,
            invalidation_conditions=llm_data.invalidation_conditions,
            conclusion=llm_data.conclusion,
            confidence=llm_data.confidence,
        )

        agent_evidence = [
            AgentEvidence(
                source=a.source,
                content=f"[{a.event_type.value}|{a.importance.value}|{a.recency.value}] {a.headline}",
            )
            for a in articles if not a.is_duplicate
        ]

        return AgentOutput(
            agent_name=self.name,
            version=self.version,
            model=getattr(self._llm, "model_name", "unknown") if self._llm else "unknown",
            status=AgentState.SUCCESS,
            data_timestamp=market_context.data_timestamp,
            confidence=llm_data.confidence,
            conclusion=llm_data.conclusion,
            evidence=agent_evidence,
            risks=llm_data.risks,
            assumptions=llm_data.assumptions,
            invalidation_conditions=llm_data.invalidation_conditions,
            raw_data=payload.model_dump(),
        )

    def _build_degraded_output(
        self,
        reason: str,
        data_timestamp: datetime,
        articles: List[NewsArticleEvidence],
        stats: Dict[str, int],
    ) -> AgentOutput:
        """Assemble structured DEGRADED output when news data is unavailable."""
        payload = NewsPayload(
            news_regime=NewsRegime.INDETERMINATE,
            overall_sentiment=NewsSentiment.INDETERMINATE,
            total_articles=stats.get("total_articles", 0),
            unique_events_count=stats.get("unique_events_count", 0),
            high_importance_count=stats.get("high_importance_count", 0),
            recent_count=stats.get("recent_count", 0),
            articles=articles,
            catalysts=[],
            headwinds=[],
            risks=["Missing news/sentiment data"],
            assumptions=[],
            invalidation_conditions=[],
            conclusion=reason,
            confidence=0.0,
        )

        return AgentOutput(
            agent_name=self.name,
            version=self.version,
            model=getattr(self._llm, "model_name", "unknown") if self._llm else "unknown",
            status=AgentState.DEGRADED,
            data_timestamp=data_timestamp,
            confidence=0.0,
            conclusion=reason,
            evidence=[],
            risks=["Missing news/sentiment data"],
            raw_data=payload.model_dump(),
        )

    def _build_failed_output(
        self,
        error_code: str,
        error_message: str,
        data_timestamp: datetime,
    ) -> AgentOutput:
        """Assemble structured FAILED output for unrecoverable errors."""
        return AgentOutput(
            agent_name=self.name,
            version=self.version,
            model=getattr(self._llm, "model_name", "unknown") if self._llm else "unknown",
            status=AgentState.FAILED,
            data_timestamp=data_timestamp,
            confidence=0.0,
            conclusion=f"News specialist failed: {error_message}",
            error=AgentError(code=error_code, message=error_message),
            evidence=[],
            raw_data=None,
        )
