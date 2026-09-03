"""
MultiSource Orchestrator — Phase 2, Phase 3B & Phase 3C Data Coverage

Coordinates multi-provider data ingestion, conflict detection/resolution,
quality scoring, multi-quarter statements, corporate actions, ownership data,
and standardized MarketContext synthesis.
"""

import asyncio
import math
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import pandas as pd

from backend.domain.schemas import (
    MarketContext,
    HistoricalWindow,
    DataQualityStatus,
    ProvenanceRecord,
    DataConflict,
    VerificationStatus,
    QuarterlyStatement,
    CorporateAction,
    OwnershipObservation,
)
from backend.infrastructure.data_providers import MarketDataProvider
from backend.infrastructure.providers.base import BaseProvider, ProviderResult
from backend.infrastructure.data_quality import validate_provenance, compute_data_quality_score, determine_completeness_state
from backend.infrastructure.conflict_engine import Phase2ConflictEngine, _TIER_HIERARCHY


class MultiSourceOrchestrator(MarketDataProvider):
    """
    Coordinates MULTI-SOURCE -> VALIDATE -> PROVENANCE -> CONFLICT RESOLUTION -> MarketContext
    pipeline across all registered providers while maintaining strict interface compatibility.
    """

    def __init__(self, providers: List[BaseProvider], tolerance_pct: float = 0.05):
        self.providers = providers
        self.conflict_engine = Phase2ConflictEngine(tolerance_pct=tolerance_pct)

    @property
    def name(self) -> str:
        return "MultiSourceOrchestrator"

    def get_historical_data(self, symbol: str, period: str = "60d") -> pd.DataFrame:
        """Fallback synchronous method required by MarketDataProvider interface."""
        import yfinance as yf
        return yf.Ticker(symbol).history(period=period)

    def get_market_context(self, symbol: str, window: HistoricalWindow = HistoricalWindow.RECENT) -> MarketContext:
        """
        Synchronous facade for the asyncio flow called in background thread.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import nest_asyncio
            nest_asyncio.apply()

        return asyncio.run(self._build_market_context(symbol, window))

    async def _build_market_context(self, symbol: str, window: HistoricalWindow) -> MarketContext:
        now = datetime.now(timezone.utc)

        # 1. Gather quotes concurrently from quote-capable providers
        quote_tasks = [
            self._safe_fetch_quote(p, symbol)
            for p in self.providers
            if p.capabilities.quotes
        ]
        quote_results = await asyncio.gather(*quote_tasks, return_exceptions=True)

        valid_provenance: List[ProvenanceRecord] = []
        for res in quote_results:
            if isinstance(res, ProviderResult) and res.status == "SUCCESS":
                for prov in res.provenance:
                    valid_provenance.append(prov)

        # 2. Conflict Resolution on Quotes
        consensus_price = 0.0
        conflicts: List[DataConflict] = []
        price_records = [r for r in valid_provenance if r.metric == "current_price"]
        winning_record: Optional[ProvenanceRecord] = None

        if price_records:
            def sort_key(r: ProvenanceRecord):
                tier_rank = _TIER_HIERARCHY.get(r.source.source_tier, 99)
                return (tier_rank, -r.observed_at.timestamp())

            price_records.sort(key=sort_key)
            winning_record = price_records[0]

            for i in range(1, len(price_records)):
                comp_record = price_records[i]
                winning_record, conflict = self.conflict_engine.resolve(winning_record, comp_record)
                if conflict:
                    conflicts.append(conflict)

            consensus_price = winning_record.value
            valid_provenance = [r for r in valid_provenance if r.metric != "current_price"]
            valid_provenance.append(winning_record)

        # 3. Quality summary
        quality_summary = {}
        for prov in valid_provenance:
            q_res = validate_provenance(prov)
            quality_summary[prov.source.provider_name] = {
                "overall": prov.quality.value,
                "fields": {k: v.value for k, v in q_res.items()},
            }

        # 4. Fetch Fundamentals, Quarterly, Corporate Actions, Historical OHLCV, News, Macro, Institutional concurrently
        fund_task = self._fetch_fundamentals(symbol)
        q_fund_task = self._fetch_quarterly_fundamentals(symbol)
        corp_task = self._fetch_corporate_actions(symbol)
        hist_task = self._fetch_historical(symbol, window)
        news_task = self._fetch_news(symbol)
        macro_task = self._fetch_macro()
        inst_task = self._fetch_institutional(symbol)

        fund_data, q_statements, corp_actions, (ohlcv, technical_indicators), news_data, macro_data, (inst_data, own_data, deal_data, deliv_data) = await asyncio.gather(
            fund_task, q_fund_task, corp_task, hist_task, news_task, macro_task, inst_task, return_exceptions=False
        )

        if consensus_price <= 0 and ohlcv and len(ohlcv) > 0:
            consensus_price = float(ohlcv[-1].get("close", 0.0))

        # 5. Build initial MarketContext
        initial_ctx = MarketContext(
            context_id=str(uuid.uuid4()),
            symbol=symbol,
            data_timestamp=now,
            provider="MultiSource",
            current_price=consensus_price,
            historical_window=window,
            ohlcv_historical=ohlcv,
            technical_indicators=technical_indicators,
            fundamental_data=fund_data,
            quarterly_fundamentals=q_statements,
            corporate_actions=corp_actions,
            macro_data=macro_data,
            news_data=news_data,
            institutional_data=inst_data,
            ownership_data=own_data,
            deal_data=deal_data,
            delivery_data=deliv_data,
            quality_status=DataQualityStatus.OK if consensus_price > 0 else DataQualityStatus.CRITICAL_FAILURE,
            provenance_records={"current_price": winning_record} if winning_record else {},
            conflicts=conflicts,
            quality_summary=quality_summary,
        )

        # Compute deterministic quality score and attach
        quality_score = compute_data_quality_score(initial_ctx)
        return initial_ctx.model_copy(update={
            "trust_score": quality_score,
            "confidence_score": quality_score,
        })

    async def _safe_fetch_quote(self, provider: BaseProvider, symbol: str) -> ProviderResult:
        try:
            return await asyncio.wait_for(provider.get_quote(symbol), timeout=5.0)
        except Exception as e:
            return ProviderResult(status="ERROR", error=str(e))

    async def _fetch_fundamentals(self, symbol: str) -> Dict[str, Any]:
        for p in self.providers:
            if p.capabilities.fundamentals:
                try:
                    res = await asyncio.wait_for(p.get_fundamentals(symbol), timeout=5.0)
                    if res.status == "SUCCESS" and res.data:
                        return res.data
                except Exception:
                    continue
        return {}

    async def _fetch_quarterly_fundamentals(self, symbol: str) -> List[QuarterlyStatement]:
        for p in self.providers:
            if p.capabilities.fundamentals and hasattr(p, "get_quarterly_fundamentals"):
                try:
                    res = await asyncio.wait_for(p.get_quarterly_fundamentals(symbol), timeout=6.0)
                    if res.status == "SUCCESS" and res.data and "quarterly_statements" in res.data:
                        raw_list = res.data["quarterly_statements"]
                        statements: List[QuarterlyStatement] = []
                        for item in raw_list:
                            if isinstance(item, QuarterlyStatement):
                                statements.append(item)
                            elif isinstance(item, dict):
                                statements.append(QuarterlyStatement(**item))
                        return statements
                except Exception:
                    continue
        return []

    async def _fetch_corporate_actions(self, symbol: str) -> List[CorporateAction]:
        for p in self.providers:
            if hasattr(p, "get_corporate_actions"):
                try:
                    res = await asyncio.wait_for(p.get_corporate_actions(symbol), timeout=5.0)
                    if res.status == "SUCCESS" and res.data and "corporate_actions" in res.data:
                        raw_list = res.data["corporate_actions"]
                        actions: List[CorporateAction] = []
                        for item in raw_list:
                            if isinstance(item, CorporateAction):
                                actions.append(item)
                            elif isinstance(item, dict):
                                actions.append(CorporateAction(**item))
                        return actions
                except Exception:
                    continue
        return []

    async def _fetch_historical(self, symbol: str, window: HistoricalWindow) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        period_map = {
            HistoricalWindow.RECENT: "3mo",
            HistoricalWindow.SHORT: "3mo",
            HistoricalWindow.MEDIUM: "3mo",
            HistoricalWindow.LONG: "1y",
        }
        for p in self.providers:
            if p.capabilities.historical:
                try:
                    res = await asyncio.wait_for(p.get_historical_data(symbol, period_map[window]), timeout=5.0)
                    if res.status == "SUCCESS" and res.data and "ohlcv" in res.data:
                        raw_df = res.data["ohlcv"]
                        if raw_df:
                            df = pd.DataFrame(raw_df)
                            if "Date" in df.columns:
                                df.set_index("Date", inplace=True)
                            df.index = pd.to_datetime(df.index, utc=True)

                            price_cols = [c for c in ["Open", "High", "Low", "Close"] if c in df.columns]
                            if price_cols:
                                df = df.dropna(how="all", subset=price_cols)
                                for col in price_cols:
                                    if df[col].isnull().any():
                                        df[col] = df[col].ffill().bfill()

                            if df.empty:
                                continue

                            from backend.indicators import calculate_indicators
                            df = calculate_indicators(df)

                            if "High" in df.columns and len(df) >= 20:
                                df["20_day_high"] = df["High"].rolling(window=20, min_periods=20).max()
                            else:
                                df["20_day_high"] = None

                            def _safe_float(val: Any) -> Optional[float]:
                                if val is None:
                                    return None
                                try:
                                    if pd.isna(val):
                                        return None
                                    f = float(val)
                                    if math.isnan(f) or math.isinf(f):
                                        return None
                                    return round(f, 2)
                                except (ValueError, TypeError):
                                    return None

                            ohlcv = []
                            target_rows = HistoricalWindow.get_days(window)
                            for index, row in df.tail(target_rows).iterrows():
                                ohlcv.append({
                                    "date": index.isoformat(),
                                    "open": _safe_float(row.get("Open")) or 0.0,
                                    "high": _safe_float(row.get("High")) or 0.0,
                                    "low": _safe_float(row.get("Low")) or 0.0,
                                    "close": _safe_float(row.get("Close")) or 0.0,
                                    "volume": _safe_float(row.get("Volume")) or 0.0,
                                    "timestamp": index.isoformat(),
                                })

                            latest = df.iloc[-1]
                            technical_indicators = {
                                "ema20": _safe_float(latest.get("EMA20")),
                                "ema50": _safe_float(latest.get("EMA50")),
                                "rsi": _safe_float(latest.get("RSI")),
                                "20_day_high": _safe_float(latest.get("20_day_high")),
                            }
                            return ohlcv, technical_indicators
                except Exception:
                    continue
        return [], {}

    async def _fetch_news(self, symbol: str) -> Dict[str, Any]:
        for p in self.providers:
            if p.capabilities.news:
                try:
                    res = await asyncio.wait_for(p.get_news(symbol), timeout=3.0)
                    if res.status == "SUCCESS" and res.data:
                        return res.data
                except Exception:
                    continue
        return {}

    async def _fetch_macro(self) -> Dict[str, Any]:
        for p in self.providers:
            if p.capabilities.macro:
                try:
                    res = await asyncio.wait_for(p.get_macro(), timeout=3.0)
                    if res.status == "SUCCESS" and res.data:
                        return res.data
                except Exception:
                    continue
        return {}

    async def _fetch_institutional(self, symbol: str) -> tuple[List[Any], List[OwnershipObservation], List[Any], List[Any]]:
        inst_data, own_data, deal_data, deliv_data = [], [], [], []
        for p in self.providers:
            if p.capabilities.institutional:
                try:
                    res = await asyncio.wait_for(p.get_institutional_flows(symbol), timeout=2.0)
                    if res.status == "SUCCESS" and res.data:
                        inst_data.extend(res.data.get("institutional_flows", []))
                except Exception:
                    pass
            if p.capabilities.ownership:
                try:
                    res = await asyncio.wait_for(p.get_ownership(symbol), timeout=3.0)
                    if res.status == "SUCCESS" and res.data:
                        raw_own = res.data.get("ownership", [])
                        for o in raw_own:
                            if isinstance(o, OwnershipObservation):
                                own_data.append(o)
                            elif isinstance(o, dict):
                                own_data.append(OwnershipObservation(**o))
                except Exception:
                    pass
            if p.capabilities.deals:
                try:
                    res1 = await asyncio.wait_for(p.get_bulk_deals(symbol), timeout=2.0)
                    if res1.status == "SUCCESS" and res1.data:
                        deal_data.extend(res1.data.get("deals", []))
                except Exception:
                    pass
            if p.capabilities.delivery:
                try:
                    res = await asyncio.wait_for(p.get_delivery_data(symbol), timeout=2.0)
                    if res.status == "SUCCESS" and res.data:
                        deliv_data.extend(res.data.get("delivery", []))
                except Exception:
                    pass
        return inst_data, own_data, deal_data, deliv_data
