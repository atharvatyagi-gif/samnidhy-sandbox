"""Strategies found in the terminal (discovery: blackbox/INVENTORY.md), re-implemented in Python, one file each, each citing its source."""
from . import aladin_weekly, crypto_ha_trend, crypto_trend, movers_top_tenth, paper_trader_v1, swing_r1

# name -> (run function, market it trades, source it mirrors)
REGISTRY = {
    "aladin_v3": (aladin_weekly.v3, "stocks", aladin_weekly.SOURCE),
    "aladin_v4_shadow": (aladin_weekly.v4_shadow, "stocks", aladin_weekly.SOURCE),
    "aladin_small_10k": (aladin_weekly.small_10k, "stocks", aladin_weekly.SOURCE),
    "swing_r1": (swing_r1.run, "stocks", swing_r1.SOURCE),
    "movers_top_tenth": (movers_top_tenth.run, "stocks", movers_top_tenth.SOURCE),
    "paper_trader_v1": (paper_trader_v1.run, "stocks", paper_trader_v1.SOURCE),
    "crypto_trend": (crypto_trend.run, "crypto", crypto_trend.SOURCE),
    "crypto_ha_trend": (crypto_ha_trend.run, "crypto", crypto_ha_trend.SOURCE),
}
