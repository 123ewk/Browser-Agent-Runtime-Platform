"""WebSocketManager —— EventBus → 前端实时推送

设计要点:
- 订阅 EventBus 的 "ALL" 事件,接收所有 Runtime 事件
- 维护 WebSocket 连接池,按 task_id 路由事件到对应客户端
- 客户端连接时声明监听的 task_id(通过 WebSocket 子协议或首个消息)
- 客户端断开时自动清理,不阻塞 EventBus
"""

from __future__ import annotations

from collections import defaultdict

import structlog
from fastapi import WebSocket

from app.runtime.event_bus import EventBus
from app.runtime.protocol.schemas import RuntimeEvent

logger = structlog.get_logger(__name__)


class WebSocketManager:
    """管理前端 WebSocket 连接,将 EventBus 事件推送给前端

    用法:
        ws_mgr = WebSocketManager(event_bus)
        # 在 FastAPI WebSocket 路由中:
        await ws_mgr.connect(websocket, task_id="task-001")
    """

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        # task_id → list[WebSocket]
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)
        # 全局监听(不筛选 task_id)
        self._global_connections: list[WebSocket] = []

        # 订阅所有事件
        event_bus.subscribe("ALL", self._on_event)

    async def connect(
        self,
        websocket: WebSocket,
        task_id: str | None = None,
    ) -> None:
        """接受 WebSocket 连接

        Args:
            websocket: FastAPI WebSocket 对象
            task_id: 客户端想监听的任务 ID(None=监听所有)
        """
        await websocket.accept()

        if task_id:
            self._connections[task_id].append(websocket)
        else:
            self._global_connections.append(websocket)

        logger.info(
            "ws.client_connected",
            task_id=task_id or "global",
            total_connections=self.connection_count(),
        )

    def disconnect(self, websocket: WebSocket, task_id: str | None = None) -> None:
        """移除 WebSocket 连接"""
        if task_id:
            conns = self._connections.get(task_id, [])
            if websocket in conns:
                conns.remove(websocket)
        else:
            if websocket in self._global_connections:
                self._global_connections.remove(websocket)

        logger.info(
            "ws.client_disconnected",
            task_id=task_id or "global",
            total_connections=self.connection_count(),
        )

        # 清理空列表
        if task_id and task_id in self._connections and not self._connections[task_id]:
            del self._connections[task_id]

    def connection_count(self) -> int:
        """当前连接总数"""
        total = len(self._global_connections)
        for conns in self._connections.values():
            total += len(conns)
        return total

    async def _on_event(self, event: RuntimeEvent) -> None:
        """EventBus handler:将事件推送给相关客户端

        - 按 task_id 路由到订阅了该任务的客户端
        - 同时推送给全局监听客户端
        """
        payload = event.model_dump_json()

        # 推送给订阅了特定 task_id 的客户端
        if event.task_id in self._connections:
            await self._broadcast(
                self._connections[event.task_id],
                payload,
                event.task_id,
            )

        # 推送给全局监听客户端
        if self._global_connections:
            await self._broadcast(
                self._global_connections,
                payload,
                event.task_id,
            )

    async def _broadcast(
        self,
        connections: list[WebSocket],
        payload: str,
        task_id: str,
    ) -> None:
        """向一组连接广播事件,单个失败不影响其他"""
        stale: list[WebSocket] = []

        # list() 快照避免并发修改:EventBus.publish 用 asyncio.gather
        # 时两个 _on_event 可能交错修改同一 connections 列表
        for ws in list(connections):
            try:
                await ws.send_text(payload)
            except Exception:
                logger.debug("ws.send_failed", task_id=task_id)
                stale.append(ws)

        # 清理已断开的连接
        for ws in stale:
            if ws in connections:
                connections.remove(ws)
