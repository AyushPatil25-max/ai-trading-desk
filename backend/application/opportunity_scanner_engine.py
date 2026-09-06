import logging
import asyncio
from typing import List, Optional, Tuple
import pandas as pd
from datetime import datetime

from backend.infrastructure.providers.market_data_provider import get_market_data_provider
from backend.application.market_data_gateway import get_market_data_gateway
from backend.infrastructure.providers.technical_indicators import (
    calc_sma, calc_ema, calc_rsi, calc_macd, calc_atr, calc_bollinger_bands, calc_pivot_points
)
from backend.application.stock_analysis_engine import StockAnalysisEngine
from backend.domain.opportunity_scanner_schemas import (
    OpportunityScannerResult, ScannerBatchResult, ScannerIdentity, ScannerMarketData,
    ScannerTechnicalData, ScannerSignals, ScannerFundamentalData, ScannerOpportunity, ScannerRiskData,
    MarketDataState, TrendClassification, BreakoutStatus, ReversalStatus, VolumeStatus,
    GapStatus, MultiTimeframeAlignment, OpportunityType, OpportunityDirection
)

try:
    from backend.application.market_data_integrity_engine import get_market_data_integrity_engine
except ImportError:
    from backend.execution.live_execution_gate import global_live_execution_gate
    def get_market_data_integrity_engine():
        return global_live_execution_gate.market_data_engine

logger = logging.getLogger(__name__)

