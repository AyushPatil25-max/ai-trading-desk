import concurrent.futures
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List
import pandas as pd
import uuid

from backend.domain.schemas import (
    MarketContext, DataQualityStatus, HistoricalWindow, DataQualityTier
)
from backend.infrastructure.data_providers import MarketDataProvider, YFinanceProvider

logger = logging.getLogger(__name__)

@dataclass
class ProviderHealthScore:
    provider_name: str
    success_count: int = 0
    failure_count: int = 0
    consecutive_failures: int = 0
    total_latency_ms: float = 0.0
    
    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        if total == 0:
            return 1.0
        return self.success_count / total
        
    @property
    def average_latency_ms(self) -> float:
        if self.success_count == 0:
            return 0.0
        return self.total_latency_ms / self.success_count
        
    def record_success(self, latency_ms: float):
        self.success_count += 1
        self.consecutive_failures = 0
        self.total_latency_ms += latency_ms
        
    def record_failure(self):
        self.failure_count += 1
        self.consecutive_failures += 1


class BaseApiProvider(MarketDataProvider):
    """Base for API-key dependent providers."""
    def __init__(self, api_key_env_var: str):
        self.api_key = os.environ.get(api_key_env_var)
        self._priority = 99
        self._tier = DataQualityTier.TIER_5_UNVERIFIED_SECONDARY

    def get_market_context(self, symbol: str, window: HistoricalWindow = HistoricalWindow.RECENT) -> MarketContext:
        if not self.api_key:
            raise ValueError(f"Missing API key for {self.name}. Cannot fetch data.")
        return self._fetch_context(symbol, window)

    def _fetch_context(self, symbol: str, window: HistoricalWindow) -> MarketContext:
        raise NotImplementedError("Implement in subclass")

    def get_historical_data(self, symbol: str, period: str = "1y") -> pd.DataFrame:
        if not self.api_key:
            raise ValueError(f"Missing API key for {self.name}.")
        return pd.DataFrame()


class AlphaVantageProvider(BaseApiProvider):
    @property
    def name(self) -> str:
        return "alpha_vantage"
        
class FMPProvider(BaseApiProvider):
    @property
    def name(self) -> str:
        return "financial_modeling_prep"

class PolygonProvider(BaseApiProvider):
    @property
    def name(self) -> str:
        return "polygon_io"
        
class TwelveDataProvider(BaseApiProvider):
    @property
    def name(self) -> str:
        return "twelve_data"


class MultiProviderMarketDataProvider(MarketDataProvider):
    """
    Coordinates multiple MarketDataProviders with fallback hierarchy,
    health scoring, timeout protection, and failover.
    """
    def __init__(self, timeout_seconds: float = 5.0):
        self.timeout_seconds = timeout_seconds
        self.health_scores: Dict[str, ProviderHealthScore] = {}
        self.providers: List[MarketDataProvider] = []
        
        # Initialize default hierarchy
        self.register_provider(FMPProvider("FMP_API_KEY"), tier=DataQualityTier.TIER_4_STANDARD_AGGREGATOR, priority=1)
        self.register_provider(PolygonProvider("POLYGON_API_KEY"), tier=DataQualityTier.TIER_4_STANDARD_AGGREGATOR, priority=2)
        self.register_provider(AlphaVantageProvider("ALPHAVANTAGE_API_KEY"), tier=DataQualityTier.TIER_4_STANDARD_AGGREGATOR, priority=3)
        self.register_provider(TwelveDataProvider("TWELVEDATA_API_KEY"), tier=DataQualityTier.TIER_4_STANDARD_AGGREGATOR, priority=4)
        self.register_provider(YFinanceProvider(), tier=DataQualityTier.TIER_5_UNVERIFIED_SECONDARY, priority=5)

    def register_provider(self, provider: MarketDataProvider, tier: DataQualityTier, priority: int):
        provider._priority = priority
        provider._tier = tier
        self.providers.append(provider)
        self.health_scores[provider.name] = ProviderHealthScore(provider.name)
        
    @property
    def name(self) -> str:
        return "multi_provider_trust_layer"

    def _rank_providers(self) -> List[MarketDataProvider]:
        """Rank providers based on health and priority."""
        def score_provider(p: MarketDataProvider) -> float:
            health = self.health_scores[p.name]
            # Rank heavily penalizes consecutive failures
            if health.consecutive_failures >= 3:
                return float('inf')  # Deprioritize severely
            # Lower priority number is better. Reward high success rate.
            return p._priority - (health.success_rate * 2.0)
            
        return sorted(self.providers, key=score_provider)

    def get_market_context(self, symbol: str, window: HistoricalWindow = HistoricalWindow.RECENT) -> MarketContext:
        ranked_providers = self._rank_providers()
        exceptions = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(ranked_providers))) as executor:
            for provider in ranked_providers:
                start_time = datetime.now(timezone.utc)
                try:
                    # Timeout protection
                    future = executor.submit(provider.get_market_context, symbol, window)
                    context = future.result(timeout=self.timeout_seconds)
                    
                    latency = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000.0
                    self.health_scores[provider.name].record_success(latency)
                    
                    # Augment context with trust layer metadata
                    enriched_context = context.model_copy(update={
                        "source_provider": provider.name,
                        "source_timestamp": context.data_timestamp,
                        "provider_priority": getattr(provider, '_priority', 99),
                        "data_quality_tier": getattr(provider, '_tier', DataQualityTier.TIER_5_UNVERIFIED_SECONDARY),
                        "trust_score": self.health_scores[provider.name].success_rate
                    })
                    return enriched_context
                    
                except concurrent.futures.TimeoutError:
                    self.health_scores[provider.name].record_failure()
                    exceptions.append(f"{provider.name}: Timeout after {self.timeout_seconds}s")
                except Exception as e:
                    self.health_scores[provider.name].record_failure()
                    exceptions.append(f"{provider.name}: {str(e)}")
                    
        # All providers failed
        now = datetime.now(timezone.utc)
        return MarketContext(
            context_id=str(uuid.uuid4()),
            symbol=symbol,
            generated_at=now,
            data_timestamp=now,
            provider=self.name,
            historical_window=window,
            current_price=0.0,
            quality_status=DataQualityStatus.CRITICAL_FAILURE,
            warnings=["All providers failed in MultiProvider fallback hierarchy."] + exceptions
        )

    def get_historical_data(self, symbol: str, period: str = "1y") -> pd.DataFrame:
        ranked_providers = self._rank_providers()
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(ranked_providers))) as executor:
            for provider in ranked_providers:
                try:
                    future = executor.submit(provider.get_historical_data, symbol, period)
                    return future.result(timeout=self.timeout_seconds)
                except Exception:
                    self.health_scores[provider.name].record_failure()
                    continue
        return pd.DataFrame()
