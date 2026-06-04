"""app.core.logging 单测。覆盖:环境分支 / processor 链 / 异常 / contextvars / 幂等性。"""
from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any

import pytest
import structlog

from app.core import logging as app_logging
from app.core.logging import configure_logging


@pytest.fixture
def fake_settings(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """给 logging 模块注入 SimpleNamespace 假 settings,避免依赖 .env。

    _add_app_metadata / configure_logging 都是调用时才去模块全局找 `settings`,
    所以 monkeypatch.setattr(app_logging, "settings", ...) 能被它们看到。
    """
    settings = SimpleNamespace(
        app_name="test-app",
        environment="dev",
        log_level="INFO",
    )
    monkeypatch.setattr(app_logging, "settings", settings)
    return settings


@pytest.fixture(autouse=True)
def reset_structlog() -> None:
    """每个测试前重置 structlog 配置 + logger 缓存,清掉上轮残留的 contextvars。

    cache_logger_on_first_use=True 会把 BoundLogger 缓存在 proxy 上,
    只有 reset_defaults 才能让下一次 get_logger 拿到新 config。
    """
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()


def _parse_json_from(out: str) -> dict[str, Any]:
    """从 capsys 捕获的 stdout 文本里挑最后一行合法 JSON(JSONRenderer 产出的那一行)。"""
    lines = [ln for ln in out.splitlines() if ln.lstrip().startswith("{")]
    assert lines, f"no JSON line found in captured stdout: {out!r}"
    return json.loads(lines[-1])


# ---------- 基础契约 ----------

def test_configure_logging_does_not_raise(fake_settings: Any) -> None:
    """configure_logging() 不抛异常是最基本的契约。"""
    configure_logging()


def test_configure_logging_is_idempotent(fake_settings: Any) -> None:
    """多次调用不应报错(basicConfig + structlog.configure 都要扛得住)。"""
    configure_logging()
    configure_logging()
    configure_logging()


def test_stdlib_logging_level_applied(fake_settings: Any) -> None:
    """log_level=WARNING 时,stdlib root logger 级别必须同步到 WARNING(兜底链路)。"""
    fake_settings.log_level = "WARNING"
    configure_logging()
    assert logging.getLogger().level == logging.WARNING


# ---------- 渲染分支 ----------

def test_dev_renders_colorful_console(
    fake_settings: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """dev 环境走 ConsoleRenderer,输出彩色文本(非 JSON,供人读)。"""
    fake_settings.environment = "dev"
    configure_logging()
    structlog.get_logger("t").info("hello", x=1)
    out = capsys.readouterr().out
    assert "hello" in out
    assert "1" in out
    # dev 不应有以 { 开头的 JSON 行
    assert not [ln for ln in out.splitlines() if ln.lstrip().startswith("{")]


def test_prod_renders_json(
    fake_settings: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """prod 环境输出必须是合法 JSON,可被 json.loads 解析。"""
    fake_settings.environment = "prod"
    configure_logging()
    structlog.get_logger("t").info("user_login", user="alice")
    record = _parse_json_from(capsys.readouterr().out)
    assert record["event"] == "user_login"
    assert record["user"] == "alice"


# ---------- processor 链各处理器职责 ----------

def test_processor_chain_injects_app_and_env(
    fake_settings: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """_add_app_metadata 必须注入 app / env,值与 settings 一致(便于按服务聚合日志)。"""
    fake_settings.environment = "prod"
    fake_settings.app_name = "my-svc"
    configure_logging()
    structlog.get_logger("t").info("evt")
    record = _parse_json_from(capsys.readouterr().out)
    assert record["app"] == "my-svc"
    assert record["env"] == "prod"


def test_processor_chain_injects_log_level(
    fake_settings: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """add_log_level 必须注入 level 字段(日志系统按 level 建索引的关键)。"""
    fake_settings.environment = "prod"
    configure_logging()
    structlog.get_logger("t").warning("evt")
    record = _parse_json_from(capsys.readouterr().out)
    assert record["level"] == "warning"


def test_processor_chain_injects_logger_name(
    fake_settings: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """CallsiteParameter.MODULE 把调用方文件 basename 注入到 event_dict["module"](排错定位)。

    注意:此字段值是 *调用方文件 basename*,不是 get_logger("...") 传入的字符串。
    我们的测试函数位于 tests/core/test_logging.py → basename 去后缀 = "test_logging"。
    """
    fake_settings.environment = "prod"
    configure_logging()
    structlog.get_logger("app.api.task").info("evt")
    record = _parse_json_from(capsys.readouterr().out)
    assert record["module"] == "test_logging"


def test_processor_chain_injects_utc_timestamp(
    fake_settings: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """TimeStamper utc=True → timestamp 以 Z 结尾,符合 ISO 8601(日志系统一律 UTC)。"""
    fake_settings.environment = "prod"
    configure_logging()
    structlog.get_logger("t").info("evt")
    record = _parse_json_from(capsys.readouterr().out)
    ts = record["timestamp"]
    assert ts.endswith("Z"), f"timestamp not UTC: {ts}"
    assert "T" in ts, f"timestamp not ISO: {ts}"


# ---------- 异常 + contextvars ----------

def test_exception_renders_traceback_in_field(
    fake_settings: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """log.exception 把 traceback 字符串塞进 exception 字段(而不是打到 stderr)。"""
    fake_settings.environment = "prod"
    configure_logging()
    try:
        raise ValueError("boom")
    except ValueError:
        structlog.get_logger("t").exception("failed")
    record = _parse_json_from(capsys.readouterr().out)
    assert record["event"] == "failed"
    assert "ValueError: boom" in record["exception"]
    assert "Traceback" in record["exception"]


def test_contextvars_auto_merged(
    fake_settings: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """bind_contextvars 后,后续所有日志自动带 request_id(无需手动传,跨 asyncio 任务传播)。"""
    fake_settings.environment = "prod"
    configure_logging()
    structlog.contextvars.bind_contextvars(request_id="req-123")
    structlog.get_logger("t").info("evt")
    record = _parse_json_from(capsys.readouterr().out)
    assert record["request_id"] == "req-123"
