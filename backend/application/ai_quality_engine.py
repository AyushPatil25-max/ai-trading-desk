import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime

from backend.domain.ai_quality_schemas import (
    ClaimValidationStatus,
    QualityClaim,
    QualityResult,
    QualityValidatedResponse
)
from backend.infrastructure.llm_provider_adapter import LLMAdapterFactory
from pydantic import BaseModel, Field

class ExtractedClaim(BaseModel):
    claim_text: str
    claim_type: str
    numerical_value: Optional[float] = None
    subject: Optional[str] = None

class ExtractionResult(BaseModel):
    claims: List[ExtractedClaim]

class EvidenceItem(BaseModel):
    evidence_id: str
    content: str
    source_reference: Optional[str] = None

class AIQualityEngine:
    def __init__(self):
        self.llm_client = LLMAdapterFactory.create_client("gemini_flash", temperature=0.0)

    async def extract_claims(self, text: str) -> List[ExtractedClaim]:
        prompt = (
            "Extract the verifiable factual claims from the following text. "
            "Focus on numerical values, dates, financial metrics, comparisons, and definitive statements. "
            "Do not extract opinions or questions. "
            f"Text: {text}"
        )
        try:
            res = await self.llm_client.generate_structured(
                system_prompt="You are a strict factual claim extractor.",
                user_prompt=prompt,
                response_model=ExtractionResult
            )
            return res.claims
        except Exception:
            # Fallback if LLM fails
            return []

    def validate_claim(self, claim: ExtractedClaim, evidence_pool: List[EvidenceItem]) -> QualityClaim:
        status = ClaimValidationStatus.UNSUPPORTED
        matched_refs = []
        explanation = "No evidence found to support this claim."
        
        # Super naive deterministic keyword/numeric check for demonstration of principle
        # In a real system, this would use semantic similarity + exact numeric matching
        claim_lower = claim.claim_text.lower()
        
        for ev in evidence_pool:
            ev_content_lower = ev.content.lower()
            
            # Simple keyword overlap heuristic
            words = set(w for w in claim_lower.split() if len(w) > 4)
            if not words:
                continue
                
            overlap = sum(1 for w in words if w in ev_content_lower)
            if overlap / len(words) > 0.5:
                # We found a potential match
                if claim.numerical_value is not None:
                    # Deterministic numeric validation
                    val_str = str(claim.numerical_value)
                    if val_str in ev_content_lower or val_str.replace(".0", "") in ev_content_lower:
                        status = ClaimValidationStatus.SUPPORTED
                        matched_refs.append(ev.evidence_id)
                        explanation = "Claim is numerically supported by evidence."
                    else:
                        # Might be a contradiction if the text is talking about the same subject but different number
                        if claim.subject and claim.subject.lower() in ev_content_lower:
                            status = ClaimValidationStatus.CONTRADICTED
                            matched_refs.append(ev.evidence_id)
                            explanation = f"Evidence discusses '{claim.subject}' but contradicts the numerical value {claim.numerical_value}."
                        else:
                            status = ClaimValidationStatus.PARTIALLY_SUPPORTED
                            matched_refs.append(ev.evidence_id)
                            explanation = "Topic matched but exact numerical value could not be deterministically verified."
                else:
                    status = ClaimValidationStatus.SUPPORTED
                    matched_refs.append(ev.evidence_id)
                    explanation = "Claim is supported by text overlap in evidence."
                    
        # If no evidence was even checked
        if not evidence_pool:
            status = ClaimValidationStatus.UNAVAILABLE
            explanation = "No evidence available to validate against."

        return QualityClaim(
            claim_id=uuid.uuid4().hex,
            claim_text=claim.claim_text,
            claim_type=claim.claim_type,
            validation_status=status,
            evidence_refs=matched_refs,
            explanation=explanation
        )

    async def validate_response(self, ai_text: str, evidence_pool: List[EvidenceItem]) -> QualityValidatedResponse:
        extracted = await self.extract_claims(ai_text)
        
        validated_claims = []
        for c in extracted:
            validated_claims.append(self.validate_claim(c, evidence_pool))
            
        supported_count = sum(1 for c in validated_claims if c.validation_status == ClaimValidationStatus.SUPPORTED)
        contradicted_count = sum(1 for c in validated_claims if c.validation_status == ClaimValidationStatus.CONTRADICTED)
        
        overall_status = "HIGH_QUALITY"
        if contradicted_count > 0:
            overall_status = "HAS_CONTRADICTIONS"
        elif len(validated_claims) > 0 and supported_count == 0:
            overall_status = "UNSUPPORTED_CLAIMS_DETECTED"
        elif len(validated_claims) > 0 and supported_count < len(validated_claims):
            overall_status = "MIXED_SUPPORT"
            
        coverage = (supported_count / len(validated_claims)) * 100 if validated_claims else 100.0
        
        warnings = []
        if contradicted_count > 0:
            warnings.append("WARNING: The AI generated claims that contradict authoritative evidence.")
            
        qr = QualityResult(
            overall_status=overall_status,
            claims=validated_claims,
            uncertainty_warnings=warnings,
            evidence_coverage_pct=coverage
        )
        
        return QualityValidatedResponse(
            original_text=ai_text,
            quality_result=qr
        )

global_ai_quality_engine = AIQualityEngine()
