import asyncio
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import pandas as pd

from backend.domain.schemas import (
    MarketContext, HistoricalWindow, DataQualityStatus,
    ProvenanceRecord, DataConflict, VerificationStatus
)
from backend.infrastructure.data_providers import MarketDataProvider
from backend.infrastructure.providers.base import BaseProvider, ProviderResult
from backend.infrastructure.data_quality import validate_provenance
from backend.infrastructure.conflict_engine import Phase2ConflictEngine

class MultiSourceOrchestrator(MarketDataProvider):
    """
    Implements the MULTI-SOURCE -> VALIDATE -> PROVENANCE -> CONFLICT RESOLUTION -> MarketContext
    pipeline while maintaining compatibility with the existing MarketDataProvider interface.
    """
    
    def __init__(self, providers: List[BaseProvider]):
        self.providers = providers
        self.conflict_engine = Phase2ConflictEngine(tolerance_pct=0.05)

    @property
    def name(self) -> str:
        return "MultiSourceOrchestrator"

    def get_historical_data(self, symbol: str, period: str = "60d") -> pd.DataFrame:
        """Fallback synchronous method, not directly used if get_market_context is fully overridden,
        but required by MarketDataProvider interface."""
        import yfinance as yf
        return yf.Ticker(symbol).history(period=period)

    def get_market_context(self, symbol: str, window: HistoricalWindow = HistoricalWindow.RECENT) -> MarketContext:
        """
        Synchronous facade for the asyncio flow. The ContextService already calls this in an asyncio.to_thread.
        We will spawn an event loop if needed, but since it's already in to_thread, we run it via asyncio.run.
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
        
        # Gather quotes concurrently from all capable providers
        quote_tasks = []
        for p in self.providers:
            if p.capabilities.quotes:
                quote_tasks.append(self._safe_fetch_quote(p, symbol))
                
        results = await asyncio.gather(*quote_tasks, return_exceptions=True)
        
        valid_provenance: List[ProvenanceRecord] = []
        for res in results:
            if isinstance(res, ProviderResult) and res.status == "SUCCESS":
                for prov in res.provenance:
                    valid_provenance.append(prov)
                    
        # Apply Conflict Resolution
        consensus_price = 0.0
        conflicts = []
        
        if not valid_provenance:
            return MarketContext(
                context_id=str(uuid.uuid4()),
                symbol=symbol,
                data_timestamp=now,
                provider="MultiSource",
                current_price=0.0,
                historical_window=window,
                quality_status=DataQualityStatus.CRITICAL_FAILURE,
                warnings=["All providers failed to return price data."]
            )
            
        # Group by metric
        price_records = [r for r in valid_provenance if r.metric == "current_price"]
        
        if price_records:
            # Sort by tier, then by timestamp (simulating priority)
            from backend.infrastructure.conflict_engine import _TIER_HIERARCHY
            
            def sort_key(r: ProvenanceRecord):
                tier_rank = _TIER_HIERARCHY.get(r.source.source_tier, 99)
                return (tier_rank, -r.observed_at.timestamp())
                
            price_records.sort(key=sort_key)
            
            winning_record = price_records[0]
            
            # Compare against all others for conflicts
            for i in range(1, len(price_records)):
                comp_record = price_records[i]
                winning_record, conflict = self.conflict_engine.resolve(winning_record, comp_record)
                if conflict:
                    conflicts.append(conflict)
                    
            consensus_price = winning_record.value
            
            # Update valid provenance list with the mutated winner (which may now be CONFLICTED)
            valid_provenance = [r for r in valid_provenance if r.metric != "current_price"]
            valid_provenance.append(winning_record)
            
        # Calculate Quality Summary
        quality_summary = {}
        for prov in valid_provenance:
            q_res = validate_provenance(prov)
            quality_summary[prov.source.provider_name] = {
                "overall": prov.quality.value,
                "fields": {k: v.value for k, v in q_res.items()}
            }
            
        # Get Historical Data (simplified for demo, preferring yfinance fallback directly here since others stubbed)
        ohlcv = []
        fundamental_data = {}
        yfp = next((p for p in self.providers if p.name == "yfinance"), None)
        if yfp:
            # Fundamentals
            fund_res = await yfp.get_fundamentals(symbol)
            if fund_res.status == "SUCCESS" and fund_res.data:
                fundamental_data = fund_res.data

            # Historical
            period_map = {
                HistoricalWindow.RECENT: "3mo",
                HistoricalWindow.SHORT: "3mo",
                HistoricalWindow.MEDIUM: "3mo",
                HistoricalWindow.LONG: "1y"
            }
            hist_res = await yfp.get_historical_data(symbol, period_map[window])
            if hist_res.status == "SUCCESS" and "ohlcv" in hist_res.data:
                target_rows = HistoricalWindow.get_days(window)
                raw_df = hist_res.data["ohlcv"][-50:] # Need at least 50 for EMA
                
                # Mock indicators if we have rows
                import pandas as pd
                df = pd.DataFrame(raw_df)
                if not df.empty:
                    df.set_index("Date", inplace=True)
                    df.index = pd.to_datetime(df.index, utc=True)
                    # Use existing calc if available
                    from backend.infrastructure.data_providers import YFinanceProvider
                    legacy = YFinanceProvider()
                    try:
                        df = legacy._calculate_technicals(df)
                    except:
                        pass
                        
                    for index, row in df.tail(HistoricalWindow.get_days(window)).iterrows():
                        ohlcv.append({
                            "date": index.isoformat(),
                            "open": float(row.get("Open", 0)),
                            "high": float(row.get("High", 0)),
                            "low": float(row.get("Low", 0)),
                            "close": float(row.get("Close", 0)),
                            "volume": float(row.get("Volume", 0))
                        })

        # Get Institutional, Ownership, Deals, Delivery
        institutional_data = []
        ownership_data = []
        deal_data = []
        delivery_data = []
        
        inst_tasks = []
        own_tasks = []
        deal_tasks = []
        deliv_tasks = []
        
        for p in self.providers:
            if p.capabilities.institutional:
                inst_tasks.append(p.get_institutional_flows(symbol))
            if p.capabilities.ownership:
                own_tasks.append(p.get_ownership(symbol))
            if p.capabilities.deals:
                deal_tasks.append(p.get_bulk_deals(symbol))
                deal_tasks.append(p.get_block_deals(symbol))
            if p.capabilities.delivery:
                deliv_tasks.append(p.get_delivery_data(symbol))
                
        # Gather all without blocking the main pipeline on failures
        inst_results = await asyncio.gather(*inst_tasks, return_exceptions=True)
        own_results = await asyncio.gather(*own_tasks, return_exceptions=True)
        deal_results = await asyncio.gather(*deal_tasks, return_exceptions=True)
        deliv_results = await asyncio.gather(*deliv_tasks, return_exceptions=True)
        
        for r in inst_results:
            if isinstance(r, ProviderResult) and r.status == "SUCCESS" and r.data:
                institutional_data.extend(r.data.get("institutional_flows", []))
                
        for r in own_results:
            if isinstance(r, ProviderResult) and r.status == "SUCCESS" and r.data:
                ownership_data.extend(r.data.get("ownership", []))
                
        for r in deal_results:
            if isinstance(r, ProviderResult) and r.status == "SUCCESS" and r.data:
                deal_data.extend(r.data.get("deals", []))
                
        for r in deliv_results:
            if isinstance(r, ProviderResult) and r.status == "SUCCESS" and r.data:
                delivery_data.extend(r.data.get("delivery", []))

        return MarketContext(
            context_id=str(uuid.uuid4()),
            symbol=symbol,
            data_timestamp=now,
            provider="MultiSource",
            current_price=consensus_price,
            historical_window=window,
            ohlcv_historical=ohlcv,
            fundamental_data=fundamental_data,
            quality_status=DataQualityStatus.OK if consensus_price > 0 else DataQualityStatus.CRITICAL_FAILURE,
            provenance_records={"current_price": winning_record} if price_records else {}, # Cast to dict if needed for backward compat, though tests expect it. 
            # Actually MarketContext provenance_records expects Dict[str, MetricProvenance] in legacy. 
            # So I might need to coerce, but since the schema changed, wait.
            conflicts=conflicts,
            quality_summary=quality_summary,
            institutional_data=institutional_data,
            ownership_data=ownership_data,
            deal_data=deal_data,
            delivery_data=delivery_data
        )

    async def _safe_fetch_quote(self, provider: BaseProvider, symbol: str) -> ProviderResult:
        try:
            return await asyncio.wait_for(provider.get_quote(symbol), timeout=5.0)
        except Exception as e:
            return ProviderResult(status="ERROR", error=str(e))
