"""
Point-In-Time Leakage Detector — Phase 5.4

Inspects all data items at decision timestamp T to programmatically verify that
no future OHLCV, financial disclosures, news, macro, or constituent updates leak in.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from backend.domain.schemas import (
    CorporateDocument,
    InstitutionalFlowObservation,
    MarketContext,
)
from backend.scanner.universe import UniverseConstituent, UniverseSnapshot
from backend.simulation.pit_filter import _parse_timestamp
from backend.validation.validation_state import LeakageFinding, LeakageSeverity


class LeakageDetector:
    """
    Detects look-ahead bias and temporal contamination in market context data.
    """

    @classmethod
    def check_market_context(
        cls,
        context: MarketContext,
        decision_timestamp: datetime,
    ) -> List[LeakageFinding]:
        findings: List[LeakageFinding] = []

        # 1. OHLCV Bars
        for bar in context.ohlcv_historical:
            ts = _parse_timestamp(bar.get("timestamp") or bar.get("date"))
            if ts and ts > decision_timestamp:
                findings.append(
                    LeakageFinding(
                        category="OHLCV",
                        symbol=context.symbol,
                        context_id=context.context_id,
                        offending_timestamp=ts,
                        decision_timestamp=decision_timestamp,
                        source=context.provider,
                        severity=LeakageSeverity.CRITICAL,
                        description=f"OHLCV bar timestamp {ts.isoformat()} is after decision time {decision_timestamp.isoformat()}",
                    )
                )

        # 2. Fundamentals
        for key, val in context.fundamental_data.items():
            if isinstance(val, dict):
                pub_ts = val.get("publication_time") or val.get("effective_time") or val.get("filing_date")
                parsed_ts = _parse_timestamp(pub_ts)
                if parsed_ts and parsed_ts > decision_timestamp:
                    findings.append(
                        LeakageFinding(
                            category="FUNDAMENTALS",
                            symbol=context.symbol,
                            context_id=context.context_id,
                            offending_timestamp=parsed_ts,
                            decision_timestamp=decision_timestamp,
                            source="DISCLOSURE",
                            severity=LeakageSeverity.CRITICAL,
                            description=f"Fundamental field '{key}' publication time {parsed_ts.isoformat()} is after decision time {decision_timestamp.isoformat()}",
                        )
                    )

        # 3. News Articles
        articles = context.news_data if isinstance(context.news_data, list) else context.news_data.get("articles", [])
        for a in articles:
            pub_ts = a.get("published_at") or a.get("timestamp") or a.get("date")
            parsed_ts = _parse_timestamp(pub_ts)
            if parsed_ts and parsed_ts > decision_timestamp:
                findings.append(
                    LeakageFinding(
                        category="NEWS",
                        symbol=context.symbol,
                        context_id=context.context_id,
                        offending_timestamp=parsed_ts,
                        decision_timestamp=decision_timestamp,
                        source="NEWS_STREAM",
                        severity=LeakageSeverity.HIGH,
                        description=f"News article '{a.get('title', 'Unknown')}' published at {parsed_ts.isoformat()} is after decision time {decision_timestamp.isoformat()}",
                    )
                )

        # 4. Institutional Flows
        for obs in context.institutional_data:
            if obs.observed_at > decision_timestamp:
                findings.append(
                    LeakageFinding(
                        category="INSTITUTIONAL",
                        symbol=context.symbol,
                        context_id=context.context_id,
                        offending_timestamp=obs.observed_at,
                        decision_timestamp=decision_timestamp,
                        source="FLOW_REPORT",
                        severity=LeakageSeverity.HIGH,
                        description=f"Institutional flow observed at {obs.observed_at.isoformat()} is after decision time {decision_timestamp.isoformat()}",
                    )
                )

        # 5. Corporate Documents
        for doc in context.corporate_documents:
            if doc.publication_time > decision_timestamp:
                findings.append(
                    LeakageFinding(
                        category="CORPORATE_DOCUMENT",
                        symbol=context.symbol,
                        context_id=context.context_id,
                        offending_timestamp=doc.publication_time,
                        decision_timestamp=decision_timestamp,
                        source="EXCHANGE_FILING",
                        severity=LeakageSeverity.HIGH,
                        description=f"Document '{doc.title}' published at {doc.publication_time.isoformat()} is after decision time {decision_timestamp.isoformat()}",
                    )
                )

        return findings

    @classmethod
    def check_universe_snapshot(
        cls,
        snapshot: UniverseSnapshot,
        decision_timestamp: datetime,
    ) -> List[LeakageFinding]:
        findings: List[LeakageFinding] = []
        for c in snapshot.constituents:
            if c.effective_from > decision_timestamp:
                findings.append(
                    LeakageFinding(
                        category="UNIVERSE_CONSTITUENT",
                        symbol=c.symbol,
                        context_id="universe-snap",
                        offending_timestamp=c.effective_from,
                        decision_timestamp=decision_timestamp,
                        source="INDEX_SERVICES",
                        severity=LeakageSeverity.CRITICAL,
                        description=f"Constituent '{c.symbol}' effective_from {c.effective_from.isoformat()} is in the future relative to {decision_timestamp.isoformat()}",
                    )
                )
        return findings

    @classmethod
    def is_clean(cls, findings: List[LeakageFinding]) -> bool:
        """Returns True if no CRITICAL or HIGH leakage findings exist."""
        return not any(f.severity in [LeakageSeverity.CRITICAL, LeakageSeverity.HIGH] for f in findings)
