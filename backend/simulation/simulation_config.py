"""
Simulation Configuration — Phase 5.2

Pydantic model and loader for historical replay and paper trading simulation.
"""

from datetime import datetime
from enum import Enum
import json
import os
from typing import List, Optional
from pydantic import BaseModel, Field


class ExecutionMode(str, Enum):
    PAPER_HISTORICAL = "PAPER_HISTORICAL"
    PAPER_LIVE = "PAPER_LIVE"


class SimulationMode(str, Enum):
    SINGLE_SYMBOL = "SINGLE_SYMBOL"
    MULTI_SYMBOL = "MULTI_SYMBOL"


class SimulationConfig(BaseModel):
    simulation_id: str = Field(default="sim-default")
    initial_cash: float = Field(default=100000.0, gt=0)
    start_date: datetime = Field(default_factory=datetime.utcnow)
    end_date: datetime = Field(default_factory=datetime.utcnow)
    symbols: List[str] = Field(default_factory=lambda: ["TCS.NS"])
    timeframe: str = Field(default="1D")
    commission_rate: float = Field(default=0.0003, ge=0.0)
    slippage_rate: float = Field(default=0.0005, ge=0.0)
    transaction_fee_flat: float = Field(default=0.0, ge=0.0)
    max_positions: int = Field(default=5, gt=0)
    benchmark_symbol: str = Field(default="^NSEI")
    execution_mode: ExecutionMode = Field(default=ExecutionMode.PAPER_HISTORICAL)
    mode: SimulationMode = Field(default=SimulationMode.SINGLE_SYMBOL)
    random_seed: Optional[int] = Field(default=42)

    @classmethod
    def from_file(cls, config_path: str) -> "SimulationConfig":
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                sim_data = data.get("simulation", data)
                return cls(**sim_data)
        return cls()
