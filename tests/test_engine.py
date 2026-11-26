import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import (Rules, buildup, choose_picks, conviction, efficiency, order_blocks,  # noqa: E402
                    strength, trade_setup, volume_profile, vwap_series)
from kite_feed import nearest_futures, resolve_equities, rows_to_candles  # noqa: E402
from market_time import IST, bucket_start, epoch, session_open  # noqa: E402
from sectors import NIFTY50, SECTOR_OF  # noqa: E402
from store import Store  # noqa: E402

R = Rules()
DAY = date(2026, 11, 20)
T0 = epoch(session_open(DAY))


def bars(ohlc):
    return [{"t": T0 + i * 300, "o": o, "h": h, "l": l, "c": c, "v": 1000} for i, (o, h, l, c) in enumerate(ohlc)]


# a rally: opening range, pullback with a red candle, then a forceful break above the range
RALLY = bars([
    (100, 101, 99.5, 100.8), (100.8, 101.2, 100.2, 100.5), (100.5, 100.9, 100.0, 100.3),  # OR high 101.2
    (100.3, 100.6, 99.8, 100.0),   # last red candle before the move = order block
    (100.0, 101.0, 99.9, 100.9),
    (100.9, 102.5, 100.9, 102.3),  # closes above 101.2 with a gap over bar 3's high -> break
    (102.3, 102.8, 101.9, 102.6),
])


def test_efficiency_straight_vs_chop():
    assert efficiency([1, 2, 3, 4]) == pytest.approx(1.0)
    assert efficiency([1, 2, 1, 2, 1]) == 0.0


def test_strength_is_volatility_normalised_and_damps_chop():
    # same 2% move: low-ADR stock scores higher than high-ADR stock
    assert strength(100, 102, 1.0, 1.0, 0.2) > strength(100, 102, 4.0, 1.0, 0.2)
    assert strength(100, 102, 2.0, 0.1, 0.2) < strength(100, 102, 2.0, 0.2, 0.2) / 2
    assert strength(100, 98, 2.0, 1.0, 0.2) < 0


def test_buildup_classification():
    assert buildup(1, 5) == "LONG BUILD-UP"
    assert buildup(-1, 5) == "SHORT BUILD-UP"
    assert buildup(1, -5) == "SHORT COVERING"
    assert buildup(-1, -5) == "LONG UNWINDING"
    assert buildup(1, None) is None


def test_bullish_order_block_is_last_red_candle_before_break():
    obs = order_blocks(RALLY, R)
    bull = [o for o in obs if o["dir"] == "bull"]
    assert bull, obs
    ob = bull[-1]
    assert (ob["lo"], ob["hi"]) == (99.8, 100.6)
    assert ob["valid"]


def test_block_invalidated_by_close_through_far_side():
    broken = RALLY + [{"t": T0 + 7 * 300, "o": 102, "h": 102, "l": 99.0, "c": 99.5, "v": 1}]
    ob = [o for o in order_blocks(broken, R) if o["dir"] == "bull"][-1]
    assert not ob["valid"] and ob["end"] == T0 + 7 * 300


def test_no_block_without_displacement():
    weak = bars([
        (100, 101, 99.5, 100.8), (100.8, 101.2, 100.2, 100.5), (100.5, 100.9, 100.0, 100.3),
        (100.3, 100.6, 99.8, 100.0),
        (100.0, 101.25, 100.5, 101.25),  # barely closes above 101.2: no gap, < 1 average candle
    ])
    assert not [o for o in order_blocks(weak, R) if o["dir"] == "bull"]


def test_trade_setup_levels_and_rr():
    obs = order_blocks(RALLY, R)
    ctx = {"adr_pct": 2.0, "prev_close": 99.0, "prev_high": 104.0, "prev_low": 98.0}
    s = trade_setup(RALLY, obs, "bull", 102.6, ctx, 100.0, R)
    assert s["zone"][0] == 100.6                       # zone starts at the block top
    assert s["z"] == pytest.approx(sum(s["zone"]) / 2)  # Z = middle of the zone
    assert s["stop"] == pytest.approx(99.8 * (1 - R.stop_buffer))
    assert s["t1"] > 102.6 and s["t2"] >= s["t1"]
    assert s["rr"] == pytest.approx((s["t2"] - s["z"]) / (s["z"] - s["stop"]))
    assert s["labels"]["stop"] == "S1"


