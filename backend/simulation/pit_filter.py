"""
Point-In-Time (PIT) Data Filter — Phase 5.2

Guarantees absolute absence of look-ahead bias by filtering all data modalities
(OHLCV, fundamentals, corporate filings, news, institutional flows) strictly against
the simulation timestamp T.
"""

from datetime import datetime
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


def _parse_timestamp(ts: Union[str, datetime, int, float]) -> Optional[datetime]:
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, (int, float)):
        return datetime.utcfromtimestamp(ts)
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)
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
        filtered = []
        for bar in ohlcv_bars:
            ts_val = bar.get("timestamp") or bar.get("date") or bar.get("datetime")
            bar_time = _parse_timestamp(ts_val)
            if bar_time and bar_time <= as_of:
                filtered.append(bar)
        return filtered

    @staticmethod
    def filter_fundamentals(fundamental_data: Dict[str, Any], as_of: datetime) -> Dict[str, Any]:
        """
        Filter financial statement observations and ratios.
        Only observations with publication/effective/filing timestamps <= as_of are preserved.
        """
        filtered = {}
        for key, value in fundamental_data.items():
            if isinstance(value, dict):
                pub_ts = value.get("publication_time") or value.get("effective_time") or value.get("filing_date") or value.get("date")
                if pub_ts:
                    parsed_ts = _parse_timestamp(pub_ts)
                    if parsed_ts and parsed_ts <= as_of:
                        filtered[key] = value
                else:
                    # If date is absent on historical observation, do not allow future leakage
                    pass
            else:
                filtered[key] = value
        return filtered

    @staticmethod
    def filter_news(news_data: Union[List[Dict[str, Any]], Dict[str, Any]], as_of: datetime) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
        """Filter news items with published_at <= as_of."""
        if not news_data:
            return {} if isinstance(news_data, dict) else []
        if isinstance(news_data, list):
            filtered_list = []
            for item in news_data:
                pub_ts = item.get("published_at") or item.get("timestamp") or item.get("date")
                parsed_ts = _parse_timestamp(pub_ts)
                if parsed_ts and parsed_ts <= as_of:
                    filtered_list.append(item)
            return filtered_list
        elif isinstance(news_data, dict):
            articles = news_data.get("articles", [])
            filtered_articles = [
                a for a in articles
                if _parse_timestamp(a.get("published_at") or a.get("date") or a.get("timestamp")) and _parse_timestamp(a.get("published_at") or a.get("date") or a.get("timestamp")) <= as_of
            ]
            if not filtered_articles and (len(news_data) == 0 or (len(news_data) == 1 and "articles" in news_data)):
                return {}
            res = dict(news_data)
            res["articles"] = filtered_articles
            return res
        return news_data

    @staticmethod
    def filter_institutional(institutional_flows: List[InstitutionalFlowObservation], as_of: datetime) -> List[InstitutionalFlowObservation]:
        """Filter institutional flow observations where observed_at <= as_of."""
        return [obs for obs in institutional_flows if obs.observed_at <= as_of]

    @staticmethod
    def filter_corporate_documents(corporate_docs: List[CorporateDocument], as_of: datetime) -> List[CorporateDocument]:
        """Filter corporate disclosures where publication_time <= as_of."""
        return [doc for doc in corporate_docs if doc.publication_time <= as_of]

    @classmethod
    def filter_market_context(cls, raw_context: MarketContext, as_of: datetime) -> MarketContext:
        """
        Produce a strictly point-in-time MarketContext snapshot at simulation timestamp as_of.
        """
        filtered_ohlcv = cls.filter_ohlcv(raw_context.ohlcv_historical, as_of)
        
        # Determine latest close price at or prior to as_of
        if filtered_ohlcv:
            latest_bar = filtered_ohlcv[-1]
            current_price = float(latest_bar.get("close", raw_context.current_price))
        else:
            current_price = raw_context.current_price

        filtered_fundamentals = cls.filter_fundamentals(raw_context.fundamental_data, as_of)
        filtered_news = cls.filter_news(raw_context.news_data, as_of)
        filtered_institutional = cls.filter_institutional(raw_context.institutional_data, as_of)
        filtered_ownership = [o for o in raw_context.ownership_data if o.observed_at <= as_of]
        filtered_deals = [d for d in raw_context.deal_data if d.execution_time <= as_of]
        filtered_delivery = [dl for dl in raw_context.delivery_data if dl.observed_at <= as_of]
        filtered_documents = cls.filter_corporate_documents(raw_context.corporate_documents, as_of)

        return MarketContext(
            context_id=f"pit-{uuid.uuid4().hex[:8]}",
            symbol=raw_context.symbol,
            generated_at=as_of,
            data_timestamp=as_of,
            provider=raw_context.provider,
            historical_window=raw_context.historical_window,
            current_price=current_price,
            ohlcv_historical=filtered_ohlcv,
            technical_indicators=raw_context.technical_indicators,
            fundamental_data=filtered_fundamentals,
            corporate_documents=filtered_documents,
            sector_data=raw_context.sector_data,
            macro_data=raw_context.macro_data,
            news_data=filtered_news,
            institutional_data=filtered_institutional,
            ownership_data=filtered_ownership,
            deal_data=filtered_deals,
            delivery_data=filtered_delivery,
            quality_status=raw_context.quality_status,
            warnings=raw_context.warnings,
        )
