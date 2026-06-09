"""Agent 列表 API —— V1 最小可用版本

端点:
  GET /agents  — 返回当前可用的 Agent 列表

V1: 返回静态单 agent(多 Agent 功能未实现)
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("")
async def list_agents() -> list[dict]:
    """列出当前可用的 Agent

    V1: 返回单个静态 Browser Agent。
    V2: 从 DB/Redis 动态发现 Agent 实例。
    """
    return [
        {
            "id": "browser-agent-01",
            "name": "Browser Agent",
            "description": "通用浏览器自动化 Agent",
            "health": "healthy",
            "lastTaskAt": None,
            "successRate24h": 0.95,
        }
    ]
