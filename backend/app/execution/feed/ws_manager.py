"""WebSocket connection manager — broadcasts market data to all clients."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WSManager:
    """Manages active WebSocket connections and broadcasts messages."""

    def __init__(self):
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.append(ws)
        logger.info("ws client connected, total=%d", len(self._connections))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            if ws in self._connections:
                self._connections.remove(ws)
        logger.info("ws client disconnected, total=%d", len(self._connections))

    async def broadcast(self, data: dict[str, Any]) -> None:
        """Send JSON message to all connected clients."""
        if not self._connections:
            return

        msg = json.dumps(data)
        dead: list[WebSocket] = []

        async with self._lock:
            for ws in self._connections:
                try:
                    await ws.send_text(msg)
                except Exception:
                    dead.append(ws)

            for ws in dead:
                self._connections.remove(ws)

    async def broadcast_text(self, text: str) -> None:
        """Send raw text to all connected clients."""
        if not self._connections:
            return

        dead: list[WebSocket] = []
        async with self._lock:
            for ws in self._connections:
                try:
                    await ws.send_text(text)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._connections.remove(ws)

    @property
    def connection_count(self) -> int:
        return len(self._connections)


ws_manager = WSManager()
