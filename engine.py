"""X-Ray analytics: strength ranking, order blocks, liquidity levels, picks.

Pure functions on plain dicts so every rule is unit-testable. Candles are
{"t": bar start epoch, "o","h","l","c","v"}; only *closed* 5m bars feed order blocks.
"""
from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from datetime import date
from statistics import mean
from typing import Optional

from market_time import BAR_SECONDS, epoch, phase, session_open
from sectors import NIFTY50, SECTORS, display_name


@dataclass(frozen=True)
class Rules:
    board_size: int = 20        # stocks per side on the board
    picks: int = 3              # trade cards per side
    sector_cap: int = 2         # max picks from one sector per side
    adr_sessions: int = 50      # "normal daily range" lookback
    chop_er: float = 0.20       # efficiency below this is treated as chop
    event_adr: float = 2.5      # fall of >= this many ADRs = event risk
    stop_buffer: float = 0.0006 # stop sits this fraction beyond the block
    swing_k: int = 2            # fractal width for swing highs/lows
    ob_lookback: int = 12       # bars searched back for the last opposite candle
    avg_bars: int = 12          # bars in the "average candle" for displacement
    level_gap: float = 0.001    # merge liquidity levels closer than 0.1%
    fallback_adr: float = 2.0   # ADR% used until daily history loads


# ====================================================================== basics
def closed_bars(candles: list[dict], now_ts: int) -> list[dict]:
    return [c for c in candles if c["t"] + BAR_SECONDS <= now_ts]


def efficiency(path: list[float]) -> float:
    """Kaufman efficiency ratio: 1.0 = straight line, ~0 = chop."""
    if len(path) < 2:
        return 0.0
    total = sum(abs(b - a) for a, b in zip(path, path[1:]))
    return abs(path[-1] - path[0]) / total if total > 0 else 0.0


def strength(day_open: float, price: float, adr_pct: float, er: float, chop_er: float) -> float:
    """Intraday move in units of the stock's normal daily range, damped by chop."""
    if not day_open or not adr_pct:
        return 0.0
    norm = (price - day_open) / day_open * 100.0 / adr_pct
    w = er if er >= chop_er else er * er / chop_er
    return norm * w


def strength_series(bars: list[dict], day_open: float, adr_pct: float, chop_er: float) -> list[float]:
    """Score at each bar close (for the X-Ray history lines)."""
    out, total, prev = [], 0.0, day_open
    for b in bars:
        total += abs(b["c"] - prev)
        prev = b["c"]
        er = abs(b["c"] - day_open) / total if total > 0 else 0.0
        out.append(strength(day_open, b["c"], adr_pct, er, chop_er))
    return out


def vwap_series(bars: list[dict]) -> list[Optional[float]]:
    out, pv, vv = [], 0.0, 0.0
    for b in bars:
        v = b.get("v") or 0
        pv += (b["h"] + b["l"] + b["c"]) / 3 * v
        vv += v
        out.append(pv / vv if vv > 0 else None)
    return out


def buildup(price_dir: float, oi_chg: Optional[float]) -> Optional[str]:
    if oi_chg is None:
        return None
    if oi_chg >= 0:
        return "LONG BUILD-UP" if price_dir >= 0 else "SHORT BUILD-UP"
    return "SHORT COVERING" if price_dir >= 0 else "LONG UNWINDING"


def daily_context(daily: list[tuple], session_date: Optional[date], n: int) -> Optional[dict]:
    rows = [r for r in daily if session_date is None or r[0] < session_date][-n:]
    rows = [r for r in rows if r[4] and r[4] > 0]
    if not rows:
        return None
    adr = mean((r[2] - r[3]) / r[4] * 100.0 for r in rows)
    last = rows[-1]
    return {"adr_pct": adr, "prev_close": last[4], "prev_high": last[2], "prev_low": last[3]}


