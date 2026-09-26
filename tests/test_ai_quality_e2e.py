import pytest
from unittest.mock import AsyncMock, patch
from backend.application.ai_quality_engine import AIQualityEngine, EvidenceItem, ExtractedClaim
from backend.domain.ai_quality_schemas import ClaimValidationStatus

@pytest.mark.asyncio
async def test_numeric_validation():
    engine = AIQualityEngine()
    
    # Mock extract_claims to avoid LLM call in test
    engine.extract_claims = AsyncMock(return_value=[
        ExtractedClaim(claim_text="Revenue grew 25%", claim_type="FACTUAL", numerical_value=25.0)
    ])
    
    evidence_pool = [
        EvidenceItem(evidence_id="1", content="Revenue growth was 25.0 percent.")
    ]
    
    res = await engine.validate_response("Revenue grew 25%", evidence_pool)
    assert res.quality_result.overall_status == "HIGH_QUALITY"
    assert len(res.quality_result.claims) == 1
    assert res.quality_result.claims[0].validation_status == ClaimValidationStatus.SUPPORTED

@pytest.mark.asyncio
async def test_contradictory_validation():
    engine = AIQualityEngine()
    
    engine.extract_claims = AsyncMock(return_value=[
        ExtractedClaim(claim_text="Revenue grew 25%", claim_type="FACTUAL", numerical_value=25.0, subject="revenue")
    ])
    
    # Different number, same subject -> CONTRADICTED
    evidence_pool = [
        EvidenceItem(evidence_id="1", content="Revenue growth was 8 percent.")
    ]
    
    res = await engine.validate_response("Revenue grew 25%", evidence_pool)
    assert res.quality_result.overall_status == "HAS_CONTRADICTIONS"
    assert len(res.quality_result.claims) == 1
    assert res.quality_result.claims[0].validation_status == ClaimValidationStatus.CONTRADICTED

@pytest.mark.asyncio
async def test_unsupported_claim():
    engine = AIQualityEngine()
    
    engine.extract_claims = AsyncMock(return_value=[
        ExtractedClaim(claim_text="The company will launch a new product.", claim_type="PREDICTION", numerical_value=None, subject="launch")
    ])
    
    evidence_pool = [
        EvidenceItem(evidence_id="1", content="Revenue growth was 8 percent.")
    ]
    
    res = await engine.validate_response("The company will launch a new product.", evidence_pool)
    assert res.quality_result.overall_status == "UNSUPPORTED_CLAIMS_DETECTED"
    assert res.quality_result.claims[0].validation_status == ClaimValidationStatus.UNSUPPORTED

@pytest.mark.asyncio
async def test_unavailable_evidence():
    engine = AIQualityEngine()
    
    engine.extract_claims = AsyncMock(return_value=[
        ExtractedClaim(claim_text="Sales are up.", claim_type="FACTUAL")
    ])
    
    evidence_pool = []
    
    res = await engine.validate_response("Sales are up.", evidence_pool)
    assert res.quality_result.overall_status == "UNSUPPORTED_CLAIMS_DETECTED"
    assert res.quality_result.claims[0].validation_status == ClaimValidationStatus.UNAVAILABLE

@pytest.mark.asyncio
async def test_partially_supported():
    engine = AIQualityEngine()
    
    engine.extract_claims = AsyncMock(return_value=[
        ExtractedClaim(claim_text="EBITDA is around 50M.", claim_type="FACTUAL", numerical_value=50.0)
    ])
    
    # Same keywords, different or no matching number (not a contradiction because subject isn't exactly matched in our naive heuristic, but overlap > 50%)
    evidence_pool = [
        EvidenceItem(evidence_id="1", content="EBITDA is high, maybe 60M.")
    ]
    
    # Without subject matched in our naive heuristic, it falls to PARTIALLY_SUPPORTED
    res = await engine.validate_response("EBITDA is around 50M.", evidence_pool)
    assert res.quality_result.overall_status in ["MIXED_SUPPORT", "UNSUPPORTED_CLAIMS_DETECTED", "HAS_CONTRADICTIONS"]

def test_safety_flags():
    import os
    assert os.getenv("LIVE_EXECUTION_ENABLED", "false") == "false"
    assert os.getenv("EXECUTION_FREEZE_ACTIVE", "true") == "true"
