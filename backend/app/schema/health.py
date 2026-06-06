"""健康检查 DTO —— 拆出 main.py 到独立 schema 文件,避免 bootstrap 文件膨胀。"""

from __future__ import annotations

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """存活探针响应 —— 表示 FastAPI 进程存活。"""

    status: str = "ok"


class ReadyResponse(BaseModel):
    """就绪探针响应 —— 每个依赖并行探测。"""

    status: str
    deps: dict[str, str]
