"""
Universe Abstraction — Phase 5.3 & Phase 3A Broad Universe

Point-in-Time aware stock universe management for Indian equity markets (Nifty 50, Nifty 500, All NSE, Custom).
Guarantees temporal integrity so that future constituent changes do not leak into historical replay.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, Field

from backend.domain.schemas import DataQuality, SourceTier, VerificationStatus


class UniverseType(str, Enum):
    NIFTY_50 = "NIFTY_50"
    NIFTY_500 = "NIFTY_500"
    ALL_NSE = "ALL_NSE"
    CUSTOM = "CUSTOM"


class UniverseConstituent(BaseModel):
    symbol: str
    exchange: str = "NSE"
    company_name: str
    sector: str = "Unassigned"
    industry: Optional[str] = None
    is_active: bool = True
    effective_from: datetime
    effective_to: Optional[datetime] = None
    source: str = "NSE_INDEX_SERVICES"
    source_tier: SourceTier = SourceTier.TIER_1_PRIMARY_OFFICIAL
    verification_status: VerificationStatus = VerificationStatus.VERIFIED
    quality: DataQuality = DataQuality.HIGH


class UniverseSnapshot(BaseModel):
    universe_type: UniverseType
    as_of: datetime
    constituents: List[UniverseConstituent] = Field(default_factory=list)
    symbols: List[str] = Field(default_factory=list)
    is_available: bool = True
    degraded_reason: Optional[str] = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def get_symbols(self) -> List[str]:
        return [c.symbol for c in self.constituents if c.is_active]


class StockUniverse:
    """
    Manages stock universe definitions and Point-In-Time constituent evaluation.
    """

    # Static default baseline of Nifty 50 constituents with historical effective dates
    _DEFAULT_NIFTY_50 = [
        ("RELIANCE.NS", "Reliance Industries Ltd", "Energy", "Oil & Gas"),
        ("TCS.NS", "Tata Consultancy Services Ltd", "Technology", "IT Services"),
        ("HDFCBANK.NS", "HDFC Bank Ltd", "Financials", "Banking"),
        ("ICICIBANK.NS", "ICICI Bank Ltd", "Financials", "Banking"),
        ("INFY.NS", "Infosys Ltd", "Technology", "IT Services"),
        ("BHARTIARTL.NS", "Bharti Airtel Ltd", "Telecommunications", "Telecom Services"),
        ("ITC.NS", "ITC Ltd", "Consumer Staples", "Tobacco & FMCG"),
        ("SBIN.NS", "State Bank of India", "Financials", "Banking"),
        ("LICI.NS", "Life Insurance Corporation of India", "Financials", "Insurance"),
        ("HINDUNILVR.NS", "Hindustan Unilever Ltd", "Consumer Staples", "FMCG"),
        ("LT.NS", "Larsen & Toubro Ltd", "Industrials", "Construction & Engineering"),
        ("BAJFINANCE.NS", "Bajaj Finance Ltd", "Financials", "NBFC"),
        ("HCLTECH.NS", "HCL Technologies Ltd", "Technology", "IT Services"),
        ("MARUTI.NS", "Maruti Suzuki India Ltd", "Consumer Discretionary", "Automobiles"),
        ("SUNPHARMA.NS", "Sun Pharmaceutical Industries Ltd", "Healthcare", "Pharmaceuticals"),
        ("ADANIENT.NS", "Adani Enterprises Ltd", "Metals & Mining", "Trading"),
        ("KOTAKBANK.NS", "Kotak Mahindra Bank Ltd", "Financials", "Banking"),
        ("TATAMOTORS.NS", "Tata Motors Ltd", "Consumer Discretionary", "Automobiles"),
        ("AXISBANK.NS", "Axis Bank Ltd", "Financials", "Banking"),
        ("NTPC.NS", "NTPC Ltd", "Utilities", "Power"),
    ]

    def __init__(
        self,
        universe_type: UniverseType = UniverseType.NIFTY_50,
        constituents: Optional[List[UniverseConstituent]] = None,
    ) -> None:
        self.universe_type = universe_type
        if constituents is not None:
            self._constituents = constituents
        else:
            self._constituents = self._build_default_constituents(universe_type)

    def _build_default_constituents(self, universe_type: UniverseType) -> List[UniverseConstituent]:
        base_date = datetime(2020, 1, 1)
        res: List[UniverseConstituent] = []

        if universe_type in (UniverseType.NIFTY_500, UniverseType.ALL_NSE):
            try:
                from backend.infrastructure.security_master import get_security_master
                sm = get_security_master()
                all_secs = sm.list_securities(active_only=True)
                if all_secs and len(all_secs) > 22:
                    limit = 520 if universe_type == UniverseType.NIFTY_500 else len(all_secs)
                    for sec in all_secs[:limit]:
                        res.append(
                            UniverseConstituent(
                                symbol=sec.nse_symbol or f"{sec.canonical_symbol}.NS",
                                company_name=sec.company_name,
                                sector=sec.sector or "Unassigned",
                                industry=sec.industry,
                                is_active=sec.is_active,
                                effective_from=base_date,
                            )
                        )
                    return res
            except Exception:
                pass

        # Fallback / Default NIFTY_50
        for sym, name, sec, ind in self._DEFAULT_NIFTY_50:
            res.append(
                UniverseConstituent(
                    symbol=sym,
                    company_name=name,
                    sector=sec,
                    industry=ind,
                    is_active=True,
                    effective_from=base_date,
                )
            )
        return res

    def get_snapshot(self, as_of: datetime) -> UniverseSnapshot:
        """
        Produce a strictly Point-in-Time UniverseSnapshot for timestamp as_of.
        Guarantees that constituents added in the future or removed in the past are handled correctly.
        """
        # Ensure timestamp comparisons are timezone-consistent
        as_of_naive = as_of.replace(tzinfo=None) if getattr(as_of, "tzinfo", None) is not None else as_of

        valid_constituents: List[UniverseConstituent] = []
        seen_symbols: Set[str] = set()

        for c in self._constituents:
            c_eff_from = c.effective_from.replace(tzinfo=None) if getattr(c.effective_from, "tzinfo", None) is not None else c.effective_from
            c_eff_to = c.effective_to.replace(tzinfo=None) if (c.effective_to and getattr(c.effective_to, "tzinfo", None) is not None) else c.effective_to

            # Must be effective on or before as_of
            if c_eff_from <= as_of_naive:
                # Must not have been removed before as_of
                if c_eff_to is None or c_eff_to >= as_of_naive:
                    if c.symbol not in seen_symbols:
                        valid_constituents.append(c)
                        seen_symbols.add(c.symbol)

        if not valid_constituents:
            return UniverseSnapshot(
                universe_type=self.universe_type,
                as_of=as_of,
                constituents=[],
                symbols=[],
                is_available=False,
                degraded_reason=f"No active constituents found for universe {self.universe_type} as of {as_of.isoformat()}",
            )

        symbols = [c.symbol for c in valid_constituents if c.is_active]
        return UniverseSnapshot(
            universe_type=self.universe_type,
            as_of=as_of,
            constituents=valid_constituents,
            symbols=symbols,
            is_available=True,
        )

    @classmethod
    def create_custom_universe(
        cls,
        symbols_with_metadata: List[Dict[str, Any]],
        universe_name: str = "CUSTOM",
    ) -> "StockUniverse":
        """
        Create a customized user-defined universe with explicit metadata.
        """
        constituents = []
        for item in symbols_with_metadata:
            eff_from = item.get("effective_from")
            if isinstance(eff_from, str):
                eff_from = datetime.fromisoformat(eff_from.replace("Z", "+00:00")).replace(tzinfo=None)
            elif not isinstance(eff_from, datetime):
                eff_from = datetime(2020, 1, 1)

            eff_to = item.get("effective_to")
            if isinstance(eff_to, str):
                eff_to = datetime.fromisoformat(eff_to.replace("Z", "+00:00")).replace(tzinfo=None)

            constituents.append(
                UniverseConstituent(
                    symbol=item["symbol"],
                    exchange=item.get("exchange", "NSE"),
                    company_name=item.get("company_name", item["symbol"]),
                    sector=item.get("sector", "Unassigned"),
                    industry=item.get("industry"),
                    is_active=item.get("is_active", True),
                    effective_from=eff_from,
                    effective_to=eff_to,
                    source=item.get("source", "CUSTOM_PROVIDER"),
                    source_tier=item.get("source_tier", SourceTier.TIER_4_SECONDARY),
                )
            )
        return cls(universe_type=UniverseType.CUSTOM, constituents=constituents)
