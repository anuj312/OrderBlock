import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from config import Config  # noqa: E402
from demo_feed import DemoFeed  # noqa: E402
from server import create_app  # noqa: E402


def make_client():
    app = create_app(Config(), start_feed=False)
    core = app.state.core
    feed = DemoFeed(core.store, core.cfg)
    feed._init_symbols()
    for m in range(120):
        feed._advance(m)
    feed.minute = 120
    core.publish_once()
    return TestClient(app), core


def test_board_has_top10_and_3_picks_per_side():
    client, core = make_client()
    b = client.get("/api/board").json()
    assert b["rules"] == {"board": 10, "picks": 3, "cap": 2}
    for side in ("bull", "bear"):
        assert len(b["boards"][side]) == 10
        assert len(b["picks"][side]) <= 3
        assert set(b["picks"][side]) <= set(b["boards"][side])
        secs = [next(x["sec"] for x in b["stocks"] if x["s"] == s) for s in b["picks"][side]]
        assert max(secs.count(s) for s in secs) <= 2
    assert b["counts"]["bull"] + b["counts"]["bear"] == b["counts"]["n"]


def test_chart_and_unknown_symbol():
    client, core = make_client()
    sym = core.engine.board["boards"]["bull"][0]
    c = client.get(f"/api/chart/{sym}").json()
    assert c["candles"] and c["stock"]["s"] == sym
    assert client.get("/api/chart/M%26M").status_code == 200
    assert client.get("/api/chart/NOT_A_STOCK").status_code == 404


def test_no_credentials_in_responses(monkeypatch):
    client, core = make_client()
    body = client.get("/api/board").text
    for secret in (core.cfg.api_key, core.cfg.access_token):
        if secret:
            assert secret not in body
