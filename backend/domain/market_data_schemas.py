"""
Phase 38 - Market Data Integrity Schemas

Defines strongly typed structures for market ticks, quotes, and freshness states.
"""

from datetime import datetime, timezone
from enum import Enum
import math
from typing import Optional, List
from pydantic import BaseModel, Field, model_validator


class MarketDataFreshness(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"

class MarketDataIntegrityState(str, Enum):
    VALID = "VALID"
    REJECTED_STALE = "REJECTED_STALE"
    REJECTED_FUTURE_DATE = "REJECTED_FUTURE_DATE"
    REJECTED_DUPLICATE = "REJECTED_DUPLICATE"
    REJECTED_OUT_OF_ORDER = "REJECTED_OUT_OF_ORDER"
    REJECTED_MALFORMED = "REJECTED_MALFORMED"
    REJECTED_CROSSED_QUOTE = "REJECTED_CROSSED_QUOTE"

class MarketDataSourceHealth(BaseModel):
    provider_id: str
    status: str = "HEALTHY"  # HEALTHY, DEGRADED, UNAVAILABLE
    last_successful_update: Optional[datetime] = None
    last_valid_update: Optional[datetime] = None
    last_invalid_update: Optional[datetime] = None
    consecutive_failures: int = 0
    sequence_gaps: int = 0
    data_age_seconds: float = 0.0

class MarketTick(BaseModel):
    model_config = {"frozen": True}

    symbol: str = Field(min_length=1)
    exchange: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)
    
    last_traded_price: float
    last_traded_quantity: int
    total_volume: int
    
    source_timestamp: datetime
    received_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sequence_number: Optional[int] = None
    
    @model_validator(mode="after")
    def validate_tick(self) -> "MarketTick":
        if math.isnan(self.last_traded_price) or math.isinf(self.last_traded_price) or self.last_traded_price <= 0:
            raise ValueError("Invalid last_traded_price")
        if self.last_traded_quantity <= 0:
            raise ValueError("Invalid last_traded_quantity")
        if self.total_volume < 0:
            raise ValueError("Invalid total_volume")
        if self.source_timestamp > datetime.now(timezone.utc):
            raise ValueError("Future dated source_timestamp")
        return self

class MarketQuote(BaseModel):
    model_config = {"frozen": True}

    symbol: str = Field(min_length=1)
    exchange: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)
    
    bid_price: float
    bid_quantity: int
    ask_price: float
    ask_quantity: int
    
    source_timestamp: datetime
    received_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sequence_number: Optional[int] = None

    @model_validator(mode="after")
    def validate_quote(self) -> "MarketQuote":
        for price in (self.bid_price, self.ask_price):
            if math.isnan(price) or math.isinf(price) or price <= 0:
                raise ValueError("Invalid price in quote")
        for qty in (self.bid_quantity, self.ask_quantity):
            if qty < 0:
                raise ValueError("Invalid quantity in quote")
        # Ensure bid < ask (crossed quotes are invalid for top of book)
        if self.bid_price >= self.ask_price:
            raise ValueError("Crossed quote: bid >= ask")
        if self.source_timestamp > datetime.now(timezone.utc):
            raise ValueError("Future dated source_timestamp")
        return self

class OHLCCandle(BaseModel):
    model_config = {"frozen": True}
    
    symbol: str
    exchange: str
    provider_id: str
    
    open: float
    high: float
    low: float
    close: float
    volume: int
    
    start_timestamp: datetime
    end_timestamp: datetime
    received_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sequence_number: Optional[int] = None

    @model_validator(mode="after")
    def validate_candle(self) -> "OHLCCandle":
        prices = [self.open, self.high, self.low, self.close]
        for p in prices:
            if math.isnan(p) or math.isinf(p) or p <= 0:
                raise ValueError("Invalid price in OHLC")
        if self.low > self.high or self.open > self.high or self.close > self.high:
            raise ValueError("High price must be highest")
        if self.low > self.open or self.low > self.close:
            raise ValueError("Low price must be lowest")
        if self.volume < 0:
            raise ValueError("Invalid volume")
        if self.start_timestamp >= self.end_timestamp:
            raise ValueError("Start timestamp must be before end timestamp")
        return self

class MarketDataSnapshot(BaseModel):
    symbol: str
    freshness: MarketDataFreshness = MarketDataFreshness.UNKNOWN
    integrity_state: MarketDataIntegrityState = MarketDataIntegrityState.VALID
    latest_tick: Optional[MarketTick] = None
    latest_quote: Optional[MarketQuote] = None
    latest_candle: Optional[OHLCCandle] = None
    provider_health: MarketDataSourceHealth
