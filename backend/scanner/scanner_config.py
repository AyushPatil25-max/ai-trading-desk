"""
Scanner Configuration — Phase 5.3

Pydantic model and loader for deterministic opportunity screening, scoring weights,
and sector diversification constraints.
"""

import json
import os
from typing import Dict, Optional
from pydantic import BaseModel, Field


class ScannerWeights(BaseModel):
    technical: float = Field(default=0.20, ge=0.0, le=1.0)
    momentum: float = Field(default=0.15, ge=0.0, le=1.0)
    quant: float = Field(default=0.10, ge=0.0, le=1.0)
    fundamental: float = Field(default=0.20, ge=0.0, le=1.0)
    valuation: float = Field(default=0.15, ge=0.0, le=1.0)
    sector: float = Field(default=0.05, ge=0.0, le=1.0)
    macro: float = Field(default=0.05, ge=0.0, le=1.0)
    news: float = Field(default=0.05, ge=0.0, le=1.0)
    institutional: float = Field(default=0.05, ge=0.0, le=1.0)


class ScannerConfig(BaseModel):
    top_k: int = Field(default=5, gt=0)
    min_opportunity_score: float = Field(default=50.0, ge=0.0, le=100.0)
    min_data_quality_score: float = Field(default=40.0, ge=0.0, le=100.0)
    max_candidates_per_sector: int = Field(default=2, gt=0)
    min_price: float = Field(default=10.0, ge=0.0)
    max_price: float = Field(default=100000.0, gt=0.0)
    min_historical_bars: int = Field(default=20, ge=1)
    require_positive_price: bool = Field(default=True)
    weights: ScannerWeights = Field(default_factory=ScannerWeights)
    data_quality_penalty_weight: float = Field(default=0.30, ge=0.0, le=1.0)

    @classmethod
    def from_file(cls, config_path: str) -> "ScannerConfig":
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                scanner_data = data.get("scanner", data)
                return cls(**scanner_data)
        return cls()
