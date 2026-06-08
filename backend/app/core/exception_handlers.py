"""
============================================================
全局异常处理 —— 业务错误透传 / 基础设施错误 503 / 兜底 500
============================================================

按异常类型派发,而不是按响应体字符串匹配。
分四类:

1) 业务逻辑(透传):HTTPException —— 409 用户名冲突、401 凭证错、403 越权等
2) 请求体(透传):RequestValidationError —— Pydantic 校验失败,FastAPI 默认 422
3) 基础设施(降级为 503):DB / Cache / Storage / LLM 不可达 —— 客户端可重试
4) 兜底(降级为 500):未分类异常 —— 一定是 bug,记 ERROR 日志含全栈

不放在 api/ 也不放在 infra/:
- api/ 是路由,本模块不写路由
- infra/ 是数据访问,本模块不读写 DB
- core/ 是配置/日志/中间件 —— 本模块属于"中间件级别的横切关注点"
============================================================
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, OperationalError, SQLAlchemyError

log = structlog.get_logger(__name__)

# 统一响应体 schema —— 前端可以靠 error_type 字段做差异化处理(如 "database_unavailable" 触发重试)
_INFRA_RESPONSE: dict[str, Any] = {
    "detail": "Service temporarily unavailable, please retry.",
    "error_type": "service_unavailable",
}


def _classify_db_error(exc: SQLAlchemyError) -> str:
    """数据库错误的细粒度分类 —— error_type 决定客户端行为。

    OperationalError:连接级问题(连不上、超时)—— 通常是基础设施瞬时故障
    DBAPIError 的其他子类:协议/认证/约束错 —— 可能是配置问题但也归为 503
    其他 SQLAlchemyError:兜底为 database_error
    """
    if isinstance(exc, OperationalError):
        return "database_unavailable"
    if isinstance(exc, DBAPIError):
        return "database_error"
    return "database_error"


async def _infra_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """基础设施层异常的通用处理 —— 全部降级为 503。

    SQLAlchemyError 是基类,涵盖 OperationalError / DBAPIError / IntegrityError 等。
    业务代码不应该从 repository 层捕获这些后再重抛业务异常(那会丢上下文),
    所以在边界统一映射。

    日志级别 WARNING 而非 ERROR:503 是预期路径(基础设施瞬时故障),
    不应该触发告警阈值。ERROR 留给"真出 bug"的 500。
    """
    if isinstance(exc, SQLAlchemyError):
        error_type = _classify_db_error(exc)
    else:
        # 留扩展位:未来加 redis/s3/llm 分类时,在 if 链加分支
        error_type = _INFRA_RESPONSE["error_type"]

    log.warning(
        "infra.exception",
        error_type=error_type,
        exc_type=type(exc).__name__,
        exc_msg=str(exc)[:200],  # 截断避免长 message 撑爆日志
        path=request.url.path,
        method=request.method,
    )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={**_INFRA_RESPONSE, "error_type": error_type},
    )


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """兜底 handler —— 捕获所有未被其他 handler 接管的异常,返回 500。

    这里一定是 bug:业务代码应该用 HTTPException 表达预期错误,
    走到这里意味着漏处理。日志级别 ERROR 含全栈,便于 on-call 定位。
    返回体不暴露 exc.detail / exc.args —— 防止敏感信息泄露(密码、内部路径)。
    """
    log.error(
        "unhandled.exception",
        exc_type=type(exc).__name__,
        exc_msg=str(exc)[:200],
        path=request.url.path,
        method=request.method,
        exc_info=True,  # 触发 structlog 的 format_exc_info processor,塞完整 traceback
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal server error.",
            "error_type": "internal_error",
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """在 FastAPI app 上注册全部 handler —— 由 main.py 在启动时调一次。

    注册顺序与不注册项:
    1) SQLAlchemyError(具体类型)→ _infra_exception_handler —— 必须早于 Exception
    2) Exception(兜底)→ _unhandled_exception_handler —— 最后兜底

    不注册 HTTPException / RequestValidationError / StarletteHTTPException:
    FastAPI 自带 handler 行为正确(HTTPException 透传 status_code + detail,
    RequestValidationError 返回 422),接管反而把 409/401 变成 503。
    """
    app.add_exception_handler(SQLAlchemyError, _infra_exception_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)
