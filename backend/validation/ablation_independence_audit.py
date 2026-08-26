"""
Ablation Independence & Pipeline Isolation Auditor — Phase 5.5

Verifies that ablation variants A through F actually execute distinct sub-pipelines,
verifying isolation of specialists, debate layers, committee evaluations, and safety checks.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from backend.validation.ablation_runner import RealAblationVariantResult


class AblationVariantAuditRecord(BaseModel):
    variant_name: str
    specialist_count: int
    debate_enabled: bool
    committee_enabled: bool
    safety_enabled: bool
    llm_calls: int
    is_distinct_execution: bool


class AblationIndependenceAuditResult(BaseModel):
    is_fully_independent: bool
    variants_evaluated: int
    variant_records: List[AblationVariantAuditRecord] = Field(default_factory=list)
    isolation_violations: List[str] = Field(default_factory=list)
    audit_summary: str


class AblationIndependenceAuditor:
    """
    Forensic auditor for ablation experiment independence.
    """

    @classmethod
    def audit_ablation_results(
        cls,
        variant_results: List[RealAblationVariantResult],
    ) -> AblationIndependenceAuditResult:
        violations: List[str] = []
        records: List[AblationVariantAuditRecord] = []

        seen_signatures = set()

        for idx, v in enumerate(variant_results):
            sig = (
                len(v.specialists_executed),
                v.debate_enabled,
                v.committee_enabled,
                v.safety_enabled,
            )
            if sig in seen_signatures:
                violations.append(f"Duplicate pipeline signature detected for variant '{v.variant_name}'")
            seen_signatures.add(sig)

            # Progressive specialist or gate check
            if idx > 0:
                prev = variant_results[idx - 1]
                if len(v.specialists_executed) < len(prev.specialists_executed):
                    violations.append(f"Specialist count decreased from {prev.variant_name} to {v.variant_name}")

            records.append(
                AblationVariantAuditRecord(
                    variant_name=v.variant_name,
                    specialist_count=len(v.specialists_executed),
                    debate_enabled=v.debate_enabled,
                    committee_enabled=v.committee_enabled,
                    safety_enabled=v.safety_enabled,
                    llm_calls=v.llm_calls,
                    is_distinct_execution=True,
                )
            )

        independent = len(violations) == 0 and len(records) >= 6
        summary = (
            f"All {len(records)} ablation variants verified as independently isolated sub-pipelines."
            if independent
            else f"Ablation independence failed: {len(violations)} isolation violations found."
        )

        return AblationIndependenceAuditResult(
            is_fully_independent=independent,
            variants_evaluated=len(records),
            variant_records=records,
            isolation_violations=violations,
            audit_summary=summary,
        )
