from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from datetime import datetime
from pydantic import BaseModel
import pandas as pd

from backend.domain.schemas import (
    ProvenanceRecord, SourceTier, VerificationStatus, DataQuality, DataSource
)

class ProviderCapabilities(BaseModel):
    quotes: bool = False
    historical: bool = False
    fundamentals: bool = False
    filings: bool = False
    news: bool = False
    macro: bool = False
    institutional: bool = False
    ownership: bool = False
    deals: bool = False
    delivery: bool = False
    earnings_calendar: bool = False

class ProviderResult(BaseModel):
    status: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    provenance: List[ProvenanceRecord] = []

class BaseProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        pass
        
    @property
    @abstractmethod
    def data_source_info(self) -> DataSource:
        pass

    async def get_quote(self, symbol: str) -> ProviderResult:
        raise NotImplementedError()

    async def get_historical_data(self, symbol: str, period: str) -> ProviderResult:
        raise NotImplementedError()

    async def get_fundamentals(self, symbol: str) -> ProviderResult:
        raise NotImplementedError()

    async def get_quarterly_fundamentals(self, symbol: str) -> ProviderResult:
        return ProviderResult(status="ERROR", error="Quarterly fundamentals not supported by provider")

    async def get_corporate_actions(self, symbol: str) -> ProviderResult:
        return ProviderResult(status="ERROR", error="Corporate actions not supported by provider")

    async def get_earnings_calendar(self, symbol: str) -> ProviderResult:
        return ProviderResult(status="ERROR", error="Earnings calendar not supported by provider")

    async def get_news(self, symbol: str) -> ProviderResult:
        return ProviderResult(status="ERROR", error="News not supported by provider")

    async def get_filings(self, symbol: str) -> ProviderResult:
        return ProviderResult(status="ERROR", error="Filings not supported by provider")
        
    async def get_macro(self, indicator: str) -> ProviderResult:
        return ProviderResult(status="ERROR", error="Macro not supported by provider")

    async def get_institutional_flows(self, symbol: str) -> ProviderResult:
        return ProviderResult(status="ERROR", error="Institutional flows not supported by provider")

    async def get_ownership(self, symbol: str) -> ProviderResult:
        return ProviderResult(status="ERROR", error="Ownership data not supported by provider")

    async def get_bulk_deals(self, symbol: str) -> ProviderResult:
        raise NotImplementedError()

    async def get_block_deals(self, symbol: str) -> ProviderResult:
        raise NotImplementedError()

    async def get_delivery_data(self, symbol: str) -> ProviderResult:
        raise NotImplementedError()
