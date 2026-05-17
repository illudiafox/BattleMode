"""Lightweight HTTP control server for Stream Deck / remote integration.

All force/skip/pause callbacks are invoked from the server thread.
Callers should route them back to the main thread via Qt signals.

Example Stream Deck command:
    curl -X POST http://localhost:9847/state/battle
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional

from battlemode.profiles.models import GameState

_STATE_MAP: dict[str, GameState] = {
    "menu":      GameState.MENU,
    "selection": GameState.SELECTION,
    "battle":    GameState.BATTLE,
    "win":       GameState.WIN,
    "loss":      GameState.LOSS,
}


class ControlServer:
    """
    Endpoints
    ---------
    GET  /state                          → {"state": "battle"}
    POST /state/<name>                   → force game state
    POST /skip                           → skip current track
    POST /pause                          → pause / resume
    """

    def __init__(
        self,
        host: str,
        port: int,
        force_state_cb: Callable[[GameState], None],
        get_state_cb: Callable[[], str],
        skip_cb: Callable[[], None],
        pause_cb: Callable[[], None],
    ) -> None:
        self._host = host
        self._port = port
        self._force_state_cb = force_state_cb
        self._get_state_cb = get_state_cb
        self._skip_cb = skip_cb
        self._pause_cb = pause_cb
        self._server: Optional[ThreadingHTTPServer] = None

    # ------------------------------------------------------------------ #

    def start(self) -> None:
        force = self._force_state_cb
        get_state = self._get_state_cb
        skip = self._skip_cb
        pause = self._pause_cb

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:
                pass  # silence console output

            def do_GET(self):
                if self.path == "/state":
                    self._json(200, {"state": get_state()})
                else:
                    self._json(404, {"error": "not found"})

            def do_POST(self):
                if self.path.startswith("/state/"):
                    name = self.path[7:]
                    state = _STATE_MAP.get(name)
                    if state:
                        force(state)
                        self._json(200, {"ok": True, "state": name})
                    else:
                        self._json(400, {"error": f"unknown state '{name}'"})
                elif self.path == "/skip":
                    skip()
                    self._json(200, {"ok": True})
                elif self.path == "/pause":
                    pause()
                    self._json(200, {"ok": True})
                else:
                    self._json(404, {"error": "not found"})

            def _json(self, code: int, data: dict) -> None:
                body = json.dumps(data).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self._server = ThreadingHTTPServer((self._host, self._port), _Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server = None

    @property
    def is_running(self) -> bool:
        return self._server is not None
