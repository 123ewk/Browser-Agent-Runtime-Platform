"""app/core/logging.py 的 API 形状"""

from app.core.config import Settings
import structlog


def configure_logging(settings: Settings) -> None:
    """lifespan 启动时调一次。配置 processor 链 + stdlib 转发。"""
    ...


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """主入口。所有业务代码从这里取 logger,不要用 logging.getLogger。"""
    ...