def oi_context(fut_oi: list[tuple], session_date: Optional[date]) -> tuple[Optional[float], Optional[float]]:
    """(oi at session close from history, oi of the previous session)."""
    prev = [r for r in fut_oi if session_date is None or r[0] < session_date]
    same = [r for r in fut_oi if r[0] == session_date]
    return (same[-1][1] if same else None), (prev[-1][1] if prev else None)


# ====================================================================== structure
def swings(bars: list[dict], k: int) -> tuple[list[int], list[int]]:
    highs, lows = [], []
    for j in range(k, len(bars) - k):
        h, l = bars[j]["h"], bars[j]["l"]
        if all(h > bars[j - i]["h"] for i in range(1, k + 1)) and all(h >= bars[j + i]["h"] for i in range(1, k + 1)):
            highs.append(j)
        if all(l < bars[j - i]["l"] for i in range(1, k + 1)) and all(l <= bars[j + i]["l"] for i in range(1, k + 1)):
            lows.append(j)
    return highs, lows


def _avg_range(bars: list[dict], i: int, n: int) -> float:
    seg = bars[max(0, i - n):i] or bars[i:i + 1]
    return mean(b["h"] - b["l"] for b in seg)


def _block(bars: list[dict], i: int, bull: bool, r: Rules) -> Optional[dict]:
    """Order block behind the structure break at bar i, if the move was forceful."""
    k = None
    for j in range(i - 1, max(-1, i - 1 - r.ob_lookback), -1):
        b = bars[j]
        if (b["c"] < b["o"]) if bull else (b["c"] > b["o"]):
            k = j
            break
    if k is None:
        return None
    ob = bars[k]
    if bull and bars[i]["c"] <= ob["h"]:
        return None
    if not bull and bars[i]["c"] >= ob["l"]:
        return None
    if bull:
        fvg = any(bars[m]["l"] > bars[m - 2]["h"] for m in range(k + 2, i + 1))
        beyond = bars[i]["c"] - ob["h"]
    else:
        fvg = any(bars[m]["h"] < bars[m - 2]["l"] for m in range(k + 2, i + 1))
        beyond = ob["l"] - bars[i]["c"]
    if not (fvg or beyond >= _avg_range(bars, i, r.avg_bars)):
        return None
    return {"dir": "bull" if bull else "bear", "lo": ob["l"], "hi": ob["h"], "k": k, "i": i,
            "t0": ob["t"], "t1": bars[i]["t"], "valid": True, "end": None}


def order_blocks(bars: list[dict], r: Rules) -> list[dict]:
    """All order blocks of the session, oldest first, with validity and draw range."""
    n = len(bars)
    if n < 4:
        return []
    sh, sl = swings(bars, r.swing_k)
    act_hi: list[tuple[int, float]] = []  # (activation index, price)
    act_lo: list[tuple[int, float]] = []
    or_hi = max(b["h"] for b in bars[:3])
    or_lo = min(b["l"] for b in bars[:3])
    pending_hi = [(j + r.swing_k + 1, bars[j]["h"]) for j in sh] + [(3, or_hi)]
    pending_lo = [(j + r.swing_k + 1, bars[j]["l"]) for j in sl] + [(3, or_lo)]
    obs: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for i in range(3, n):
        act_hi += [p for p in pending_hi if p[0] == i]
        act_lo += [p for p in pending_lo if p[0] == i]
        c = bars[i]["c"]
        if any(c > p for _, p in act_hi):
            act_hi = [x for x in act_hi if c <= x[1]]
            ob = _block(bars, i, True, r)
            if ob and ("bull", ob["k"]) not in seen:
                seen.add(("bull", ob["k"]))
                obs.append(ob)
        if any(c < p for _, p in act_lo):
            act_lo = [x for x in act_lo if c >= x[1]]
            ob = _block(bars, i, False, r)
            if ob and ("bear", ob["k"]) not in seen:
                seen.add(("bear", ob["k"]))
                obs.append(ob)
    for ob in obs:  # invalidate on a close through the far side
        for j in range(ob["i"] + 1, n):
            if (bars[j]["c"] < ob["lo"]) if ob["dir"] == "bull" else (bars[j]["c"] > ob["hi"]):
                ob["valid"], ob["end"] = False, bars[j]["t"]
                break
    for a in obs:  # each box is drawn over its own part of the day
        nxt = [b["t1"] for b in obs if b["dir"] == a["dir"] and b["t1"] > a["t1"]]
        ends = [x for x in (a["end"], min(nxt) if nxt else None) if x is not None]
        a["until"] = min(ends) if ends else None
    return obs


