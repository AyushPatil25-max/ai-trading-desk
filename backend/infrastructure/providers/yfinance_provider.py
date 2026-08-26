import asyncio
import yfinance as yf
from datetime import datetime, timezone
import uuid

from backend.infrastructure.providers.base import BaseProvider, ProviderCapabilities, ProviderResult
from backend.domain.schemas import (
    ProvenanceRecord, SourceTier, VerificationStatus, DataQuality, DataSource
)

class YFinanceProvider(BaseProvider):
    @property
    def name(self) -> str:
        return "yfinance"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            quotes=True,
            historical=True,
            fundamentals=True,
            filings=False,
            news=True,
            macro=False,
            institutional=False,
            ownership=False,
            deals=False,
            delivery=False
        )
        
    @property
    def data_source_info(self) -> DataSource:
        return DataSource(
            provider_name=self.name,
            source_tier=SourceTier.TIER_4_SECONDARY,
            authority="Aggregator",
            subscription_required=False,
            authentication_required=False,
            provider_version="yfinance-python"
        )

    def _get_quote_sync(self, symbol: str) -> ProviderResult:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.fast_info
            price = info.last_price
            
            now = datetime.now(timezone.utc)
            
            prov = ProvenanceRecord(
                metric="current_price",
                symbol=symbol,
                value=price,
                unit="currency",
                currency=ticker.info.get("currency", "UNKNOWN"),
                source=self.data_source_info,
                verification_status=VerificationStatus.UNVERIFIED,
                quality=DataQuality.MEDIUM,
                observed_at=now,
                retrieved_at=now,
                publication_time=now,
                effective_time=now,
                period="real-time",
                context_id=str(uuid.uuid4()),
                adjusted=False
            )
            
            return ProviderResult(
                status="SUCCESS",
                data={"current_price": price},
                provenance=[prov]
            )
        except Exception as e:
            return ProviderResult(
                status="ERROR",
                error=str(e),
                provenance=[]
            )

    async def get_quote(self, symbol: str) -> ProviderResult:
        return await asyncio.to_thread(self._get_quote_sync, symbol)
        
    def _get_historical_sync(self, symbol: str, period: str) -> ProviderResult:
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period)
            if df.empty:
                return ProviderResult(status="ERROR", error="Empty dataframe returned.")
            
            df = df.reset_index()
            # Simple metadata extraction for demo purposes
            now = datetime.now(timezone.utc)
            return ProviderResult(
                status="SUCCESS",
                data={"ohlcv": df.to_dict(orient="records")},
                provenance=[]
            )
        except Exception as e:
            return ProviderResult(status="ERROR", error=str(e))

    async def get_historical_data(self, symbol: str, period: str) -> ProviderResult:
        return await asyncio.to_thread(self._get_historical_sync, symbol, period)

    def _get_fundamentals_sync(self, symbol: str) -> ProviderResult:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            
            # Use info dict for fast TTM fundamentals
            data = {}
            if "totalRevenue" in info:
                data["revenue"] = info["totalRevenue"]
            if "grossProfits" in info:
                data["gross_profit"] = info["grossProfits"]
            if "operatingMargins" in info and "totalRevenue" in info:
                data["operating_profit"] = info["totalRevenue"] * info["operatingMargins"]
            if "netIncomeToCommon" in info:
                data["net_income"] = info["netIncomeToCommon"]
            if "trailingEps" in info:
                data["eps"] = info["trailingEps"]
            if "totalCash" in info:
                data["cash"] = info["totalCash"]
            if "totalDebt" in info:
                data["total_debt"] = info["totalDebt"]
            if "operatingCashflow" in info:
                data["operating_cash_flow"] = info["operatingCashflow"]
            if "freeCashflow" in info:
                data["free_cash_flow"] = info["freeCashflow"]
            if "sharesOutstanding" in info:
                data["shares_outstanding"] = info["sharesOutstanding"]

            # Add context for fundamental_calculator
            data["period"] = "TTM"
            now = datetime.now(timezone.utc)
            data["report_date"] = now.isoformat() # Approx for YF fast info
            
            from backend.domain.schemas import FinancialObservation, PeriodType
            
            prov_records = []
            ctx_id = str(uuid.uuid4())
            currency = info.get("currency", "UNKNOWN")
            
            for k, v in data.items():
                if k in ["period", "report_date"]:
                    continue
                obs = FinancialObservation(
                    symbol=symbol,
                    metric=k,
                    value=float(v) if v is not None else 0.0,
                    unit="currency" if k != "shares_outstanding" else "shares",
                    currency=currency,
                    period="TTM",
                    period_type=PeriodType.TTM,
                    report_date=now,
                    publication_time=now,
                    effective_time=now,
                    source=self.name,
                    source_tier=SourceTier.TIER_4_SECONDARY,
                    context_id=ctx_id
                )
                data[k] = obs
                prov_records.append(obs) # Though FinancialObservation is not ProvenanceRecord exactly, it acts as one. 

            return ProviderResult(
                status="SUCCESS",
                data=data,
                provenance=[] # Financial observations act as the data itself here
            )
        except Exception as e:
            return ProviderResult(status="ERROR", error=str(e))

    async def get_fundamentals(self, symbol: str) -> ProviderResult:
        return await asyncio.to_thread(self._get_fundamentals_sync, symbol)
        
    async def get_news(self, symbol: str) -> ProviderResult:
        return ProviderResult(status="ERROR", error="Not explicitly mocked for now, but capability exists.")
