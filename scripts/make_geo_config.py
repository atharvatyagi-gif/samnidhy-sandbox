"""One-off generator for data/config/geo_exposure.json (kept so the file's reasoning is reviewable and editable).
Exposure notes are broad, widely stated rules of thumb about how a region's news tends to relate to Indian listed
companies and sectors. They are NOT forecasts and are not measured from data here. `ind` values are exact
universe.json industry names; `sym` values are NSE symbols (scripts/check_geo.py verifies both)."""
import json
from pathlib import Path

OIL_UP = [{"sym": s, "dir": "+", "why": "Earns more when crude prices rise"} for s in ("ONGC", "OIL")]
OIL_DN = [{"sym": s, "dir": "-", "why": "Buys crude: dearer oil squeezes margins"} for s in ("IOC", "BPCL", "HINDPETRO")]
DEFENCE = [{"sym": s, "dir": "+", "why": "Defence order flow tends to draw attention in tense periods"} for s in ("HAL", "BEL", "BDL")]

R = [
    ("hormuz", "Iran / Strait of Hormuz", "chokepoint", 26.6, 56.3,
     '(intitle:Hormuz OR intitle:Iran OR intitle:"Persian Gulf")', ["hormuz", "iran", "persian gulf", "tehran"],
     OIL_UP + OIL_DN + [{"sym": "INDIGO", "dir": "-", "why": "Jet fuel is a large cost"}, {"sym": "ASIANPAINT", "dir": "-", "why": "Crude-linked raw materials"},
                        {"ind": "Chemicals", "dir": "-", "why": "Crude-linked input costs"}]),
    ("redsea", "Red Sea / Bab el-Mandeb", "chokepoint", 13.5, 43.3,
     '(intitle:"Red Sea" OR intitle:Houthi OR intitle:Houthis OR intitle:"Bab el-Mandeb")', ["red sea", "houthi", "bab el-mandeb", "suez"],
     [{"sym": "SCI", "dir": "+", "why": "Longer routes and higher freight rates help shipping lines"}, {"ind": "Textiles", "dir": "-", "why": "Exports to Europe face delays and costlier freight"},
      {"ind": "Chemicals", "dir": "-", "why": "Freight and delivery delays on exports"}]),
    ("israel", "Israel / Gaza / Lebanon", "conflict", 31.5, 34.8,
     '(intitle:Israel OR intitle:Gaza OR intitle:Lebanon OR intitle:Hezbollah)', ["israel", "gaza", "lebanon", "hezbollah"],
     DEFENCE + OIL_UP[:1]),
    ("ukraine", "Russia / Ukraine", "conflict", 49.0, 32.0,
     '(intitle:Ukraine OR intitle:Kyiv OR intitle:Russia)', ["ukraine", "kyiv", "russia", "moscow"],
     OIL_UP + [{"sym": "CHAMBLFERT", "dir": "-", "why": "Fertiliser makers depend on imported gas and inputs"}]),
    ("indpak", "India / Pakistan", "conflict", 32.0, 74.8,
     '(intitle:Pakistan AND india) -cricket -hockey -football -"asia cup" -"live streaming" -kabaddi -T20 -ODI', ["pakistan", "kashmir", "line of control"],
     DEFENCE + [{"ind": "Financial Services", "dir": "-", "why": "Domestic risk-off weighs on banks, the heaviest index group"}]),
    ("indchina", "India / China border (LAC)", "conflict", 34.0, 78.5,
     '(intitle:LAC OR (intitle:China AND intitle:India AND border))', ["lac", "ladakh", "galwan", "arunachal"],
     [{"sym": "DIXON", "dir": "-", "why": "Electronics assembly depends on Chinese components"}, {"ind": "Healthcare", "dir": "-", "why": "Drug makers import many active ingredients from China"}]),
    ("taiwan", "Taiwan Strait / South China Sea", "chokepoint", 23.7, 121.0,
     '(intitle:Taiwan OR intitle:"South China Sea")', ["taiwan", "south china sea", "taipei"],
     [{"ind": "Information Technology", "dir": "-", "why": "Global tech demand and hardware supply chains"}, {"sym": "DIXON", "dir": "-", "why": "Chip and component supply"}]),
    ("ustariff", "US tariffs on India", "policy", 38.9, -77.0,
     '(intitle:tariff AND (india OR indian))', ["tariff", "trade deal", "duties"],
     [{"ind": "Textiles", "dir": "-", "why": "Large US export share"}, {"ind": "Healthcare", "dir": "-", "why": "US is the biggest generics market"},
      {"ind": "Automobile and Auto Components", "dir": "-", "why": "Auto parts exports"}, {"ind": "Information Technology", "dir": "-", "why": "US clients are the main revenue source"}]),
    ("malacca", "Strait of Malacca", "chokepoint", 2.5, 101.5,
     '(intitle:"Strait of Malacca" OR (intitle:Malacca -polls -election -Melaka -state -Umno -BN -PAS))', ["malacca", "singapore strait"],
     [{"ind": "Metals & Mining", "dir": "-", "why": "East Asia trade routes"}, {"ind": "Chemicals", "dir": "-", "why": "East Asia trade routes"}]),
    ("opec", "OPEC+ policy", "policy", 48.2, 16.4,
     '(intitle:OPEC)', ["opec", "output cut", "oil output"],
     OIL_UP + OIL_DN + [{"sym": "INDIGO", "dir": "-", "why": "Jet fuel is a large cost"}]),
]
out = {"version": 1,
       "note": "Exposure lines are widely stated rules of thumb about how a region's news tends to relate to Indian companies, not measured relationships and not forecasts. dir '+' = tends to gain when attention on the region rises, '-' = tends to lose.",
       "regions": [{"id": i, "name": n, "kind": k, "lat": la, "lon": lo, "news_query": q, "keywords": kw, "exposure": ex} for i, n, k, la, lo, q, kw, ex in R]}
p = Path(__file__).resolve().parent.parent / "data" / "config" / "geo_exposure.json"
p.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
print("wrote", p, len(R), "regions")
