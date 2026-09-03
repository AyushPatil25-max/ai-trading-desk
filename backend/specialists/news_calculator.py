"""
news_calculator.py — Phase 3.9 & Phase 3D Indian News + Regulatory Filings Data Layer

Pure Python deterministic news normalization, recency classification,
source quality grading, event classification, deduplication, materiality scoring,
security identification, and summary statistics.
Zero external network calls, zero LLM dependency.
"""

import re
import math
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from backend.domain.schemas import (
    MarketContext,
    NewsArticleEvidence,
    NewsEvent,
    NewsEventType,
    NewsImportance,
    NewsRecency,
    NewsSourceQuality,
    SourceTier,
    VerificationStatus,
    DataQuality,
)


def _parse_timestamp(ts: Any) -> Optional[datetime]:
    """Parse various timestamp representations into a timezone-aware UTC datetime."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)
    if isinstance(ts, (int, float)):
        if math.isnan(ts) or math.isinf(ts):
            return None
        try:
            # Handle milliseconds vs seconds
            if ts > 1e11:
                ts = ts / 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None
    if isinstance(ts, str):
        ts = ts.strip()
        if not ts:
            return None
        # Try standard ISO parsing
        for fmt in (
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                dt = datetime.strptime(ts.replace("Z", "+0000"), fmt if "Z" not in fmt else fmt.replace("Z", "%z"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except ValueError:
                pass
        try:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def calculate_recency(published_at_str: Optional[str], context_timestamp: datetime) -> NewsRecency:
    """
    Deterministically classify news recency relative to MarketContext.data_timestamp.
    - <= 24h: VERY_RECENT
    - <= 72h (3d): RECENT
    - <= 720h (30d): OLDER
    - > 720h: STALE
    """
    if not published_at_str:
        return NewsRecency.UNKNOWN

    pub_dt = _parse_timestamp(published_at_str)
    if not pub_dt:
        return NewsRecency.UNKNOWN

    ctx_dt = _parse_timestamp(context_timestamp)
    if not ctx_dt:
        ctx_dt = datetime.now(timezone.utc)

    diff_seconds = (ctx_dt - pub_dt).total_seconds()
    
    # Handle slight clock skew / negative diff within 1 hour
    if diff_seconds < -3600:
        # Published far into the future -> STALE/UNKNOWN
        return NewsRecency.UNKNOWN
    
    diff_hours = max(0.0, diff_seconds / 3600.0)

    if diff_hours <= 24.0:
        return NewsRecency.VERY_RECENT
    elif diff_hours <= 72.0:
        return NewsRecency.RECENT
    elif diff_hours <= 720.0:
        return NewsRecency.OLDER
    else:
        return NewsRecency.STALE


def classify_source_quality(source_name: Optional[str]) -> NewsSourceQuality:
    """Classify the credibility tier of a news publisher or disclosure source."""
    if not source_name or not isinstance(source_name, str):
        return NewsSourceQuality.UNKNOWN

    s = source_name.lower().strip()

    official_keywords = [
        "sec", "bse", "nse", "company pr", "press release", "investor relations",
        "official disclosure", "regulatory filing", "edgar", "company disclosure",
    ]
    regulatory_keywords = [
        "rbi", "sebi", "fed", "federal reserve", "uspto", "fda", "doj", "ftc",
        "cci", "treasury", "ecb", "court",
    ]
    reputable_keywords = [
        "reuters", "bloomberg", "wsj", "wall street journal", "financial times",
        "ft", "cnbc", "moneycontrol", "mint", "economic times", "business standard",
        "barron", "associated press", "dow jones", "marketwatch",
    ]
    secondary_keywords = [
        "seeking alpha", "fool", "motley fool", "benzinga", "zacks", "tipranks",
        "reddit", "twitter", "x.com", "blog", "forum", "yahoo finance", "investopedia",
    ]

    for kw in official_keywords:
        if kw in s:
            return NewsSourceQuality.OFFICIAL

    for kw in regulatory_keywords:
        if kw in s:
            return NewsSourceQuality.REGULATORY

    for kw in reputable_keywords:
        if kw in s:
            return NewsSourceQuality.REPUTABLE_MEDIA

    for kw in secondary_keywords:
        if kw in s:
            return NewsSourceQuality.SECONDARY

    return NewsSourceQuality.UNKNOWN


def classify_event_type(raw_event_type: Optional[str], headline: str, summary: str = "") -> NewsEventType:
    """Map or infer event classification deterministically."""
    if raw_event_type and isinstance(raw_event_type, str):
        norm = raw_event_type.upper().strip().replace(" ", "_").replace("-", "_").replace("&", "_AND_")
        for member in NewsEventType:
            if member.value == norm:
                return member

    text = f"{headline} {summary}".lower()

    if any(w in text for w in ["earnings", "q1", "q2", "q3", "q4", "quarterly results", "eps beat", "eps miss", "net profit", "financial results"]):
        return NewsEventType.EARNINGS
    if any(w in text for w in ["guidance", "revenue outlook", "profit forecast", "lowers guidance", "raises guidance"]):
        return NewsEventType.GUIDANCE
    if any(w in text for w in ["ceo", "cfo", "appoints", "resigns", "executive", "board of directors", "management change"]):
        return NewsEventType.MANAGEMENT
    if any(w in text for w in ["probe", "investigation", "sebi", "sec violation", "penalty", "compliance", "regulatory"]):
        return NewsEventType.REGULATORY
    if any(w in text for w in ["lawsuit", "sued", "court", "litigation", "settlement", "patent dispute", "injunction"]):
        return NewsEventType.LEGAL
    if any(w in text for w in ["acquisition", "acquire", "merger", "m&a", "buyout", "takeover", "divestiture", "demerger"]):
        return NewsEventType.M_AND_A
    if any(w in text for w in ["fda approval", "launch", "unveils", "new product", "patent granted"]):
        return NewsEventType.PRODUCT
    if any(w in text for w in ["contract", "order win", "bagged order", "partnership", "deal signed", "agreement"]):
        return NewsEventType.CONTRACT
    if any(w in text for w in ["capex", "new plant", "facility expansion", "capacity expansion", "manufacturing unit"]):
        return NewsEventType.CAPEX
    if any(w in text for w in ["dividend", "buyback", "share repurchase", "fundraise", "rights issue", "bond offering", "ipo"]):
        return NewsEventType.FINANCING
    if any(w in text for w in ["upgrade", "downgrade", "price target", "rating raised", "rating cut", "credit rating", "crisil", "icra"]):
        return NewsEventType.RATING
    if any(w in text for w in ["inflation", "gdp", "interest rate", "central bank", "rate hike", "rate cut", "macro"]):
        return NewsEventType.MACRO
    if any(w in text for w in ["sector", "industry wide", "tariff", "government policy", "subsidy"]):
        return NewsEventType.GOVERNMENT

    return NewsEventType.OTHER


def calc_event_materiality(
    event_category: NewsEventType,
    source_quality: NewsSourceQuality,
    headline: str,
    summary: str = "",
) -> Tuple[NewsImportance, float]:
    """
    Deterministically computes EVENT MATERIALITY (importance tier & 0.0-1.0 score).
    Does NOT predict market return; scores factual institutional significance.
    """
    text = f"{headline} {summary}".lower()
    base_score = 0.4

    # Category weightings
    if event_category in (
        NewsEventType.EARNINGS,
        NewsEventType.GUIDANCE,
        NewsEventType.M_AND_A,
        NewsEventType.REGULATORY,
        NewsEventType.LEGAL,
    ):
        base_score = 0.75
    elif event_category in (
        NewsEventType.CONTRACT,
        NewsEventType.PRODUCT,
        NewsEventType.MANAGEMENT,
        NewsEventType.FINANCING,
        NewsEventType.RATING,
        NewsEventType.CAPEX,
    ):
        base_score = 0.55
    else:
        base_score = 0.35

    # Source credibility adjustment
    if source_quality in (NewsSourceQuality.OFFICIAL, NewsSourceQuality.REGULATORY):
        base_score += 0.15
    elif source_quality == NewsSourceQuality.REPUTABLE_MEDIA:
        base_score += 0.05
    elif source_quality == NewsSourceQuality.SECONDARY:
        base_score -= 0.10

    # Keyword materiality boosters
    if any(kw in text for kw in ["fraud", "penalty", "halted", "resigns", "sebi order", "delisting", "bankruptcy", "default"]):
        base_score += 0.15

    score = max(0.05, min(0.99, round(base_score, 2)))

    if score >= 0.70:
        return NewsImportance.HIGH, score
    elif score >= 0.40:
        return NewsImportance.MEDIUM, score
    else:
        return NewsImportance.LOW, score


def assess_importance(
    raw_importance: Optional[str],
    event_type: NewsEventType,
    source_quality: NewsSourceQuality,
) -> NewsImportance:
    """Deterministically assign importance level."""
    if raw_importance and isinstance(raw_importance, str):
        norm = raw_importance.upper().strip()
        for member in NewsImportance:
            if member.value == norm:
                return member

    # Rule-based importance
    if event_type in (
        NewsEventType.EARNINGS,
        NewsEventType.GUIDANCE,
        NewsEventType.M_AND_A,
        NewsEventType.REGULATORY,
        NewsEventType.LEGAL,
    ) or source_quality in (NewsSourceQuality.OFFICIAL, NewsSourceQuality.REGULATORY):
        return NewsImportance.HIGH

    if event_type in (
        NewsEventType.CONTRACT,
        NewsEventType.PRODUCT,
        NewsEventType.MANAGEMENT,
        NewsEventType.FINANCING,
        NewsEventType.RATING,
        NewsEventType.CAPEX,
    ):
        return NewsImportance.MEDIUM

    return NewsImportance.LOW


def _normalize_headline_for_dedup(headline: str) -> str:
    """Normalize headline string for deterministic clustering."""
    s = headline.lower().strip()
    s = re.sub(r"^(breaking|update|exclusive|just in|report|live):\s*", "", s)
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def resolve_security_identifier(identifier: str) -> Optional[str]:
    """
    Resolve any symbol, ISIN, BSE code, or alias to the canonical SecurityMaster identifier (e.g. TCS.NS).
    Returns None if identity cannot be resolved or is unknown. Never guesses.
    """
    if not identifier:
        return None
    try:
        from backend.infrastructure.security_master import SecurityMaster
        sm = SecurityMaster.get_instance()
        q = identifier.strip().upper()
        
        # Check if known in indexes
        if q in sm._securities:
            sec = sm._securities[q]
            return sec.nse_symbol or sec.canonical_symbol
        if q in sm._by_nse:
            sec = sm._securities[sm._by_nse[q]]
            return sec.nse_symbol or sec.canonical_symbol
        if q in sm._by_isin:
            sec = sm._securities[sm._by_isin[q]]
            return sec.nse_symbol or sec.canonical_symbol
        if q in sm._by_bse_code:
            sec = sm._securities[sm._by_bse_code[q]]
            return sec.nse_symbol or sec.canonical_symbol
        if q in sm._by_bse_symbol:
            sec = sm._securities[sm._by_bse_symbol[q]]
            return sec.nse_symbol or sec.canonical_symbol
        if q in sm._by_alias:
            sec = sm._securities[sm._by_alias[q]]
            return sec.nse_symbol or sec.canonical_symbol
            
        base = q.replace(".NS", "").replace(".BO", "")
        if base in sm._securities:
            sec = sm._securities[base]
            return sec.nse_symbol or sec.canonical_symbol
        if base in sm._by_alias:
            sec = sm._securities[sm._by_alias[base]]
            return sec.nse_symbol or sec.canonical_symbol

        return None
    except Exception:
        pass
    return None


def normalize_news_event(
    raw: Dict[str, Any],
    symbol: str,
    isin: Optional[str] = None,
    data_timestamp: Optional[datetime] = None,
) -> NewsEvent:
    """
    Converts raw provider article dictionary into canonical NewsEvent model with
    deterministic categorization and materiality score.
    """
    headline = str(raw.get("headline") or raw.get("title") or "").strip()
    summary = str(raw.get("summary") or raw.get("content") or "").strip()
    publisher = str(raw.get("publisher") or raw.get("source") or "UNKNOWN").strip()
    url = raw.get("link") or raw.get("url")

    pub_time = _parse_timestamp(raw.get("published_at") or raw.get("publication_time") or raw.get("article_timestamp"))
    now = datetime.now(timezone.utc)

    # Source tier & quality
    raw_tier = raw.get("source_tier")
    if isinstance(raw_tier, SourceTier):
        source_tier = raw_tier
    elif isinstance(raw_tier, str) and raw_tier in SourceTier._value2member_map_:
        source_tier = SourceTier(raw_tier)
    else:
        source_tier = SourceTier.TIER_4_SECONDARY

    source_quality = classify_source_quality(publisher)
    event_category = classify_event_type(raw.get("event_category") or raw.get("event_type"), headline, summary)
    materiality, mat_score = calc_event_materiality(event_category, source_quality, headline, summary)

    return NewsEvent(
        symbol=symbol,
        isin=isin,
        headline=headline,
        summary=summary,
        publisher=publisher,
        url=url,
        reference_id=raw.get("reference_id") or raw.get("id"),
        publication_time=pub_time,
        ingestion_timestamp=now,
        event_category=event_category,
        materiality=materiality,
        materiality_score=mat_score,
        source_tier=source_tier,
        source=raw.get("source") or publisher,
        verification_status=VerificationStatus.VERIFIED if source_tier == SourceTier.TIER_1_PRIMARY_OFFICIAL else VerificationStatus.UNVERIFIED,
        quality=DataQuality.HIGH if source_tier == SourceTier.TIER_1_PRIMARY_OFFICIAL else DataQuality.MEDIUM,
        raw_data=raw,
    )


def deduplicate_news_events(events: List[NewsEvent]) -> List[NewsEvent]:
    """
    Deterministic deduplication of NewsEvent records.
    Clusters by normalized headline and time proximity without deleting provenance.
    """
    if not events:
        return []

    seen_signatures: Dict[str, str] = {}
    deduped: List[NewsEvent] = []

    for idx, event in enumerate(events):
        norm_h = _normalize_headline_for_dedup(event.headline)
        # Create temporal signature (e.g. date bucket if publication_time present)
        date_str = event.publication_time.strftime("%Y-%m-%d") if event.publication_time else "nodate"
        sig = f"{event.symbol}:{norm_h}:{date_str}"

        if sig in seen_signatures:
            # Mark as duplicate and record duplicate group
            updated = event.model_copy(update={
                "is_duplicate": True,
                "duplicate_group_id": seen_signatures[sig],
            })
            deduped.append(updated)
        else:
            group_id = f"dedup-group-{idx + 1}"
            seen_signatures[sig] = group_id
            updated = event.model_copy(update={
                "is_duplicate": False,
                "duplicate_group_id": group_id,
            })
            deduped.append(updated)

    return deduped


class NewsCalculator:
    """
    Deterministic news evidence processor.
    Calculates recency, classifies source quality, event types, assigns importance,
    deduplicates repeated coverage, and computes summary statistics.
    """

    @staticmethod
    def process_news_data(market_context: MarketContext) -> Tuple[List[NewsArticleEvidence], Dict[str, int]]:
        """
        Process raw news articles from MarketContext.news_data.
        
        Returns:
            (articles, summary_stats)
        """
        news_data = market_context.news_data or {}
        raw_articles = news_data.get("articles", [])
        if isinstance(raw_articles, dict):
            raw_articles = [raw_articles]
        elif not isinstance(raw_articles, list):
            raw_articles = []

        context_id = market_context.context_id
        data_ts_str = market_context.data_timestamp.isoformat()
        ctx_timestamp = market_context.data_timestamp

        articles: List[NewsArticleEvidence] = []
        seen_signatures: Dict[str, str] = {}  # signature -> first article duplicate_group_id

        for idx, raw in enumerate(raw_articles):
            if not isinstance(raw, dict):
                continue

            headline = str(raw.get("headline") or raw.get("title") or "").strip()
            if not headline:
                continue

            source = str(raw.get("source") or raw.get("publisher") or "UNKNOWN").strip()
            published_at = raw.get("published_at") or raw.get("article_timestamp") or raw.get("publication_time")
            if published_at is not None:
                published_at = str(published_at).strip()

            summary = str(raw.get("summary") or raw.get("content") or "").strip()
            
            # Numeric relevance score
            relevance = 1.0
            raw_relevance = raw.get("ticker_relevance") or raw.get("relevance_score")
            if raw_relevance is not None:
                try:
                    rel_f = float(raw_relevance)
                    if not (math.isnan(rel_f) or math.isinf(rel_f)):
                        relevance = max(0.0, min(1.0, rel_f))
                except (ValueError, TypeError):
                    pass

            # Classifications
            source_quality = classify_source_quality(source or raw.get("source_quality"))
            event_type = classify_event_type(raw.get("event_type") or raw.get("event_category"), headline, summary)
            importance = assess_importance(raw.get("importance") or raw.get("materiality"), event_type, source_quality)
            recency = calculate_recency(published_at, ctx_timestamp)

            # Deduplication
            explicit_event_id = raw.get("event_id") or raw.get("event_group_id")
            if explicit_event_id:
                sig = f"event:{explicit_event_id}"
            else:
                norm_h = _normalize_headline_for_dedup(headline)
                sig = f"h:{norm_h}"

            is_duplicate = False
            group_id = None
            if sig in seen_signatures:
                is_duplicate = True
                group_id = seen_signatures[sig]
            else:
                group_id = f"group-{idx+1}"
                seen_signatures[sig] = group_id

            evidence = NewsArticleEvidence(
                headline=headline,
                source=source,
                published_at=published_at,
                event_type=event_type,
                importance=importance,
                summary=summary,
                ticker_relevance=relevance,
                source_quality=source_quality,
                recency=recency,
                is_duplicate=is_duplicate,
                duplicate_group_id=group_id,
                data_timestamp=data_ts_str,
                context_id=context_id,
            )
            articles.append(evidence)

        # Summary statistics
        total_articles = len(articles)
        unique_events = [a for a in articles if not a.is_duplicate]
        unique_events_count = len(unique_events)
        high_importance_count = sum(1 for a in unique_events if a.importance == NewsImportance.HIGH)
        recent_count = sum(1 for a in unique_events if a.recency in (NewsRecency.VERY_RECENT, NewsRecency.RECENT))

        stats = {
            "total_articles": total_articles,
            "unique_events_count": unique_events_count,
            "high_importance_count": high_importance_count,
            "recent_count": recent_count,
        }

        return articles, stats
