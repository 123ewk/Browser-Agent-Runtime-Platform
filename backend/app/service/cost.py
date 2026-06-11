"""LLM 成本计算 —— 纯函数, 从 YAML 定价表读取, 支持 mtime 热重载。

设计原则:
- 定价表外置 YAML, 模型调价不需要重新部署 Runtime
- mtime 自动检测: 文件变更后下一次 LLM 调用自动重载
- 未知模型 / 缺失文件 → 返回 0.0, 不抛异常, 不阻断任务
"""

from __future__ import annotations

import os
from pathlib import Path

import structlog
import yaml

logger = structlog.get_logger(__name__)

# 定价表路径 —— 通过环境变量覆盖, 默认相对于 backend/ 运行目录
_PRICING_PATH = Path(os.getenv("LLM_PRICING_PATH", "app/core/llm_pricing.yaml"))

# 进程级缓存: mtime + 解析结果
_pricing_cache: dict[str, tuple[float, float]] = {}
_pricing_mtime: float = 0.0


def _resolve_path() -> Path:
    """解析定价表路径 —— 支持相对路径 (相对于 backend/)"""
    if _PRICING_PATH.is_absolute():
        return _PRICING_PATH
    # 从 cwd 往上找直到找到文件
    resolved = Path.cwd() / _PRICING_PATH
    if resolved.exists():
        return resolved
    # fallback: 相对于本文件所在目录
    return Path(__file__).resolve().parent.parent / "core" / "llm_pricing.yaml"


def _load_pricing(force: bool = False) -> dict[str, tuple[float, float]]:
    """读定价表, YAML 文件 mtime 变化时自动重载 (实现热更新)

    性能: 每次 calculate_cost() 调用前检查 mtime, O(1) stat 调用,
    只有 mtime 变化才重新解析 YAML (几十 KB, 毫秒级)。
    """
    global _pricing_cache, _pricing_mtime

    path = _resolve_path()

    if not path.exists():
        logger.warning("cost.pricing_file_missing", path=str(path))
        return {}

    current_mtime = path.stat().st_mtime
    if not force and current_mtime == _pricing_mtime and _pricing_cache:
        return _pricing_cache

    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except Exception:
        logger.warning("cost.pricing_parse_failed", path=str(path), exc_info=True)
        return _pricing_cache  # 返回旧缓存, 不抛异常

    if raw is None or not isinstance(raw, dict):
        logger.warning("cost.pricing_empty", path=str(path))
        return {}

    models = raw.get("models", {})
    _pricing_cache = {
        model: (float(prices["input"]), float(prices["output"])) for model, prices in models.items()
    }
    _pricing_mtime = current_mtime
    logger.info(
        "cost.pricing_reloaded",
        models=len(_pricing_cache),
        version=raw.get("version", "unknown"),
    )
    return _pricing_cache


def calculate_cost(model: str, tokens_prompt: int, tokens_completion: int) -> float:
    """计算 LLM 调用成本

    Args:
        model: 模型名 (如 "deepseek-v4-pro")
        tokens_prompt: 输入 token 数
        tokens_completion: 输出 token 数

    Returns:
        成本 (USD), 保留 6 位小数:
        - 匹配到模型 → 按定价计算
        - 未知模型 → 使用 _default 定价 (默认 0.0)
        - 定价文件缺失 → 返回 0.0
    """
    pricing = _load_pricing()
    input_price, output_price = pricing.get(model, pricing.get("_default", (0.0, 0.0)))
    cost = (tokens_prompt / 1_000_000) * input_price + (
        tokens_completion / 1_000_000
    ) * output_price
    return round(cost, 6)
