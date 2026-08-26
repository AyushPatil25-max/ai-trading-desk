"""
Model Benchmark Engine & Multi-Dimensional Selection System — Phase 5.6F

Executes normalized candidate model evaluation across stratified historical contexts,
computes multi-dimensional composite ranking scores, and guarantees strict separation
between Model Selection Datasets and Holdout Validation Datasets.
"""

from datetime import datetime
from enum import Enum
import hashlib
import json
import os
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from backend.domain.schemas import MarketContext
from backend.infrastructure.llm_provider_adapter import LLMAdapterFactory, ModelCandidateDescriptor
from backend.infrastructure.llm_replay_cache import LLMReplayCache
from backend.validation.real_llm_protocol import (
    ModelQualityMetrics,
    PairedModelExperimentConfig,
    RealLLMValidationProtocol,
    StratifiedContextSelector,
    StratifiedSamplingConfig,
)


class ModelDatasetPartition(str, Enum):
    MODEL_SELECTION_DATASET = "MODEL_SELECTION_DATASET"
    HOLDOUT_OOS_DATASET = "HOLDOUT_OOS_DATASET"


class ModelSelectionDatasetConfig(BaseModel):
    selection_start: datetime = Field(default_factory=lambda: datetime(2021, 1, 1))
    selection_end: datetime = Field(default_factory=lambda: datetime(2022, 12, 31))
    holdout_start: datetime = Field(default_factory=lambda: datetime(2023, 1, 1))
    holdout_end: datetime = Field(default_factory=lambda: datetime(2024, 12, 31))
    is_leakage_protected: bool = True

    def validate_partition_isolation(self, context_timestamp: datetime, partition: ModelDatasetPartition) -> bool:
        if partition == ModelDatasetPartition.MODEL_SELECTION_DATASET:
            return self.selection_start <= context_timestamp <= self.selection_end
        elif partition == ModelDatasetPartition.HOLDOUT_OOS_DATASET:
            return self.holdout_start <= context_timestamp <= self.holdout_end
        return False

    def assert_no_holdout_leakage(self, contexts: List[MarketContext]) -> None:
        for c in contexts:
            if not self.validate_partition_isolation(c.data_timestamp, ModelDatasetPartition.MODEL_SELECTION_DATASET):
                raise ValueError(
                    f"HOLDOUT_LEAKAGE_VIOLATION: Context {c.context_id} timestamp {c.data_timestamp} "
                    f"falls outside model selection window [{self.selection_start}, {self.selection_end}]."
                )


class MultiDimensionalScoreWeights(BaseModel):
    reasoning_quality: float = 0.25
    evidence_grounding: float = 0.20
    risk_recognition: float = 0.20
    decision_stability: float = 0.15
    schema_reliability: float = 0.10
    cost_efficiency: float = 0.05
    latency_efficiency: float = 0.05


class ModelComparisonScorecard(BaseModel):
    model_id: str
    slot_name: str
    provider: str
    composite_score: float = Field(ge=0.0, le=100.0)
    reasoning_score: float
    grounding_score: float
    risk_score: float
    stability_score: float
    schema_score: float
    cost_score: float
    latency_score: float
    rank: int = 1
    is_production_ready: bool = False
    is_disqualified: bool = False
    disqualification_reason: str = "NONE"
    metrics: ModelQualityMetrics


