import json
from typing import Dict, Set
from fastapi import WebSocket

class GameHub:
    def __init__(self):
        self.host_sockets: Dict[str, Set[WebSocket]] = {}
        self.player_sockets: Dict[str, Set[WebSocket]] = {}

    async def connect_host(self, code: str, ws: WebSocket):
        await ws.accept()
        self.host_sockets.setdefault(code, set()).add(ws)

    async def connect_player(self, code: str, ws: WebSocket):
        await ws.accept()
        self.player_sockets.setdefault(code, set()).add(ws)

    def _drop(self, d: Dict[str, Set[WebSocket]], code: str, ws: WebSocket):
        s = d.get(code)
        if not s:
            return
        if ws in s:
            s.remove(ws)
        if not s:
            d.pop(code, None)

    async def disconnect_host(self, code: str, ws: WebSocket):
        self._drop(self.host_sockets, code, ws)

    async def disconnect_player(self, code: str, ws: WebSocket):
        self._drop(self.player_sockets, code, ws)

    async def broadcast_host(self, code: str, payload: dict):
        msg = json.dumps(payload)
        for ws in list(self.host_sockets.get(code, set())):
            try:
                await ws.send_text(msg)
            except Exception:
                self._drop(self.host_sockets, code, ws)

    async def broadcast_players(self, code: str, payload: dict):
        msg = json.dumps(payload)
        for ws in list(self.player_sockets.get(code, set())):
            try:
                await ws.send_text(msg)
            except Exception:
                self._drop(self.player_sockets, code, ws)

hub = GameHub()
