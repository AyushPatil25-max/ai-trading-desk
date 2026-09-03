import logging
from typing import List, Optional
from datetime import datetime
import pandas as pd
import numpy as np

from backend.domain.stock_schemas import (
    StockFundamentalData,
    StockTechnicalData,
    StockAnalysisResult,
    StockDecision,
    StrategyScore
)
from backend.infrastructure.security_master import get_security_master, SecurityDefinition

logger = logging.getLogger(__name__)

class StockAnalysisEngine:
    def __init__(self):
        self.security_master = get_security_master()

    async def analyze_stock(self, symbol: str, fundamental: StockFundamentalData, technical: StockTechnicalData) -> StockAnalysisResult:
        if fundamental is None or technical is None:
            return StockAnalysisResult(
                symbol=symbol,
                overall_score=0.0,
                fundamental_score=0.0,
                valuation_score=0.0,
                technical_score=0.0,
                momentum_score=0.0,
                quality_score=0.0,
                risk_score=0.0,
                confidence=0.0,
                data_quality_score=0.0,
                decision=StockDecision.INSUFFICIENT_DATA,
                positive_factors=[],
                negative_factors=[],
                risk_warnings=["Missing core fundamental or technical data"],
                invalidation_conditions=[]
            )

        f_score = self._analyze_fundamental(fundamental)
        v_score = self._analyze_valuation(fundamental, technical)
        t_score = self._analyze_technical(technical)
        m_score = self._analyze_momentum(technical)
        q_score, r_score = self._analyze_quality_risk(fundamental, technical)

        overall = (f_score.score * 0.3) + (v_score.score * 0.2) + (t_score.score * 0.2) + (m_score.score * 0.1) + (q_score.score * 0.2)
        confidence = min(f_score.confidence, v_score.confidence, t_score.confidence)

        decision = StockDecision.HOLD
        if overall > 75 and confidence > 0.7:
            decision = StockDecision.STRONG_BUY
        elif overall > 50 and confidence > 0.6:
            decision = StockDecision.BUY
        elif overall < 0:
            decision = StockDecision.AVOID
        elif overall < 25:
            decision = StockDecision.WATCH

        if r_score.score > 70:
            decision = StockDecision.AVOID

        positive = f_score.reasons + v_score.reasons + t_score.reasons + m_score.reasons + q_score.reasons
        warnings = r_score.reasons

        return StockAnalysisResult(
            symbol=symbol,
            overall_score=overall,
            fundamental_score=f_score.score,
            valuation_score=v_score.score,
            technical_score=t_score.score,
            momentum_score=m_score.score,
            quality_score=q_score.score,
            risk_score=r_score.score,
            confidence=confidence,
            data_quality_score=1.0,
            decision=decision,
            positive_factors=[p for p in positive if p],
            negative_factors=[],
            risk_warnings=warnings,
            invalidation_conditions=["Quarterly earnings miss", "Promoter pledge increase"]
        )

    def _analyze_fundamental(self, data: StockFundamentalData) -> StrategyScore:
        score = 0.0
        reasons = []
        conf = 1.0
        if data.roe is not None:
            if data.roe > 20: score += 40; reasons.append(f"Strong ROE: {data.roe}%")
            elif data.roe > 12: score += 20
        else: conf -= 0.2

        if data.revenue_growth is not None:
            if data.revenue_growth > 15: score += 30; reasons.append("Strong revenue growth")
        else: conf -= 0.2

        if data.debt_equity is not None:
            if data.debt_equity < 0.5: score += 30; reasons.append("Low debt-to-equity")
            elif data.debt_equity > 2.0: score -= 30
        
        return StrategyScore(score=score, confidence=max(0.0, conf), reasons=reasons)

    def _analyze_valuation(self, f: StockFundamentalData, t: StockTechnicalData) -> StrategyScore:
        score = 0.0
        reasons = []
        conf = 1.0
        if f.pe:
            if f.pe < 15: score += 50; reasons.append("Attractive P/E (<15)")
            elif f.pe > 50: score -= 40
        else: conf -= 0.5

        if f.pb:
            if f.pb < 2: score += 30; reasons.append("Attractive P/B (<2)")
        
        return StrategyScore(score=score, confidence=max(0.0, conf), reasons=reasons)

    def _analyze_technical(self, t: StockTechnicalData) -> StrategyScore:
        score = 0.0
        reasons = []
        conf = 1.0
        if t.current_price and t.sma_200:
            if t.current_price > t.sma_200:
                score += 50; reasons.append("Trading above 200 SMA")
            else:
                score -= 30
        else: conf -= 0.3

        if t.rsi_14:
            if 40 < t.rsi_14 < 60: score += 20
            elif t.rsi_14 > 70: score -= 20
        
        return StrategyScore(score=score, confidence=max(0.0, conf), reasons=reasons)

    def _analyze_momentum(self, t: StockTechnicalData) -> StrategyScore:
        score = 0.0
        reasons = []
        if t.macd and t.macd_signal:
            if t.macd > t.macd_signal:
                score += 50; reasons.append("Bullish MACD crossover")
        return StrategyScore(score=score, confidence=1.0, reasons=reasons)

    def _analyze_quality_risk(self, f: StockFundamentalData, t: StockTechnicalData) -> (StrategyScore, StrategyScore):
        q_score = 0.0
        r_score = 0.0
        q_reasons = []
        r_reasons = []
        
        if f.promoter_holding and f.promoter_holding > 50:
            q_score += 50; q_reasons.append("High promoter holding")
            
        if f.promoter_pledge and f.promoter_pledge > 25:
            r_score += 80; r_reasons.append("High promoter pledge risk")

        return StrategyScore(score=q_score, confidence=1.0, reasons=q_reasons), \
               StrategyScore(score=r_score, confidence=1.0, reasons=r_reasons)
