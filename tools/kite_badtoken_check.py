"""Dev check: a bad Kite token must surface as a clear status error with no secret leaked."""
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import Config  # noqa: E402
from kite_feed import KiteFeed  # noqa: E402
from store import Store  # noqa: E402

cfg = replace(Config(), mode="kite", api_key="dummykey123", access_token="dummytoken456")
st = Store()
KiteFeed(st, cfg).start()
for _ in range(30):
    time.sleep(1)
    s = st.get_status()
    if s["error"]:
        break
s = st.get_status()
print("message:", s["message"])
print("error:", s["error"])
print("leak:", "dummytoken456" in str(s) or "dummykey123" in str(s))
