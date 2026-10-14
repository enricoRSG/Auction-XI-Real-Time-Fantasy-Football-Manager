from __future__ import annotations

from collections import defaultdict
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self._connections: dict[int, list[WebSocket]] = defaultdict(list)

    async def connect(self, auction_id: int, websocket: WebSocket):
        await websocket.accept()
        self._connections[auction_id].append(websocket)

    def disconnect(self, auction_id: int, websocket: WebSocket):
        if websocket in self._connections.get(auction_id, []):
            self._connections[auction_id].remove(websocket)

    async def broadcast(self, auction_id: int, payload: dict):
        stale = []
        for ws in list(self._connections.get(auction_id, [])):
            try:
                await ws.send_json(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(auction_id, ws)


manager = ConnectionManager()