class ModelBenchmarkEngine:
    """
    Evaluates candidate models across identical canonical historical contexts
    and computes multi-dimensional composite ranking scores.
    """

    @classmethod
    def compute_composite_score(
        cls,
        metrics: ModelQualityMetrics,
        weights: Optional[MultiDimensionalScoreWeights] = None,
    ) -> float:
        if not metrics.is_live_executed or metrics.contexts_evaluated == 0:
            return 0.0

        w = weights or MultiDimensionalScoreWeights()

        # Score components normalized to 0 - 100
        r_score = metrics.specialist_agreement_pct
        g_score = metrics.evidence_grounding_score * 100.0
        risk_score = metrics.risk_recognition_rate_pct
        stab_score = 100.0 - metrics.decision_flip_rate_pct
        schema_score = 100.0 - metrics.schema_violation_rate_pct
        cost_score = max(0.0, 100.0 - (metrics.cost_per_100_contexts_usd * 50.0))
        lat_score = max(0.0, 100.0 - (metrics.avg_latency_ms / 20.0))

        composite = (
            w.reasoning_quality * r_score
            + w.evidence_grounding * g_score
            + w.risk_recognition * risk_score
            + w.decision_stability * stab_score
            + w.schema_reliability * schema_score
            + w.cost_efficiency * cost_score
            + w.latency_efficiency * lat_score
        )
        return round(min(100.0, max(0.0, composite)), 2)

    @classmethod
    def evaluate_candidates(
        cls,
        contexts: List[MarketContext],
        candidate_slots: Optional[List[str]] = None,
        weights: Optional[MultiDimensionalScoreWeights] = None,
        selection_cfg: Optional[ModelSelectionDatasetConfig] = None,
        replay_cache: Optional[LLMReplayCache] = None,
    ) -> List[ModelComparisonScorecard]:
        # Enforce strict holdout protection
        cfg = selection_cfg or ModelSelectionDatasetConfig()
        cfg.assert_no_holdout_leakage(contexts)

        slots = candidate_slots or list(LLMAdapterFactory.CANDIDATES.keys())
        w = weights or MultiDimensionalScoreWeights()
        scorecards: List[ModelComparisonScorecard] = []

        for slot in slots:
            cand = LLMAdapterFactory.get_candidate(slot)
            metrics = RealLLMValidationProtocol.evaluate_model_quality(cand.model_id, contexts, replay_cache=replay_cache)
            comp_score = cls.compute_composite_score(metrics, w)

            # Check hard disqualifiers
            is_disqualified = False
            disqual_reason = "NONE"
            if metrics.numerical_boundary_violations > 0:
                is_disqualified = True
                disqual_reason = f"NUMERICAL_MUTATION_DETECTED: {metrics.numerical_boundary_violations} violations"
            elif metrics.schema_violation_rate_pct > 0.5:
                is_disqualified = True
                disqual_reason = f"EXCESSIVE_SCHEMA_FAILURES: {metrics.schema_violation_rate_pct}%"
            elif not cand.is_configured and not metrics.is_live_executed:
                is_disqualified = True
                disqual_reason = "NOT_EXECUTED — MISSING_CREDENTIALS"

            scorecard = ModelComparisonScorecard(
                model_id=cand.model_id,
                slot_name=cand.slot_name,
                provider=cand.provider.value,
                composite_score=comp_score,
                reasoning_score=metrics.specialist_agreement_pct,
                grounding_score=round(metrics.evidence_grounding_score * 100.0, 2),
                risk_score=metrics.risk_recognition_rate_pct,
                stability_score=round(100.0 - metrics.decision_flip_rate_pct, 2) if metrics.is_live_executed else 0.0,
                schema_score=round(100.0 - metrics.schema_violation_rate_pct, 2) if metrics.is_live_executed else 0.0,
                cost_score=round(max(0.0, 100.0 - (metrics.cost_per_100_contexts_usd * 50.0)), 2) if metrics.is_live_executed else 0.0,
                latency_score=round(max(0.0, 100.0 - (metrics.avg_latency_ms / 20.0)), 2) if metrics.is_live_executed else 0.0,
                is_production_ready=cand.is_configured and comp_score >= 85.0 and not is_disqualified,
                is_disqualified=is_disqualified,
                disqualification_reason=disqual_reason,
                metrics=metrics,
            )
            scorecards.append(scorecard)

        # Rank by composite score descending
        scorecards.sort(key=lambda s: s.composite_score, reverse=True)
        for rank_idx, s in enumerate(scorecards, 1):
            s.rank = rank_idx

        return scorecards
