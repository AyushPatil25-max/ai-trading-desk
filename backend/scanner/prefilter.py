"""
Deterministic Pre-screening Engine — Phase 5.3

Evaluates inexpensive quantitative, technical, and data completeness filters
without calling any LLMs. Rejects unviable setups early to conserve compute.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from backend.domain.schemas import MarketContext
from backend.scanner.scanner_config import ScannerConfig


class PrefilterResult(BaseModel):
    symbol: str
    passed: bool
    rejection_reasons: List[str] = Field(default_factory=list)
    current_price: float = 0.0
    bar_count: int = 0
    metrics_summary: Dict[str, Any] = Field(default_factory=dict)


class DeterministicPrefilter:
    """
    Executes fast, deterministic screening checks on candidate market data.
    """

    def __init__(self, config: Optional[ScannerConfig] = None) -> None:
        self.config = config or ScannerConfig()

    def filter_candidate(
        self,
        symbol: str,
        data: Dict[str, Any],
    ) -> PrefilterResult:
        rejection_reasons = []

        # 1. Price Verification
        current_price = float(data.get("current_price", 0.0))
        ohlcv = data.get("ohlcv_historical", [])
        if not current_price and ohlcv:
            current_price = float(ohlcv[-1].get("close", 0.0))

        if self.config.require_positive_price and current_price <= 0:
            rejection_reasons.append(f"Invalid current price: {current_price} <= 0")

        if current_price < self.config.min_price:
            rejection_reasons.append(
                f"Price ₹{current_price:.2f} below minimum threshold ₹{self.config.min_price:.2f}"
            )
        elif current_price > self.config.max_price:
            rejection_reasons.append(
                f"Price ₹{current_price:.2f} exceeds maximum threshold ₹{self.config.max_price:.2f}"
            )

        # 2. Historical Bar Sufficiency
        bar_count = len(ohlcv)
        if bar_count < self.config.min_historical_bars:
            rejection_reasons.append(
                f"Insufficient historical bars: {bar_count} < {self.config.min_historical_bars}"
            )

        # 3. Technical Structure Extraction (if available)
        tech_indicators = data.get("technical_indicators", {})
        rsi = tech_indicators.get("rsi_14")
        ema_20 = tech_indicators.get("ema_20")
        ema_50 = tech_indicators.get("ema_50")

        metrics_summary = {
            "current_price": current_price,
            "bar_count": bar_count,
            "rsi_14": rsi,
            "ema_20": ema_20,
            "ema_50": ema_50,
            "has_fundamentals": bool(data.get("fundamental_data")),
            "has_news": bool(data.get("news_data")),
            "has_institutional": bool(data.get("institutional_data")),
        }

        passed = len(rejection_reasons) == 0
        return PrefilterResult(
            symbol=symbol,
            passed=passed,
            rejection_reasons=rejection_reasons,
            current_price=current_price,
            bar_count=bar_count,
            metrics_summary=metrics_summary,
        )
