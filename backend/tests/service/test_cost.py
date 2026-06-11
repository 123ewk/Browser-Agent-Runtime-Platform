"""LLM 成本计算测试 —— V2.5"""

from __future__ import annotations

from app.service.cost import calculate_cost


class TestCalculateCost:
    """成本计算测试"""

    def test_deepseek_v4_pro_cost(self) -> None:
        """deepseek-v4-pro: $0.55/$1.10 per 1M tokens"""
        cost = calculate_cost("deepseek-v4-pro", 1000000, 1000000)
        # 1M input * 0.55/1M + 1M output * 1.10/1M = 0.55 + 1.10 = 1.65
        assert cost == 1.65

    def test_zero_tokens(self) -> None:
        """零 token → 零成本"""
        cost = calculate_cost("deepseek-v4-pro", 0, 0)
        assert cost == 0.0

    def test_unknown_model_returns_zero(self) -> None:
        """未知模型 → 0.0 (缺省定价)"""
        cost = calculate_cost("nonexistent-model-v99", 1000, 1000)
        assert cost == 0.0

    def test_deepseek_flash_is_cheaper(self) -> None:
        """deepseek-v4-flash 比 pro 便宜"""
        flash_cost = calculate_cost("deepseek-v4-flash", 1000000, 1000000)
        pro_cost = calculate_cost("deepseek-v4-pro", 1000000, 1000000)
        assert flash_cost < pro_cost

    def test_gpt4o_is_expensive(self) -> None:
        """gpt-4o 明显贵于 deepseek"""
        gpt4o_cost = calculate_cost("gpt-4o", 1000000, 1000000)
        assert gpt4o_cost > 10.0  # $2.50 + $10.00 = $12.50

    def test_missing_model_returns_zero(self) -> None:
        """YAML 中不存在的模型返回 _default 定价 (0.0)"""
        cost = calculate_cost("totally-unknown-model-xyz", 1000000, 1000000)
        assert cost == 0.0
