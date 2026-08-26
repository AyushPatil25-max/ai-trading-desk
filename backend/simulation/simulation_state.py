"""
Simulation State & Report Schemas — Phase 5.2

Data models for trade journals, decision tracking, equity curves,
data-quality statistics, risk metrics, and simulation reports.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from backend.domain.execution_schemas import (
    ExecutionDecision,
    OrderSide,
    OrderStatus,
    RejectionReason,
)
from backend.domain.investment_committee_schemas import (
    InvestmentAction,
    InvestmentDecisionState,
)
from backend.simulation.simulation_config import SimulationConfig


class TradeJournalEntry(BaseModel):
    trade_id: str
    order_id: str
    timestamp: datetime
    symbol: str
    side: OrderSide
    quantity: float
    requested_price: float
    executed_price: float
    slippage: float = 0.0
    commission: float = 0.0
    total_cost: float = 0.0
    realized_pnl: float = 0.0
    context_id: str
    run_id: Optional[str] = None
    decision_id: Optional[str] = None
    committee_decision_state: InvestmentDecisionState
    confidence: float
    execution_decision: ExecutionDecision
    order_status: OrderStatus
    rejection_reasons: List[RejectionReason] = Field(default_factory=list)


class DecisionJournalEntry(BaseModel):
    timestamp: datetime
    symbol: str
    context_id: str
    run_id: Optional[str] = None
    current_price: float
    specialist_count: int = 0
    specialists_successful: int = 0
    specialists_degraded: int = 0
    specialists_failed: int = 0
    bull_strength: float = 0.0
    bear_strength: float = 0.0
    risk_score: float = 0.0
    debate_status: str = "UNKNOWN"
    committee_state: InvestmentDecisionState
    committee_action: InvestmentAction
    recommended_size_pct: float = 0.0
    risk_veto_active: bool = False
    execution_decision: ExecutionDecision
    order_created: bool = False
    order_filled: bool = False
    portfolio_equity_after: float


class EquityCurvePoint(BaseModel):
    timestamp: datetime
    portfolio_value: float
    cash: float
    invested_capital: float = 0.0
    gross_exposure: float = 0.0
    net_exposure: float = 0.0
    drawdown: float = 0.0
    drawdown_pct: float = 0.0
    peak_equity: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    daily_return: float = 0.0
    cumulative_return: float = 0.0
    benchmark_value: Optional[float] = None
    benchmark_return: Optional[float] = None
    number_of_positions: int = 0


class DataQualityStatistics(BaseModel):
    contexts_processed: int = 0
    contexts_rejected: int = 0
    stale_contexts_count: int = 0
    missing_fundamentals_count: int = 0
    missing_news_count: int = 0
    missing_institutional_count: int = 0
    provider_failures_count: int = 0
    degraded_specialist_runs: int = 0
    committee_insufficient_evidence_count: int = 0
    risk_veto_count: int = 0
    data_quality_veto_count: int = 0
    execution_rejections_count: int = 0


class PerformanceMetrics(BaseModel):
    initial_capital: float
    final_capital: float
    total_return_pct: float = 0.0
    benchmark_return_pct: Optional[float] = None
    excess_return_pct: Optional[float] = None
    annualized_return_pct: float = 0.0
    annualized_volatility: float = 0.0
    max_drawdown_pct: float = 0.0
    max_drawdown_amount: float = 0.0
    sharpe_ratio: Optional[float] = None
    sortino_ratio: Optional[float] = None
    win_rate: float = 0.0
    loss_rate: float = 0.0
    profit_factor: Optional[float] = None
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    avg_win_amount: float = 0.0
    avg_loss_amount: float = 0.0
    win_loss_ratio: Optional[float] = None
    avg_holding_period_days: float = 0.0
    total_commission_paid: float = 0.0
    total_slippage_cost: float = 0.0
    turnover: float = 0.0


class SimulationReport(BaseModel):
    simulation_id: str
    config: SimulationConfig
    start_date: datetime
    end_date: datetime
    symbols: List[str]
    initial_capital: float
    final_capital: float
    metrics: PerformanceMetrics
    data_quality: DataQualityStatistics
    equity_curve: List[EquityCurvePoint] = Field(default_factory=list)
    trade_journal: List[TradeJournalEntry] = Field(default_factory=list)
    decision_journal: List[DecisionJournalEntry] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)
