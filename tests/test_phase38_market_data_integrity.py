"""
Phase 38 Dedicated Tests: Real-Time Market Data & Signal Integrity
"""

import unittest
from datetime import datetime, timezone, timedelta
from pydantic import ValidationError

from backend.domain.market_data_schemas import (
    MarketTick, MarketQuote, OHLCCandle,
    MarketDataFreshness, MarketDataIntegrityState
)
from backend.application.market_data_integrity_engine import MarketDataIntegrityEngine
from backend.application.tamper_evident_audit_chain import global_audit_chain

class TestMarketDataIntegrity(unittest.TestCase):
    def setUp(self):
        self.engine = MarketDataIntegrityEngine(stale_threshold_seconds=5.0)
        global_audit_chain.reset()
        
    def _now(self):
        return datetime.now(timezone.utc)

    # ---------------------------------------------------------
    # Schema Validation Tests
    # ---------------------------------------------------------
    
    def test_01_valid_tick_acceptance(self):
        tick = {
            "symbol": "AAPL",
            "exchange": "NASDAQ",
            "provider_id": "P1",
            "last_traded_price": 150.0,
            "last_traded_quantity": 100,
            "total_volume": 1000,
            "source_timestamp": self._now(),
            "sequence_number": 1
        }
        res = self.engine.process_tick(tick)
        self.assertEqual(res, MarketDataIntegrityState.VALID)
        self.assertTrue(self.engine.fail_closed_check("AAPL"))

    def test_02_malformed_tick_nan(self):
        tick = {
            "symbol": "AAPL",
            "exchange": "NASDAQ",
            "provider_id": "P1",
            "last_traded_price": float('nan'),
            "last_traded_quantity": 100,
            "total_volume": 1000,
            "source_timestamp": self._now()
        }
        res = self.engine.process_tick(tick)
        self.assertEqual(res, MarketDataIntegrityState.REJECTED_MALFORMED)
        self.assertFalse(self.engine.fail_closed_check("AAPL"))

    def test_03_malformed_tick_negative_price(self):
        tick = {
            "symbol": "AAPL",
            "exchange": "NASDAQ",
            "provider_id": "P1",
            "last_traded_price": -10.0,
            "last_traded_quantity": 100,
            "total_volume": 1000,
            "source_timestamp": self._now()
        }
        res = self.engine.process_tick(tick)
        self.assertEqual(res, MarketDataIntegrityState.REJECTED_MALFORMED)

    def test_04_malformed_tick_infinity(self):
        tick = {
            "symbol": "AAPL",
            "exchange": "NASDAQ",
            "provider_id": "P1",
            "last_traded_price": float('inf'),
            "last_traded_quantity": 100,
            "total_volume": 1000,
            "source_timestamp": self._now()
        }
        res = self.engine.process_tick(tick)
        self.assertEqual(res, MarketDataIntegrityState.REJECTED_MALFORMED)

    def test_05_future_timestamp_rejection(self):
        tick = {
            "symbol": "AAPL",
            "exchange": "NASDAQ",
            "provider_id": "P1",
            "last_traded_price": 150.0,
            "last_traded_quantity": 100,
            "total_volume": 1000,
            "source_timestamp": self._now() + timedelta(seconds=10)
        }
        res = self.engine.process_tick(tick)
        self.assertEqual(res, MarketDataIntegrityState.REJECTED_FUTURE_DATE)

    def test_06_crossed_quote_rejection(self):
        quote = {
            "symbol": "AAPL",
            "exchange": "NASDAQ",
            "provider_id": "P1",
            "bid_price": 151.0,
            "bid_quantity": 100,
            "ask_price": 150.0,
            "ask_quantity": 100,
            "source_timestamp": self._now()
        }
        res = self.engine.process_quote(quote)
        self.assertEqual(res, MarketDataIntegrityState.REJECTED_CROSSED_QUOTE)

    def test_07_valid_quote_acceptance(self):
        quote = {
            "symbol": "AAPL",
            "exchange": "NASDAQ",
            "provider_id": "P1",
            "bid_price": 149.0,
            "bid_quantity": 100,
            "ask_price": 150.0,
            "ask_quantity": 100,
            "source_timestamp": self._now()
        }
        res = self.engine.process_quote(quote)
        self.assertEqual(res, MarketDataIntegrityState.VALID)

    # ---------------------------------------------------------
    # Engine Integrity & Sequences
    # ---------------------------------------------------------
    
    def test_08_stale_tick_rejection(self):
        tick = {
            "symbol": "AAPL",
            "exchange": "NASDAQ",
            "provider_id": "P1",
            "last_traded_price": 150.0,
            "last_traded_quantity": 100,
            "total_volume": 1000,
            "source_timestamp": self._now() - timedelta(seconds=10)
        }
        res = self.engine.process_tick(tick)
        self.assertEqual(res, MarketDataIntegrityState.REJECTED_STALE)

    def test_09_duplicate_tick_detection(self):
        now = self._now()
        tick = {
            "symbol": "AAPL", "exchange": "NASDAQ", "provider_id": "P1",
            "last_traded_price": 150.0, "last_traded_quantity": 100,
            "total_volume": 1000, "source_timestamp": now, "sequence_number": 1
        }
        self.assertEqual(self.engine.process_tick(tick), MarketDataIntegrityState.VALID)
        self.assertEqual(self.engine.process_tick(tick), MarketDataIntegrityState.REJECTED_DUPLICATE)

    def test_10_out_of_order_tick_detection_by_timestamp(self):
        now = self._now()
        tick1 = {
            "symbol": "AAPL", "exchange": "NASDAQ", "provider_id": "P1",
            "last_traded_price": 150.0, "last_traded_quantity": 100,
            "total_volume": 1000, "source_timestamp": now
        }
        tick2 = {
            "symbol": "AAPL", "exchange": "NASDAQ", "provider_id": "P1",
            "last_traded_price": 151.0, "last_traded_quantity": 100,
            "total_volume": 1100, "source_timestamp": now - timedelta(seconds=1)
        }
        self.assertEqual(self.engine.process_tick(tick1), MarketDataIntegrityState.VALID)
        self.assertEqual(self.engine.process_tick(tick2), MarketDataIntegrityState.REJECTED_OUT_OF_ORDER)

    def test_11_out_of_order_by_sequence(self):
        now = self._now()
        tick1 = {
            "symbol": "AAPL", "exchange": "NASDAQ", "provider_id": "P1",
            "last_traded_price": 150.0, "last_traded_quantity": 100,
            "total_volume": 1000, "source_timestamp": now, "sequence_number": 10
        }
        tick2 = {
            "symbol": "AAPL", "exchange": "NASDAQ", "provider_id": "P1",
            "last_traded_price": 151.0, "last_traded_quantity": 100,
            "total_volume": 1100, "source_timestamp": now, "sequence_number": 9
        }
        self.assertEqual(self.engine.process_tick(tick1), MarketDataIntegrityState.VALID)
        self.assertEqual(self.engine.process_tick(tick2), MarketDataIntegrityState.REJECTED_OUT_OF_ORDER)

    def test_12_sequence_gap_detection(self):
        now = self._now()
        tick1 = {
            "symbol": "AAPL", "exchange": "NASDAQ", "provider_id": "P1",
            "last_traded_price": 150.0, "last_traded_quantity": 100,
            "total_volume": 1000, "source_timestamp": now - timedelta(seconds=1), "sequence_number": 10
        }
        tick2 = {
            "symbol": "AAPL", "exchange": "NASDAQ", "provider_id": "P1",
            "last_traded_price": 151.0, "last_traded_quantity": 100,
            "total_volume": 1100, "source_timestamp": now, "sequence_number": 12 # Gap of 1
        }
        self.assertEqual(self.engine.process_tick(tick1), MarketDataIntegrityState.VALID)
        self.assertEqual(self.engine.process_tick(tick2), MarketDataIntegrityState.VALID)
        
        health = self.engine._get_health("AAPL", "P1")
        self.assertEqual(health.sequence_gaps, 1)
        
    def test_13_provider_failure_degradation(self):
        for i in range(4): # 4 invalid ticks
            tick = {
                "symbol": "TSLA", "exchange": "NASDAQ", "provider_id": "P2",
                "last_traded_price": -10.0, "last_traded_quantity": 100,
                "total_volume": 1000, "source_timestamp": self._now()
            }
            self.engine.process_tick(tick)
            
        health = self.engine._get_health("TSLA", "P2")
        self.assertEqual(health.status, "DEGRADED")
        
    def test_14_provider_failure_unavailable(self):
        for i in range(7): # > 5 invalid ticks
            tick = {
                "symbol": "TSLA", "exchange": "NASDAQ", "provider_id": "P2",
                "last_traded_price": -10.0, "last_traded_quantity": 100,
                "total_volume": 1000, "source_timestamp": self._now()
            }
            self.engine.process_tick(tick)
            
        health = self.engine._get_health("TSLA", "P2")
        self.assertEqual(health.status, "UNAVAILABLE")

    def test_15_provider_recovery(self):
        self.test_14_provider_failure_unavailable()
        
        tick = {
            "symbol": "TSLA", "exchange": "NASDAQ", "provider_id": "P2",
            "last_traded_price": 150.0, "last_traded_quantity": 100,
            "total_volume": 1000, "source_timestamp": self._now()
        }
        res = self.engine.process_tick(tick)
        self.assertEqual(res, MarketDataIntegrityState.VALID)
        health = self.engine._get_health("TSLA", "P2")
        self.assertEqual(health.status, "HEALTHY")

    def test_16_freshness_transition(self):
        tick = {
            "symbol": "MSFT", "exchange": "NASDAQ", "provider_id": "P1",
            "last_traded_price": 150.0, "last_traded_quantity": 100,
            "total_volume": 1000, "source_timestamp": self._now() - timedelta(seconds=4)
        }
        self.engine.process_tick(tick)
        self.assertTrue(self.engine.fail_closed_check("MSFT"))
        
        # Manually alter the timestamp to simulate time passing without a new tick
        snap = self.engine.get_snapshot("MSFT")
        # Change source timestamp to 6 seconds ago
        object.__setattr__(snap.latest_tick, 'source_timestamp', self._now() - timedelta(seconds=6))
        
        # Fail closed check should now fail because update_freshness will downgrade it
        self.assertFalse(self.engine.fail_closed_check("MSFT"))
        self.assertEqual(snap.freshness, MarketDataFreshness.STALE)

    # ---------------------------------------------------------
    # OHLC Validation
    # ---------------------------------------------------------
    def test_17_valid_ohlc(self):
        candle = OHLCCandle(
            symbol="AAPL", exchange="NASDAQ", provider_id="P1",
            open=150.0, high=151.0, low=149.0, close=150.5, volume=1000,
            start_timestamp=self._now() - timedelta(minutes=1),
            end_timestamp=self._now()
        )
        self.assertEqual(candle.symbol, "AAPL")

    def test_18_invalid_ohlc_high(self):
        with self.assertRaises(ValueError):
            OHLCCandle(
                symbol="AAPL", exchange="NASDAQ", provider_id="P1",
                open=150.0, high=140.0, low=149.0, close=150.5, volume=1000,
                start_timestamp=self._now() - timedelta(minutes=1),
                end_timestamp=self._now()
            )

    def test_19_invalid_ohlc_low(self):
        with self.assertRaises(ValueError):
            OHLCCandle(
                symbol="AAPL", exchange="NASDAQ", provider_id="P1",
                open=150.0, high=151.0, low=160.0, close=150.5, volume=1000,
                start_timestamp=self._now() - timedelta(minutes=1),
                end_timestamp=self._now()
            )

    def test_20_invalid_ohlc_timestamps(self):
        with self.assertRaises(ValueError):
            OHLCCandle(
                symbol="AAPL", exchange="NASDAQ", provider_id="P1",
                open=150.0, high=151.0, low=149.0, close=150.5, volume=1000,
                start_timestamp=self._now(),
                end_timestamp=self._now() - timedelta(minutes=1)
            )
            
    # ---------------------------------------------------------
    # Audit & Observability Integration
    # ---------------------------------------------------------
    def test_21_audit_events_emitted(self):
        tick = {
            "symbol": "AMZN", "exchange": "NASDAQ", "provider_id": "P1",
            "last_traded_price": 150.0, "last_traded_quantity": 100,
            "total_volume": 1000, "source_timestamp": self._now() + timedelta(seconds=10) # future
        }
        self.engine.process_tick(tick)
        
        events = global_audit_chain.query_events(category="MARKET_DATA")
        self.assertTrue(any(e.event_type == "MARKET_DATA_FUTURE_DATE" and e.symbol == "AMZN" for e in events))

    # ---------------------------------------------------------
    # Adversarial Scenarios
    # ---------------------------------------------------------
    
    def test_22_rapid_timestamp_changes_regression(self):
        now = self._now()
        # 1. Valid tick
        self.assertEqual(
            self.engine.process_tick({
                "symbol": "GOOG", "exchange": "NASDAQ", "provider_id": "P1",
                "last_traded_price": 150.0, "last_traded_quantity": 100,
                "total_volume": 1000, "source_timestamp": now, "sequence_number": 1
            }), MarketDataIntegrityState.VALID
        )
        # 2. Regression
        self.assertEqual(
            self.engine.process_tick({
                "symbol": "GOOG", "exchange": "NASDAQ", "provider_id": "P1",
                "last_traded_price": 150.0, "last_traded_quantity": 100,
                "total_volume": 1000, "source_timestamp": now - timedelta(seconds=1), "sequence_number": 2
            }), MarketDataIntegrityState.REJECTED_OUT_OF_ORDER
        )
        
    def test_23_provider_disappearing_mid_session(self):
        # Simulate ticking, then 10 seconds of silence, fail_closed should block
        now = self._now()
        self.engine.process_tick({
            "symbol": "FB", "exchange": "NASDAQ", "provider_id": "P1",
            "last_traded_price": 150.0, "last_traded_quantity": 100,
            "total_volume": 1000, "source_timestamp": now
        })
        self.assertTrue(self.engine.fail_closed_check("FB"))
        
        # 6 seconds pass (no ticks)
        snap = self.engine.get_snapshot("FB")
        object.__setattr__(snap.latest_tick, 'source_timestamp', now - timedelta(seconds=6))
        
        # Preflight should be blocked
        self.assertFalse(self.engine.fail_closed_check("FB"))

    def test_24_burst_ingestion(self):
        now = self._now() - timedelta(seconds=2)
        for i in range(100):
            res = self.engine.process_tick({
                "symbol": "BURST", "exchange": "NASDAQ", "provider_id": "P1",
                "last_traded_price": 150.0 + i, "last_traded_quantity": 100,
                "total_volume": 1000 + i, "source_timestamp": now + timedelta(milliseconds=i),
                "sequence_number": i
            })
            self.assertEqual(res, MarketDataIntegrityState.VALID)
            
        snap = self.engine.get_snapshot("BURST")
        self.assertEqual(snap.latest_tick.sequence_number, 99)

    def test_25_missing_market_data(self):
        # symbol never ticked
        self.assertFalse(self.engine.fail_closed_check("NEVER_SEEN"))
        
    def test_26_concurrent_updates_same_instrument(self):
        # Same sequence should reject as duplicate
        now = self._now()
        t1 = {
            "symbol": "CONC", "exchange": "NASDAQ", "provider_id": "P1",
            "last_traded_price": 150.0, "last_traded_quantity": 100,
            "total_volume": 1000, "source_timestamp": now, "sequence_number": 1
        }
        self.assertEqual(self.engine.process_tick(t1), MarketDataIntegrityState.VALID)
        self.assertEqual(self.engine.process_tick(t1), MarketDataIntegrityState.REJECTED_DUPLICATE)

    def test_27_restart_behavior(self):
        # Fresh instance shouldn't trust old data
        engine2 = MarketDataIntegrityEngine()
        self.assertFalse(engine2.fail_closed_check("AAPL"))

    def test_28_clock_skew_adversarial(self):
        # If client's clock is way in the future, reject
        t1 = {
            "symbol": "SKEW", "exchange": "NASDAQ", "provider_id": "P1",
            "last_traded_price": 150.0, "last_traded_quantity": 100,
            "total_volume": 1000, "source_timestamp": self._now() + timedelta(days=1), "sequence_number": 1
        }
        self.assertEqual(self.engine.process_tick(t1), MarketDataIntegrityState.REJECTED_FUTURE_DATE)

    def test_29_quote_stale_rejection(self):
        q = {
            "symbol": "QSTALE", "exchange": "NASDAQ", "provider_id": "P1",
            "bid_price": 149.0, "bid_quantity": 100, "ask_price": 150.0, "ask_quantity": 100,
            "source_timestamp": self._now() - timedelta(seconds=10)
        }
        self.assertEqual(self.engine.process_quote(q), MarketDataIntegrityState.REJECTED_STALE)

    def test_30_fail_closed_after_quote_stale(self):
        now = self._now()
        # Tick is fresh
        self.engine.process_tick({
            "symbol": "MIXED", "exchange": "NASDAQ", "provider_id": "P1",
            "last_traded_price": 150.0, "last_traded_quantity": 100,
            "total_volume": 1000, "source_timestamp": now, "sequence_number": 1
        })
        self.assertTrue(self.engine.fail_closed_check("MIXED"))
        
        # Quote is processed but then ages
        self.engine.process_quote({
            "symbol": "MIXED", "exchange": "NASDAQ", "provider_id": "P1",
            "bid_price": 149.0, "bid_quantity": 100, "ask_price": 150.0, "ask_quantity": 100,
            "source_timestamp": now
        })
        self.assertTrue(self.engine.fail_closed_check("MIXED"))
        
        snap = self.engine.get_snapshot("MIXED")
        object.__setattr__(snap.latest_quote, 'source_timestamp', now - timedelta(seconds=10))
        
        # tick is fresh, but quote is stale! Wait, update_freshness will downgrade freshness to STALE if ANY of tick/quote is stale
        self.assertFalse(self.engine.fail_closed_check("MIXED"))
        
    def test_31_ai_boundary_enforcement(self):
        # AI metadata cannot override invalid data
        # In reality, this is testing that fail_closed_check doesn't have an "ai_override" parameter
        # and relies strictly on the schema's deterministic validation.
        # This asserts the design constraint is preserved.
        with self.assertRaises(TypeError):
            self.engine.fail_closed_check("AAPL", ai_override=True)

if __name__ == '__main__':
    unittest.main()
