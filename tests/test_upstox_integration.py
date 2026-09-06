import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from backend.application.market_data_normalizer import MarketDataNormalizer
from backend.config.app_config import AppConfig, get_app_config
from backend.infrastructure.security_master import get_security_master
from backend.application.stock_analysis_engine import StockAnalysisEngine
from backend.domain.stock_schemas import StockFundamentalData, StockTechnicalData, StockDecision
from backend.domain.ipo_schemas import IPOMaster, IPOStatus, IPOType
from backend.application.market_data_integrity_engine import MarketDataIntegrityEngine
from backend.execution.live_execution_gate import global_live_execution_gate

def test_normalize_upstox_ff_ltpc():
    # Simulate Upstox V3 FullFeed payload with marketFF
    msg = {
        "fullFeed": {
            "marketFF": {
                "ltpc": {
                    "ltp": 2500.50,
                    "cp": 2490.00,
                    "ltq": "25",
                    "ltt": "1690000000000"
                },
                "vtt": "150000",
                "atp": 2495.0,
                "marketLevel": {
                    "bidAskQuote": [
                        {"bidP": 2500.0, "bidQ": "100", "askP": 2501.0, "askQ": "200"}
                    ]
                },
                "marketOHLC": {
                    "ohlc": [
                        {"open": 2490.0, "high": 2510.0, "low": 2485.0, "close": 2500.5, "vol": "150000"}
                    ]
                }
            }
        }
    }
    
    normalized = MarketDataNormalizer.normalize_upstox_tick("NSE_EQ|INE002A01018", "RELIANCE", msg)
    assert normalized is not None
    assert normalized["symbol"] == "RELIANCE"
    assert normalized["last_traded_price"] == 2500.50
    assert normalized["total_volume"] == 150000
    assert normalized["last_traded_quantity"] == 25
    assert normalized["previous_close"] == 2490.00
    assert normalized["atp"] == 2495.0
    assert normalized["bid"] == 2500.0
    assert normalized["ask"] == 2501.0
    assert normalized["bid_quantity"] == 100
    assert normalized["ask_quantity"] == 200
    assert normalized["open"] == 2490.0
    assert normalized["high"] == 2510.0
    assert normalized["low"] == 2485.0
    assert normalized["provider_id"] == "upstox"

def test_normalize_upstox_index_ff():
    # Simulate Upstox Index Full Feed
    msg = {
        "fullFeed": {
            "indexFF": {
                "ltpc": {
                    "ltp": 24500.25,
                    "cp": 24400.0,
                    "ltt": "1690000000000"
                },
                "marketOHLC": {
                    "ohlc": [
                        {"open": 24450.0, "high": 24550.0, "low": 24400.0, "close": 24500.25}
                    ]
                }
            }
        }
    }
    normalized = MarketDataNormalizer.normalize_upstox_tick("NSE_INDEX|Nifty 50", "NIFTY 50", msg)
    assert normalized is not None
    assert normalized["last_traded_price"] == 24500.25
    assert normalized["open"] == 24450.0
    assert normalized["high"] == 24550.0

def test_normalize_upstox_ltp_only():
    msg = {
        "ltp": 1400.25,
        "exchangeTimeStamp": 1690000000000
    }
    normalized = MarketDataNormalizer.normalize_upstox_tick("NSE_EQ|INE123", "HDFCBANK", msg)
    assert normalized is not None
    assert normalized["last_traded_price"] == 1400.25

def test_normalize_upstox_invalid():
    msg = {"heartbeat": True}
    normalized = MarketDataNormalizer.normalize_upstox_tick("NSE_EQ|INE123", "TCS", msg)
    assert normalized is None

def test_security_master_dynamic_resolution():
    sm = get_security_master()
    test_symbols = ["TCS", "RELIANCE", "HDFCBANK", "INFY", "ICICIBANK"]
    for sym in test_symbols:
        sec = sm.resolve_symbol(sym)
        assert sec is not None, f"Failed to resolve {sym}"
        assert sec.canonical_symbol == sym
        assert sec.exchange == "NSE"
        assert sec.upstox_instrument_token is not None, f"Missing Upstox token for {sym}"
        assert sec.upstox_instrument_token.startswith("NSE_EQ|")

