# terminal-v2 source verification — 2026-10-01T04:55:41+00:00 (GitHub Actions)

| Category | Source | Status | Detail |
|---|---|---|---|
| map | OpenSky /states/all (Hormuz bbox) | **OK** | HTTP 200 |
| map | IMF PortWatch: chokepoints_database | **OK** | HTTP 200 |
| map | IMF PortWatch: Daily_Chokepoints_Data | **OK** | HTTP 200 |
| map | IMF PortWatch: portwatch_disruptions_database | **OK** | HTTP 200 |
| map | IMF PortWatch: PortWatch_ports_database (India) | **OK** | HTTP 200 |
| map | IMF PortWatch: Daily_Ports_Data | **OK** | HTTP 200 |
| map | Shipping lanes (newzealandpaul/Shipping-Lanes, CC BY 4.0) | **OK** | HTTP 200 |
| map | TeleGeography submarine cables | **OK** | HTTP 200 |
| map | TeleGeography landing points | **OK** | HTTP 200 |
| map | WRI Global Power Plant Database (CSV) | **OK** | HTTP 200 |
| map | USGS earthquakes M4.5+ (7 days) | **OK** | HTTP 200 |
| map | NASA EONET v3 (open events) | **OK** | HTTP 200 |
| map | GDACS event list | **OK** | HTTP 200 |
| map | Wikidata SPARQL (company facilities, Reliance test query) | **OK** | HTTP 200 |
| map | GDELT DOC 2.0 (claimed failing from Actions - testing live) | **FAIL** | HTTP 429 |
| map | Google News RSS (GDELT fallback) | **OK** | HTTP 200 |
| map | aisstream.io (ship AIS) | **NEEDS_KEY** | AISSTREAM_KEY not set - user must register a free account and provide it as a GitHub secret. |
| map | ACLED API (conflict events) | **NEEDS_KEY** | ACLED_KEY/ACLED_EMAIL not set - user must register a free account and provide both as GitHub secrets. |
| macro | Yahoo Finance (yfinance) FX & commodities | **OK** | fetched |
| macro | RBI reference rate page | **OK** | HTTP 200 |
| macro | RBI current rates page | **OK** | HTTP 200 |
| macro | MOSPI release calendar | **OK** | HTTP 200 |
| macro | World Bank API (India GDP) | **OK** | HTTP 200 |
| macro | IMF DataMapper API (India real GDP growth) | **OK** | HTTP 200 |
| macro | FRED API | **NEEDS_KEY** | FRED_KEY not set (optional) - free to register at fred.stlouisfed.org. |
| macro | NSE corporate announcements | **FAIL** | ReadTimeout: HTTPSConnectionPool(host='www.nseindia.com', port=443): Read timed out. (read timeout=20) |