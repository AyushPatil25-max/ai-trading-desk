"""
Validation Configuration — Phase 5.4

Pydantic model and loader for walk-forward windowing, robustness parameters,
and baseline evaluations.
"""

from datetime import datetime
import json
import os
from typing import List, Optional
from pydantic import BaseModel, Field

from backend.scanner.universe import UniverseType


class WalkForwardConfig(BaseModel):
    train_window_days: int = Field(default=756, gt=0)  # 3 years
    val_window_days: int = Field(default=252, gt=0)    # 1 year
    test_window_days: int = Field(default=252, gt=0)   # 1 year
    step_days: int = Field(default=252, gt=0)          # 1 year rolling step
    initial_capital: float = Field(default=100000.0, gt=0.0)
    benchmark_symbol: str = Field(default="^NSEI")
    commission_rate: float = Field(default=0.0003, ge=0.0)
    slippage_rate: float = Field(default=0.0005, ge=0.0)
    top_k: int = Field(default=5, gt=0)
    max_candidates_per_sector: int = Field(default=2, gt=0)
    min_opportunity_score: float = Field(default=50.0, ge=0.0)
    min_data_quality_score: float = Field(default=40.0, ge=0.0)
    cost_sensitivity_bps: List[int] = Field(default_factory=lambda: [0, 5, 10, 20, 30, 50])
    slippage_sensitivity_pct: List[float] = Field(default_factory=lambda: [0.0, 0.0005, 0.0010, 0.0020, 0.0050])
    sizing_multipliers: List[float] = Field(default_factory=lambda: [0.5, 1.0, 1.5, 2.0])
    universe_type: UniverseType = Field(default=UniverseType.NIFTY_50)

    @classmethod
    def from_file(cls, config_path: str) -> "WalkForwardConfig":
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                wf_data = data.get("walk_forward", data)
                return cls(**wf_data)
        return cls()