def _unbroken(bars: list[dict], idx: list[int], key: str, above: bool) -> list[float]:
    out = []
    for j in idx:
        p = bars[j][key]
        later = bars[j + 1:]
        if not any((b["c"] > p) if above else (b["c"] < p) for b in later):
            out.append(p)
    return out


def _merge(levels: list[tuple[float, bool]], gap: float, ascending: bool) -> list[tuple[float, bool]]:
    out: list[tuple[float, bool]] = []
    for p, proj in sorted(levels, key=lambda x: x[0], reverse=not ascending):
        if out and abs(p - out[-1][0]) / out[-1][0] < gap:
            continue
        out.append((p, proj))
    return out


def trade_setup(bars: list[dict], obs: list[dict], side: str, ltp: float, ctx: dict,
                day_open: float, r: Rules) -> Optional[dict]:
    """Z / stop / targets around the latest valid block on the stock's side."""
    bull = side == "bull"
    mine = [o for o in obs if o["dir"] == side and o["valid"]]
    if not mine or not bars or not ltp:
        return None
    ob = mine[-1]
    last = bars[-1]
    adr_abs = ctx["adr_pct"] / 100.0 * ltp
    sh, sl = swings(bars, r.swing_k)
    day_hi = max(max(b["h"] for b in bars), ltp)
    day_lo = min(min(b["l"] for b in bars), ltp)
    if bull:
        z_hi = max(ob["hi"], min(ltp, last["l"]))
        zone = (ob["hi"], z_hi)
        z = (zone[0] + zone[1]) / 2
        stop = ob["lo"] * (1 - r.stop_buffer)
        floor = ltp * (1 + 0.0005)
        cand = [(p, False) for p in _unbroken(bars, sh, "h", True) if p > floor]
        if day_hi > floor:
            cand.append((day_hi, False))
        if ctx.get("prev_high") and ctx["prev_high"] > floor:
            cand.append((ctx["prev_high"], False))
        cand += [(o["lo"], False) for o in obs if o["dir"] == "bear" and o["valid"] and o["lo"] > floor]
        tg = _merge(cand, r.level_gap, True)
        for f in (0.25, 0.5, 0.75):
            if len(tg) >= 2:
                break
            p = max(z, ltp) + f * adr_abs
            if not tg or p > tg[-1][0] * (1 + r.level_gap):
                tg.append((p, True))
        ex = [(o["lo"], False) for o in mine[:-1] if o["lo"] < stop]
        ex += [(p, False) for p in _unbroken(bars, sl, "l", False) if p < stop]
        if day_open < stop:
            ex.append((day_open, False))
        if ctx.get("prev_close") and day_lo > ctx["prev_close"] and ctx["prev_close"] < stop:
            ex.append((ctx["prev_close"], False))  # unfilled gap
        extras = _merge(ex, r.level_gap, False)[:3]
        labels = {"stop": "S1", "t1": "R1", "t2": "R2", "extras": ["S2", "S3", "S4"]}
        risk = z - stop
    else:
        z_lo = min(ob["lo"], max(ltp, last["h"]))
        zone = (z_lo, ob["lo"])
        z = (zone[0] + zone[1]) / 2
        stop = ob["hi"] * (1 + r.stop_buffer)
        ceil = ltp * (1 - 0.0005)
        cand = [(p, False) for p in _unbroken(bars, sl, "l", False) if p < ceil]
        if day_lo < ceil:
            cand.append((day_lo, False))
        if ctx.get("prev_low") and ctx["prev_low"] < ceil:
            cand.append((ctx["prev_low"], False))
        cand += [(o["hi"], False) for o in obs if o["dir"] == "bull" and o["valid"] and o["hi"] < ceil]
        tg = _merge(cand, r.level_gap, False)
        for f in (0.25, 0.5, 0.75):
            if len(tg) >= 2:
                break
            p = min(z, ltp) - f * adr_abs
            if not tg or p < tg[-1][0] * (1 - r.level_gap):
                tg.append((p, True))
        ex = [(o["hi"], False) for o in mine[:-1] if o["hi"] > stop]
        ex += [(p, False) for p in _unbroken(bars, sh, "h", True) if p > stop]
        if day_open > stop:
            ex.append((day_open, False))
        if ctx.get("prev_close") and day_hi < ctx["prev_close"] and ctx["prev_close"] > stop:
            ex.append((ctx["prev_close"], False))
        extras = _merge(ex, r.level_gap, True)[:3]
        labels = {"stop": "R1", "t1": "S1", "t2": "S2", "extras": ["R2", "R3", "R4"]}
        risk = stop - z
    t1 = tg[0] if tg else None
    t2 = tg[1] if len(tg) > 1 else t1
    rr = None
    if t2 and risk > 0:
        rr = ((t2[0] - z) if bull else (z - t2[0])) / risk
    return {
        "dir": side, "ob": {"lo": ob["lo"], "hi": ob["hi"], "t0": ob["t0"], "t1": ob["t1"]},
        "zone": [zone[0], zone[1]], "z": z, "stop": stop,
        "t1": t1[0] if t1 else None, "t2": t2[0] if t2 else None,
        "proj": [bool(t1 and t1[1]), bool(t2 and t2[1])],
        "extras": [p for p, _ in extras], "labels": labels,
        "rr": rr, "riskPct": risk / z * 100.0 if z else None,
    }


