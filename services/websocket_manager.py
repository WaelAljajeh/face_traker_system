import asyncio
import json
import logging
from typing import Set
from fastapi import WebSocket
from datetime import datetime

logger = logging.getLogger(__name__)


class WebSocketManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self.active_connections.add(websocket)
        logger.info(f"[WS] Client connected. Total: {len(self.active_connections)}")

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            self.active_connections.discard(websocket)
        logger.info(f"[WS] Client disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        dead = set()
        async with self._lock:
            for ws in self.active_connections:
                try:
                    await ws.send_json(message)
                except Exception:
                    dead.add(ws)
            self.active_connections -= dead
        if dead:
            logger.info(f"[WS] Removed {len(dead)} dead connections. Total: {len(self.active_connections)}")

    async def broadcast_scan(self, scan_data: dict):
        await self.broadcast({
            "type": "scan",
            "event": scan_data,
            "timestamp": datetime.utcnow().isoformat(),
        })

    async def broadcast_ack(self, scan_id: str):
        await self.broadcast({
            "type": "ack",
            "scan_id": scan_id,
            "timestamp": datetime.utcnow().isoformat(),
        })

    async def broadcast_mode_change(self, mode: str):
        await self.broadcast({
            "type": "mode_change",
            "mode": mode,
            "timestamp": datetime.utcnow().isoformat(),
        })