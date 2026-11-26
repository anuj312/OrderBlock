"""IST session helpers. IST has no DST, so a fixed offset avoids a tzdata dependency."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30), "IST")
OPEN_T = time(9, 15)
CLOSE_T = time(15, 30)
BAR_SECONDS = 300  # 5-minute candles


def now_ist() -> datetime:
    return datetime.now(IST)


def to_ist(dt: datetime) -> datetime:
    if dt.tzinfo is None:  # Kite returns naive IST datetimes for historical data
        return dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


def session_open(d: date) -> datetime:
    return datetime.combine(d, OPEN_T, IST)


def session_close(d: date) -> datetime:
    return datetime.combine(d, CLOSE_T, IST)


def epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def bucket_start(dt: datetime) -> datetime | None:
    """Start of the 5-minute bar containing dt, or None outside 09:15-15:30."""
    dt = to_ist(dt)
    o, c = session_open(dt.date()), session_close(dt.date())
    if dt < o or dt >= c:
        return None
    n = int((dt - o).total_seconds() // BAR_SECONDS)
    return o + timedelta(seconds=n * BAR_SECONDS)


def phase(now: datetime, session_date: date | None) -> str:
    """PRE / LIVE / CLOSED for the board header."""
    now = to_ist(now)
    if session_date is not None and session_date < now.date():
        return "CLOSED"
    if now.weekday() >= 5:
        return "CLOSED"
    if now < session_open(now.date()):
        return "PRE"
    if now >= session_close(now.date()):
        return "CLOSED"
    return "LIVE"
