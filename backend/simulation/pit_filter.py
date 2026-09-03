"""
Point-In-Time (PIT) Data Filter — Phase 5.2 & Phase 3D

Guarantees absolute absence of look-ahead bias by filtering all data modalities
(OHLCV, fundamentals, quarterly statements, corporate actions, ownership,
corporate filings, news, institutional flows) strictly against the simulation timestamp T.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
import uuid

from backend.domain.schemas import (
    CorporateDocument,
    DeliveryObservation,
    HistoricalWindow,
    InstitutionalDeal,
    InstitutionalFlowObservation,
    MarketContext,
    OwnershipObservation,
)


def _normalize_dt(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    return None


def _parse_timestamp(ts: Union[str, datetime, int, float, None]) -> Optional[datetime]:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return _normalize_dt(ts)
    if isinstance(ts, (int, float)):
        try:
            if ts > 1e11:
                ts = ts / 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
        except Exception:
            return None
    if isinstance(ts, str):
        ts = ts.strip()
        if not ts:
            return None
        try:
            return _normalize_dt(datetime.fromisoformat(ts.replace("Z", "+00:00")))
        except Exception:
            try:
                return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            except Exception:
                try:
                    return datetime.strptime(ts, "%Y-%m-%d")
                except Exception:
                    return None
    return None


class PointInTimeFilter:
    """
    Deterministic Point-in-Time filter preventing look-ahead bias across all market datasets.
    """

    @staticmethod
    def filter_ohlcv(ohlcv_bars: List[Dict[str, Any]], as_of: datetime) -> List[Dict[str, Any]]:
        """Filter historical OHLCV bars strictly <= as_of timestamp."""
        norm_as_of = _normalize_dt(as_of)
        filtered = []
        for bar in ohlcv_bars:
            ts_val = bar.get("timestamp") or bar.get("date") or bar.get("datetime")
            bar_time = _parse_timestamp(ts_val)
            if bar_time and norm_as_of and bar_time <= norm_as_of:
                filtered.append(bar)
        return filtered

    @staticmethod
    def filter_fundamentals(fundamental_data: Dict[str, Any], as_of: datetime) -> Dict[str, Any]:
        """
        Filter financial statement observations and ratios.
        Only observations with publication/effective/filing timestamps <= as_of are preserved.
        """
        norm_as_of = _normalize_dt(as_of)
        filtered = {}
        for key, value in fundamental_data.items():
            if isinstance(value, dict):
                pub_ts = value.get("publication_time") or value.get("effective_time") or value.get("filing_date") or value.get("date")
                if pub_ts:
                    parsed_ts = _parse_timestamp(pub_ts)
                    if parsed_ts and norm_as_of and parsed_ts <= norm_as_of:
                        filtered[key] = value
                else:
                    # If date is absent on historical observation, do not allow future leakage
                    pass
            else:
                filtered[key] = value
        return filtered

    @staticmethod
    def filter_news(news_data: Union[List[Any], Dict[str, Any]], as_of: datetime) -> Union[List[Any], Dict[str, Any]]:
        """Filter news items with publication_time or published_at <= as_of."""
        norm_as_of = _normalize_dt(as_of)
        if not news_data:
            return {} if isinstance(news_data, dict) else []
        if isinstance(news_data, list):
            filtered_list = []
            for item in news_data:
                pub_ts = getattr(item, "publication_time", None) or getattr(item, "published_at", None)
                if pub_ts is None and isinstance(item, dict):
                    pub_ts = item.get("publication_time") or item.get("published_at") or item.get("timestamp") or item.get("date")
                parsed_ts = _parse_timestamp(pub_ts)
                if parsed_ts and norm_as_of and parsed_ts <= norm_as_of:
                    filtered_list.append(item)
            return filtered_list
        elif isinstance(news_data, dict):
            articles = news_data.get("articles", [])
            filtered_articles = []
            for a in articles:
                pub_ts = getattr(a, "publication_time", None) or getattr(a, "published_at", None)
                if pub_ts is None and isinstance(a, dict):
                    pub_ts = a.get("publication_time") or a.get("published_at") or a.get("date") or a.get("timestamp")
                parsed_ts = _parse_timestamp(pub_ts)
                if parsed_ts and norm_as_of and parsed_ts <= norm_as_of:
                    filtered_articles.append(a)
            if not filtered_articles and (len(news_data) == 0 or (len(news_data) == 1 and "articles" in news_data)):
                return {}
            res = dict(news_data)
            res["articles"] = filtered_articles
            return res
        return news_data

    @staticmethod
    def filter_institutional(institutional_flows: List[InstitutionalFlowObservation], as_of: datetime) -> List[InstitutionalFlowObservation]:
        """Filter institutional flow observations where observed_at <= as_of."""
        norm_as_of = _normalize_dt(as_of)
        return [obs for obs in institutional_flows if _normalize_dt(obs.observed_at) <= norm_as_of]

    @staticmethod
    def filter_quarterly_statements(quarterly_statements: List[Any], as_of: datetime) -> List[Any]:
        """
        Filter quarterly financial statements where publication_time or filing_date <= as_of.
        Prevents look-ahead bias from future financial results releases.
        """
        norm_as_of = _normalize_dt(as_of)
        filtered = []
        for stmt in quarterly_statements:
            pub_time = getattr(stmt, "publication_time", None) or getattr(stmt, "filing_date", None)
            if pub_time is None and isinstance(stmt, dict):
                pub_time = stmt.get("publication_time") or stmt.get("filing_date")
            
            if pub_time:
                parsed_ts = _parse_timestamp(pub_time)
                if parsed_ts and norm_as_of and parsed_ts <= norm_as_of:
                    filtered.append(stmt)
            else:
                pass
        return filtered

    @staticmethod
    def filter_corporate_actions(corporate_actions: List[Any], as_of: datetime) -> List[Any]:
        """
        Filter corporate actions where publication_time or announcement_date or ex_date <= as_of.
        Prevents look-ahead bias from future dividend declarations or stock splits.
        """
        norm_as_of = _normalize_dt(as_of)
        filtered = []
        for act in corporate_actions:
            pub_time = getattr(act, "publication_time", None) or getattr(act, "announcement_date", None) or getattr(act, "ex_date", None)
            if pub_time is None and isinstance(act, dict):
                pub_time = act.get("publication_time") or act.get("announcement_date") or act.get("ex_date")

            if pub_time:
                parsed_ts = _parse_timestamp(pub_time)
                if parsed_ts and norm_as_of and parsed_ts <= norm_as_of:
                    filtered.append(act)
            else:
                pass
        return filtered

    @staticmethod
    def filter_ownership(ownership_data: List[Any], as_of: datetime) -> List[Any]:
        """
        Filter ownership disclosures where publication_time or report_date or observed_at <= as_of.
        """
        norm_as_of = _normalize_dt(as_of)
        filtered = []
        for obs in ownership_data:
            pub_time = getattr(obs, "publication_time", None) or getattr(obs, "report_date", None) or getattr(obs, "observed_at", None)
            if pub_time is None and isinstance(obs, dict):
                pub_time = obs.get("publication_time") or obs.get("report_date") or obs.get("observed_at")

            if pub_time:
                parsed_ts = _parse_timestamp(pub_time)
                if parsed_ts and norm_as_of and parsed_ts <= norm_as_of:
                    filtered.append(obs)
            else:
                pass
        return filtered

    @staticmethod
    def filter_corporate_documents(corporate_docs: List[Any], as_of: datetime) -> List[Any]:
        """Filter corporate disclosures/filings where publication_time <= as_of."""
        norm_as_of = _normalize_dt(as_of)
        filtered = []
        for doc in corporate_docs:
            pub_ts = getattr(doc, "publication_time", None)
            if pub_ts is None and isinstance(doc, dict):
                pub_ts = doc.get("publication_time")
            parsed_ts = _parse_timestamp(pub_ts)
            if parsed_ts and norm_as_of and parsed_ts <= norm_as_of:
                filtered.append(doc)
        return filtered

    @classmethod
    def filter_market_context(cls, raw_context: MarketContext, as_of: datetime) -> MarketContext:
        """
        Filters a MarketContext object to only contain data available as of timestamp `as_of`.
        Ensures strict mathematical PIT invariance for simulation and backtesting.
        """
        filtered_ohlcv = cls.filter_ohlcv(raw_context.ohlcv_historical, as_of)
        filtered_fundamentals = cls.filter_fundamentals(raw_context.fundamental_data, as_of)
        filtered_quarterly = cls.filter_quarterly_statements(raw_context.quarterly_fundamentals, as_of)
        filtered_corporate_actions = cls.filter_corporate_actions(raw_context.corporate_actions, as_of)
        filtered_ownership = cls.filter_ownership(raw_context.ownership_data, as_of)
        filtered_docs = cls.filter_corporate_documents(raw_context.corporate_documents, as_of)
        filtered_news = cls.filter_news(raw_context.news_data, as_of)
        filtered_flows = cls.filter_institutional(raw_context.institutional_data, as_of)

        # Re-derive current price from latest available OHLCV bar if needed
        current_price = raw_context.current_price
        if filtered_ohlcv:
            latest_bar = filtered_ohlcv[-1]
            current_price = latest_bar.get("close", current_price)

        return raw_context.model_copy(
            update={
                "context_id": f"pit-{raw_context.context_id}-{as_of.strftime('%Y%m%d%H%M%S')}",
                "data_timestamp": as_of,
                "current_price": current_price,
                "ohlcv_historical": filtered_ohlcv,
                "fundamental_data": filtered_fundamentals,
                "quarterly_fundamentals": filtered_quarterly,
                "corporate_actions": filtered_corporate_actions,
                "ownership_data": filtered_ownership,
                "corporate_documents": filtered_docs,
                "news_data": filtered_news,
                "institutional_data": filtered_flows,
            }
        )