def volume_profile(bars: list[dict], bins: int = 18) -> Optional[dict]:
    if not bars:
        return None
    lo, hi = min(b["l"] for b in bars), max(b["h"] for b in bars)
    if hi <= lo:
        return None
    vol, up = [0.0] * bins, [0.0] * bins
    step = (hi - lo) / bins
    for b in bars:
        v = b.get("v") or 0
        if v <= 0:
            continue
        a = min(bins - 1, int((b["l"] - lo) / step))
        z = min(bins - 1, int((b["h"] - lo) / step))
        share = v / (z - a + 1)
        for i in range(a, z + 1):
            vol[i] += share
            if b["c"] >= b["o"]:
                up[i] += share
    m = max(vol) or 1.0
    return {"lo": lo, "hi": hi, "b": [[round(v / m, 3), round(u / v, 2) if v else 0.5] for v, u in zip(vol, up)]}


def conviction(side_pct: float, er: float, above_vwap: Optional[bool], bu: Optional[str], side: str) -> int:
    vw = 0.5 if above_vwap is None else (1.0 if above_vwap == (side == "bull") else 0.0)
    good = {"bull": {"LONG BUILD-UP": 1.0, "SHORT COVERING": 0.6},
            "bear": {"SHORT BUILD-UP": 1.0, "LONG UNWINDING": 0.6}}[side]
    oi = 0.5 if bu is None else good.get(bu, 0.0)
    v = 100 * (0.55 * side_pct + 0.20 * min(er, 1.0) + 0.13 * vw + 0.12 * oi)
    return int(max(1, min(99, round(v))))


def choose_picks(board: list[dict], r: Rules) -> dict[str, str]:
    """RULE text per board symbol: top N after sector cap and event-risk filters."""
    rules, per_sector, picked = {}, {}, 0
    for st in board:
        if st["ev"]:
            rules[st["s"]] = "NOT PICKED · event risk"
        elif st.get("setup") is None:
            rules[st["s"]] = "NOT PICKED · no setup"
        elif per_sector.get(st["sec"], 0) >= r.sector_cap:
            rules[st["s"]] = "NOT PICKED · sector cap"
        elif picked >= r.picks:
            rules[st["s"]] = f"NOT PICKED · outside top {r.picks}"
        else:
            picked += 1
            per_sector[st["sec"]] = per_sector.get(st["sec"], 0) + 1
            rules[st["s"]] = f"PICK · {'BULLISH' if st['side'] == 'bull' else 'BEARISH'} #{picked}"
    return rules


