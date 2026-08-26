from backend.infrastructure.providers.base import BaseProvider, ProviderCapabilities, ProviderResult
from backend.domain.schemas import DataSource, SourceTier

class SEBIProvider(BaseProvider):
    @property
    def name(self) -> str:
        return "SEBI_Official"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            quotes=False,
            historical=False,
            fundamentals=False,
            filings=True,
            news=True,
            macro=False
        )
        
    @property
    def data_source_info(self) -> DataSource:
        return DataSource(
            provider_name=self.name,
            source_tier=SourceTier.TIER_2_REGULATORY,
            authority="Securities and Exchange Board of India",
            subscription_required=False,
            authentication_required=True,
            provider_version="v1"
        )

    async def get_filings(self, symbol: str) -> ProviderResult:
        return ProviderResult(status="ERROR", error="SEBI data feed requires formal access. Stubbed.")