def test_picks_respect_sector_cap_event_risk_and_setup():
    setup = {"x": 1}
    board = [
        {"s": "A", "sec": "BANK", "side": "bull", "ev": False, "setup": setup},
        {"s": "B", "sec": "BANK", "side": "bull", "ev": False, "setup": setup},
        {"s": "C", "sec": "BANK", "side": "bull", "ev": False, "setup": setup},  # 3rd bank -> cap
        {"s": "D", "sec": "IT", "side": "bull", "ev": True, "setup": setup},     # event risk
        {"s": "E", "sec": "IT", "side": "bull", "ev": False, "setup": None},     # no setup
        {"s": "F", "sec": "AUTO", "side": "bull", "ev": False, "setup": setup},
        {"s": "G", "sec": "AUTO", "side": "bull", "ev": False, "setup": setup},
    ]
    rules = choose_picks(board, R)
    assert [s for s, r in rules.items() if r.startswith("PICK")] == ["A", "B", "F"]
    assert rules["C"].endswith("sector cap")
    assert rules["D"].endswith("event risk")
    assert rules["E"].endswith("no setup")
    assert rules["G"].endswith("outside top 3")


def test_conviction_bounds():
    assert 1 <= conviction(0, 0, None, None, "bull") <= 99
    assert conviction(1, 1, True, "LONG BUILD-UP", "bull") > conviction(1, 1, False, "SHORT BUILD-UP", "bull")


def test_vwap_and_profile():
    vw = vwap_series(RALLY)
    assert vw[0] == pytest.approx((101 + 99.5 + 100.8) / 3)
    vp = volume_profile(RALLY)
    assert vp["lo"] == 99.5 and vp["hi"] == 102.8 and max(b[0] for b in vp["b"]) == 1.0


def test_sectors_index_basket_is_not_a_sector():
    assert SECTOR_OF["AXISBANK"] == "BANK"
    assert SECTOR_OF["BHARTIARTL"] == "OTHERS"  # only in NIFTY_50
    assert "AXISBANK" in NIFTY50


def test_store_builds_5m_candles_from_ticks():
    st = Store()
    st.seed_candles("TCS", [])
    t = session_open(DAY)
    for i, (sec, px, vol) in enumerate([(0, 100, 10), (60, 101, 25), (240, 99, 40), (300, 102, 60)]):
        st.on_quote("TCS", t + timedelta(seconds=sec), px, cum_vol=vol)
    c = st.syms["TCS"].candles
    assert len(c) == 2
    assert (c[0]["o"], c[0]["h"], c[0]["l"], c[0]["c"]) == (100, 101, 99, 99)
    assert c[0]["v"] == 30 and c[1]["v"] == 20  # first tick only sets the volume baseline
    # pre-open tick of a new day must not wipe the current session
    st.on_quote("TCS", datetime(2026, 11, 21, 9, 5, tzinfo=IST), 105)
    assert len(st.syms["TCS"].candles) == 2


def test_bucket_start():
    assert bucket_start(datetime(2026, 11, 20, 9, 14, tzinfo=IST)) is None
    assert bucket_start(datetime(2026, 11, 20, 9, 19, 59, tzinfo=IST)) == session_open(DAY)
    assert bucket_start(datetime(2026, 11, 20, 15, 30, tzinfo=IST)) is None


def test_kite_helpers():
    ins = [
        {"tradingsymbol": "TCS", "segment": "NSE", "instrument_type": "EQ", "instrument_token": 1},
        {"tradingsymbol": "TCS-BE", "segment": "NSE", "instrument_type": "EQ", "instrument_token": 2},
        {"name": "TCS", "segment": "NFO-FUT", "instrument_type": "FUT", "instrument_token": 10, "expiry": date(2026, 11, 20)},
        {"name": "TCS", "segment": "NFO-FUT", "instrument_type": "FUT", "instrument_token": 11, "expiry": date(2026, 12, 29)},
        {"name": "TCS", "segment": "NFO-FUT", "instrument_type": "FUT", "instrument_token": 12, "expiry": date(2027, 1, 27)},
    ]
    eq, missing = resolve_equities(ins, ["TCS", "INFY"])
    assert eq == {"TCS": 1} and missing == ["INFY"]
    assert nearest_futures(ins, ["TCS"], date(2026, 11, 20)) == {"TCS": 11}  # skips expiry day
    c = rows_to_candles([{"date": datetime(2026, 11, 20, 9, 15), "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 9}])
    assert c[0]["t"] == T0 and c[0]["v"] == 9
