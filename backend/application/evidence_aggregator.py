"""
Phase 4.1A — Hardened Evidence Aggregator

Extracts MULTIPLE real evidence items per specialist, preserves provenance,
implements duplicate detection, metric/domain-level agreements, typed conflicts,
evidence-aware weighting with specialist contribution caps, PIT validation,
and structured missing-data categorisation.

All calculations are deterministic Python.  No LLM calls.
"""

import json
import uuid
import logging
import hashlib
from pathlib import Path
from typing import List, Dict, Set, Tuple, Optional
from datetime import datetime, timedelta
from collections import defaultdict

from backend.domain.schemas import (
    SpecialistRunResult, AgentExecutionRecord, AgentState,
    UnifiedEvidencePackage, NormalizedEvidence, EvidenceConflict,
    EvidenceAgreement, EvidenceCategory, SignalDirection, EvidenceType,
    ConflictSeverity, ResearchRegime, SourceTier, VerificationStatus,
    MissingDataCategory, ConflictType, AgreementLevel, PITStatus,
    MissingDataRecord,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "evidence_metric_config.json"

def _load_config() -> dict:
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.warning("Could not load evidence_metric_config.json; using fallbacks.")
        return {}

_CONFIG = _load_config()

# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------

class AggregationError(Exception):
    pass


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Specialist contribution cap: no single specialist may contribute more
# than MAX_SPECIALIST_CONTRIBUTION_SHARE of the total directional score.
MAX_SPECIALIST_CONTRIBUTION_SHARE = 0.20

# PIT drift tolerance: evidence timestamps must be within this window
# of the MarketContext data_timestamp to be considered PIT-consistent.
PIT_DRIFT_TOLERANCE = timedelta(hours=48)

# Confidence penalty schedule (per severity of conflict/missing data)
CONFIDENCE_PENALTIES = {
    ConflictSeverity.LOW: 0.01,
    ConflictSeverity.MODERATE: 0.03,
    ConflictSeverity.HIGH: 0.06,
    ConflictSeverity.CRITICAL: 0.10,
}

# Verification status multiplier for weighting
VERIFICATION_MULTIPLIER = {
    VerificationStatus.VERIFIED: 1.0,
    VerificationStatus.PROVISIONAL: 0.85,
    VerificationStatus.UNVERIFIED: 0.7,
    VerificationStatus.CONFLICTED: 0.5,
}

# Source tier quality multiplier for weighting
SOURCE_QUALITY_MULTIPLIER = {
    SourceTier.TIER_1_PRIMARY_OFFICIAL: 1.0,
    SourceTier.TIER_2_REGULATORY: 0.95,
    SourceTier.TIER_3_LICENSED: 0.85,
    SourceTier.TIER_4_SECONDARY: 0.75,
    SourceTier.TIER_5_UNVERIFIED: 0.6,
}

# Direct-extraction metrics (DETERMINISTIC_FACT)
_FACT_METRICS: Set[str] = set()
_overrides = _CONFIG.get("metric_evidence_type_overrides", {})
for k, v in _overrides.items():
    if k.startswith("_"):
        continue
    if v == "DETERMINISTIC_FACT":
        _FACT_METRICS.add(k)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class EvidenceAggregator:
    """
    Phase 4.1A hardened evidence aggregator.

    Weighting formula (per evidence item):
        importance = specialist_weight × confidence × verification_multiplier × source_quality_multiplier

    Confidence formula:
        base_conf = Σ(confidence × importance) / Σ(importance)
        conflict_penalty = Σ CONFIDENCE_PENALTIES[severity] for each conflict
        missing_penalty  = (failed + timed_out) × 0.10
        final = clamp(base_conf − conflict_penalty − missing_penalty, 0, 1)

    Specialist contribution cap:
        Each specialist's directional contribution is capped at
        MAX_SPECIALIST_CONTRIBUTION_SHARE of total weight.
    """

    WEIGHTS: Dict[EvidenceCategory, float] = {
        EvidenceCategory.TECHNICAL: 1.0,
        EvidenceCategory.MOMENTUM: 0.9,
        EvidenceCategory.QUANT: 1.0,
        EvidenceCategory.FUNDAMENTAL: 1.2,
        EvidenceCategory.VALUATION: 1.1,
        EvidenceCategory.SECTOR: 0.9,
        EvidenceCategory.MACRO: 0.8,
        EvidenceCategory.NEWS: 0.7,
        EvidenceCategory.INSTITUTIONAL: 1.0,
        EvidenceCategory.UNKNOWN: 0.5,
    }

    def __init__(self, weights: Optional[Dict[EvidenceCategory, float]] = None):
        self.weights = weights if weights else self.WEIGHTS.copy()
        self._regime_dir_map: Dict[str, str] = _CONFIG.get("regime_direction_map", {})
        self._specialist_category_map: Dict[str, str] = _CONFIG.get("specialist_category_map", {})
        self._specialist_evidence_key: Dict[str, str] = _CONFIG.get("specialist_evidence_list_key", {})
        self._specialist_metric_key: Dict[str, str] = _CONFIG.get("specialist_metric_name_key", {})
        self._specialist_regime_keys: Dict[str, list] = _CONFIG.get("specialist_regime_keys", {})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def aggregate(self, run_result: SpecialistRunResult) -> UnifiedEvidencePackage:
        if not run_result.records:
            return self._build_empty_package(run_result)

        self._validate_context_consistency(run_result.records, run_result.context_id)

        pkg = UnifiedEvidencePackage(
            run_id=run_result.run_id,
            context_id=run_result.context_id,
            symbol=run_result.symbol,
            data_timestamp=run_result.started_at,
            specialists_total=len(run_result.records),
        )

        # Duplicate detection set
        seen_keys: Set[str] = set()

        for record in run_result.records:
            if record.status == AgentState.SUCCESS:
                pkg.specialists_successful += 1
                self._process_specialist_output(record, pkg, seen_keys)
            elif record.status == AgentState.DEGRADED:
                pkg.specialists_degraded += 1
                self._process_specialist_output(record, pkg, seen_keys)
                pkg.missing_data.append(f"{record.agent_name} degraded")
                pkg.missing_data_records.append(MissingDataRecord(
                    specialist_name=record.agent_name,
                    category=MissingDataCategory.SPECIALIST_DEGRADED,
                    detail=f"{record.agent_name} ran in degraded mode",
                ))
            elif record.status == AgentState.FAILED:
                pkg.specialists_failed += 1
                pkg.missing_data.append(f"{record.agent_name} failed: {record.error_message}")
                pkg.missing_data_records.append(MissingDataRecord(
                    specialist_name=record.agent_name,
                    category=MissingDataCategory.SPECIALIST_FAILED,
                    detail=f"{record.agent_name} failed: {record.error_message}",
                ))
            elif record.status == AgentState.TIMEOUT:
                pkg.specialists_timed_out += 1
                pkg.missing_data.append(f"{record.agent_name} timed out")
                pkg.missing_data_records.append(MissingDataRecord(
                    specialist_name=record.agent_name,
                    category=MissingDataCategory.SPECIALIST_TIMEOUT,
                    detail=f"{record.agent_name} timed out",
                ))
            else:
                pkg.missing_data.append(f"{record.agent_name} unknown state: {record.status}")

        # Phase 4.1A: PIT validation pass
        self._validate_pit_consistency(pkg)

        # Compute agreements & conflicts
        self._compute_agreements_and_conflicts(pkg)

        # Compute final metrics with caps
        self._compute_final_metrics(pkg)

        pkg.total_evidence_extracted = len(pkg.evidence_items)
        return pkg

    # ------------------------------------------------------------------
    # Context validation
    # ------------------------------------------------------------------

    def _validate_context_consistency(self, records: List[AgentExecutionRecord], expected_id: str):
        ctx_ids = set([expected_id])
        for r in records:
            if getattr(r, "context_id", None):
                ctx_ids.add(r.context_id)
        if len(ctx_ids) > 1:
            raise AggregationError(f"Context ID mismatch in SpecialistRunResult: {ctx_ids}")

    # ------------------------------------------------------------------
    # Multi-evidence extraction
    # ------------------------------------------------------------------

    def _process_specialist_output(
        self,
        record: AgentExecutionRecord,
        pkg: UnifiedEvidencePackage,
        seen_keys: Set[str],
    ):
        if not record.output:
            return

        cat = self._map_agent_to_category(record.agent_name)
        raw = record.output.raw_data or {}
        specialist_weight = self.weights.get(cat, 1.0)

        # ---- 1. Extract regime-level evidence (LLM interpretation) ----
        regime_direction = self._extract_specialist_regime_direction(record.agent_name, raw)
        regime_ne = NormalizedEvidence(
            evidence_id=str(uuid.uuid4()),
            specialist_name=record.agent_name,
            metric_name=f"{cat.value}_REGIME",
            category=cat,
            direction=regime_direction,
            confidence=record.output.confidence or 0.5,
            importance=specialist_weight,
            context_id=pkg.context_id,
            data_timestamp=pkg.data_timestamp,
            is_deterministic=False,
            is_llm_interpretation=True,
            evidence_type=EvidenceType.LLM_INTERPRETATION,
        )
        self._add_evidence_dedup(regime_ne, pkg, seen_keys)

        # ---- 2. Extract per-metric evidence items ----
        evidence_list_key = self._specialist_evidence_key.get(record.agent_name, "evidence")
        metric_name_key = self._specialist_metric_key.get(record.agent_name, "metric_name")
        evidence_list = raw.get(evidence_list_key, [])

        if isinstance(evidence_list, list):
            for item in evidence_list:
                if not isinstance(item, dict):
                    continue
                metric_name = item.get(metric_name_key, item.get("name", "unknown_metric"))
                if not metric_name:
                    continue

                # Determine value
                value = item.get("value")
                if value is not None:
                    try:
                        value = float(value)
                    except (TypeError, ValueError):
                        value = None

                # Determine availability
                available = item.get("available", True)

                # Determine evidence type
                evidence_type = self._classify_evidence_type(metric_name, item, available)

                # Determine unit
                unit = item.get("unit", "")

                # Determine source and provenance
                source = item.get("source", "UNKNOWN")
                calc_method = item.get("calculation_method", item.get("formula", item.get("method", "")))

                # Source tier and verification (from institutional metrics or defaults)
                source_tier = SourceTier.TIER_5_UNVERIFIED
                verification = VerificationStatus.UNVERIFIED
                raw_tier = item.get("source_tier")
                if raw_tier:
                    try:
                        source_tier = SourceTier(raw_tier)
                    except ValueError:
                        pass
                raw_verif = item.get("verification_status")
                if raw_verif:
                    try:
                        verification = VerificationStatus(raw_verif)
                    except ValueError:
                        pass

                # Data timestamp
                data_ts = pkg.data_timestamp
                raw_ts = item.get("data_timestamp")
                if raw_ts:
                    try:
                        data_ts = datetime.fromisoformat(str(raw_ts))
                    except (ValueError, TypeError):
                        pass

                # Context ID from item or fallback to package
                item_context = item.get("context_id", pkg.context_id)

                # Determine direction for metric-level evidence
                metric_direction = self._infer_metric_direction(metric_name, value, item)

                # Compute importance = weight * confidence * verification * source_quality
                conf = record.output.confidence or 0.5
                verif_mult = VERIFICATION_MULTIPLIER.get(verification, 0.7)
                sq_mult = SOURCE_QUALITY_MULTIPLIER.get(source_tier, 0.6)
                importance = specialist_weight * conf * verif_mult * sq_mult

                ne = NormalizedEvidence(
                    evidence_id=str(uuid.uuid4()),
                    specialist_name=record.agent_name,
                    metric_name=str(metric_name),
                    category=cat,
                    direction=metric_direction if available else SignalDirection.UNKNOWN,
                    value=value,
                    unit=str(unit),
                    confidence=conf,
                    importance=importance,
                    source=str(source),
                    source_tier=source_tier,
                    verification_status=verification,
                    context_id=str(item_context),
                    data_timestamp=data_ts,
                    calculation_method=str(calc_method),
                    is_deterministic=(evidence_type in (
                        EvidenceType.DETERMINISTIC_FACT,
                        EvidenceType.DETERMINISTIC_CALCULATION,
                    )),
                    is_llm_interpretation=(evidence_type == EvidenceType.LLM_INTERPRETATION),
                    evidence_type=evidence_type,
                )

                if not available:
                    ne = ne.model_copy(update={
                        "evidence_type": EvidenceType.UNAVAILABLE,
                        "is_deterministic": False,
                    })
                    pkg.missing_data_records.append(MissingDataRecord(
                        specialist_name=record.agent_name,
                        category=MissingDataCategory.METRIC_UNAVAILABLE,
                        detail=item.get("unavailable_reason", f"{metric_name} unavailable"),
                        metric_name=str(metric_name),
                    ))

                self._add_evidence_dedup(ne, pkg, seen_keys)

        # ---- 3. Populate backward-compatible signal lists ----
        if regime_direction == SignalDirection.BULLISH:
            pkg.bull_signals.append(f"{record.agent_name}: BULLISH")
        elif regime_direction == SignalDirection.BEARISH:
            pkg.bear_signals.append(f"{record.agent_name}: BEARISH")
        elif regime_direction == SignalDirection.NEUTRAL:
            pkg.neutral_signals.append(f"{record.agent_name}: NEUTRAL")

        if record.output.confidence and record.output.confidence >= 0.8:
            pkg.high_confidence_signals.append(record.agent_name)
        elif record.output.confidence and record.output.confidence < 0.5:
            pkg.low_confidence_signals.append(record.agent_name)

        # Aggregate risks, assumptions, invalidation
        if "risks" in raw and isinstance(raw["risks"], list):
            pkg.risks.extend(raw["risks"])
        if "invalidation_conditions" in raw and isinstance(raw["invalidation_conditions"], list):
            pkg.invalidation_conditions.extend(raw["invalidation_conditions"])
        if "assumptions" in raw and isinstance(raw["assumptions"], list):
            pkg.assumptions.extend(raw["assumptions"])

    # ------------------------------------------------------------------
    # Duplicate detection
    # ------------------------------------------------------------------

    def _add_evidence_dedup(
        self,
        ne: NormalizedEvidence,
        pkg: UnifiedEvidencePackage,
        seen_keys: Set[str],
    ):
        key = ne.duplicate_key
        if key in seen_keys:
            pkg.duplicates_detected += 1
            return
        seen_keys.add(key)
        pkg.evidence_items.append(ne)

    # ------------------------------------------------------------------
    # Category mapping
    # ------------------------------------------------------------------

    def _map_agent_to_category(self, agent_name: str) -> EvidenceCategory:
        cfg_cat = self._specialist_category_map.get(agent_name)
        if cfg_cat:
            try:
                return EvidenceCategory(cfg_cat)
            except ValueError:
                pass
        mapping = {
            "TechnicalSpecialist": EvidenceCategory.TECHNICAL,
            "MomentumSpecialist": EvidenceCategory.MOMENTUM,
            "QuantSpecialist": EvidenceCategory.QUANT,
            "FundamentalSpecialist": EvidenceCategory.FUNDAMENTAL,
            "ValuationSpecialist": EvidenceCategory.VALUATION,
            "SectorSpecialist": EvidenceCategory.SECTOR,
            "MacroSpecialist": EvidenceCategory.MACRO,
            "NewsSpecialist": EvidenceCategory.NEWS,
            "InstitutionalSpecialist": EvidenceCategory.INSTITUTIONAL,
        }
        return mapping.get(agent_name, EvidenceCategory.UNKNOWN)

    # ------------------------------------------------------------------
    # Direction extraction
    # ------------------------------------------------------------------

    def _extract_specialist_regime_direction(self, agent_name: str, raw_data: dict) -> SignalDirection:
        """Extract regime-level direction using config-driven regime keys."""
        regime_keys = self._specialist_regime_keys.get(agent_name, [])
        for key in regime_keys:
            val = raw_data.get(key)
            if val:
                direction = self._map_regime_to_direction(str(val).upper())
                if direction != SignalDirection.UNKNOWN:
                    return direction

        # Fallback: scan all string values
        return self._extract_signal_direction(raw_data)

    def _map_regime_to_direction(self, regime_value: str) -> SignalDirection:
        mapped = self._regime_dir_map.get(regime_value)
        if mapped:
            try:
                return SignalDirection(mapped)
            except ValueError:
                pass
        # Direct match
        try:
            return SignalDirection(regime_value)
        except ValueError:
            pass
        return SignalDirection.UNKNOWN

    def _extract_signal_direction(self, raw_data: dict) -> SignalDirection:
        """Legacy fallback: scan raw_data for known directional strings."""
        target_keys = [
            "trend_direction", "trend", "momentum_regime", "momentum_direction",
            "quant_regime", "statistical_regime",
            "fundamental_regime", "fundamental_quality",
            "valuation_regime", "valuation_status",
            "sector_regime", "macro_regime",
            "news_sentiment", "news_regime", "overall_sentiment",
            "institutional_regime",
        ]
        for k in target_keys:
            if k in raw_data and raw_data[k]:
                v = str(raw_data[k]).upper()
                direction = self._map_regime_to_direction(v)
                if direction != SignalDirection.UNKNOWN:
                    return direction

        for k, v in raw_data.items():
            if isinstance(v, str):
                direction = self._map_regime_to_direction(v.upper())
                if direction != SignalDirection.UNKNOWN:
                    return direction

        return SignalDirection.UNKNOWN

    def _infer_metric_direction(
        self, metric_name: str, value: Optional[float], item: dict
    ) -> SignalDirection:
        """Infer direction from a per-metric evidence item."""
        # If the item itself carries a direction-like field
        for key in ("interpretation", "direction"):
            interp = item.get(key, "")
            if isinstance(interp, str):
                up = interp.upper()
                if "BULLISH" in up or "ABOVE" in up or "OVERBOUGHT" in up:
                    return SignalDirection.BULLISH
                if "BEARISH" in up or "BELOW" in up or "OVERSOLD" in up:
                    return SignalDirection.BEARISH

        # Default: derive from parent regime (will be set at specialist level)
        return SignalDirection.NEUTRAL

    # ------------------------------------------------------------------
    # Evidence type classification
    # ------------------------------------------------------------------

    def _classify_evidence_type(
        self, metric_name: str, item: dict, available: bool
    ) -> EvidenceType:
        if not available:
            return EvidenceType.UNAVAILABLE

        # Check config overrides
        if metric_name in _FACT_METRICS:
            return EvidenceType.DETERMINISTIC_FACT

        # If it has calculation_method/formula → DETERMINISTIC_CALCULATION
        if item.get("calculation_method") or item.get("formula"):
            return EvidenceType.DETERMINISTIC_CALCULATION

        # If it has a numeric value and a source → DETERMINISTIC_FACT
        if item.get("value") is not None and item.get("source"):
            return EvidenceType.DETERMINISTIC_FACT

        return EvidenceType.LLM_INTERPRETATION

    # ------------------------------------------------------------------
    # PIT validation
    # ------------------------------------------------------------------

    def _validate_pit_consistency(self, pkg: UnifiedEvidencePackage):
        """Mark evidence items with PIT status based on timestamp drift."""
        ref_ts = pkg.data_timestamp
        for i, ev in enumerate(pkg.evidence_items):
            if ev.data_timestamp and ref_ts:
                drift = abs((ev.data_timestamp - ref_ts).total_seconds())
                if drift <= PIT_DRIFT_TOLERANCE.total_seconds():
                    pkg.evidence_items[i] = ev.model_copy(update={
                        "pit_status": PITStatus.CONSISTENT,
                    })
                else:
                    pkg.evidence_items[i] = ev.model_copy(update={
                        "pit_status": PITStatus.PIT_INCONSISTENT,
                    })
                    pkg.pit_inconsistent_count += 1
            else:
                pkg.evidence_items[i] = ev.model_copy(update={
                    "pit_status": PITStatus.UNKNOWN,
                })

    # ------------------------------------------------------------------
    # Agreement & Conflict computation
    # ------------------------------------------------------------------

    def _compute_agreements_and_conflicts(self, pkg: UnifiedEvidencePackage):
        """
        Two-level agreement/conflict detection:
        1. Domain-level: group regime evidences by direction
        2. Metric-level: find metrics with same name across specialists
        """
        # ---- Domain-level agreements (same as Phase 4.1 but with typed conflicts) ----
        regime_items = [e for e in pkg.evidence_items if e.metric_name.endswith("_REGIME")]
        bulls = [e for e in regime_items if e.direction == SignalDirection.BULLISH]
        bears = [e for e in regime_items if e.direction == SignalDirection.BEARISH]

        if len(bulls) >= 2:
            pkg.agreement_summary.append(EvidenceAgreement(
                agreement_id=str(uuid.uuid4()),
                categories=[e.category for e in bulls],
                direction=SignalDirection.BULLISH,
                supporting_specialists=[e.specialist_name for e in bulls],
                support_count=len(bulls),
                weighted_strength=sum(e.importance * e.confidence for e in bulls),
                explanation=f"Bullish agreement among {len(bulls)} specialists.",
                level=AgreementLevel.DOMAIN_LEVEL,
            ))

        if len(bears) >= 2:
            pkg.agreement_summary.append(EvidenceAgreement(
                agreement_id=str(uuid.uuid4()),
                categories=[e.category for e in bears],
                direction=SignalDirection.BEARISH,
                supporting_specialists=[e.specialist_name for e in bears],
                support_count=len(bears),
                weighted_strength=sum(e.importance * e.confidence for e in bears),
                explanation=f"Bearish agreement among {len(bears)} specialists.",
                level=AgreementLevel.DOMAIN_LEVEL,
            ))

        # ---- Metric-level agreements ----
        metric_groups: Dict[str, List[NormalizedEvidence]] = defaultdict(list)
        for e in pkg.evidence_items:
            if not e.metric_name.endswith("_REGIME"):
                metric_groups[e.metric_name].append(e)

        for metric_name, items in metric_groups.items():
            if len(items) < 2:
                continue
            # Check if multiple specialists produced same-direction evidence
            specialists_by_dir: Dict[SignalDirection, List[NormalizedEvidence]] = defaultdict(list)
            for item in items:
                if item.direction in (SignalDirection.BULLISH, SignalDirection.BEARISH):
                    specialists_by_dir[item.direction].append(item)
            for direction, aligned in specialists_by_dir.items():
                if len(aligned) >= 2:
                    unique_specialists = list(set(e.specialist_name for e in aligned))
                    if len(unique_specialists) >= 2:
                        pkg.agreement_summary.append(EvidenceAgreement(
                            agreement_id=str(uuid.uuid4()),
                            categories=list(set(e.category for e in aligned)),
                            direction=direction,
                            supporting_specialists=unique_specialists,
                            support_count=len(unique_specialists),
                            weighted_strength=sum(e.importance * e.confidence for e in aligned),
                            explanation=f"Metric-level {direction.value} agreement on '{metric_name}' across {len(unique_specialists)} specialists.",
                            level=AgreementLevel.METRIC_LEVEL,
                        ))

        # ---- Domain-level conflicts (DOMAIN_TENSION) ----
        for b in bulls:
            for br in bears:
                sev = ConflictSeverity.MODERATE
                if b.importance > 1.0 and br.importance > 1.0:
                    sev = ConflictSeverity.CRITICAL
                elif b.importance >= 1.0 or br.importance >= 1.0:
                    sev = ConflictSeverity.HIGH

                conflict_type = ConflictType.DOMAIN_TENSION
                if b.category == br.category:
                    conflict_type = ConflictType.DIRECT_CONFLICT

                pkg.conflict_summary.append(EvidenceConflict(
                    conflict_id=str(uuid.uuid4()),
                    category_a=b.category,
                    category_b=br.category,
                    signal_a=b.direction,
                    signal_b=br.direction,
                    specialist_a=b.specialist_name,
                    specialist_b=br.specialist_name,
                    severity=sev,
                    explanation=f"Conflict between {b.category.value} ({b.direction.value}) and {br.category.value} ({br.direction.value})",
                    context_id=pkg.context_id,
                    conflict_type=conflict_type,
                ))

        # ---- Metric-level conflicts (DIRECT_CONFLICT) ----
        for metric_name, items in metric_groups.items():
            if len(items) < 2:
                continue
            bulls_m = [e for e in items if e.direction == SignalDirection.BULLISH]
            bears_m = [e for e in items if e.direction == SignalDirection.BEARISH]
            for b in bulls_m:
                for br in bears_m:
                    if b.specialist_name == br.specialist_name:
                        continue
                    pkg.conflict_summary.append(EvidenceConflict(
                        conflict_id=str(uuid.uuid4()),
                        category_a=b.category,
                        category_b=br.category,
                        signal_a=b.direction,
                        signal_b=br.direction,
                        specialist_a=b.specialist_name,
                        specialist_b=br.specialist_name,
                        severity=ConflictSeverity.HIGH,
                        explanation=f"Direct conflict on metric '{metric_name}': {b.specialist_name} ({b.direction.value}) vs {br.specialist_name} ({br.direction.value})",
                        context_id=pkg.context_id,
                        conflict_type=ConflictType.DIRECT_CONFLICT,
                    ))

    # ------------------------------------------------------------------
    # Final metrics computation
    # ------------------------------------------------------------------

    def _compute_final_metrics(self, pkg: UnifiedEvidencePackage):
        if not pkg.evidence_items:
            pkg.overall_research_confidence = 0.0
            pkg.research_regime = ResearchRegime.INSUFFICIENT_DATA
            return

        total_weight = 0.0
        bull_score = 0.0
        bear_score = 0.0
        conf_sum = 0.0

        # Per-specialist contribution tracking for cap enforcement
        specialist_bull: Dict[str, float] = defaultdict(float)
        specialist_bear: Dict[str, float] = defaultdict(float)
        specialist_weight_sum: Dict[str, float] = defaultdict(float)

        for e in pkg.evidence_items:
            w = e.importance
            c = e.confidence
            total_weight += w
            conf_sum += c * w

            contribution = w * c
            specialist_weight_sum[e.specialist_name] += w

            if e.direction == SignalDirection.BULLISH:
                specialist_bull[e.specialist_name] += contribution
            elif e.direction == SignalDirection.BEARISH:
                specialist_bear[e.specialist_name] += contribution

        # Apply specialist contribution caps
        max_contribution = total_weight * MAX_SPECIALIST_CONTRIBUTION_SHARE if total_weight > 0 else 1.0

        for specialist in specialist_bull:
            capped = min(specialist_bull[specialist], max_contribution)
            bull_score += capped
            pkg.specialist_contributions[specialist] = capped

        for specialist in specialist_bear:
            capped = min(specialist_bear[specialist], max_contribution)
            bear_score += capped
            if specialist not in pkg.specialist_contributions:
                pkg.specialist_contributions[specialist] = capped
            else:
                pkg.specialist_contributions[specialist] += capped

        # For specialists that are neutral/unknown, record their contribution
        for specialist in specialist_weight_sum:
            if specialist not in pkg.specialist_contributions:
                pkg.specialist_contributions[specialist] = 0.0

        # Confidence calculation
        base_conf = conf_sum / total_weight if total_weight > 0 else 0.0

        # Evidence-aware conflict penalty
        conflict_penalty = 0.0
        for conflict in pkg.conflict_summary:
            conflict_penalty += CONFIDENCE_PENALTIES.get(conflict.severity, 0.03)

        missing_penalty = (pkg.specialists_failed + pkg.specialists_timed_out) * 0.1

        final_conf = max(0.0, min(1.0, base_conf - missing_penalty - conflict_penalty))
        pkg.overall_research_confidence = final_conf

        # Regime determination
        diff = bull_score - bear_score
        threshold = 0.5

        if total_weight < 1.0:
            pkg.research_regime = ResearchRegime.INSUFFICIENT_DATA
        else:
            if diff > threshold:
                pkg.research_regime = ResearchRegime.BULLISH
            elif diff < -threshold:
                pkg.research_regime = ResearchRegime.BEARISH
            else:
                pkg.research_regime = ResearchRegime.MIXED

    # ------------------------------------------------------------------
    # Empty package builder
    # ------------------------------------------------------------------

    def _build_empty_package(self, run_result: SpecialistRunResult) -> UnifiedEvidencePackage:
        return UnifiedEvidencePackage(
            run_id=run_result.run_id,
            context_id="empty",
            symbol="unknown",
            data_timestamp=datetime.utcnow(),
            specialists_total=0,
        )
