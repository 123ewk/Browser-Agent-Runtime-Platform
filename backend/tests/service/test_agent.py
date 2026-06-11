"""AgentService 健康状态计算 —— 纯函数,表驱动测试"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.schema.agent import AgentMetrics
from app.service.agent import AgentHealth, _compute_health, _compute_success_rate


def _stub_settings(**overrides):
    """构造 Settings stub,只带健康阈值字段"""
    from app.core.config import Settings

    kwargs = {
        "agent_health_degraded_failure_rate": 0.10,
        "agent_health_down_failure_rate": 0.50,
        "agent_health_inactive_days": 7,
    }
    kwargs.update(overrides)
    return Settings(**kwargs)


now = datetime.now(UTC)


# ── _compute_health 表驱动(7 场景) ──


@pytest.mark.parametrize(
    "metrics,last_task_at,expected",
    [
        # 1. 新 agent 无任务 → healthy(规则 1 early return)
        (AgentMetrics(0, 0, 0, 0), None, AgentHealth.HEALTHY),
        # 2. 1h 全成功 → healthy(规则 3c)
        (
            AgentMetrics(3, 3, 3, 3),
            now - timedelta(minutes=10),
            AgentHealth.HEALTHY,
        ),
        # 3. 1h 内有少量失败(33% < down 阈值 50%)→ degraded(规则 3b)
        (
            AgentMetrics(5, 6, 2, 3),
            now - timedelta(minutes=10),
            AgentHealth.DEGRADED,
        ),
        # 4. 1h 内无任务,24h 全成功,last_task_at 在 2h 前 → healthy(规则 4b)
        (
            AgentMetrics(3, 3, 0, 0),
            now - timedelta(hours=2),
            AgentHealth.HEALTHY,
        ),
        # 5. 1h 内无任务,24h 失败率 33%(≥10%) → degraded(规则 4a)
        (
            AgentMetrics(2, 3, 0, 0),
            now - timedelta(hours=2),
            AgentHealth.DEGRADED,
        ),
        # 6. 1h 全失败 → down(规则 3a)
        (
            AgentMetrics(3, 6, 0, 3),
            now - timedelta(minutes=10),
            AgentHealth.DOWN,
        ),
        # 7. 超过 inactive_days 无任务 → down(规则 2)
        (
            AgentMetrics(1, 1, 0, 0),
            now - timedelta(days=8),
            AgentHealth.DOWN,
        ),
    ],
)
def test_compute_health(metrics, last_task_at, expected):
    assert _compute_health(metrics, last_task_at, _stub_settings()) == expected


def test_compute_health_inactive_days_boundary():
    """刚好在 inactive_days 边界内 → 不触发 down"""
    last_task_at = now - timedelta(days=6, hours=23)
    # 1h 内有少量失败 → degraded(规则 3b 触发)
    metrics = AgentMetrics(2, 3, 2, 3)
    assert _compute_health(metrics, last_task_at, _stub_settings()) == AgentHealth.DEGRADED


def test_compute_health_custom_thresholds():
    """自定义阈值: down_failure_rate=0.20 → 33% 失败触发 down 而非 degraded"""
    cfg = _stub_settings(agent_health_down_failure_rate=0.20)
    metrics = AgentMetrics(5, 6, 2, 3)
    last_task_at = now - timedelta(minutes=10)
    assert _compute_health(metrics, last_task_at, cfg) == AgentHealth.DOWN


# ── _compute_success_rate ──


def test_success_rate_no_terminal_tasks():
    """无终态任务 → 返回 0.0"""
    assert _compute_success_rate(AgentMetrics(0, 0, 0, 0)) == 0.0


def test_success_rate_all_success():
    """全部成功 → 1.0"""
    assert _compute_success_rate(AgentMetrics(5, 5, 0, 0)) == 1.0


def test_success_rate_mixed():
    """混合结果 → 3/5 = 0.6"""
    result = _compute_success_rate(AgentMetrics(3, 5, 0, 0))
    assert result == 0.6


def test_success_rate_1h_ignored():
    """1h 字段不影响 successRate(只用 24h)"""
    # 1h 全失败但 24h 全成功 → 1.0
    result = _compute_success_rate(AgentMetrics(5, 5, 0, 3))
    assert result == 1.0