@pytest.mark.asyncio
async def test_stock_analysis_engine_insufficient_data():
    engine = StockAnalysisEngine()
    # When technicals or fundamentals are None, must return INSUFFICIENT_DATA
    res = await engine.analyze_stock("TCS", None, None)
    assert res.decision == StockDecision.INSUFFICIENT_DATA
    assert res.verdict == "INSUFFICIENT_DATA"
    assert res.overall_score == 0.0
    assert len(res.risk_warnings) > 0

@pytest.mark.asyncio
async def test_stock_analysis_engine_deterministic_classifications():
    engine = StockAnalysisEngine()
    
    # Bullish scenario
    f_bull = StockFundamentalData(symbol="TCS", roe=25.0, revenue_growth=20.0, debt_equity=0.2, pe=14.0, pb=1.8, promoter_holding=70.0)
    t_bull = StockTechnicalData(symbol="TCS", current_price=3500.0, sma_200=3000.0, rsi_14=55.0, macd=10.0, macd_signal=5.0)
    res_bull = await engine.analyze_stock("TCS", f_bull, t_bull)
    assert res_bull.decision == StockDecision.BULLISH
    assert res_bull.confidence > 0.6

    # Bearish scenario
    f_bear = StockFundamentalData(symbol="WEAK", roe=2.0, revenue_growth=-10.0, debt_equity=2.5, pe=60.0)
    t_bear = StockTechnicalData(symbol="WEAK", current_price=100.0, sma_200=150.0, rsi_14=25.0, macd=-5.0, macd_signal=0.0)
    res_bear = await engine.analyze_stock("WEAK", f_bear, t_bear)
    assert res_bear.decision in (StockDecision.BEARISH, StockDecision.HOLD, StockDecision.REJECT)

    # Reject scenario (extreme risk)
    f_risk = StockFundamentalData(symbol="RISKY", roe=25.0, promoter_pledge=50.0) # >25% promoter pledge
    t_risk = StockTechnicalData(symbol="RISKY", current_price=200.0)
    res_risk = await engine.analyze_stock("RISKY", f_risk, t_risk)
    assert res_risk.decision == StockDecision.REJECT

def test_ipo_minimum_investment_calculation():
    # 1. With issue_price
    ipo1 = IPOMaster(
        id="IPO_TEST_1",
        company_name="Test Company",
        exchange="NSE",
        segment=IPOType.MAINBOARD,
        status=IPOStatus.OPEN,
        issue_price=100.0,
        lot_size=150,
        minimum_application_lots=1
    )
    assert ipo1.minimum_investment == 15000.0

    # 2. With price_band_low when issue_price not yet decided
    ipo2 = IPOMaster(
        id="IPO_TEST_2",
        company_name="Test Company 2",
        exchange="NSE",
        segment=IPOType.MAINBOARD,
        status=IPOStatus.UPCOMING,
        price_band_low=450.0,
        price_band_high=475.0,
        lot_size=30,
        minimum_application_lots=1
    )
    # the schema now prefers band low based on priority
    assert ipo2.minimum_investment == 13500.0

def test_market_data_integrity_stale_detection():
    engine = MarketDataIntegrityEngine(stale_threshold_seconds=1.0)
    stale_tick = {
        "symbol": "TCS",
        "exchange": "NSE",
        "provider_id": "upstox",
        "last_traded_price": 3500.0,
        "last_traded_quantity": 10,
        "total_volume": 1000,
        "source_timestamp": datetime.now(timezone.utc) - timedelta(seconds=10) # 10s old
    }
    state = engine.process_tick(stale_tick)
    # Stale tick should be rejected
    from backend.domain.market_data_schemas import MarketDataIntegrityState
    assert state == MarketDataIntegrityState.REJECTED_STALE

def test_safety_gate_remains_locked_without_live_market_data():
    from backend.domain.broker_schemas import OrderRequest, OrderSide, OrderType, ProductType, ExchangeSegment
    gate = global_live_execution_gate
    gate.market_data_engine.snapshots.clear()
    
    order = OrderRequest(
        symbol="TCS",
        exchange_segment=ExchangeSegment.NSE,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        product_type=ProductType.MIS,
        quantity=1,
        price=3500.0
    )
    result = gate.evaluate_live_order(order, operator_token_id="test_op")
    assert not result.is_approved
    assert "locked" in result.reason.lower() or "disarmed" in result.reason.lower() or "stale" in result.reason.lower() or "disabled" in result.reason.lower() or "rejected" in result.reason.lower()


