"""
Regression tests for JSON safety boundary, robust technical indicator calculations,
missing/insufficient OHLCV data handling, and /api/analyze serialization.

Tests:
1. Normal market data calculation
2. Missing High values (handled without producing NaN)
3. Fewer than 20 valid observations (20_day_high returns None, not NaN or error)
4. Empty dataframe (handled cleanly without crash)
5. NaN and Infinity values in indicators sanitized to None (null)
6. Complete /api/analyze response JSON serialization test (including WIPRO.NS simulation)
"""

import unittest
import asyncio
import json
import math
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock

from backend.domain.schemas import (
    MarketContext,
    HistoricalWindow,
    DataQualityStatus,
    AgentInput,
    AgentOutput,
    AgentState,
)
from backend.infrastructure.data_providers import YFinanceProvider
from backend.utils.json_safety import sanitize_for_json
from backend.application.orchestration import analyze_symbol_application
from backend.agents.technical_agent import TechnicalAnalysis
from backend.agents.risk_agent import RiskAssessment
from fastapi.testclient import TestClient
from backend.main import app


class TestJsonSafetyAndMarketData(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.client = TestClient(app)

    # 1. Normal Market Data
    def test_normal_market_data_calculation(self):
        dates = pd.date_range(end=self.now, periods=60, freq="D", tz="UTC")
        df = pd.DataFrame({
            "Open": np.linspace(100, 150, 60),
            "High": np.linspace(105, 155, 60),
            "Low": np.linspace(95, 145, 60),
            "Close": np.linspace(102, 152, 60),
            "Volume": np.full(60, 1000000),
        }, index=dates)

        provider = YFinanceProvider()
        df_calc = provider._calculate_technicals(df)
        self.assertIn("20_day_high", df_calc.columns)
        self.assertFalse(math.isnan(df_calc["20_day_high"].iloc[-1]))
        self.assertAlmostEqual(df_calc["20_day_high"].iloc[-1], 155.0, places=2)

    # 2. Missing High values (e.g. trailing NaN in High column)
    def test_missing_high_values_handled(self):
        dates = pd.date_range(end=self.now, periods=60, freq="D", tz="UTC")
        highs = np.linspace(105, 155, 60)
        highs[-1] = np.nan  # trailing NaN as observed in live WIPRO.NS feed
        highs[-5] = np.nan  # intermediate NaN

        df = pd.DataFrame({
            "Open": np.linspace(100, 150, 60),
            "High": highs,
            "Low": np.linspace(95, 145, 60),
            "Close": np.linspace(102, 152, 60),
            "Volume": np.full(60, 1000000),
        }, index=dates)

        provider = YFinanceProvider()
        with patch.object(provider, "get_historical_data", return_value=df):
            ctx = provider.get_market_context("WIPRO.NS", HistoricalWindow.RECENT)
            techs = ctx.technical_indicators
            
            # Must NOT be float('nan')
            high_val = techs.get("20_day_high")
            if high_val is not None:
                self.assertFalse(math.isnan(high_val))
                self.assertFalse(math.isinf(high_val))

            # JSON serializability test
            serialized = json.dumps(techs)
            self.assertNotIn("NaN", serialized)
            self.assertNotIn("nan", serialized)

    # 3. Fewer than 20 valid observations
    def test_fewer_than_20_observations(self):
        dates = pd.date_range(end=self.now, periods=10, freq="D", tz="UTC")
        df = pd.DataFrame({
            "Open": np.linspace(100, 110, 10),
            "High": np.linspace(105, 115, 10),
            "Low": np.linspace(95, 105, 10),
            "Close": np.linspace(102, 112, 10),
            "Volume": np.full(10, 500000),
        }, index=dates)

        provider = YFinanceProvider()
        with patch.object(provider, "get_historical_data", return_value=df):
            ctx = provider.get_market_context("SHORT.NS", HistoricalWindow.RECENT)
            techs = ctx.technical_indicators
            # 20_day_high should legitimately be None when fewer than 20 observations
            self.assertIsNone(techs.get("20_day_high"))
            # Context must serialize to JSON without error
            json_str = json.dumps(sanitize_for_json(techs))
            self.assertIn('"20_day_high": null', json_str)

    # 4. Empty dataframe handling
    def test_empty_dataframe_handled(self):
        empty_df = pd.DataFrame()
        provider = YFinanceProvider()
        with patch.object(provider, "get_historical_data", return_value=empty_df):
            ctx = provider.get_market_context("EMPTY.NS", HistoricalWindow.RECENT)
            self.assertEqual(ctx.quality_status, DataQualityStatus.CRITICAL_FAILURE)
            self.assertEqual(ctx.current_price, 0.0)
            json_str = json.dumps(sanitize_for_json(ctx.model_dump()))
            self.assertIsInstance(json_str, str)

    # 5. NaN and Infinity values in indicators sanitized to None
    def test_nan_infinity_sanitized_to_null(self):
        raw_dict = {
            "symbol": "TEST.NS",
            "market_data": {
                "latest_close": 150.25,
                "20_day_high": float("nan"),
                "ema20": float("inf"),
                "ema50": float("-inf"),
                "rsi": np.nan,
            },
            "nested_list": [1.0, float("nan"), float("inf"), 4.5],
            "valid_int": 42,
            "valid_str": "hello",
            "valid_bool": True,
        }

        sanitized = sanitize_for_json(raw_dict)
        self.assertIsNone(sanitized["market_data"]["20_day_high"])
        self.assertIsNone(sanitized["market_data"]["ema20"])
        self.assertIsNone(sanitized["market_data"]["ema50"])
        self.assertIsNone(sanitized["market_data"]["rsi"])
        self.assertEqual(sanitized["market_data"]["latest_close"], 150.25)
        self.assertEqual(sanitized["nested_list"], [1.0, None, None, 4.5])
        self.assertEqual(sanitized["valid_int"], 42)

        # Ensure standard json.dumps succeeds without ValueError
        json_output = json.dumps(sanitized)
        parsed = json.loads(json_output)
        self.assertIsNone(parsed["market_data"]["20_day_high"])
        self.assertIsNone(parsed["market_data"]["ema20"])
        self.assertEqual(parsed["market_data"]["latest_close"], 150.25)

    # 6. Complete /api/analyze response JSON serialization test
    def test_api_analyze_serialization_end_to_end(self):
        mock_tech = TechnicalAnalysis(
            symbol="WIPRO.NS",
            trend="BEARISH",
            setup="PULLBACK",
            technical_score=4.5,
            confirmation=False
        )
        mock_risk = RiskAssessment(
            symbol="WIPRO.NS",
            risk_level="HIGH",
            max_position_size_pct=2.0,
            stop_loss_pct=3.0,
            risk_summary="High volatility with resistance at 20-day high."
        )

        with patch("backend.adapters.legacy_agents._get_technical_runner", return_value=AsyncMock(return_value=mock_tech)), \
             patch("backend.adapters.legacy_agents._get_risk_runner", return_value=AsyncMock(return_value=mock_risk)):
            response = self.client.get("/api/analyze?symbol=WIPRO.NS")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertIn("symbol", data)
            self.assertIn("market_data", data)
            self.assertIn("final_verdict", data)
            # Ensure market_data fields are JSON compliant (numbers or null, not NaN string)
            for k, v in data["market_data"].items():
                if v is not None:
                    self.assertIsInstance(v, (int, float))
                    self.assertFalse(math.isnan(v))


if __name__ == "__main__":
    unittest.main()