def _r(x: Optional[float], n: int = 2) -> Optional[float]:
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(x, n)


# ====================================================================== engine
class Engine:
    def __init__(self, store, rules: Rules = Rules()):
        self.store = store
        self.r = rules
        self._lock = threading.Lock()
        self._ob_cache: dict[str, tuple] = {}
        self._base_ranks: dict[str, tuple[str, int]] = {}
        self._last_ranks: dict[str, tuple[str, int]] = {}
        self._board_prev: set[str] = set()
        self._entered: dict[str, int] = {}
        self._minute: Optional[int] = None
        self.board: dict = {"status": {}, "stocks": []}
        self.history: dict = {"t0": None, "bars": {}}
        self._rows: dict[str, dict] = {}

    # ------------------------------------------------------------ per stock
    def _analyze(self, d: dict, now_ts: int) -> Optional[dict]:
        r = self.r
        bars = d["candles"]
        if not bars and d["ltp"] is None:
            return None
        ctx = daily_context(d["daily"], d["date"], r.adr_sessions) or {}
        adr = ctx.get("adr_pct") or r.fallback_adr
        ctx = {**ctx, "adr_pct": adr}
        closed = closed_bars(bars, now_ts)
        ltp = d["ltp"] if d["ltp"] is not None else (bars[-1]["c"] if bars else None)
        day_open = d["open"] or (bars[0]["o"] if bars else ltp)
        prev_close = d["prevClose"] or ctx.get("prev_close")
        if not ltp or not day_open:
            return None
        vw_series = vwap_series(bars)
        vwap = d["vwap"] or (vw_series[-1] if vw_series else None)
        path = [day_open] + [b["c"] for b in closed] + [ltp]
        er = efficiency(path)
        score = strength(day_open, ltp, adr, er, r.chop_er)
        chg = (ltp - prev_close) / prev_close * 100 if prev_close else 0.0
        hist_oi, prev_oi = oi_context(d["futOi"], d["date"])
        oi = d["oi"] if d["oi"] is not None else hist_oi
        oi_chg = (oi - prev_oi) / prev_oi * 100 if (oi is not None and prev_oi) else None
        key = (len(closed), closed[-1]["t"] if closed else 0, closed[-1]["c"] if closed else 0)
        cached = self._ob_cache.get(d["s"])
        if cached and cached[0] == key and cached[4] == (day_open, adr):
            obs, series, path_series = cached[1], cached[2], cached[3]
        else:
            obs = order_blocks(closed, r)
            series = strength_series(closed, day_open, adr, r.chop_er)
            # intraday path in units of the normal daily range (what the X-Ray lines draw)
            path_series = [(b["c"] - day_open) / day_open * 100.0 / adr for b in closed]
            self._ob_cache[d["s"]] = (key, obs, series, path_series, (day_open, adr))
        side = "bull" if (score > 0 or (score == 0 and chg >= 0)) else "bear"
        return {
            "s": d["s"], "sec": d["sec"], "n50": d["n50"], "date": d["date"],
            "ltp": ltp, "open": day_open, "pc": prev_close, "chg": chg, "chgAbs": ltp - (prev_close or ltp),
            "mv": (ltp - day_open) / day_open * 100, "sc": score, "er": er, "adr": adr, "side": side,
            "vw": vwap, "av": (ltp > vwap) if vwap else None,
            "oiChg": oi_chg, "oiAbs": (oi - prev_oi) if (oi is not None and prev_oi) else None,
            "bu": buildup(ltp - day_open, oi_chg), "ev": chg <= -r.event_adr * adr,
            "_bars": bars, "_closed": closed, "_obs": obs, "_ctx": ctx, "_series": series, "_vw": vw_series,
            "_path": path_series,
        }

    # ------------------------------------------------------------ full pass
    def compute(self) -> dict:
        r = self.r
        now = self.store.clock()
        now_ts = epoch(now)
        data = self.store.read()
        rows = [x for x in (self._analyze(d, now_ts) for d in data) if x]
        n = len(rows)
        ranked = sorted(rows, key=lambda x: x["sc"], reverse=True)
        scores = [x["sc"] for x in ranked]
        for x in ranked:  # percentile against the whole board
            lower = sum(1 for s in scores if s < x["sc"])
            equal = sum(1 for s in scores if s == x["sc"])
            x["p"] = (lower + 0.5 * equal) / n * 100 if n else 0
        bull = [x for x in ranked if x["side"] == "bull"]
        bear = [x for x in reversed(ranked) if x["side"] == "bear"]
        for side_list in (bull, bear):
            m = len(side_list)
            for i, x in enumerate(side_list):
                x["r"] = i + 1
                x["sideN"] = m
                side_pct = 1 - i / max(1, m - 1) if m > 1 else 1.0
                x["cv"] = conviction(side_pct, x["er"], x["av"], x["bu"], x["side"])
        board_bull, board_bear = bull[:r.board_size], bear[:r.board_size]
        on_board = {x["s"] for x in board_bull + board_bear}
        for x in rows:
            x["setup"] = None
            if x["s"] in on_board:
                x["setup"] = trade_setup(x["_closed"] or x["_bars"], x["_obs"], x["side"], x["ltp"],
                                         x["_ctx"], x["open"], r)
        rules = {**choose_picks(board_bull, r), **choose_picks(board_bear, r)}
        picks = {"bull": [x["s"] for x in board_bull if rules[x["s"]].startswith("PICK")],
                 "bear": [x["s"] for x in board_bear if rules[x["s"]].startswith("PICK")]}
        with self._lock:
            minute = now_ts // 60
            cur = {x["s"]: (x["side"], x["r"]) for x in rows}
            if self._minute is None:
                self._base_ranks = cur
            elif minute != self._minute:
                self._base_ranks = self._last_ranks
            self._minute = minute
            self._last_ranks = cur
            for s in on_board - self._board_prev:
                if self._board_prev:
                    self._entered[s] = now_ts
            self._board_prev = on_board
            self._entered = {s: t for s, t in self._entered.items() if now_ts - t < 90 and s in on_board}
        for x in rows:
            base = self._base_ranks.get(x["s"])
            x["dr"] = (base[1] - x["r"]) if base and base[0] == x["side"] else None
            x["rule"] = rules.get(x["s"], f"NOT PICKED · outside top {r.board_size}")
        self._rows = {x["s"]: x for x in rows}

        # sectors (+ NIFTY 50 basket row)
        groups: dict[str, list[dict]] = {}
        for x in rows:
            groups.setdefault(x["sec"], []).append(x)
            if x["s"] in NIFTY50:
                groups.setdefault("NIFTY_50", []).append(x)
        sectors = []
        for name in SECTORS + ["NIFTY_50"]:
            g = groups.get(name)
            if not g:
                continue
            sectors.append({
                "id": name, "name": display_name(name), "index": name == "NIFTY_50",
                "sc": _r(mean(x["sc"] for x in g), 3), "chg": _r(mean(x["chg"] for x in g)),
                "up": sum(1 for x in g if x["chg"] >= 0), "n": len(g),
                "cells": [[x["s"], _r(x["chg"])] for x in sorted(g, key=lambda y: y["chg"], reverse=True)],
            })
        real = sorted([s for s in sectors if not s["index"]], key=lambda s: s["sc"], reverse=True)
        sectors = real + [s for s in sectors if s["index"]]
        dates = [x["date"] for x in rows if x["date"]]
        session_date = max(dates) if dates else now.date()
        st = self.store.get_status()
        status = {
            "mode": st["mode"], "phase": phase(now, session_date), "now": now_ts,
            "session": session_date.isoformat(), "message": st["message"], "error": st["error"],
            "loaded": st["loaded"], "total": st["total"], "ticker": st["ticker"],
            "missing": st["missing"][:30], "lastTick": st["lastTick"],
        }
        details = {}
        for x in board_bull + board_bear:
            details[x["s"]] = {
                "setup": _round_setup(x["setup"]), "vp": volume_profile(x["_bars"]),
                "spark": [_r(b["c"]) for b in x["_bars"]],
            }
        board = {
            "status": status, "rules": {"board": r.board_size, "picks": r.picks, "cap": r.sector_cap},
            "t0": epoch(session_open(session_date)),
            "counts": {"bull": len(bull), "bear": len(bear), "up": sum(1 for x in rows if x["chg"] >= 0),
                       "down": sum(1 for x in rows if x["chg"] < 0), "n": n},
            "lead": real[0] if real else None, "lag": real[-1] if real else None,
            "stocks": [_public(x) for x in ranked],
            "boards": {"bull": [x["s"] for x in board_bull], "bear": [x["s"] for x in board_bear]},
            "picks": picks, "entered": sorted(self._entered), "details": details,
            "sectors": [{k: v for k, v in s.items()} for s in sectors],
        }
        self.board = board
        self.history = {"t0": board["t0"], "now": now_ts,
                        "bars": {x["s"]: [_r(v, 3) for v in x["_series"]] for x in rows},
                        "path": {x["s"]: [_r(v, 3) for v in x["_path"]] for x in rows}}
        return board

    # ------------------------------------------------------------ popup chart
    def chart(self, sym: str) -> Optional[dict]:
        x = self._rows.get(sym)
        if x is None:
            return None
        setup = x["setup"] or trade_setup(x["_closed"] or x["_bars"], x["_obs"], x["side"], x["ltp"],
                                          x["_ctx"], x["open"], self.r)
        return {
            "stock": _public(x), "setup": _round_setup(setup),
            "candles": [[b["t"], b["o"], b["h"], b["l"], b["c"], b.get("v") or 0] for b in x["_bars"]],
            "vwap": [_r(v) for v in x["_vw"]],
            "obs": [{"dir": o["dir"], "lo": o["lo"], "hi": o["hi"], "t0": o["t0"], "t1": o["t1"],
                     "valid": o["valid"], "until": o["until"]} for o in x["_obs"]],
            "closedN": len(x["_closed"]),
        }


