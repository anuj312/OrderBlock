"""Zerodha Kite Connect feed (read-only: no orders, no account changes).

1. Verify the access token, resolve NSE EQ tokens + the nearest stock future per symbol
   (skipping a contract that expires today, whose OI is distorted by rollover).
2. Start one KiteTicker socket in FULL mode (equity: price/volume/VWAP, futures: OI).
3. Throttled historical loader: 50+ daily sessions (ADR, previous close/high/low) and
   futures daily OI (previous session OI), cached per day, then the latest session's
   5-minute candles. Kite allows ~3 historical requests/sec; we stay under it.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

from market_time import CLOSE_T, IST, epoch, now_ist, to_ist
from sectors import ALL_SYMBOLS, NIFTY50

log = logging.getLogger("xray.kite")


# ---------------------------------------------------------------- pure helpers
def resolve_equities(instruments: Iterable[dict], symbols: Iterable[str]) -> tuple[dict[str, int], list[str]]:
    wanted, found = set(symbols), {}
    for ins in instruments:
        ts = ins.get("tradingsymbol")
        if ts in wanted and ins.get("segment") == "NSE" and ins.get("instrument_type") == "EQ":
            found[ts] = int(ins["instrument_token"])
    return found, sorted(wanted - set(found))


def _as_date(x) -> Optional[date]:
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    try:
        return date.fromisoformat(str(x)[:10])
    except ValueError:
        return None


def nearest_futures(instruments: Iterable[dict], symbols: Iterable[str], today: date) -> dict[str, int]:
    wanted, best = set(symbols), {}
    for ins in instruments:
        name = ins.get("name")
        if name not in wanted or ins.get("segment") != "NFO-FUT" or ins.get("instrument_type") != "FUT":
            continue
        exp = _as_date(ins.get("expiry"))
        if exp is None or exp <= today:  # expiry-day OI collapses on rollover; use next month
            continue
        if name not in best or exp < best[name][1]:
            best[name] = (int(ins["instrument_token"]), exp)
    return {k: v[0] for k, v in best.items()}


def rows_to_candles(rows: Iterable[dict]) -> list[dict]:
    out = []
    for r in rows:
        d = r.get("date")
        if isinstance(d, datetime):
            out.append({"t": epoch(to_ist(d)), "o": float(r["open"]), "h": float(r["high"]),
                        "l": float(r["low"]), "c": float(r["close"]), "v": int(r.get("volume") or 0)})
    return out


def rows_to_daily(rows: Iterable[dict], drop_from: date) -> list[tuple]:
    out = []
    for r in rows:
        d = _as_date(r.get("date"))
        if d and d < drop_from:
            out.append((d, float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])))
    return out


def rows_to_oi(rows: Iterable[dict], drop_from: date) -> list[tuple]:
    return [(d, float(r["oi"])) for r in rows
            if (d := _as_date(r.get("date"))) and d < drop_from and r.get("oi") is not None]


# ---------------------------------------------------------------- feed
class KiteFeed:
    def __init__(self, store, cfg):
        self.store, self.cfg = store, cfg
        self.kite = None
        self.ticker = None
        self.eq: dict[str, int] = {}
        self.fut: dict[str, int] = {}
        self.token_map: dict[int, tuple[str, str]] = {}
        self._last_call = 0.0

    def start(self) -> None:
        threading.Thread(target=self._run, name="kite-feed", daemon=True).start()

    def _fail(self, msg: str) -> None:
        from config import redact
        self.store.set_status(error=redact(msg, self.cfg), message="Kite feed stopped")
        log.error(redact(msg, self.cfg))

    def _run(self) -> None:
        from kiteconnect import KiteConnect
        from kiteconnect.exceptions import TokenException
        self.store.set_status(mode="kite", message="connecting to Kite")
        if not self.cfg.api_key or not self.cfg.access_token:
            self._fail("KITE_API_KEY / KITE_ACCESS_TOKEN missing in .env")
            return
        self.kite = KiteConnect(api_key=self.cfg.api_key)
        self.kite.set_access_token(self.cfg.access_token)
        try:
            self.kite.profile()
        except TokenException:
            self._fail("Kite rejected the access token (tokens expire daily). "
                       "Put today's token in KITE_ACCESS_TOKEN and restart.")
            return
        except Exception as e:  # network etc.
            self._fail(f"Kite profile check failed: {e}")
            return
        try:
            today = now_ist().date()
            self.store.set_status(message="loading instruments")
            self.eq, missing = resolve_equities(self.kite.instruments("NSE"), ALL_SYMBOLS)
            self.fut = nearest_futures(self.kite.instruments("NFO"), self.eq.keys(), today)
            self.store.set_status(missing=missing)
            for s, t in self.eq.items():
                self.token_map[t] = (s, "EQ")
            for s, t in self.fut.items():
                self.token_map[t] = (s, "FUT")
        except Exception as e:
            self._fail(f"instrument load failed: {e}")
            return
        self._start_ticker()
        self._load_history(today)

    # ------------------------------------------------------------ ticker
    def _start_ticker(self) -> None:
        from kiteconnect import KiteTicker
        kws = KiteTicker(self.cfg.api_key, self.cfg.access_token)
        tokens = list(self.token_map)
        st = self.store

        def on_connect(ws, _resp):
            ws.subscribe(tokens)
            ws.set_mode(ws.MODE_FULL, tokens)
            st.set_status(ticker="connected")

        def on_ticks(_ws, ticks):
            received = now_ist()
            for t in ticks:
                info = self.token_map.get(t.get("instrument_token"))
                if not info:
                    continue
                sym, kind = info
                ts = t.get("exchange_timestamp") or t.get("last_trade_time")
                ts = to_ist(ts) if isinstance(ts, datetime) else received
                if ts > received + timedelta(seconds=5):
                    ts = received
                if kind == "EQ":
                    ohlc = t.get("ohlc") or {}
                    st.on_quote(sym, ts, t.get("last_price"), cum_vol=t.get("volume_traded"),
                                vwap=t.get("average_traded_price"), day_open=ohlc.get("open"),
                                prev_close=ohlc.get("close"))
                else:
                    st.on_oi(sym, ts, t.get("oi"))

        kws.on_connect = on_connect
        kws.on_ticks = on_ticks
        kws.on_close = lambda ws, code, reason: st.set_status(ticker=f"closed ({code})")
        kws.on_error = lambda ws, code, reason: st.set_status(ticker=f"error ({code})")
        kws.on_reconnect = lambda ws, n: st.set_status(ticker=f"reconnecting ({n})")
        kws.on_noreconnect = lambda ws: st.set_status(ticker="stopped")
        self.ticker = kws
        kws.connect(threaded=True)

    # ------------------------------------------------------------ history
    def _call(self, fn, *a, **kw):
        from kiteconnect.exceptions import TokenException
        for attempt in range(4):
            wait = 1.0 / max(0.5, self.cfg.history_rate) - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()
            try:
                return fn(*a, **kw)
            except TokenException:
                raise
            except Exception as e:
                if attempt == 3:
                    raise
                backoff = 2.0 * (attempt + 1) if "too many" in str(e).lower() else 0.7 * (attempt + 1)
                time.sleep(backoff)

    def _cache_path(self, today: date):
        self.cfg.cache_dir.mkdir(parents=True, exist_ok=True)
        return self.cfg.cache_dir / f"daily-{today.isoformat()}.json"

    def _load_cache(self, today: date) -> dict:
        p = self._cache_path(today)
        try:
            raw = json.loads(p.read_text("utf-8"))
        except (OSError, ValueError):
            return {}
        out = {}
        for s, v in raw.items():
            out[s] = {"eq": [(date.fromisoformat(r[0]), *r[1:]) for r in v.get("eq", [])],
                      "fut": [(date.fromisoformat(r[0]), r[1]) for r in v.get("fut", [])]}
        return out

    def _save_cache(self, today: date, cache: dict) -> None:
        raw = {s: {"eq": [[r[0].isoformat(), *r[1:]] for r in v["eq"]],
                   "fut": [[r[0].isoformat(), r[1]] for r in v["fut"]]} for s, v in cache.items()}
        tmp = self._cache_path(today).with_suffix(".tmp")
        tmp.write_text(json.dumps(raw), "utf-8")
        tmp.replace(self._cache_path(today))

    def _load_history(self, today: date) -> None:
        from kiteconnect.exceptions import TokenException
        now = now_ist()
        # today's daily row is final only after the close
        drop_from = today + timedelta(days=1) if now.time() >= CLOSE_T else today
        cache = self._load_cache(today)
        order = sorted(self.eq, key=lambda s: (s not in NIFTY50, s))
        loaded = 0
        self.store.set_status(message="loading history", loaded=0, total=len(order))
        for i, sym in enumerate(order):
            try:
                c = cache.get(sym)
                if c is None:
                    eq_rows = self._call(self.kite.historical_data, self.eq[sym],
                                         now - timedelta(days=100), now, "day")
                    fut_rows = []
                    if sym in self.fut:
                        fut_rows = self._call(self.kite.historical_data, self.fut[sym],
                                              now - timedelta(days=20), now, "day", oi=True)
                    c = cache[sym] = {"eq": rows_to_daily(eq_rows, drop_from), "fut": rows_to_oi(fut_rows, drop_from)}
                    if i % 20 == 19:
                        self._save_cache(today, cache)
                self.store.set_daily(sym, c["eq"])
                self.store.set_fut_oi_daily(sym, c["fut"])
                start = datetime.combine(now.date() - timedelta(days=7), datetime.min.time(), IST)
                bars = self._call(self.kite.historical_data, self.eq[sym], start, now, "5minute")
                self.store.seed_candles(sym, rows_to_candles(bars))
                loaded += 1
                self.store.set_status(loaded=loaded)
            except TokenException:
                self._fail("Kite token expired while loading history. Update KITE_ACCESS_TOKEN and restart.")
                return
            except Exception as e:
                from config import redact
                log.warning("history %s failed: %s", sym, redact(str(e), self.cfg))
                self.store.seed_candles(sym, [])  # still allow live candles from now on
        self._save_cache(today, cache)
        self.store.set_status(message="live")