class OpportunityScannerEngine:
    def __init__(self):
        self.provider = get_market_data_provider()
        self.gateway = get_market_data_gateway()
        self.integrity_engine = get_market_data_integrity_engine()
        self.stock_engine = StockAnalysisEngine()

    async def scan_single(self, symbol: str) -> Optional[OpportunityScannerResult]:
        try:
            # 1. Fetch Daily OHLCV
            raw_data = await self.provider.get_historical_ohlcv(symbol, '1y', '1d')
            if raw_data is None:
                return self._create_insufficient_data_result(symbol)
                
            df = raw_data if isinstance(raw_data, pd.DataFrame) else pd.DataFrame(raw_data)
            if df.empty or len(df) < 50:
                return self._create_insufficient_data_result(symbol)

            # Check if DatetimeIndex exists for weekly resampling, otherwise MTF unavailable
            mtf_alignment = MultiTimeframeAlignment.INSUFFICIENT_DATA
            if isinstance(df.index, pd.DatetimeIndex) and len(df) >= 100:
                try:
                    weekly_df = df.resample('W').agg({'Open':'first', 'High':'max', 'Low':'min', 'Close':'last', 'Volume':'sum'}).dropna()
                    if len(weekly_df) >= 20:
                        w_close = weekly_df['Close']
                        w_sma20 = calc_sma(w_close, 20).iloc[-1]
                        if pd.notna(w_sma20):
                            w_trend_up = float(w_close.iloc[-1]) > float(w_sma20)
                            w_trend_down = float(w_close.iloc[-1]) < float(w_sma20)
                            # We'll set MTF alignment later after daily trend is calculated
                except Exception:
                    pass

            # 2. Fetch Live Quote & Check Integrity
            quote = self.gateway.get_latest_quote(symbol)
            is_valid = self.integrity_engine.fail_closed_check(symbol)
            
            close_col = 'Close' if 'Close' in df.columns else 'close'
            high_col = 'High' if 'High' in df.columns else 'high'
            low_col = 'Low' if 'Low' in df.columns else 'low'
            vol_col = 'Volume' if 'Volume' in df.columns else 'volume'
            open_col = 'Open' if 'Open' in df.columns else 'open'
            
            # LIVE DATA SEMANTICS
            if quote:
                ltp = float(quote.get("last_traded_price") or quote.get("ltp") or df[close_col].iloc[-1])
                current_vol = float(quote.get("volume") or df[vol_col].iloc[-1])
                if is_valid:
                    data_quality = MarketDataState.LIVE
                else:
                    data_quality = MarketDataState.STALE
            else:
                ltp = float(df[close_col].iloc[-1])
                current_vol = float(df[vol_col].iloc[-1])
                data_quality = MarketDataState.HISTORICAL
                
            close = df[close_col].astype(float)
            high = df[high_col].astype(float)
            low = df[low_col].astype(float)
            volume = df[vol_col].astype(float)
            
            def safe_float(val):
                return float(val) if pd.notna(val) else None

            # 3. Technical Indicators
            sma20 = safe_float(calc_sma(close, 20).iloc[-1])
            sma50 = safe_float(calc_sma(close, 50).iloc[-1])
            sma200 = safe_float(calc_sma(close, 200).iloc[-1])
            ema20 = safe_float(calc_ema(close, 20).iloc[-1])
            ema50 = safe_float(calc_ema(close, 50).iloc[-1])
            rsi14 = safe_float(calc_rsi(close, 14).iloc[-1])
            
            macd, macd_signal_s, _ = calc_macd(close)
            macd_curr = safe_float(macd.iloc[-1])
            macd_sig_curr = safe_float(macd_signal_s.iloc[-1])
            macd_prev = safe_float(macd.iloc[-2]) if len(macd) > 1 else None
            macd_sig_prev = safe_float(macd_signal_s.iloc[-2]) if len(macd_signal_s) > 1 else None
            
            atr = safe_float(calc_atr(high, low, close).iloc[-1])
            
            # SHIFTED technicals for breakout resistance levels (prior candle)
            bb_upper, bb_mid, bb_lower = calc_bollinger_bands(close)
            bbu_prev = safe_float(bb_upper.shift(1).iloc[-1])
            bbl_prev = safe_float(bb_lower.shift(1).iloc[-1])
            
            pivots = calc_pivot_points(float(high.iloc[-2]), float(low.iloc[-2]), float(close.iloc[-2])) if len(df) > 1 else {}
            res1 = pivots.get('R1')
            sup1 = pivots.get('S1')
            
            # 4. Liquidity & Volume
            vol_sma20 = safe_float(volume.shift(1).rolling(20).mean().iloc[-1])
            avg_traded_value = None
            liquidity_class = "LOW"
            if vol_sma20 and sma20:
                avg_traded_value = vol_sma20 * sma20
                if avg_traded_value > 10000000: # 1 Crore
                    liquidity_class = "HIGH"
                elif avg_traded_value > 2500000: # 25 Lakh
                    liquidity_class = "MODERATE"
            
            volume_spike_signal = VolumeStatus.NORMAL
            vol_ratio = None
            if vol_sma20 and vol_sma20 > 0:
                vol_ratio = float(current_vol / vol_sma20)
                if vol_ratio > 3.0:
                    volume_spike_signal = VolumeStatus.EXTREME
                elif vol_ratio > 1.5:
                    volume_spike_signal = VolumeStatus.VOLUME_SPIKE
                elif vol_ratio > 1.2:
                    volume_spike_signal = VolumeStatus.ELEVATED
            
            # 5. Breakout / Breakdown (vs prior levels)
            breakout_signal = BreakoutStatus.NONE
            b_level = bbu_prev if bbu_prev else res1
            s_level = bbl_prev if bbl_prev else sup1
            
            if b_level:
                if ltp > b_level:
                    if vol_ratio and vol_ratio > 1.2:
                        breakout_signal = BreakoutStatus.CONFIRMED_BREAKOUT
                    else:
                        breakout_signal = BreakoutStatus.POTENTIAL_BREAKOUT
                elif float(high.iloc[-1]) > b_level and ltp <= b_level:
                    breakout_signal = BreakoutStatus.FAILED_BREAKOUT
                    
            if s_level and breakout_signal == BreakoutStatus.NONE:
                if ltp < s_level:
                    if vol_ratio and vol_ratio > 1.2:
                        breakout_signal = BreakoutStatus.CONFIRMED_BREAKDOWN
                    else:
                        breakout_signal = BreakoutStatus.POTENTIAL_BREAKDOWN
                elif float(low.iloc[-1]) < s_level and ltp >= s_level:
                    breakout_signal = BreakoutStatus.FAILED_BREAKDOWN
                
            # 6. Momentum
            momentum_signal = False
            if rsi14 is not None and macd_curr is not None and macd_sig_curr is not None:
                if (rsi14 > 55) and (macd_curr > macd_sig_curr) and (ltp > (ema20 or 0)):
                    momentum_signal = True
                elif (rsi14 < 45) and (macd_curr < macd_sig_curr) and (ltp < (ema20 or 999999)):
                    momentum_signal = True # bearish momentum
                
            # 7. Reversal (MACD Crossover confirmed by RSI extremes)
            reversal_signal = ReversalStatus.NONE
            if macd_curr is not None and macd_prev is not None and macd_sig_curr is not None and macd_sig_prev is not None:
                bullish_cross = macd_prev <= macd_sig_prev and macd_curr > macd_sig_curr
                bearish_cross = macd_prev >= macd_sig_prev and macd_curr < macd_sig_curr
                
                if bullish_cross and rsi14 and rsi14 < 40: # Allow slightly wider net than 30 for confirming crossovers
                    reversal_signal = ReversalStatus.POTENTIAL_BULLISH_REVERSAL
                elif bearish_cross and rsi14 and rsi14 > 60:
                    reversal_signal = ReversalStatus.POTENTIAL_BEARISH_REVERSAL
                
            # 8. Gap
            gap_signal = GapStatus.NONE
            gap_dir = None
            gap_pct = None
            if len(df) > 1:
                prev_close = safe_float(close.iloc[-2])
                curr_open = safe_float(df[open_col].iloc[-1])
                if prev_close and curr_open and prev_close > 0:
                    gap = (curr_open - prev_close) / prev_close
                    gap_pct = abs(gap) * 100
                    if gap_pct > 2.0:
                        gap_signal = GapStatus.LARGE_GAP
                    elif gap_pct > 0.5:
                        gap_signal = GapStatus.MEANINGFUL_GAP
                    elif gap_pct > 0.1:
                        gap_signal = GapStatus.SMALL_GAP
                        
                    if gap_signal != GapStatus.NONE:
                        gap_dir = OpportunityDirection.BULLISH if gap > 0 else OpportunityDirection.BEARISH
                    
            # 9. Trend Classification
            trend_signal = TrendClassification.SIDEWAYS
            if sma50 and sma200 and ema20:
                if ltp > sma50 and sma50 > sma200:
                    if ltp > ema20:
                        trend_signal = TrendClassification.STRONG_UPTREND
                    else:
                        trend_signal = TrendClassification.UPTREND
                elif ltp < sma50 and sma50 < sma200:
                    if ltp < ema20:
                        trend_signal = TrendClassification.STRONG_DOWNTREND
                    else:
                        trend_signal = TrendClassification.DOWNTREND
                        
            # Set MTF Alignment now that we have daily trend
            try:
                if 'w_trend_up' in locals():
                    d_trend_up = trend_signal in [TrendClassification.UPTREND, TrendClassification.STRONG_UPTREND]
                    d_trend_down = trend_signal in [TrendClassification.DOWNTREND, TrendClassification.STRONG_DOWNTREND]
                    if w_trend_up and d_trend_up:
                        mtf_alignment = MultiTimeframeAlignment.ALIGNED_BULLISH
                    elif w_trend_down and d_trend_down:
                        mtf_alignment = MultiTimeframeAlignment.ALIGNED_BEARISH
                    else:
                        mtf_alignment = MultiTimeframeAlignment.MIXED
            except Exception:
                pass
                
            # 10. 52W High Breakout (Shifted)
            high52w_prev = safe_float(high.shift(1).rolling(252).max().iloc[-1])
            low52w_prev = safe_float(low.shift(1).rolling(252).min().iloc[-1])
            fifty_two_week_high_signal = False
            fifty_two_week_low_signal = False
            if high52w_prev and ltp >= high52w_prev * 0.98:
                fifty_two_week_high_signal = True
            if low52w_prev and ltp <= low52w_prev * 1.02:
                fifty_two_week_low_signal = True
                
            # 11. Fundamentals and Valuation
            fundamental_data = await self.provider.get_fundamentals(symbol)
            f_score_obj = self.stock_engine._analyze_fundamental(fundamental_data)
            v_score_obj, v_rationale = self.stock_engine._analyze_valuation(fundamental_data, None)
            
            f_score = f_score_obj.score if f_score_obj.score > 0 else None
            v_score = v_score_obj.score if v_score_obj.score > 0 else None
            f_conf = f_score_obj.confidence
                    
            # 12. Priority logic for OpportunityType
            opp_type = OpportunityType.MEAN_REVERSION
            if fifty_two_week_high_signal and breakout_signal in [BreakoutStatus.POTENTIAL_BREAKOUT, BreakoutStatus.CONFIRMED_BREAKOUT]:
                opp_type = OpportunityType.FIFTY_TWO_W_HIGH_BREAKOUT
            elif breakout_signal in [BreakoutStatus.POTENTIAL_BREAKOUT, BreakoutStatus.CONFIRMED_BREAKOUT]:
                opp_type = OpportunityType.BREAKOUT
            elif breakout_signal in [BreakoutStatus.POTENTIAL_BREAKDOWN, BreakoutStatus.CONFIRMED_BREAKDOWN]:
                opp_type = OpportunityType.BREAKDOWN
            elif trend_signal in [TrendClassification.UPTREND, TrendClassification.STRONG_UPTREND] and momentum_signal:
                opp_type = OpportunityType.TREND_CONTINUATION
            elif reversal_signal != ReversalStatus.NONE:
                opp_type = OpportunityType.REVERSAL
            elif gap_signal != GapStatus.NONE:
                opp_type = OpportunityType.GAP_UP if gap_dir == OpportunityDirection.BULLISH else OpportunityType.GAP_DOWN
            elif volume_spike_signal in [VolumeStatus.VOLUME_SPIKE, VolumeStatus.EXTREME]:
                opp_type = OpportunityType.VOLUME_SPIKE
            elif momentum_signal:
                opp_type = OpportunityType.MOMENTUM
                
            direction = OpportunityDirection.NEUTRAL
            if opp_type in [OpportunityType.BREAKOUT, OpportunityType.FIFTY_TWO_W_HIGH_BREAKOUT, OpportunityType.TREND_CONTINUATION, OpportunityType.GAP_UP]:
                direction = OpportunityDirection.BULLISH
            elif opp_type in [OpportunityType.BREAKDOWN, OpportunityType.GAP_DOWN]:
                direction = OpportunityDirection.BEARISH
            elif opp_type == OpportunityType.REVERSAL:
                direction = OpportunityDirection.BULLISH if reversal_signal == ReversalStatus.POTENTIAL_BULLISH_REVERSAL else OpportunityDirection.BEARISH
            elif opp_type == OpportunityType.MOMENTUM:
                direction = OpportunityDirection.BULLISH if (rsi14 and rsi14 > 50) else OpportunityDirection.BEARISH
                
            # 13. Risk/Reward Calculation
            # Must be strictly structurally valid
            sl_ref = None
            tgt_ref = None
            if direction == OpportunityDirection.BULLISH:
                if sup1 and ltp > sup1: sl_ref = sup1
                if res1 and res1 > ltp: tgt_ref = res1
            elif direction == OpportunityDirection.BEARISH:
                if res1 and ltp < res1: sl_ref = res1
                if sup1 and sup1 < ltp: tgt_ref = sup1
                
            risk_reward = None
            if sl_ref and tgt_ref and ltp:
                if direction == OpportunityDirection.BULLISH:
                    risk = ltp - sl_ref
                    reward = tgt_ref - ltp
                else:
                    risk = sl_ref - ltp
                    reward = ltp - tgt_ref
                    
                if risk > 0 and reward > 0:
                    risk_reward = float(reward / risk)
            
            # 14. Confidence & Score Calculation
            confidence = 0.0
            score = 0.0
            
            # Confidence components (Bounded to 1.0)
            if data_quality == MarketDataState.LIVE: confidence += 0.3
            elif data_quality == MarketDataState.STALE: confidence += 0.15
            elif data_quality == MarketDataState.HISTORICAL: confidence += 0.2
            
            if f_conf > 0.5: confidence += 0.2
            elif f_conf > 0: confidence += 0.1
            
            if mtf_alignment in [MultiTimeframeAlignment.ALIGNED_BULLISH, MultiTimeframeAlignment.ALIGNED_BEARISH]:
                confidence += 0.2
            elif mtf_alignment == MultiTimeframeAlignment.MIXED:
                confidence += 0.1
                
            if liquidity_class == "HIGH": confidence += 0.2
            elif liquidity_class == "MODERATE": confidence += 0.1
            
            if vol_ratio and vol_ratio > 1.5: confidence += 0.1
            
            confidence = min(1.0, max(0.0, confidence))
            
            # Score components (Bounded to 100)
            # Technicals (30%)
            if trend_signal in [TrendClassification.STRONG_UPTREND, TrendClassification.STRONG_DOWNTREND]: score += 30.0
            elif trend_signal in [TrendClassification.UPTREND, TrendClassification.DOWNTREND]: score += 20.0
            elif trend_signal == TrendClassification.SIDEWAYS: score += 10.0
            
            # Fundamentals (20%)
            if f_score: score += (f_score / 100.0) * 20.0
            if v_score: score += (v_score / 100.0) * 10.0 # extra 10%
            
            # Setup (30%)
            if opp_type in [OpportunityType.BREAKOUT, OpportunityType.FIFTY_TWO_W_HIGH_BREAKOUT]: score += 30.0
            elif opp_type in [OpportunityType.REVERSAL, OpportunityType.GAP_UP, OpportunityType.GAP_DOWN, OpportunityType.VOLUME_SPIKE]: score += 20.0
            elif opp_type in [OpportunityType.TREND_CONTINUATION, OpportunityType.MOMENTUM]: score += 25.0
            
            # Risk/Reward & Liquidity (10%)
            if risk_reward and risk_reward > 2.0: score += 10.0
            elif risk_reward and risk_reward > 1.0: score += 5.0
            
            score = min(100.0, max(0.0, score))
            
            return OpportunityScannerResult(
                identity=ScannerIdentity(symbol=symbol),
                market=ScannerMarketData(
                    ltp=ltp, 
                    volume=int(current_vol) if pd.notna(current_vol) else 0, 
                    average_volume=vol_sma20, 
                    volume_ratio=vol_ratio, 
                    average_traded_value=avg_traded_value,
                    liquidity_classification=liquidity_class,
                    data_quality=data_quality
                ),
                technical=ScannerTechnicalData(
                    trend=trend_signal,
                    sma_20=sma20, sma_50=sma50, sma_200=sma200,
                    ema_20=ema20, ema_50=ema50,
                    rsi_14=rsi14, macd=macd_curr, macd_signal=macd_sig_curr,
                    atr=atr, bollinger_upper=bbu_prev, bollinger_lower=bbl_prev,
                    pivot_level=pivots.get('pivot'),
                    support=sup1, resistance=res1
                ),
                signals=ScannerSignals(
                    momentum_signal=momentum_signal,
                    breakout_signal=breakout_signal,
                    breakdown_signal=breakout_signal if breakout_signal in [BreakoutStatus.POTENTIAL_BREAKDOWN, BreakoutStatus.CONFIRMED_BREAKDOWN, BreakoutStatus.FAILED_BREAKDOWN] else BreakoutStatus.NONE,
                    reversal_signal=reversal_signal,
                    volume_spike_signal=volume_spike_signal,
                    gap_signal=gap_signal, gap_direction=gap_dir, gap_percent=gap_pct,
                    trend_signal=trend_signal,
                    multi_timeframe_alignment=mtf_alignment,
                    fifty_two_week_high_signal=fifty_two_week_high_signal,
                    fifty_two_week_low_signal=fifty_two_week_low_signal
                ),
                fundamental=ScannerFundamentalData(fundamental_score=f_score, valuation_score=v_score),
                opportunity=ScannerOpportunity(
                    opportunity_score=score,
                    confidence=confidence,
                    opportunity_type=opp_type,
                    direction=direction,
                    rationale=f"Dynamically calculated based on {'live' if data_quality==MarketDataState.LIVE else 'historical'} data."
                ),
                risk=ScannerRiskData(
                    entry_reference=ltp,
                    stop_loss_reference=sl_ref,
                    target_reference=tgt_ref,
                    atr_risk=atr,
                    risk_reward=risk_reward,
                    data_risk="NONE" if data_quality == MarketDataState.LIVE else str(data_quality.name)
                )
            )
        except Exception as e:
            logger.error(f"Error scanning {symbol}: {e}")
            return None

    def _create_insufficient_data_result(self, symbol: str) -> OpportunityScannerResult:
        return OpportunityScannerResult(
            identity=ScannerIdentity(symbol=symbol),
            market=ScannerMarketData(data_quality=MarketDataState.INSUFFICIENT_DATA),
            technical=ScannerTechnicalData(trend=TrendClassification.INSUFFICIENT_DATA),
            signals=ScannerSignals(trend_signal=TrendClassification.INSUFFICIENT_DATA),
            fundamental=ScannerFundamentalData(),
            opportunity=ScannerOpportunity(
                opportunity_score=0.0,
                confidence=0.0,
                opportunity_type=OpportunityType.MEAN_REVERSION,
                direction=OpportunityDirection.NEUTRAL,
                rationale="Insufficient historical data."
            ),
            risk=ScannerRiskData()
        )

    async def scan_symbols(self, symbols: List[str]) -> ScannerBatchResult:
        tasks = [self.scan_single(sym) for sym in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        valid_results = []
        unavailable = []
        
        for idx, res in enumerate(results):
            if isinstance(res, Exception) or res is None:
                unavailable.append(symbols[idx])
                if isinstance(res, Exception):
                    logger.error(f"Scan failed for {symbols[idx]} with error: {res}")
            else:
                valid_results.append(res)
                
        return ScannerBatchResult(
            opportunities=valid_results,
            total_scanned=len(symbols),
            total_opportunities=len([r for r in valid_results if r.opportunity.opportunity_score > 50]),
            unavailable_symbols=unavailable
        )
