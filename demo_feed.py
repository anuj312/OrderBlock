"""Synthetic market for off-hours development. Clearly labelled DEMO in the UI.

A virtual clock starts at 09:15 + DEMO_START_MINUTE and advances one market minute
every DEMO_SECONDS_PER_MINUTE real seconds, pushing ticks through the same Store
path the Kite feed uses, so candles, order blocks and rankings are built identically.
"""
from __future__ import annotations

import math
import random
import threading
import time
from datetime import date, datetime, timedelta

from market_time import IST, session_open
from sectors import ALL_SYMBOLS, SECTOR_OF, SECTORS

SESSION_MINUTES = 375
SUBTICKS = 4


def _session_day() -> date:
    d = datetime.now(IST).date()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


class DemoFeed:
    def __init__(self, store, cfg):
        self.store = store
        self.cfg = cfg
        self.day = _session_day()
        self.t0 = session_open(self.day)
        self.minute = 0
        self._step_at = time.monotonic()
        self.rng = random.Random(self.day.toordinal())
        store.clock = self.clock
        self.state: dict[str, dict] = {}

    def clock(self) -> datetime:
        frac = 0.0
        if self.minute < SESSION_MINUTES:
            frac = min(0.999, (time.monotonic() - self._step_at) / max(0.1, self.cfg.demo_seconds_per_minute))
        return self.t0 + timedelta(minutes=self.minute + frac)

    # ------------------------------------------------------------------ setup
    def _init_symbols(self) -> None:
        rng = self.rng
        market = rng.gauss(0.25, 0.35)
        sector_drift = {s: rng.gauss(0, 0.55) for s in SECTORS}
        crash = set(rng.sample(ALL_SYMBOLS, 2))
        for sym in ALL_SYMBOLS:
            prev_close = round(math.exp(rng.uniform(math.log(80), math.log(6000))), 1)
            adr = rng.uniform(1.2, 3.8)
            trend = market * rng.uniform(0.6, 1.4) + sector_drift[SECTOR_OF[sym]] + rng.gauss(0, 0.6)
            if rng.random() < 0.12:
                trend += rng.choice((-1, 1)) * rng.uniform(1.0, 2.0)
            if sym in crash:
                trend = -rng.uniform(3.5, 5.0)
            gap = rng.gauss(0, 0.25) * adr / 100
            day_open = prev_close * (1 + gap)
            prev_oi = rng.randint(20, 400) * 10_000
            oi_dir = 1 if rng.random() < 0.7 else -1
            self.state[sym] = {
                "pc": prev_close, "adr": adr, "trend": trend, "px": day_open, "open": day_open,
                "sigma": 0.032 * adr / 100, "wave_a": rng.uniform(0.03, 0.09) * adr / 100,
                "wave_p": rng.uniform(18, 45), "wave_ph": rng.uniform(0, 6.28),
                "vol": 0, "pv": 0.0, "base_vol": rng.randint(2, 60) * 1000,
                "prev_oi": prev_oi, "oi_day": oi_dir * rng.uniform(0.02, 0.16),
            }
            daily, c = [], prev_close
            for k in range(60, 0, -1):  # 60 synthetic sessions ending yesterday
                d = self.day - timedelta(days=k)
                rngf = adr * rng.uniform(0.6, 1.4) / 100
                o = c * (1 + rng.gauss(0, rngf / 4))
                h, l = max(o, c) * (1 + rngf / 2), min(o, c) * (1 - rngf / 2)
                daily.append((d, o, h, l, c))
            last = daily[-1]
            daily[-1] = (last[0], last[1], max(last[2], prev_close), min(last[3], prev_close), prev_close)
            self.store.set_daily(sym, daily)
            self.store.set_fut_oi_daily(sym, [(self.day - timedelta(days=1), prev_oi)])
            self.store.seed_candles(sym, [])

    def _advance(self, minute: int) -> None:
        rng = self.rng
        frac_day = minute / SESSION_MINUTES
        vol_shape = 1.6 - 1.2 * math.sin(math.pi * frac_day)  # U-shaped intraday volume
        for sym, s in self.state.items():
            drift = s["trend"] * s["adr"] / 100 / SESSION_MINUTES
            for k in range(SUBTICKS):
                t = minute + k / SUBTICKS
                wave = s["wave_a"] * (math.sin(t / s["wave_p"] * 6.283 + s["wave_ph"])
                                      - math.sin((t - 1 / SUBTICKS) / s["wave_p"] * 6.283 + s["wave_ph"]))
                ret = drift / SUBTICKS + wave + rng.gauss(0, s["sigma"] / math.sqrt(SUBTICKS))
                s["px"] = max(1.0, s["px"] * (1 + ret))
                q = int(s["base_vol"] / SUBTICKS * vol_shape * (1 + abs(ret) / s["sigma"]) * rng.uniform(0.5, 1.5))
                s["vol"] += q
                s["pv"] += q * s["px"]
                ts = self.t0 + timedelta(minutes=t)
                px = round(s["px"], 2)
                self.store.on_quote(sym, ts, px, cum_vol=s["vol"], vwap=s["pv"] / s["vol"] if s["vol"] else px,
                                    day_open=round(s["open"], 2), prev_close=s["pc"])
            oi = s["prev_oi"] * (1 + s["oi_day"] * min(1.0, (minute + 1) / 240))
            self.store.on_oi(sym, self.t0 + timedelta(minutes=minute), round(oi))

    # ------------------------------------------------------------------ run
    def start(self) -> None:
        threading.Thread(target=self._run, name="demo-feed", daemon=True).start()

    def _run(self) -> None:
        self.store.set_status(mode="demo", message="DEMO: synthetic market, not real prices", ticker="demo")
        self._init_symbols()
        start = max(1, min(SESSION_MINUTES, self.cfg.demo_start_minute))
        for m in range(start):
            self._advance(m)
        self.minute = start
        self._step_at = time.monotonic()
        self.store.set_status(loaded=len(ALL_SYMBOLS))
        while self.minute < SESSION_MINUTES:
            time.sleep(max(0.05, self.cfg.demo_seconds_per_minute - (time.monotonic() - self._step_at)))
            self._advance(self.minute)
            self.minute += 1
            self._step_at = time.monotonic()
        self.store.set_status(message="DEMO session closed. Restart to replay.")