def _round_setup(s: Optional[dict]) -> Optional[dict]:
    if not s:
        return None
    out = dict(s)
    for k in ("z", "stop", "t1", "t2"):
        out[k] = _r(s[k])
    out["zone"] = [_r(v) for v in s["zone"]]
    out["extras"] = [_r(v) for v in s["extras"]]
    out["rr"] = _r(s["rr"], 1)
    out["riskPct"] = _r(s["riskPct"])
    out["ob"] = {**s["ob"], "lo": _r(s["ob"]["lo"]), "hi": _r(s["ob"]["hi"])}
    return out


def _public(x: dict) -> dict:
    return {
        "s": x["s"], "sec": x["sec"], "secName": display_name(x["sec"]), "n50": x["n50"],
        "ltp": _r(x["ltp"]), "chg": _r(x["chg"]), "chgAbs": _r(x["chgAbs"]), "mv": _r(x["mv"]),
        "sc": _r(x["sc"], 3), "p": _r(x["p"], 1), "side": x["side"], "r": x["r"], "sideN": x["sideN"],
        "dr": x.get("dr"), "cv": x["cv"], "er": _r(x["er"], 2), "vw": _r(x["vw"]), "av": x["av"],
        "oiChg": _r(x["oiChg"], 1), "oiAbs": _r(x["oiAbs"], 0), "bu": x["bu"], "ev": x["ev"],
        "rule": x.get("rule"), "adr": _r(x["adr"], 2),
    }
