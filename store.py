"""Thread-safe market state. Feeds write ticks; the engine reads consistent copies.

Candles are 5-minute bars keyed by bar start (epoch seconds, IST session grid).
A symbol only builds candles from ticks once it is "seeded" (history loaded or demo),
so a partially loaded symbol never shows a half-built day.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable, Optional

from market_time import IST, bucket_start, epoch, now_ist, to_ist
from sectors import ALL_SYMBOLS, NIFTY50, SECTOR_OF


@dataclass
class SymState:
    symbol: str
    sector: str
    n50: bool
    session_date: Optional[date] = None
    candles: list[dict] = field(default_factory=list)
    seeded: bool = False
    # live quote (valid only when tick_date == session_date)
    tick_date: Optional[date] = None
    ltp: Optional[float] = None
    day_open: Optional[float] = None
    prev_close: Optional[float] = None
    vwap: Optional[float] = None
    cum_vol: Optional[int] = None
    oi: Optional[float] = None
    oi_date: Optional[date] = None
    # history
    daily: list[tuple] = field(default_factory=list)        # (date, o, h, l, c), oldest first
    fut_oi_daily: list[tuple] = field(default_factory=list)  # (date, oi), oldest first


class Store:
    def __init__(self, clock: Callable[[], datetime] = now_ist):
        self._lock = threading.RLock()
        self.clock = clock
        self.syms: dict[str, SymState] = {
            s: SymState(s, SECTOR_OF[s], s in NIFTY50) for s in ALL_SYMBOLS}
        self.status: dict = {"mode": "?", "message": "starting", "loaded": 0, "total": len(ALL_SYMBOLS),
                             "ticker": "idle", "missing": [], "error": None, "lastTick": None}

    # ------------------------------------------------------------------ status
    def set_status(self, **kw) -> None:
        with self._lock:
            self.status.update(kw)

    def get_status(self) -> dict:
        with self._lock:
            return dict(self.status)

    # ------------------------------------------------------------------ history
    def set_daily(self, sym: str, rows: list[tuple]) -> None:
        with self._lock:
            self.syms[sym].daily = sorted(rows, key=lambda r: r[0])

    def set_fut_oi_daily(self, sym: str, rows: list[tuple]) -> None:
        with self._lock:
            self.syms[sym].fut_oi_daily = sorted(rows, key=lambda r: r[0])

    def seed_candles(self, sym: str, candles: list[dict]) -> None:
        """Seed with 5m history (any number of days); keeps the latest session only.

        If live ticks already started a newer session for this symbol, the seed is ignored.
        """
        by_day: dict[date, list[dict]] = {}
        for c in candles:
            d = datetime.fromtimestamp(c["t"], tz=IST).date()
            by_day.setdefault(d, []).append(c)
        with self._lock:
            st = self.syms[sym]
            if by_day:
                day = max(by_day)
                if st.session_date is None or day >= st.session_date:
                    bars = sorted(by_day[day], key=lambda c: c["t"])
                    if st.session_date == day and st.candles:
                        # merge: history wins for bars it has, live keeps newer bars
                        last_hist = bars[-1]["t"]
                        bars = bars + [c for c in st.candles if c["t"] > last_hist]
                    st.session_date = day
                    st.candles = [dict(c) for c in bars]
            st.seeded = True
            st.cum_vol = None  # next tick only sets the volume baseline

    # ------------------------------------------------------------------ live
    def on_quote(self, sym: str, ts: datetime, ltp: float, cum_vol: Optional[int] = None,
                 vwap: Optional[float] = None, day_open: Optional[float] = None,
                 prev_close: Optional[float] = None) -> None:
        if ltp is None or ltp <= 0:
            return
        ts = to_ist(ts)
        b = bucket_start(ts)
        with self._lock:
            st = self.syms.get(sym)
            if st is None:
                return
            d = ts.date()
            if st.session_date is not None and d < st.session_date:
                return
            if st.session_date is not None and d > st.session_date:
                if b is None:  # pre-open tick for a new day: keep showing the last session
                    return
                st.session_date, st.candles, st.cum_vol = d, [], None
            if st.session_date is None:
                if b is None:
                    return
                st.session_date = d
            st.tick_date = d
            st.ltp = float(ltp)
            if vwap:
                st.vwap = float(vwap)
            if day_open:
                st.day_open = float(day_open)
            if prev_close:
                st.prev_close = float(prev_close)
            dv = 0
            if cum_vol is not None:
                if st.cum_vol is not None and cum_vol >= st.cum_vol:
                    dv = int(cum_vol - st.cum_vol)
                st.cum_vol = int(cum_vol)
            self.status["lastTick"] = epoch(ts)
            if b is None or not st.seeded:
                return
            t = epoch(b)
            last = st.candles[-1] if st.candles else None
            if last is not None and last["t"] == t:
                last["h"] = max(last["h"], ltp)
                last["l"] = min(last["l"], ltp)
                last["c"] = ltp
                last["v"] = (last.get("v") or 0) + dv
            elif last is None or t > last["t"]:
                st.candles.append({"t": t, "o": ltp, "h": ltp, "l": ltp, "c": ltp, "v": dv})

    def on_oi(self, sym: str, ts: datetime, oi: float) -> None:
        if oi is None:
            return
        with self._lock:
            st = self.syms.get(sym)
            if st is not None:
                st.oi, st.oi_date = float(oi), to_ist(ts).date()

    # ------------------------------------------------------------------ read
    def read(self) -> list[dict]:
        """Consistent copy of every symbol for one engine pass."""
        with self._lock:
            out = []
            for st in self.syms.values():
                candles = list(st.candles)
                if candles:
                    candles[-1] = dict(candles[-1])  # only the last bar is mutated in place
                live = st.tick_date is not None and st.tick_date == st.session_date
                out.append({
                    "s": st.symbol, "sec": st.sector, "n50": st.n50, "date": st.session_date,
                    "candles": candles, "seeded": st.seeded,
                    "ltp": st.ltp if live else None, "open": st.day_open if live else None,
                    "prevClose": st.prev_close if live else None, "vwap": st.vwap if live else None,
                    "oi": st.oi if (st.oi_date is not None and st.oi_date == st.session_date) else None,
                    "daily": st.daily, "futOi": st.fut_oi_daily,
                })
            return out
