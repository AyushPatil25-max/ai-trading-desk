# Data Provider Matrix

| Provider | Data Type | Authority | API Available? | Authentication | Historical Data | Point-in-Time | Rate Limits | License/Access Notes | Implementation Status | Fallback |
|---|---|---|---|---|---|---|---|---|---|---|
| **NSE (Official)** | Market Data, Filings | National Stock Exchange | No public open API | Required (Corporate) | Yes (via auth feeds) | Yes | Unknown | Proprietary | Stubbed | YFinance |
| **BSE (Official)** | Market Data, Filings | BSE Limited | No public open API | Required (Corporate) | Yes (via auth feeds) | Yes | Unknown | Proprietary | Stubbed | YFinance |
| **SEBI (Official)** | Regulatory, Filings | Securities and Exchange Board of India | No formal API | Yes/No (Scraping disallowed) | Varies | Varies | Unknown | Proprietary | Stubbed | None |
| **RBI (Official)** | Macro, Rates | Reserve Bank of India | Partial (DBIE) | Varies | Yes | Yes | Unknown | Open Data / DBIE | Stubbed | None |
| **Company Filings (Direct)** | Fundamentals, Filings | Corporate IR | No | No | Yes (PDF/XBRL) | Yes | N/A | Open | Stubbed | YFinance |
| **YFinance** | Market Data, Fundamentals, News | Secondary Aggregator | Yes (Unofficial) | No | Yes | No (Overwrites) | Dynamic/Blocked on abuse | OSS/Scraped | Implemented | None |
