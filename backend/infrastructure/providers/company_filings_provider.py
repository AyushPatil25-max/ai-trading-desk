from backend.infrastructure.providers.base import BaseProvider, ProviderCapabilities, ProviderResult
from backend.domain.schemas import DataSource, SourceTier

class CompanyFilingsProvider(BaseProvider):
    @property
    def name(self) -> str:
        return "Company_Filings_Direct"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            quotes=False,
            historical=False,
            fundamentals=True,
            filings=True,
            news=True,
            macro=False
        )
        
    @property
    def data_source_info(self) -> DataSource:
        return DataSource(
            provider_name=self.name,
            source_tier=SourceTier.TIER_1_PRIMARY_OFFICIAL,
            authority="Corporate Investor Relations",
            subscription_required=False,
            authentication_required=False,
            provider_version="v1"
        )

    async def get_filings(self, symbol: str) -> ProviderResult:
        return ProviderResult(status="ERROR", error="Direct company filings ingestion requires EDGAR/XBRL parsers. Stubbed.")
