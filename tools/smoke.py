"""Offline smoke test: run the demo market to a given minute and print the board."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import Config  # noqa: E402
from demo_feed import DemoFeed  # noqa: E402
from engine import Engine  # noqa: E402
from store import Store  # noqa: E402

minute = int(sys.argv[1]) if len(sys.argv) > 1 else 150
st = Store()
f = DemoFeed(st, Config())
f._init_symbols()
for m in range(minute):
    f._advance(m)
f.minute = minute
e = Engine(st)
t = time.time()
b = e.compute()
print("compute s", round(time.time() - t, 3))
print("counts", b["counts"], "phase", b["status"]["phase"])
print("bull", b["boards"]["bull"])
print("bear", b["boards"]["bear"])
print("picks", b["picks"])
s0 = b["boards"]["bull"][0]
print("setup", json.dumps(b["details"][s0]["setup"]))
print([(x["s"], x["rule"], x["bu"], x["cv"], x["p"]) for x in b["stocks"][:5]])
print("lead", b["lead"]["name"], b["lead"]["chg"], "lag", b["lag"]["name"], b["lag"]["chg"])
print("board KB", len(json.dumps(b, default=str)) // 1024, "history KB", len(json.dumps(e.history)) // 1024)
c = e.chart(s0)
print("chart obs", len(c["obs"]), "candles", len(c["candles"]))
print("no setup", [s for s in b["boards"]["bull"] + b["boards"]["bear"] if b["details"][s]["setup"] is None])
