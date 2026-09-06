import logging
from typing import List, Optional, Tuple
from datetime import datetime

from backend.domain.stock_schemas import (
    StockFundamentalData,
    StockTechnicalData,
    StockAnalysisResult,
    StockDecision,
    StrategyScore
)
from backend.infrastructure.security_master import get_security_master

logger = logging.getLogger(__name__)

class StockAnalysisEngine:
    def __init__(self):
        self.security_master = get_security_master()

    async def analyze_stock(self, symbol: str, fundamental: Optional[StockFundamentalData], technical: Optional[StockTechnicalData]) -> StockAnalysisResult:
        sec = self.security_master.resolve_symbol(symbol)
        company_name = sec.company_name if sec else symbol
        exchange = sec.exchange if sec else "NSE"
        
        # Calculate scores
        f_score = self._analyze_fundamental(fundamental)
        t_score = self._analyze_technical(technical)
        m_score = self._analyze_momentum(technical)
        trend_score = self._analyze_trend(technical)
        v_score, val_verdict = self._analyze_valuation(fundamental, technical)
        q_score, r_score = self._analyze_quality_risk(fundamental, technical)
        
        # Data Quality Assessment
        dq_status, dq_reasons, dq_score = self._assess_data_quality(fundamental, technical)
        
        # Calculate Confidence
        confidence = self._calculate_confidence(f_score, t_score, v_score, dq_score)
        
        # Calculate Overall Score (0-100)
        overall = 0.0
        if dq_score >= 0.3:
            overall = (f_score.score * 0.25) + (v_score.score * 0.15) + (t_score.score * 0.20) + (trend_score.score * 0.15) + (m_score.score * 0.10) + (q_score.score * 0.15)
            # Apply risk penalty
            overall -= (r_score.score * 0.5)
            overall = max(0.0, min(100.0, overall))

        # Final Decision Logic
        decision = StockDecision.INSUFFICIENT_DATA
        if dq_score < 0.3:
            decision = StockDecision.INSUFFICIENT_DATA
        elif r_score.score >= 50:
            decision = StockDecision.REJECT
        elif overall >= 75 and confidence >= 0.7 and trend_score.score >= 60:
            decision = StockDecision.STRONG_BULLISH
        elif overall >= 60 and confidence >= 0.5:
            decision = StockDecision.BULLISH
        elif overall <= 30 and trend_score.score <= 30:
            decision = StockDecision.STRONG_BEARISH
        elif overall <= 45:
            decision = StockDecision.BEARISH
        else:
            decision = StockDecision.HOLD
            
        positive = [p for p in (f_score.reasons + v_score.reasons + t_score.reasons + trend_score.reasons + m_score.reasons + q_score.reasons) if p]
        negative = [] # can add later based on penalties
        warnings = r_score.reasons + dq_reasons

        conf_pct = round(confidence * 100, 1)

        return StockAnalysisResult(
            symbol=symbol,
            company_name=company_name,
            exchange=exchange,
            overall_score=round(overall, 1),
            fundamental_score=round(f_score.score, 1),
            valuation_score=round(v_score.score, 1),
            technical_score=round(t_score.score, 1),
            momentum_score=round(m_score.score, 1),
            trend_score=round(trend_score.score, 1),
            quality_score=round(q_score.score, 1),
            risk_score=round(r_score.score, 1),
            confidence=round(confidence, 2),
            confidence_score=conf_pct,
            data_quality_score=round(dq_score, 2),
            decision=decision,
            verdict=val_verdict,
            current_price=technical.current_price if technical else None,
            price_change=technical.absolute_change if technical else None,
            price_change_pct=technical.percentage_change if technical else None,
            volume=technical.volume if technical else None,
            data_status=dq_status,
            data_freshness=technical.data_freshness if technical else "UNAVAILABLE",
            data_source="Upstox/YFinance",
            reasons=positive,
            positive_factors=positive,
            negative_factors=negative,
            risk_warnings=warnings,
            invalidation_conditions=[],
            fundamental_data=fundamental,
            technical_data=technical
        )

    def _assess_data_quality(self, f: Optional[StockFundamentalData], t: Optional[StockTechnicalData]) -> Tuple[str, List[str], float]:
        reasons = []
        score = 1.0
        
        if not f:
            score -= 0.4
            reasons.append("missing_fundamentals")
        else:
            if f.roe is None:
                score -= 0.1
                reasons.append("missing_roe")
            if f.roce is None:
                reasons.append("missing_roce")
            if f.pe is None:
                score -= 0.1
                reasons.append("missing_pe")
                
        if not t:
            score -= 0.5
            reasons.append("missing_technicals")
        else:
            if not t.current_price:
                score -= 0.3
                reasons.append("missing_price")
            if not t.sma_200:
                score -= 0.2
                reasons.append("insufficient_history")
            if t.data_freshness == "STALE":
                score -= 0.3
                reasons.append("stale_market_data")
                
        score = max(0.0, score)
        if score == 1.0: status = "COMPLETE"
        elif score >= 0.7: status = "PARTIAL"
        elif score > 0.0 and "stale_market_data" in reasons: status = "STALE"
        elif score > 0.0: status = "INSUFFICIENT"
        else: status = "ERROR"
        
        return status, reasons, score

    def _calculate_confidence(self, f: StrategyScore, t: StrategyScore, v: StrategyScore, dq: float) -> float:
        conf = (f.confidence * 0.3) + (t.confidence * 0.4) + (v.confidence * 0.3)
        return conf * dq

    def _analyze_fundamental(self, data: Optional[StockFundamentalData]) -> StrategyScore:
        if not data: return StrategyScore(score=0, confidence=0, reasons=[])
        
        score = 0.0
        conf = 1.0
        reasons = []
        
        # Growth
        if data.revenue_growth is not None:
            if data.revenue_growth > 15: score += 20; reasons.append("Strong revenue growth (>15%)")
            elif data.revenue_growth < 0: score -= 10
        else: conf -= 0.15
            
        if data.pat_growth is not None:
            if data.pat_growth > 15: score += 20; reasons.append("Strong PAT growth (>15%)")
            elif data.pat_growth < 0: score -= 10
        else: conf -= 0.15
            
        # Returns
        if data.roe is not None:
            if data.roe > 20: score += 20; reasons.append(f"High ROE ({data.roe}%)")
            elif data.roe < 5: score -= 10
        else: conf -= 0.15
            
        # Leverage
        if data.debt_equity is not None:
            if data.debt_equity < 0.5: score += 20; reasons.append("Low leverage (D/E < 0.5)")
            elif data.debt_equity > 2.0: score -= 20
        else: conf -= 0.15
            
        # Cash Flow
        if data.free_cash_flow is not None:
            if data.free_cash_flow > 0: score += 20; reasons.append("Positive Free Cash Flow")
            else: score -= 10
        else: conf -= 0.15
            
        score = max(0.0, min(100.0, score))
        return StrategyScore(score=score, confidence=max(0.0, conf), reasons=reasons)

    def _analyze_technical(self, t: Optional[StockTechnicalData]) -> StrategyScore:
        if not t or not t.current_price: return StrategyScore(score=0, confidence=0, reasons=[])
        
        score = 50.0
        conf = 1.0
        reasons = []
        
        p = t.current_price
        
        if t.sma_20 and t.sma_50 and t.sma_200:
            if p > t.sma_200: score += 15; reasons.append("Price > 200 SMA")
            else: score -= 15
            
            if t.sma_50 > t.sma_200: score += 15; reasons.append("Golden Cross active (50 SMA > 200 SMA)")
            elif t.sma_50 < t.sma_200: score -= 15
        else:
            conf -= 0.4
            
        if t.rsi_14:
            if 40 <= t.rsi_14 <= 60: score += 10; reasons.append("RSI in neutral/healthy zone")
            elif t.rsi_14 > 70: score -= 10
            elif t.rsi_14 < 30: score += 10; reasons.append("RSI oversold")
        else:
            conf -= 0.2
            
        score = max(0.0, min(100.0, score))
        return StrategyScore(score=score, confidence=max(0.0, conf), reasons=reasons)
        
    def _analyze_trend(self, t: Optional[StockTechnicalData]) -> StrategyScore:
        if not t or not t.current_price: return StrategyScore(score=0, confidence=0, reasons=[])
        
        score = 50.0
        conf = 1.0
        reasons = []
        
        if t.adx and t.plus_di and t.minus_di:
            if t.adx > 25:
                if t.plus_di > t.minus_di:
                    score += 30; reasons.append("Strong Bullish Trend (ADX > 25, +DI > -DI)")
                else:
                    score -= 30
            else:
                reasons.append("Weak Trend (ADX < 25)")
        else:
            conf -= 0.5
            
        if t.supertrend and t.current_price:
            if t.current_price > t.supertrend:
                score += 20; reasons.append("Price > SuperTrend")
            else:
                score -= 20
        else:
            conf -= 0.3
            
        score = max(0.0, min(100.0, score))
        return StrategyScore(score=score, confidence=max(0.0, conf), reasons=reasons)

    def _analyze_momentum(self, t: Optional[StockTechnicalData]) -> StrategyScore:
        if not t: return StrategyScore(score=0, confidence=0, reasons=[])
        
        score = 50.0
        conf = 1.0
        reasons = []
        
        if t.macd and t.macd_signal and t.macd_histogram:
            if t.macd > t.macd_signal:
                score += 30; reasons.append("MACD Bullish Crossover")
                if t.macd_histogram > 0:
                    score += 20; reasons.append("MACD Histogram Positive")
            else:
                score -= 30
        else:
            conf -= 0.8
            
        score = max(0.0, min(100.0, score))
        return StrategyScore(score=score, confidence=max(0.0, conf), reasons=reasons)

    def _analyze_valuation(self, f: Optional[StockFundamentalData], t: Optional[StockTechnicalData]) -> Tuple[StrategyScore, str]:
        if not f: return StrategyScore(score=0, confidence=0, reasons=[]), "INSUFFICIENT_DATA"
        
        score = 50.0
        conf = 1.0
        reasons = []
        
        if f.pe:
            if f.pe < 15: score += 25; reasons.append(f"Attractive P/E ({f.pe})")
            elif f.pe > 50: score -= 25; reasons.append(f"High P/E ({f.pe})")
        else:
            conf -= 0.4
            
        if f.pb:
            if f.pb < 2: score += 25; reasons.append(f"Attractive P/B ({f.pb})")
            elif f.pb > 8: score -= 25
        else:
            conf -= 0.4
            
        score = max(0.0, min(100.0, score))
        
        verdict = "INSUFFICIENT_DATA"
        if conf > 0.4:
            if score >= 70: verdict = "UNDERVALUED"
            elif score <= 30: verdict = "OVERVALUED"
            else: verdict = "FAIRLY_VALUED"
            
        return StrategyScore(score=score, confidence=max(0.0, conf), reasons=reasons), verdict

    def _analyze_quality_risk(self, f: Optional[StockFundamentalData], t: Optional[StockTechnicalData]) -> Tuple[StrategyScore, StrategyScore]:
        q_score = 50.0
        r_score = 0.0
        q_reasons = []
        r_reasons = []
        
        if f:
            if f.promoter_holding and f.promoter_holding > 50:
                q_score += 25; q_reasons.append("High promoter holding (>50%)")
            elif f.promoter_holding and f.promoter_holding < 20:
                r_score += 30; r_reasons.append("Low promoter holding (<20%)")
                
            if f.promoter_pledge and f.promoter_pledge > 25:
                r_score += 50; r_reasons.append(f"High promoter pledge ({f.promoter_pledge}%)")
                
        if t and t.distance_low_52w is not None:
            if t.distance_low_52w < 5:
                r_score += 20; r_reasons.append("Trading near 52W low")
                
        q_score = max(0.0, min(100.0, q_score))
        r_score = max(0.0, min(100.0, r_score))
        
        return StrategyScore(score=q_score, confidence=1.0, reasons=q_reasons), \
               StrategyScore(score=r_score, confidence=1.0, reasons=r_reasons)

