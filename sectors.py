"""Sector map for the X-Ray universe.

NIFTY_50 is an index basket, not a sector: it is shown as its own row in the sector
panel but never used as a stock's sector (so it does not count toward the pick cap).
A stock's sector is the first non-index group it appears in; stocks that only appear
in NIFTY_50 fall into OTHERS.
"""
from __future__ import annotations

SECTOR_DEFINITIONS: dict[str, list[str]] = {
    "METAL": [
        "ADANIENT", "APLAPOLLO", "BHARATFORG", "COALINDIA",
        "HINDALCO", "HINDZINC", "JSWSTEEL", "JINDALSTEL", "NMDC",
        "NATIONALUM", "SAIL", "TATASTEEL", "VEDL",
    ],
    "REALTY": [
        "PHOENIXLTD", "GODREJPROP", "LODHA", "OBEROIRLTY", "DLF",
        "PRESTIGE", "NBCC", "RVNL",
    ],
    "ENERGY": [
        "RELIANCE", "ONGC", "IOC", "BPCL", "OIL", "NTPC", "POWERGRID",
        "POWERINDIA", "TATAPOWER", "JSWENERGY", "ADANIGREEN", "ADANIENSOL", "ADANIPOWER",
        "NHPC", "IREDA", "SUZLON", "INOXWIND", "WAAREEENER", "PREMIERENE",
        "PETRONET", "GAIL", "HINDPETRO", "ENRIN", "GVT&D",
    ],
    "AUTO": [
        "BOSCHLTD", "TIINDIA", "HEROMOTOCO", "M&M", "EICHERMOT",
        "BAJAJ-AUTO", "ASHOKLEY", "MARUTI", "TVSMOTOR", "MOTHERSON",
        "SONACOMS", "UNOMINDA", "TMPV", "HYUNDAI", "AMBER", "ATHERENERG", "FORCEMOT",
    ],
    "IT": [
        "INFY", "TCS", "HCLTECH", "WIPRO", "TECHM", "LTM", "MPHASIS",
        "KPITTECH", "COFORGE", "PERSISTENT", "TATAELXSI", "OFSS", "CAMS",
        "NAUKRI", "KAYNES", "SAGILITY", "SYRMA",
    ],
    "PHARMA": [
        "CIPLA", "ALKEM", "BIOCON", "DRREDDY", "MANKIND", "TORNTPHARM",
        "ZYDUSLIFE", "DIVISLAB", "LUPIN", "LAURUSLABS", "FORTIS", "AUROPHARMA",
        "GLENMARK", "SUNPHARMA", "MAXHEALTH", "APOLLOHOSP",
    ],
    "FMCG": [
        "HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "DABUR", "MARICO",
        "COLPAL", "GODREJCP", "TATACONSUM", "PATANJALI", "UNITDSPR", "RADICO",
        "VBL", "DMART", "NYKAA", "ETERNAL", "SWIGGY", "TITAN", "TRENT",
        "VMM", "KALYANKJIL", "JUBLFOOD", "ASIANPAINT", "GODFRYPHLP",
    ],
    "CEMENT": [
        "ULTRACEMCO", "SHREECEM", "AMBUJACEM", "GRASIM", "ASTRAL",
        "PIDILITIND", "SUPREMEIND",
    ],
    "FINSERVICE": [
        "BAJFINANCE", "BAJAJFINSV", "ICICILIFE", "ICICIGI", "SBILIFE",
        "HDFCLIFE", "LICI", "LICHSGFIN", "PNBHOUSING", "MUTHOOTFIN", "MANAPPURAM",
        "CHOLAFIN", "PFC", "RECLTD", "MOTILALOFS", "HDFCAMC", "360ONE", "KFINTECH",
        "PAYTM", "POLICYBZR", "SBICARD", "JIOFIN", "SHRIRAMFIN", "ANGELONE",
        "BSE", "CDSL", "MCX", "IRFC", "ABCAPITAL", "LTF", "MFSL", "ANANDRATHI",
        "NAM-INDIA", "IEX",
    ],
    "BANK": [
        "HDFCBANK", "ICICIBANK", "AXISBANK", "KOTAKBANK", "IDFCFIRSTB", "FEDERALBNK",
        "INDUSINDBK", "AUBANK", "BANDHANBNK", "RBLBANK", "YESBANK", "CUB",
        "KARURVYSYA", "UJJIVANSFB",
    ],
    "PSUBANK": [
        "SBIN", "PNB", "BANKBARODA", "CANBK", "UNIONBANK", "BANKINDIA", "INDIANB",
        "MAHABANK",
    ],
    "DURABLES": [
        "INDUSTOWER", "HAVELLS", "KEI", "POLYCAB", "CROMPTON", "VOLTAS", "PGEL",
        "DIXON", "SRF", "NAVINFLUOR", "IDEA",
    ],
    "LOGISTICS": [
        "CONCOR", "DELHIVERY", "INDIGO", "INDHOTEL", "BLUESTARCO",
        "GMRAIRPORT", "PAGEIND", "UPL", "ADANIPORTS", "PIIND", "COROMANDEL",
    ],
    "DEFENCE": [
        "ABB", "BEL", "BDL", "BHEL", "CGPOWER", "CUMMINSIND", "HAL", "LT",
        "MAZDOCK", "COCHINSHIP", "SIEMENS", "SOLARINDS", "DATAPATTNS",
    ],
    "NIFTY_50": [
        "ADANIENT", "APOLLOHOSP", "ASIANPAINT", "AXISBANK", "BAJAJ-AUTO", "BAJFINANCE",
        "BAJAJFINSV", "BEL", "BHARTIARTL", "BPCL", "CIPLA", "COALINDIA", "DRREDDY",
        "EICHERMOT", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HINDALCO",
        "HINDUNILVR", "ICICIBANK", "INFY", "INDIGO", "ITC", "JIOFIN", "JSWSTEEL",
        "KOTAKBANK", "LT", "M&M", "MARUTI", "MAXHEALTH", "NESTLEIND", "NTPC", "ONGC",
        "POWERGRID", "RELIANCE", "SBILIFE", "SHRIRAMFIN", "SBIN", "SUNPHARMA", "TCS",
        "TATACONSUM", "TATASTEEL", "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO",
        "TMPV", "ETERNAL",
    ],
}

INDEX_GROUPS = {"NIFTY_50"}
OTHERS = "OTHERS"


def _build() -> tuple[dict[str, str], list[str], set[str]]:
    sector_of: dict[str, str] = {}
    for name, members in SECTOR_DEFINITIONS.items():
        if name in INDEX_GROUPS:
            continue
        for sym in members:
            sector_of.setdefault(sym, name)
    nifty = set(SECTOR_DEFINITIONS.get("NIFTY_50", []))
    for sym in nifty:
        sector_of.setdefault(sym, OTHERS)
    return sector_of, sorted(sector_of), nifty


SECTOR_OF, ALL_SYMBOLS, NIFTY50 = _build()
SECTORS = [n for n in SECTOR_DEFINITIONS if n not in INDEX_GROUPS] + (
    [OTHERS] if OTHERS in SECTOR_OF.values() else [])


def display_name(sector: str) -> str:
    return {"PSUBANK": "PSU BANK", "FINSERVICE": "FIN SERVICE", "NIFTY_50": "NIFTY 50"}.get(sector, sector)
