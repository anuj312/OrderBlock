"""X-Ray terminal server.

    python server.py            # uses MARKET_MODE from .env (demo | kite)

Binds to 127.0.0.1 by default. There is no login: do not expose it publicly.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from config import ROOT, Config, redact
from engine import Engine, Rules
from sectors import ALL_SYMBOLS
from store import Store

log = logging.getLogger("xray")
STATIC = ROOT / "static"


class App:
    def __init__(self, cfg: Config, start_feed: bool = True):
        self.cfg = cfg
        self.store = Store()
        self.engine = Engine(self.store, Rules(board_size=cfg.board_size, picks=cfg.picks,
                                               sector_cap=cfg.sector_cap))
        self._board = b"{}"
        self._history = b"{}"
        self._stop = threading.Event()
        if start_feed:
            self.feed = self._make_feed()

    def _make_feed(self):
        if self.cfg.mode == "kite":
            from kite_feed import KiteFeed
            return KiteFeed(self.store, self.cfg)
        from demo_feed import DemoFeed
        return DemoFeed(self.store, self.cfg)

    def publish_once(self) -> None:
        board = self.engine.compute()
        self._board = json.dumps(board, separators=(",", ":"), default=str).encode()
        self._history = json.dumps(self.engine.history, separators=(",", ":")).encode()

    def _loop(self) -> None:
        while not self._stop.is_set():
            t = time.monotonic()
            try:
                self.publish_once()
            except Exception as e:  # keep serving the last good board
                log.exception("engine pass failed: %s", redact(str(e), self.cfg))
            self._stop.wait(max(0.2, self.cfg.publish_seconds - (time.monotonic() - t)))

    def start(self) -> None:
        self.feed.start()
        threading.Thread(target=self._loop, name="engine", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()


def create_app(cfg: Config | None = None, start_feed: bool = True) -> FastAPI:
    cfg = cfg or Config()
    core = App(cfg, start_feed=start_feed)

    @asynccontextmanager
    async def lifespan(_app):
        if start_feed:
            core.start()
        yield
        core.stop()

    api = FastAPI(title="Order X-Ray", lifespan=lifespan, docs_url=None, redoc_url=None)
    api.state.core = core
    # Compress JSON, HTML, JS and CSS for clients that send Accept-Encoding: gzip (all browsers).
    # Board JSON (~110 KB every 2 s) shrinks to roughly a fifth. Tiny responses are left as is.
    api.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)
    no_store = {"Cache-Control": "no-store"}

    @api.get("/")
    def index():
        return FileResponse(STATIC / "index.html", headers=no_store)

    @api.get("/api/board")
    def board():
        return Response(core._board, media_type="application/json", headers=no_store)

    @api.get("/api/history")
    def history():
        return Response(core._history, media_type="application/json", headers=no_store)

    @api.get("/api/chart/{symbol}")
    def chart(symbol: str):
        if symbol not in ALL_SYMBOLS:
            raise HTTPException(404, "unknown symbol")
        data = core.engine.chart(symbol)
        if data is None:
            raise HTTPException(404, "no data yet")
        return Response(json.dumps(data, separators=(",", ":"), default=str), media_type="application/json",
                        headers=no_store)

    api.mount("/static", StaticFiles(directory=STATIC), name="static")
    return api


if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    c = Config()
    print(f"Order X-Ray ({c.mode}) on http://{c.host}:{c.port}")
    uvicorn.run(create_app(c), host=c.host, port=c.port, log_level="warning")
