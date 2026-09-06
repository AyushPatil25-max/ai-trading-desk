import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import time

logger = logging.getLogger(__name__)

class MarketDataNormalizer:
    @staticmethod
    def normalize_upstox_tick(instrument_token: str, symbol: str, msg: Dict[str, Any], exchange: str = "NSE") -> Optional[Dict[str, Any]]:
        """
        Translates Upstox protobuf-decoded dict into a standard raw_tick_dict.
        Handles fullFeed (marketFF, indexFF) and ltpc modes.
        """
        try:
            if not isinstance(msg, dict):
                return None

            ltp = None
            ltq = 1
            close_price = None
            ltt = None
            volume = 0
            atp = None
            open_price = None
            high_price = None
            low_price = None
            bid_price = None
            ask_price = None
            bid_qty = None
            ask_qty = None

            # 1. Direct LTP
            if "ltp" in msg:
                ltp = float(msg.get("ltp", 0.0))

            # 2. Extract from ltpc block (root or inside fullFeed)
            ltpc_block = msg.get("ltpc")
            
            # Check fullFeed structures
            full_feed = msg.get("fullFeed") or msg.get("ff")
            if isinstance(full_feed, dict):
                market_ff = full_feed.get("marketFF")
                index_ff = full_feed.get("indexFF")
                
                if isinstance(market_ff, dict):
                    if not ltpc_block and "ltpc" in market_ff:
                        ltpc_block = market_ff["ltpc"]
                    if "atp" in market_ff:
                        atp = float(market_ff["atp"])
                    if "vtt" in market_ff:
                        volume = int(market_ff["vtt"])
                    # Market Depth / Bids & Asks
                    market_level = market_ff.get("marketLevel")
                    if isinstance(market_level, dict) and "bidAskQuote" in market_level:
                        quotes = market_level["bidAskQuote"]
                        if isinstance(quotes, list) and len(quotes) > 0 and isinstance(quotes[0], dict):
                            best_quote = quotes[0]
                            bid_price = float(best_quote.get("bidP", 0.0)) or None
                            ask_price = float(best_quote.get("askP", 0.0)) or None
                            bid_qty = int(best_quote.get("bidQ", 0)) or None
                            ask_qty = int(best_quote.get("askQ", 0)) or None
                    # OHLC
                    market_ohlc = market_ff.get("marketOHLC")
                    if isinstance(market_ohlc, dict) and "ohlc" in market_ohlc:
                        ohlc_list = market_ohlc["ohlc"]
                        if isinstance(ohlc_list, list) and len(ohlc_list) > 0 and isinstance(ohlc_list[-1], dict):
                            c = ohlc_list[-1]
                            open_price = float(c.get("open", 0.0)) or None
                            high_price = float(c.get("high", 0.0)) or None
                            low_price = float(c.get("low", 0.0)) or None
                            if not volume and "vol" in c:
                                volume = int(c["vol"])
                                
                elif isinstance(index_ff, dict):
                    if not ltpc_block and "ltpc" in index_ff:
                        ltpc_block = index_ff["ltpc"]
                    market_ohlc = index_ff.get("marketOHLC")
                    if isinstance(market_ohlc, dict) and "ohlc" in market_ohlc:
                        ohlc_list = market_ohlc["ohlc"]
                        if isinstance(ohlc_list, list) and len(ohlc_list) > 0 and isinstance(ohlc_list[-1], dict):
                            c = ohlc_list[-1]
                            open_price = float(c.get("open", 0.0)) or None
                            high_price = float(c.get("high", 0.0)) or None
                            low_price = float(c.get("low", 0.0)) or None

            # Parse ltpc block if found
            if isinstance(ltpc_block, dict):
                if ltp is None and "ltp" in ltpc_block:
                    ltp = float(ltpc_block["ltp"])
                if "ltq" in ltpc_block:
                    ltq = int(ltpc_block["ltq"])
                if "cp" in ltpc_block:
                    close_price = float(ltpc_block["cp"])
                if "ltt" in ltpc_block:
                    ltt = ltpc_block["ltt"]

            if ltp is None:
                return None

            # Exchange timestamp resolution
            ts_exchange = None
            if ltt is not None:
                try:
                    ts_exchange = int(ltt)
                except (ValueError, TypeError):
                    pass
            if not ts_exchange:
                ts_msg = msg.get("currentTs") or msg.get("exchangeTimeStamp")
                if ts_msg is not None:
                    try:
                        ts_exchange = int(ts_msg)
                    except (ValueError, TypeError):
                        pass

            if not ts_exchange or ts_exchange <= 0:
                ts_exchange = int(time.time() * 1000)

            # Requires: symbol, exchange, provider_id, last_traded_price, last_traded_quantity, total_volume, source_timestamp
            raw_tick_dict = {
                "symbol": symbol,
                "exchange": exchange,
                "provider_id": "upstox",
                "last_traded_price": max(0.01, ltp),
                "last_traded_quantity": max(1, ltq),
                "total_volume": max(1, volume),
                "source_timestamp": datetime.fromtimestamp(ts_exchange / 1000.0, timezone.utc),
                # Additional fields for market depth and analytics
                "instrument_token": instrument_token,
                "previous_close": close_price,
                "atp": atp,
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "bid": bid_price,
                "ask": ask_price,
                "bid_quantity": bid_qty,
                "ask_quantity": ask_qty,
            }
            
            return raw_tick_dict
        except Exception as e:
            logger.error(f"Error normalizing Upstox tick for {symbol}: {e}")
            return None
