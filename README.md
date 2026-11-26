# Order X-Ray

A live order-block and liquidity terminal for NSE F&O stocks, built on Zerodha Kite Connect.
It ranks every stock in `sectors.py` by one-directional intraday strength, shows the **top 10**
on each side, and builds a trade card for the **top 3** per side.

Read-only: it never places orders or changes anything in your Kite account.

## Run

```powershell
cd OrderFlowStudio\xray
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env      # then edit .env
.\.venv\Scripts\python.exe server.py
```

Open http://127.0.0.1:8010.

- `MARKET_MODE=demo` uses a synthetic market (labelled DEMO) so you can work on it off-hours.
- `MARKET_MODE=kite` needs `KITE_API_KEY` and `KITE_ACCESS_TOKEN` in `.env`. Kite access tokens
  expire every morning (~06:00 IST): put the new token in `.env` and restart.

On first start each day, Kite mode loads history at ~2.5 requests/s (Kite allows 3/s). That's
about 3 calls per symbol, so ~4-5 minutes for ~218 symbols. The header shows `history n/218`
and the board fills in as symbols load. Daily data is cached in `.cache/`, so a restart the same
day only reloads intraday candles (~1.5 min). Outside market hours it shows the last session.

## How it works

| Stage | Rule |
|---|---|
| Data | Kite ticker in FULL mode: equity price, volume, VWAP (`average_traded_price`); nearest stock future for OI (skips a contract expiring today) |
| Candles | 5-minute bars built from ticks, seeded from Kite historical. Order blocks use **closed** bars only |
| Strength | `(price − open) / open / ADR50 × efficiency`. ADR50 = average daily range of the last 50 sessions; efficiency = net move ÷ path length (chop scores near 0) |
| Side | Positive strength = bullish, negative = bearish. Percentile `p` is against the whole board |
| Board | Top 10 per side (`BOARD_SIZE`) |
| Order block | Close beyond a swing high/low or the first 15-min range (break of structure). The move must leave a fair value gap or close beyond the block by ≥ 1 average candle. Block = last opposite-colour candle before the move. Invalid after any 5m close through its far side |
| Levels | Zone = block edge → price; **Z** = middle of zone; stop = 0.06% beyond the block; targets = unbroken swing highs/lows, day high/low, previous-day high/low, opposing blocks (projected from ADR if none; marked `*`); amber extras = older blocks, swing points, day open, unfilled gap |
| R:R | `(T2 − Z) / (Z − stop)` |
| Picks | Top 3 per side (`PICKS`) after: max 2 per sector (`SECTOR_CAP`), no event risk (fall ≥ 2.5 ADR), must have a valid setup |
| Build-up | Price vs today's open × OI vs previous session: long build-up / short build-up / short covering / long unwinding |
| CONV | 0–99: 55% rank within side, 20% efficiency, 13% VWAP side, 12% OI build-up agreement |

NIFTY_50 is treated as an index basket (its own sector-panel row and the blue reference line),
not a sector, so it doesn't count toward the sector cap. Stocks only listed in NIFTY_50 go to OTHERS.

## Screen

- **Header strip**: every stock as a dot at its day % (bullish above the line, bearish below). Board stocks glow, picks are ringed, event-risk stocks are amber. Lagging and leading sector at the ends.
- **X-Ray**: one line per stock from 09:15 to now; vertical position is the stock's rank position (the axis shows strength values). Lines end in the ranked column, and flows carry the top 10 / bottom 10 into the tiles, then picks into the cards. Blue band = first 15 minutes, blue line = NIFTY 50 basket. Click a sector to highlight its stocks.
- **Tiles**: rank, day %, OI build-up, volume-at-price profile, rank change since the last minute.
- **Cards**: the 3 picks per side with zone, stop, targets, risk %, R:R.
- **Popup** (hover; tap on mobile; or search with `/`): 5m candles, VWAP, current block + zone, older blocks, all levels.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Security

- Credentials are read from `.env` only, used server-side, and redacted from every error/log line.
- The server binds to `127.0.0.1` and has no login. Don't expose it to a network as-is.

Analytics for education, not investment advice.
