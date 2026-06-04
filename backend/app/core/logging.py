"""
============================================================
为什么选 structlog 而不是其它 logging 库
============================================================

候选对比:

1) stdlib logging (Python 内置)
   优:零依赖、Python 自带
   缺:JSON 需手写 Formatter;无 processor 链;contextvars 支持弱,
      async 场景下 request_id 难传递;接 uvicorn/sqlalchemy 需胶水

2) loguru
   优:API 简洁、装饰器友好、彩色输出开箱即用
   缺:与 stdlib logging 整合差(接管三方库日志麻烦);
      JSON 需手写 serialize;context 传递不如 structlog 优雅

3) python-json-logger
   优:给 stdlib 加 JSON 输出能力
   缺:只能依附 stdlib,无 processor 链;字段注入靠 extra={} 拼接

4) structlog (本项目选用) ✓
   - 结构化日志(JSON / key-value),Loki/ELK 友好消费
   - Processor 链:像中间件可组合,字段注入/格式化/异常渲染
     全交给 processor,业务侧只关心"打日志"
   - contextvars 原生支持:跨 asyncio 任务自动传 request_id,
     无需显式透参
   - 与 stdlib logging 完全兼容:通过 formatter 桥接,
     一并接管 uvicorn / sqlalchemy / alembic 日志
   - 性能优:cache_logger_on_first_use=True 后首次缓存 logger
   - dev / prod 一套代码:renderer 切换即可(dev 彩色,prod JSON)

结论:本项目作为 Browser Agent Runtime Platform,需
- 跨异步任务追踪(agent task / browser task)
- 多来源日志(uvicorn + sqlalchemy + 业务)统一格式
- 接入日志系统做检索/告警
structlog 在这三项上综合最优。

应用启动期由 main.py 调用 configure_logging()。
"""
from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor

from app.core.config import settings


def _add_app_metadata(_: Any, __: str, event_dict: EventDict) -> EventDict:
    """每条日志自动带 app / env,避免业务层重复打。Processor 三参签名固定。"""
    event_dict["app"] = settings.app_name # 应用名称,默认 browser-agent-runtime
    event_dict["env"] = settings.environment # 环境,默认 dev
    return event_dict


def _shared_processors() -> list[Processor]:
    """
    dev / prod 共用的 processor 链(渲染器之前的部分),保证两环境字段一致。
    ## 顺序为什么不能乱
    processor 链是 单向、不可逆 的,不能乱序。
    """
    return [
        structlog.contextvars.merge_contextvars,            # 合并 contextvars,跨 asyncio 任务传 request_id,把当前协程的 ContextVar(如 request_id)合并进事件
        structlog.processors.add_log_level,                 # 加 level 字段
        # CallsiteParameterAdder 用 sys._getframe() 拿调用方文件 basename,注入到 event_dict["module"]。
        # 注意:25+ API 是传一个参数列表,不是 *args。structlog 25+ 的标准做法,比自己解析 _name 稳。
        structlog.processors.CallsiteParameterAdder(
            [structlog.processors.CallsiteParameter.MODULE],
        ),
        structlog.processors.TimeStamper(fmt="iso", utc=True),  # UTC ISO8601,展示层再转本地,加 UTC ISO8601 时间戳
        _add_app_metadata,                                  # 加 app / env 固定元信息
        structlog.processors.StackInfoRenderer(),           # stack_info=True 时打印调用栈,只有 log.info(..., stack_info=True) 时才打印调用栈,平时不生效
        structlog.processors.format_exc_info,               # 只有 log.exception(...) 才把异常转成多行 traceback(回溯) 塞进 exception(异常) 字段
    ]


def configure_logging() -> None:
    """初始化全局日志。幂等:重复调用以最后一次配置为准。"""
    level = getattr(logging, settings.log_level) # getattr() 获取日志级别,如 logging.INFO
    is_dev = settings.environment == "dev"

    # 1) stdlib logging 兜底:把 uvicorn / sqlalchemy / alembic 的日志也并入同一管道
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level, force=True) # force=True 确保配置生效

    # 2) 选择渲染器:dev 彩色可读,prod JSON 给日志系统(Loki/ELK)消费
    renderer: Processor = (
        structlog.dev.ConsoleRenderer(colors=is_dev) # dev 彩色可读
        if is_dev 
        else structlog.processors.JSONRenderer() # prod JSON 给日志系统(Loki/ELK)消费
    )

    structlog.configure(
        processors=[*_shared_processors(), renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level), # 过滤日志级别,只打印 >= level 的日志
        context_class=dict, # 上下文类,默认 dict
        logger_factory=structlog.PrintLoggerFactory(), # 打印日志工厂,默认 console
        cache_logger_on_first_use=True,  # 性能:首次后不再走 wrapper_class 解析,直接返回缓存的日志器,避免重复解析
    )
