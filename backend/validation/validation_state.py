"""
Validation Domain Models — Phase 5.4

Schemas for walk-forward windows, leakage findings, regime segmentations,
specialist attributions, ablation studies, cost sensitivity, and the final scorecard.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from backend.simulation.simulation_state import PerformanceMetrics, SimulationReport


class LeakageSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class LeakageFinding(BaseModel):
    category: str
    symbol: str
    context_id: str
    offending_timestamp: datetime
    decision_timestamp: datetime
    source: str
    severity: LeakageSeverity
    description: str


class WalkForwardWindow(BaseModel):
    window_index: int
    train_start: datetime
    train_end: datetime
    val_start: datetime
    val_end: datetime
    test_start: datetime
    test_end: datetime
    is_valid: bool = True
    leakage_findings: List[LeakageFinding] = Field(default_factory=list)
    out_of_sample_metrics: Optional[PerformanceMetrics] = None
    data_quality_summary: Dict[str, Any] = Field(default_factory=dict)


class RegimeType(str, Enum):
    BULL = "BULL"
    BEAR = "BEAR"
    SIDEWAYS = "SIDEWAYS"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"


class RegimePerformance(BaseModel):
    regime: RegimeType
    total_return_pct: float
    win_rate: float
    max_drawdown_pct: float
    trade_count: int


class SectorPerformance(BaseModel):
    sector: str
    total_return_pct: float
    win_rate: float
    trade_count: int
    contribution_pct: float


class SpecialistAttribution(BaseModel):
    specialist_name: str
    signal_count: int
    win_rate_when_active: float
    profit_contribution: float
    avg_score: float


class AblationResult(BaseModel):
    pipeline_variant: str
    description: str
    total_return_pct: float
    sharpe_ratio: Optional[float] = None
    max_drawdown_pct: float = 0.0
    win_rate: float = 0.0
    profit_factor: Optional[float] = None
    total_trades: int = 0


class CostSensitivityPoint(BaseModel):
    commission_bps: int
    slippage_pct: float
    total_return_pct: float
    sharpe_ratio: Optional[float] = None
    profit_factor: Optional[float] = None
    total_cost_paid: float = 0.0


class RobustnessResult(BaseModel):
    perturbation_type: str
    baseline_return_pct: float
    perturbed_return_pct: float
    stability_score: float  # 0.0 to 100.0


class ValidationScorecard(BaseModel):
    predictive_quality_score: float = Field(ge=0.0, le=100.0)
    risk_adjusted_score: float = Field(ge=0.0, le=100.0)
    drawdown_score: float = Field(ge=0.0, le=100.0)
    consistency_score: float = Field(ge=0.0, le=100.0)
    robustness_score: float = Field(ge=0.0, le=100.0)
    data_quality_score: float = Field(ge=0.0, le=100.0)
    out_of_sample_score: float = Field(ge=0.0, le=100.0)
    overall_validation_score: float = Field(ge=0.0, le=100.0)
    passed_validation: bool = False
    summary: str


class BaselineStrategyResult(BaseModel):
    strategy_name: str
    total_return_pct: float
    sharpe_ratio: Optional[float] = None
    max_drawdown_pct: float = 0.0
    win_rate: float = 0.0
    profit_factor: Optional[float] = None


class WalkForwardResult(BaseModel):
    run_id: str
    start_date: datetime
    end_date: datetime
    windows: List[WalkForwardWindow] = Field(default_factory=list)
    overall_out_of_sample_metrics: PerformanceMetrics
    baseline_comparisons: List[BaselineStrategyResult] = Field(default_factory=list)
    regime_analysis: List[RegimePerformance] = Field(default_factory=list)
    sector_analysis: List[SectorPerformance] = Field(default_factory=list)
    specialist_attribution: List[SpecialistAttribution] = Field(default_factory=list)
    ablation_results: List[AblationResult] = Field(default_factory=list)
    cost_sensitivity: List[CostSensitivityPoint] = Field(default_factory=list)
    robustness: List[RobustnessResult] = Field(default_factory=list)
    scorecard: ValidationScorecard
    generated_at: datetime = Field(default_factory=datetime.utcnow)
