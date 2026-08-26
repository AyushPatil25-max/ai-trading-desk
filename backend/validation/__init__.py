"""
Validation Package — Phase 5.4, 5.4A, 5.4B, 5.4C, 5.5, 5.6, 5.6B, 5.6C & Phase 5.6E

Walk-forward backtesting, Point-In-Time leakage detection, baseline strategy comparisons,
regime segmentation, specialist attribution, ablation studies, empirical data trust auditing,
strategy classification scorecards, empirical runner integrity auditing, historical universe reconstitution,
genuine multi-variant ablation & baseline runners, universe verification, proxy detection, ablation independence auditing,
real LLM historical replay validation, stratified sampling protocols, paired-model comparison harnesses,
provider-neutral model adapters, multi-dimensional candidate model benchmarking, and forensic benchmark verification.
"""

from backend.infrastructure.llm_provider_adapter import (
    LLMAdapterFactory,
    LLMExecutionStats,
    LLMProviderType,
    ModelCandidateDescriptor,
    ProviderNeutralLLMClient,
)
from backend.infrastructure.llm_replay_cache import CachedLLMResponse, LLMReplayCache
from backend.scanner.historical_universe import HistoricalConstituent, HistoricalUniverse
from backend.validation.ablation_independence_audit import (
    AblationIndependenceAuditResult,
    AblationIndependenceAuditor,
    AblationVariantAuditRecord,
)
from backend.validation.ablation_runner import RealAblationRunner, RealAblationVariantResult
from backend.validation.baseline_runner import RealBaselineRunner, RealBaselineStrategyResult
from backend.validation.empirical_audit import (
    DataSufficiencyReport,
    DataTrustAuditor,
    EmpiricalScorecard,
    ProviderAvailabilityEntry,
    StrategyClassification,
)
from backend.validation.empirical_runner import EmpiricalValidationRunner
from backend.validation.integrity_auditor import (
    AuditClassification,
    DataClassification,
    EmpiricalIntegrityAuditor,
    ExecutionMode,
    IntegrityAuditReport,
    TradeLineageRecord,
)
from backend.validation.leakage_detector import LeakageDetector
from backend.validation.model_benchmark_engine import (
    ModelBenchmarkEngine,
    ModelComparisonScorecard,
    ModelDatasetPartition,
    ModelSelectionDatasetConfig,
    MultiDimensionalScoreWeights,
)
from backend.validation.model_benchmark_verifier import (
    BenchmarkForensicAuditResult,
    BenchmarkForensicClassification,
    ModelBenchmarkVerifier,
    ModelExecutionAuditRecord,
)
from backend.validation.real_llm_protocol import (
    EventWindowType,
    MarketRegimePartition,
    ModelQualityMetrics,
    PairedModelExperimentConfig,
    RealLLMValidationProtocol,
    StratifiedContextSelector,
    StratifiedSamplingConfig,
)
from backend.validation.real_llm_runner import (
    AIModeComparisonResult,
    LLMExecutionMode,
    RealLLMRunner,
    RealLLMValidationClassification,
    RealLLMValidationReport,
)
from backend.validation.robustness import RobustnessEngine
from backend.validation.survivorship_audit import (
    SurvivorshipAuditor,
    SurvivorshipAuditResult,
    SurvivorshipFinding,
    SurvivorshipFindingType,
)
from backend.validation.universe_verification import (
    ReconstitutionEventVerification,
    UniverseVerificationResult,
    UniverseVerificationStatus,
    UniverseVerifier,
)
from backend.validation.validation_config import WalkForwardConfig
from backend.validation.validation_report import ValidationReportBuilder
from backend.validation.validation_state import (
    AblationResult,
    BaselineStrategyResult,
    CostSensitivityPoint,
    LeakageFinding,
    LeakageSeverity,
    RegimePerformance,
    RegimeType,
    RobustnessResult,
    SectorPerformance,
    SpecialistAttribution,
    ValidationScorecard,
    WalkForwardResult,
    WalkForwardWindow,
)
from backend.validation.walk_forward import WalkForwardEngine

__all__ = [
    "AIModeComparisonResult",
    "AblationIndependenceAuditResult",
    "AblationIndependenceAuditor",
    "AblationResult",
    "AblationVariantAuditRecord",
    "AuditClassification",
    "BaselineStrategyResult",
    "BenchmarkForensicAuditResult",
    "BenchmarkForensicClassification",
    "CachedLLMResponse",
    "CostSensitivityPoint",
    "DataClassification",
    "DataSufficiencyReport",
    "DataTrustAuditor",
    "EmpiricalIntegrityAuditor",
    "EmpiricalScorecard",
    "EmpiricalValidationRunner",
    "EventWindowType",
    "ExecutionMode",
    "HistoricalConstituent",
    "HistoricalUniverse",
    "IntegrityAuditReport",
    "LLMAdapterFactory",
    "LLMExecutionMode",
    "LLMExecutionStats",
    "LLMProviderType",
    "LLMReplayCache",
    "LeakageDetector",
    "LeakageFinding",
    "LeakageSeverity",
    "MarketRegimePartition",
    "ModelBenchmarkEngine",
    "ModelBenchmarkVerifier",
    "ModelCandidateDescriptor",
    "ModelComparisonScorecard",
    "ModelDatasetPartition",
    "ModelExecutionAuditRecord",
    "ModelQualityMetrics",
    "ModelSelectionDatasetConfig",
    "MultiDimensionalScoreWeights",
    "PairedModelExperimentConfig",
    "ProviderAvailabilityEntry",
    "ProviderNeutralLLMClient",
    "ProxyAuditResult",
    "ProxyDetectionFinding",
    "ProxyDetector",
    "RealAblationRunner",
    "RealAblationVariantResult",
    "RealBaselineRunner",
    "RealBaselineStrategyResult",
    "RealLLMRunner",
    "RealLLMValidationClassification",
    "RealLLMValidationProtocol",
    "RealLLMValidationReport",
    "ReconstitutionEventVerification",
    "RegimePerformance",
    "RegimeType",
    "RobustnessEngine",
    "RobustnessResult",
    "SectorPerformance",
    "SpecialistAttribution",
    "StratifiedContextSelector",
    "StratifiedSamplingConfig",
    "StrategyClassification",
    "SurvivorshipAuditResult",
    "SurvivorshipAuditor",
    "SurvivorshipFinding",
    "SurvivorshipFindingType",
    "TradeLineageRecord",
    "UniverseVerificationResult",
    "UniverseVerificationStatus",
    "UniverseVerifier",
    "ValidationReportBuilder",
    "ValidationScorecard",
    "WalkForwardConfig",
    "WalkForwardEngine",
    "WalkForwardResult",
    "WalkForwardWindow",
]
