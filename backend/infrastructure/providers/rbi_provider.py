from backend.infrastructure.providers.base import BaseProvider, ProviderCapabilities, ProviderResult
from backend.domain.schemas import DataSource, SourceTier

class RBIProvider(BaseProvider):
    @property
    def name(self) -> str:
        return "RBI_Official"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            quotes=False,
            historical=False,
            fundamentals=False,
            filings=False,
            news=True,
            macro=True
        )
        
    @property
    def data_source_info(self) -> DataSource:
        return DataSource(
            provider_name=self.name,
            source_tier=SourceTier.TIER_1_PRIMARY_OFFICIAL,
            authority="Reserve Bank of India",
            subscription_required=False,
            authentication_required=False,
            provider_version="v1"
        )

    async def get_macro(self, indicator: str) -> ProviderResult:
        return ProviderResult(status="ERROR", error="Official RBI DBIE API access requires setup. Stubbed.")
