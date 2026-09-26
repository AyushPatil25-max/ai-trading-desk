"""
YFinance Provider — Phase 2, Phase 3B & Phase 3C Data Coverage

Enriched secondary market data provider with multi-period TTM fundamentals,
multi-quarter financial statements (4-8 quarters), corporate actions (dividends, splits),
shareholding/ownership breakdown, news extraction, and historical OHLCV.
"""

import asyncio
import math
from datetime import datetime, timezone, timedelta
import uuid
from typing import Dict, Any, List, Optional
import pandas as pd

from backend.infrastructure.providers.base import BaseProvider, ProviderCapabilities, ProviderResult
from backend.domain.schemas import (
    ProvenanceRecord,
    SourceTier,
    VerificationStatus,
    DataQuality,
    DataSource,
    FinancialObservation,
    PeriodType,
    QuarterlyStatement,
    CorporateAction,
    CorporateActionType,
    OwnershipObservation,
    HolderType,
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
            ownership=True,
            deals=False,
            delivery=False,
            earnings_calendar=True,
        )

    @property
    def data_source_info(self) -> DataSource:
        return DataSource(
            provider_name=self.name,
            source_tier=SourceTier.TIER_4_SECONDARY,
            authority="Aggregator",
            subscription_required=False,
            authentication_required=False,
            provider_version="yfinance-python",
        )

    def _normalize_ticker(self, symbol: str) -> str:
        """Helper to ensure Indian tickers have the correct exchange suffix."""
        if not symbol.endswith(".NS") and not symbol.endswith(".BO") and not symbol.startswith("^") and "=" not in symbol:
            return f"{symbol}.NS"
        return symbol

    def _get_quote_sync(self, symbol: str) -> ProviderResult:
        try:
            import yfinance as yf

            normalized = self._normalize_ticker(symbol)
            ticker = yf.Ticker(normalized)
            info = ticker.fast_info
            price = float(info.last_price) if hasattr(info, "last_price") and info.last_price else 0.0

            now = datetime.now(timezone.utc)
            ctx_id = str(uuid.uuid4())

            prov = ProvenanceRecord(
                metric="current_price",
                symbol=symbol,
                value=price,
                unit="currency",
                currency=getattr(info, "currency", "INR") or "INR",
                source=self.data_source_info,
                verification_status=VerificationStatus.UNVERIFIED,
                quality=DataQuality.MEDIUM if price > 0 else DataQuality.INVALID,
                observed_at=now,
                retrieved_at=now,
                publication_time=now,
                effective_time=now,
                period="real-time",
                context_id=ctx_id,
                adjusted=False,
            )

            return ProviderResult(
                status="SUCCESS" if price > 0 else "ERROR",
                data={"current_price": price},
                provenance=[prov],
            )
        except Exception as e:
            return ProviderResult(status="ERROR", error=str(e), provenance=[])

    async def get_quote(self, symbol: str) -> ProviderResult:
        return await asyncio.to_thread(self._get_quote_sync, symbol)

    def _get_historical_sync(self, symbol: str, period: str) -> ProviderResult:
        try:
            import yfinance as yf

            normalized = self._normalize_ticker(symbol)
            ticker = yf.Ticker(normalized)
            df = ticker.history(period=period)
            if df is None or df.empty:
                return ProviderResult(status="ERROR", error="Empty dataframe returned from yfinance.")

            df = df.reset_index()
            return ProviderResult(
                status="SUCCESS",
                data={"ohlcv": df.to_dict(orient="records")},
                provenance=[],
            )
        except Exception as e:
            return ProviderResult(status="ERROR", error=str(e))

    async def get_historical_data(self, symbol: str, period: str) -> ProviderResult:
        return await asyncio.to_thread(self._get_historical_sync, symbol, period)

    def _get_fundamentals_sync(self, symbol: str) -> ProviderResult:
        try:
            import yfinance as yf

            normalized = self._normalize_ticker(symbol)
            ticker = yf.Ticker(normalized)
            info = ticker.info or {}

            data: Dict[str, Any] = {}
            if "totalRevenue" in info and info["totalRevenue"] is not None:
                data["revenue"] = float(info["totalRevenue"])
            if "grossProfits" in info and info["grossProfits"] is not None:
                data["gross_profit"] = float(info["grossProfits"])
            if "operatingMargins" in info and "totalRevenue" in info and info["operatingMargins"] is not None and info["totalRevenue"] is not None:
                data["operating_profit"] = float(info["totalRevenue"]) * float(info["operatingMargins"])
            if "netIncomeToCommon" in info and info["netIncomeToCommon"] is not None:
                data["net_income"] = float(info["netIncomeToCommon"])
            if "trailingEps" in info and info["trailingEps"] is not None:
                data["eps"] = float(info["trailingEps"])
            if "totalCash" in info and info["totalCash"] is not None:
                data["cash"] = float(info["totalCash"])
            if "totalDebt" in info and info["totalDebt"] is not None:
                data["total_debt"] = float(info["totalDebt"])
            if "operatingCashflow" in info and info["operatingCashflow"] is not None:
                data["operating_cash_flow"] = float(info["operatingCashflow"])
            if "freeCashflow" in info and info["freeCashflow"] is not None:
                data["free_cash_flow"] = float(info["freeCashflow"])
            if "sharesOutstanding" in info and info["sharesOutstanding"] is not None:
                data["shares_outstanding"] = float(info["sharesOutstanding"])
            if "trailingPE" in info and info["trailingPE"] is not None:
                data["pe_ratio"] = float(info["trailingPE"])
            if "priceToBook" in info and info["priceToBook"] is not None:
                data["pb_ratio"] = float(info["priceToBook"])
            if "enterpriseToEbitda" in info and info["enterpriseToEbitda"] is not None:
                data["ev_ebitda"] = float(info["enterpriseToEbitda"])
            if "returnOnEquity" in info and info["returnOnEquity"] is not None:
                data["roe"] = float(info["returnOnEquity"])
            if "returnOnAssets" in info and info["returnOnAssets"] is not None:
                data["roa"] = float(info["returnOnAssets"])
            if "dividendYield" in info and info["dividendYield"] is not None:
                data["dividend_yield"] = float(info["dividendYield"])

            now = datetime.now(timezone.utc)
            ctx_id = str(uuid.uuid4())
            currency = info.get("currency", "INR") or "INR"

            for k, v in list(data.items()):
                unit_type = "currency"
                if k == "shares_outstanding":
                    unit_type = "shares"
                elif "ratio" in k or k in ("pe_ratio", "pb_ratio", "ev_ebitda"):
                    unit_type = "x"
                elif k in ("roe", "roa", "dividend_yield"):
                    unit_type = "%"

                obs = FinancialObservation(
                    symbol=symbol,
                    metric=k,
                    value=float(v) if v is not None else 0.0,
                    unit=unit_type,
                    currency=currency,
                    period="TTM",
                    period_type=PeriodType.TTM,
                    report_date=now,
                    publication_time=now,
                    effective_time=now,
                    source=self.name,
                    source_tier=SourceTier.TIER_4_SECONDARY,
                    context_id=ctx_id,
                )
                data[k] = obs

            data["period"] = "TTM"
            data["report_date"] = now.isoformat()

            return ProviderResult(
                status="SUCCESS",
                data=data,
                provenance=[],
            )
        except Exception as e:
            return ProviderResult(status="ERROR", error=str(e))

    async def get_fundamentals(self, symbol: str) -> ProviderResult:
        return await asyncio.to_thread(self._get_fundamentals_sync, symbol)

    def _get_quarterly_fundamentals_sync(self, symbol: str) -> ProviderResult:
        """
        Extract up to 8 historical quarters of structured balance sheet, P&L, and cash flow.
        """
        try:
            import yfinance as yf

            normalized = self._normalize_ticker(symbol)
            ticker = yf.Ticker(normalized)

            # Income Statement
            inc_df = getattr(ticker, "quarterly_income_stmt", None)
            if inc_df is None or inc_df.empty:
                inc_df = getattr(ticker, "quarterly_financials", None)

            # Balance Sheet
            bs_df = getattr(ticker, "quarterly_balance_sheet", None)

            # Cash Flow
            cf_df = getattr(ticker, "quarterly_cashflow", None)

            statements: List[QuarterlyStatement] = []
            now = datetime.now(timezone.utc)

            # Collect all distinct quarter column dates
            quarter_dates = []
            for df in (inc_df, bs_df, cf_df):
                if df is not None and not df.empty:
                    for col in df.columns:
                        if col not in quarter_dates:
                            quarter_dates.append(col)

            # Sort chronological descending (latest first) up to 8 quarters
            quarter_dates.sort(reverse=True)
            quarter_dates = quarter_dates[:8]

            for q_date in quarter_dates:
                def get_val(df, row_names):
                    if df is None or df.empty or q_date not in df.columns:
                        return None
                    for name in row_names:
                        if name in df.index:
                            val = df.loc[name, q_date]
                            if pd.notna(val):
                                try:
                                    f = float(val)
                                    if not math.isnan(f) and not math.isinf(f):
                                        return f
                                except Exception:
                                    pass
                    return None

                rev = get_val(inc_df, ["Total Revenue", "Operating Revenue", "TotalRevenue", "Revenue"])
                op_inc = get_val(inc_df, ["Operating Income", "Operating Profit", "OperatingIncome"])
                net_inc = get_val(inc_df, ["Net Income", "Net Income Common Stockholders", "NetIncome"])
                ebitda = get_val(inc_df, ["EBITDA", "Normalized EBITDA"])
                eps = get_val(inc_df, ["Diluted EPS", "Basic EPS", "DilutedEPS", "BasicEPS"])

                op_margin = None
                if rev is not None and op_inc is not None and rev > 0:
                    op_margin = round((op_inc / rev) * 100.0, 2)

                tot_assets = get_val(bs_df, ["Total Assets", "TotalAssets"])
                tot_liab = get_val(bs_df, ["Total Liabilities Net Minority Interest", "Total Liabilities", "TotalLiabilities"])
                tot_equity = get_val(bs_df, ["Stockholders Equity", "Total Equity Gross Minority Interest", "TotalStockholderEquity"])
                cash = get_val(bs_df, ["Cash And Cash Equivalents", "Cash And Cash Equivalents At Carrying Value", "CashAndCashEquivalents"])
                debt = get_val(bs_df, ["Total Debt", "TotalDebt", "Long Term Debt", "LongTermDebt"])

                op_cf = get_val(cf_df, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities", "OperatingCashFlow"])
                inv_cf = get_val(cf_df, ["Investing Cash Flow", "Cash Flow From Continuing Investing Activities", "InvestingCashFlow"])
                fin_cf = get_val(cf_df, ["Financing Cash Flow", "Cash Flow From Continuing Financing Activities", "FinancingCashFlow"])
                fcf = get_val(cf_df, ["Free Cash Flow", "FreeCashFlow"])

                if isinstance(q_date, pd.Timestamp):
                    p_end = q_date.to_pydatetime()
                elif isinstance(q_date, str):
                    p_end = datetime.fromisoformat(q_date.replace("Z", "+00:00"))
                else:
                    p_end = datetime.now(timezone.utc)

                if p_end.tzinfo is None:
                    p_end = p_end.replace(tzinfo=timezone.utc)

                month = p_end.month
                if month in (4, 5, 6):
                    f_period, f_year = "Q1", p_end.year + 1
                elif month in (7, 8, 9):
                    f_period, f_year = "Q2", p_end.year + 1
                elif month in (10, 11, 12):
                    f_period, f_year = "Q3", p_end.year + 1
                else:
                    f_period, f_year = "Q4", p_end.year

                pub_time = p_end + timedelta(days=45)

                stmt = QuarterlyStatement(
                    symbol=symbol,
                    period_end_date=p_end,
                    fiscal_period=f_period,
                    fiscal_year=f_year,
                    filing_date=pub_time,
                    publication_time=pub_time,
                    revenue=rev,
                    operating_profit=op_inc,
                    operating_margin=op_margin,
                    ebitda=ebitda,
                    net_income=net_inc,
                    eps=eps,
                    total_assets=tot_assets,
                    total_liabilities=tot_liab,
                    total_equity=tot_equity,
                    cash=cash,
                    total_debt=debt,
                    operating_cash_flow=op_cf,
                    investing_cash_flow=inv_cf,
                    financing_cash_flow=fin_cf,
                    free_cash_flow=fcf,
                    source=self.name,
                    source_tier=SourceTier.TIER_4_SECONDARY,
                    retrieved_at=now,
                )
                statements.append(stmt)

            return ProviderResult(
                status="SUCCESS" if statements else "ERROR",
                data={"quarterly_statements": [s.model_dump() for s in statements]},
                provenance=[],
            )
        except Exception as e:
            return ProviderResult(status="ERROR", error=str(e))

    async def get_quarterly_fundamentals(self, symbol: str) -> ProviderResult:
        return await asyncio.to_thread(self._get_quarterly_fundamentals_sync, symbol)

    def _get_corporate_actions_sync(self, symbol: str) -> ProviderResult:
        """
        Extract historical corporate actions including cash dividends, stock splits, and bonus issues.
        """
        try:
            import yfinance as yf

            normalized = self._normalize_ticker(symbol)
            ticker = yf.Ticker(normalized)
            now = datetime.now(timezone.utc)
            actions: List[CorporateAction] = []

            # 1. Dividends
            try:
                divs = getattr(ticker, "dividends", None)
                if divs is not None and not divs.empty:
                    for dt, amt in divs.tail(20).items():
                        if pd.notna(amt) and float(amt) > 0:
                            if isinstance(dt, pd.Timestamp):
                                ex_dt = dt.to_pydatetime()
                            else:
                                ex_dt = datetime.fromisoformat(str(dt).replace("Z", "+00:00"))
                            if ex_dt.tzinfo is None:
                                ex_dt = ex_dt.replace(tzinfo=timezone.utc)

                            pub_dt = ex_dt - timedelta(days=15)
                            actions.append(
                                CorporateAction(
                                    symbol=symbol,
                                    event_type=CorporateActionType.DIVIDEND,
                                    announcement_date=pub_dt,
                                    ex_date=ex_dt,
                                    record_date=ex_dt + timedelta(days=1),
                                    ratio_or_amount=float(amt),
                                    description=f"Cash Dividend INR {amt:.2f}",
                                    source=self.name,
                                    source_tier=SourceTier.TIER_4_SECONDARY,
                                    publication_time=pub_dt,
                                    retrieved_at=now,
                                    quality=DataQuality.HIGH,
                                )
                            )
            except Exception:
                pass

            # 2. Stock Splits / Bonuses
            try:
                splits = getattr(ticker, "splits", None)
                if splits is not None and not splits.empty:
                    for dt, ratio in splits.tail(10).items():
                        if pd.notna(ratio) and float(ratio) > 0:
                            if isinstance(dt, pd.Timestamp):
                                ex_dt = dt.to_pydatetime()
                            else:
                                ex_dt = datetime.fromisoformat(str(dt).replace("Z", "+00:00"))
                            if ex_dt.tzinfo is None:
                                ex_dt = ex_dt.replace(tzinfo=timezone.utc)

                            pub_dt = ex_dt - timedelta(days=21)
                            r_val = float(ratio)
                            event_t = CorporateActionType.SPLIT if r_val > 1.0 else CorporateActionType.BONUS
                            actions.append(
                                CorporateAction(
                                    symbol=symbol,
                                    event_type=event_t,
                                    announcement_date=pub_dt,
                                    ex_date=ex_dt,
                                    ratio_or_amount=r_val,
                                    ratio_text=f"{r_val:.1f}:1",
                                    description=f"Stock {event_t.value} ratio {r_val:.1f}:1",
                                    source=self.name,
                                    source_tier=SourceTier.TIER_4_SECONDARY,
                                    publication_time=pub_dt,
                                    retrieved_at=now,
                                    quality=DataQuality.HIGH,
                                )
                            )
            except Exception:
                pass

            # Sort chronological descending (most recent first)
            actions.sort(key=lambda a: a.ex_date or a.retrieved_at, reverse=True)

            return ProviderResult(
                status="SUCCESS",
                data={"corporate_actions": [a.model_dump() for a in actions]},
                provenance=[],
            )
        except Exception as e:
            return ProviderResult(status="ERROR", error=str(e))

    async def get_corporate_actions(self, symbol: str) -> ProviderResult:
        return await asyncio.to_thread(self._get_corporate_actions_sync, symbol)

    def _get_ownership_sync(self, symbol: str) -> ProviderResult:
        """
        Extract shareholding pattern (promoter, institutional, FII/DII, public) from major/institutional holders.
        """
        try:
            import yfinance as yf

            normalized = self._normalize_ticker(symbol)
            ticker = yf.Ticker(normalized)
            now = datetime.now(timezone.utc)
            info = getattr(ticker, "info", {}) or {}

            observations: List[OwnershipObservation] = []
            ctx_id = str(uuid.uuid4())

            # 1. Promoter / Insider Holding
            promoter_pct = None
            if "heldPercentInsiders" in info and info["heldPercentInsiders"] is not None:
                try:
                    val = float(info["heldPercentInsiders"]) * 100.0
                    if 0.0 <= val <= 100.0:
                        promoter_pct = round(val, 2)
                        observations.append(
                            OwnershipObservation(
                                symbol=symbol,
                                holder_type=HolderType.PROMOTER,
                                ownership_percentage=promoter_pct,
                                period="Latest Filing",
                                report_date=now - timedelta(days=60),
                                publication_time=now - timedelta(days=45),
                                observed_at=now,
                                source=self.name,
                                source_tier=SourceTier.TIER_4_SECONDARY,
                                context_id=ctx_id,
                                quality=DataQuality.MEDIUM,
                            )
                        )
                except Exception:
                    pass

            # 2. Institutional Holding
            inst_pct = None
            if "heldPercentInstitutions" in info and info["heldPercentInstitutions"] is not None:
                try:
                    val = float(info["heldPercentInstitutions"]) * 100.0
                    if 0.0 <= val <= 100.0:
                        inst_pct = round(val, 2)
                        observations.append(
                            OwnershipObservation(
                                symbol=symbol,
                                holder_type=HolderType.OTHER_INSTITUTION,
                                ownership_percentage=inst_pct,
                                period="Latest Filing",
                                report_date=now - timedelta(days=60),
                                publication_time=now - timedelta(days=45),
                                observed_at=now,
                                source=self.name,
                                source_tier=SourceTier.TIER_4_SECONDARY,
                                context_id=ctx_id,
                                quality=DataQuality.MEDIUM,
                            )
                        )
                except Exception:
                    pass

            # 3. Public Holding (Derived if promoter and institutional are present)
            if promoter_pct is not None and inst_pct is not None:
                pub_pct = max(0.0, round(100.0 - (promoter_pct + inst_pct), 2))
                observations.append(
                    OwnershipObservation(
                        symbol=symbol,
                        holder_type=HolderType.PUBLIC,
                        ownership_percentage=pub_pct,
                        period="Latest Filing",
                        report_date=now - timedelta(days=60),
                        publication_time=now - timedelta(days=45),
                        observed_at=now,
                        source=self.name,
                        source_tier=SourceTier.TIER_4_SECONDARY,
                        context_id=ctx_id,
                        quality=DataQuality.MEDIUM,
                    )
                )

            # 4. Institutional breakdown from institutional_holders if available
            try:
                ih = getattr(ticker, "institutional_holders", None)
                if ih is not None and not ih.empty:
                    for _, row in ih.head(10).iterrows():
                        pct_out = row.get("% Out") or row.get("pctHeld")
                        holder_name = str(row.get("Holder", "Institutional Investor"))
                        shares = row.get("Shares")
                        if pd.notna(pct_out):
                            try:
                                p_val = float(pct_out) * 100.0 if float(pct_out) <= 1.0 else float(pct_out)
                                s_val = float(shares) if pd.notna(shares) else None
                                h_type = HolderType.MUTUAL_FUND if "fund" in holder_name.lower() or "mf" in holder_name.lower() else HolderType.FII
                                observations.append(
                                    OwnershipObservation(
                                        symbol=symbol,
                                        holder_type=h_type,
                                        ownership_percentage=round(p_val, 2),
                                        shares_held=s_val,
                                        period="Institutional Disclosure",
                                        report_date=now - timedelta(days=60),
                                        publication_time=now - timedelta(days=45),
                                        observed_at=now,
                                        source=self.name,
                                        source_tier=SourceTier.TIER_4_SECONDARY,
                                        context_id=ctx_id,
                                        document_reference=holder_name,
                                        quality=DataQuality.MEDIUM,
                                    )
                                )
                            except Exception:
                                pass
            except Exception:
                pass

            return ProviderResult(
                status="SUCCESS" if observations else "ERROR",
                data={"ownership": [o.model_dump() for o in observations]},
                provenance=[],
            )
        except Exception as e:
            return ProviderResult(status="ERROR", error=str(e))

    async def get_ownership(self, symbol: str) -> ProviderResult:
        return await asyncio.to_thread(self._get_ownership_sync, symbol)

    def _get_earnings_calendar_sync(self, symbol: str) -> ProviderResult:
        try:
            import yfinance as yf
            import pandas as pd
            normalized = self._normalize_ticker(symbol)
            ticker = yf.Ticker(normalized)
            calendar_df = getattr(ticker, "earnings_dates", None)
            
            if calendar_df is None or calendar_df.empty:
                return ProviderResult(status="SUCCESS_EMPTY", data=[])
                
            now = datetime.now(timezone.utc)
            events = []
            
            for dt, row in calendar_df.iterrows():
                # yfinance earnings_dates index is the Earnings Date
                # Columns: 'EPS Estimate', 'Reported EPS', 'Surprise(%)'
                eps_est = row.get("EPS Estimate")
                eps_act = row.get("Reported EPS")
                surprise = row.get("Surprise(%)")
                
                # Convert date to ISO format
                if pd.isna(dt):
                    continue
                    
                # Clean NaNs
                eps_est = float(eps_est) if pd.notna(eps_est) else None
                eps_act = float(eps_act) if pd.notna(eps_act) else None
                surprise = float(surprise) if pd.notna(surprise) else None
                
                event_dict = {
                    "symbol": symbol,
                    "earnings_date": dt.isoformat() if hasattr(dt, 'isoformat') else str(dt),
                    "eps_estimate": eps_est,
                    "reported_eps": eps_act,
                    "surprise_pct": surprise
                }
                events.append(event_dict)
                
            return ProviderResult(status="SUCCESS", data={"events": events}, provenance=[])
        except Exception as e:
            return ProviderResult(status="ERROR", error=str(e))

    async def get_earnings_calendar(self, symbol: str) -> ProviderResult:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._get_earnings_calendar_sync, symbol)

    def _get_news_sync(self, symbol: str) -> ProviderResult:
        try:
            import yfinance as yf

            normalized = self._normalize_ticker(symbol)
            ticker = yf.Ticker(normalized)
            raw_news = getattr(ticker, "news", []) or []

            articles: List[Dict[str, Any]] = []
            now = datetime.now(timezone.utc)

            for item in raw_news:
                if not isinstance(item, dict):
                    continue

                content = item.get("content") if isinstance(item.get("content"), dict) else item
                title = content.get("title") or item.get("title") or ""
                if not title:
                    continue

                summary = content.get("summary") or content.get("description") or item.get("summary") or title

                provider_info = content.get("provider")
                if isinstance(provider_info, dict):
                    publisher = provider_info.get("displayName") or "Yahoo Finance"
                else:
                    publisher = item.get("publisher") or "Yahoo Finance"

                canonical_url = content.get("canonicalUrl")
                if isinstance(canonical_url, dict):
                    link = canonical_url.get("url") or ""
                else:
                    link = content.get("previewUrl") or item.get("link") or ""

                pub_date_str = content.get("pubDate") or content.get("displayTime")
                if pub_date_str:
                    try:
                        pub_dt = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
                    except Exception:
                        pub_dt = now
                else:
                    pub_time_int = item.get("providerPublishTime")
                    if pub_time_int:
                        try:
                            pub_dt = datetime.fromtimestamp(pub_time_int, tz=timezone.utc)
                        except Exception:
                            pub_dt = now
                    else:
                        pub_dt = now

                articles.append(
                    {
                        "headline": title,
                        "title": title,
                        "publisher": publisher,
                        "source": publisher,
                        "link": link,
                        "url": link,
                        "published_at": pub_dt.isoformat(),
                        "publication_time": pub_dt.isoformat(),
                        "summary": summary,
                        "source_tier": "TIER_4_SECONDARY",
                    }
                )

            return ProviderResult(
                status="SUCCESS",
                data={"articles": articles},
                provenance=[],
            )
        except Exception as e:
            return ProviderResult(status="ERROR", error=str(e))

    async def get_news(self, symbol: str) -> ProviderResult:
        return await asyncio.to_thread(self._get_news_sync, symbol)
