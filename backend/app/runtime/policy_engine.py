"""PolicyEngine —— 轨迹条件化反应式策略引擎

数学形式: π(a_t | s_0:t, g) — 基于完整轨迹 + 目标,输出下一步动作

设计约束 (硬):
- 只做 reactive decision: (goal + trajectory) → next action
- 禁止: long-term reasoning, global plan optimization
- 只输出单一动作,不是多步计划
- is_terminal 只是建议, Runtime 最终判定终止
- LLM 失败时回退 regex URL 提取
"""

from __future__ import annotations

import json
import re
from urllib.parse import quote

import structlog

from app.infra.llm import LLMProvider
from app.runtime.protocol.schemas import ActionDetail, DecisionResponse
from app.runtime.trajectory import Trajectory

logger = structlog.get_logger(__name__)

# ── Policy Prompt ──
_SYSTEM_PROMPT = """You are a browser automation policy engine. Based on the user's goal and execution trajectory, decide the SINGLE next browser action.

Current goal: {goal}
Execution trajectory:
{trajectory_summary}

Rules:
1. Always output skill "browser"
2. Based on the trajectory, decide the next action:
   - If trajectory is empty (first step): extract URL from goal, use "navigate"
   - If already on the target page: use "click" / "input_text" to interact
   - If goal appears complete: set is_terminal=true
3. Output exactly ONE action, never multiple steps
4. Action types: navigate, click, input_text, screenshot, extract
5. Do NOT do long-term reasoning or cross-site planning
6. For navigate: put the full URL in the "target" field
7. For click/input_text: put the CSS selector in "target", input text in "value"

Output ONLY valid JSON (no other text):
{{"skill": "browser", "action": {{"type": "...", "target": "...", "value": null, "description": "..."}}, "reasoning": "...", "is_terminal": false}}"""


# ── URL 提取回退 (LLM 不可用时) ──
_URL_PATTERN = re.compile(r"https?://[^\s]+")

_SITE_FALLBACK: dict[str, str] = {
    "百度": "https://www.baidu.com",
    "谷歌": "https://www.google.com",
    "必应": "https://www.bing.com",
    "淘宝": "https://www.taobao.com",
    "京东": "https://www.jd.com",
    "微博": "https://weibo.com",
    "知乎": "https://www.zhihu.com",
    "b站": "https://www.bilibili.com",
    "bilibili": "https://www.bilibili.com",
    "github": "https://github.com",
}


class PolicyEngine:
    """轨迹条件化策略引擎

    用法:
        engine = PolicyEngine(llm_provider)
        response = await engine.decide("打开百度")
        # → DecisionResponse(skill="browser", action=ActionDetail(type="navigate", ...))
    """

    def __init__(
        self,
        llm: LLMProvider,
        *,
        model: str | None = None,
        temperature: float = 0.3,  # 低温度: 减少幻觉,提高确定性
        max_tokens: int = 500,
    ) -> None:
        self._llm = llm
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens

    async def decide(
        self,
        goal: str,
        trajectory: Trajectory | None = None,
    ) -> DecisionResponse:
        """基于目标和轨迹决定下一步动作

        Args:
            goal: 用户原始目标
            trajectory: 累积操作轨迹 (None = 第一步)

        Returns:
            DecisionResponse with skill + action
        """
        traj_summary = (
            trajectory.summary_for_prompt()
            if trajectory and not trajectory.is_empty
            else "(empty - this is the first step)"
        )

        # 用 str.replace 而非 .format(),避免 goal 中包含 { 或 } 时触发 KeyError
        prompt = _SYSTEM_PROMPT.replace("{goal}", goal).replace(
            "{trajectory_summary}", traj_summary
        )
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": goal},
        ]

        try:
            response = await self._llm.chat(
                messages,
                model=self._model,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )
            return self._parse_response(response.content, goal)
        except Exception:
            logger.warning(
                "policy_engine.llm_failed_fallback",
                goal=goal[:80],
                exc_info=True,
            )
            return self._fallback_decide(goal)

    # ═══════════════════════════════════════════════════════════
    # 内部: JSON 解析 + 回退
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _parse_response(content: str, goal: str) -> DecisionResponse:
        """解析 LLM 返回的 JSON → DecisionResponse

        容错: 尝试从 markdown 代码块中提取 JSON。
        """
        # 尝试提取 JSON (可能被 markdown ```json ``` 包裹)
        json_str = content.strip()

        # 移除 markdown 代码块
        if json_str.startswith("```"):
            # 找到第一个 { 和最后一个 }
            start = json_str.find("{")
            end = json_str.rfind("}")
            if start != -1 and end != -1:
                json_str = json_str[start : end + 1]

        try:
            data = json.loads(json_str)
            return DecisionResponse(
                skill=data.get("skill", "browser"),
                action=ActionDetail(
                    type=data["action"]["type"],
                    target=data["action"].get("target"),
                    value=data["action"].get("value"),
                    description=data["action"].get("description", ""),
                ),
                reasoning=data.get("reasoning", ""),
                is_terminal=data.get("is_terminal", False),
            )
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(
                "policy_engine.json_parse_failed",
                content=content[:200],
                error=str(e),
            )
            return PolicyEngine._fallback_decide(goal)

    @staticmethod
    def _fallback_decide(goal: str) -> DecisionResponse:
        """回退: regex URL 提取 → navigate action

        这是 PolicyEngine 的兜底机制 —— 不依赖 LLM 也能执行基本导航任务。
        """
        # 1: 直接包含 URL
        url_match = _URL_PATTERN.search(goal)
        if url_match:
            url = url_match.group(0)
            return DecisionResponse(
                skill="browser",
                action=ActionDetail(
                    type="navigate",
                    target=url,
                    description=f"Navigate to {url}",
                ),
                reasoning="Fallback: regex URL extraction",
            )

        # 2: 常见网站映射
        for keyword, url in _SITE_FALLBACK.items():
            if keyword.lower() in goal.lower():
                return DecisionResponse(
                    skill="browser",
                    action=ActionDetail(
                        type="navigate",
                        target=url,
                        description=f"Navigate to {keyword}",
                    ),
                    reasoning=f"Fallback: site map matched '{keyword}'",
                )

        # 3: Bing 搜索
        return DecisionResponse(
            skill="browser",
            action=ActionDetail(
                type="navigate",
                target=f"https://www.bing.com/search?q={quote(goal)}",
                description=f"Search for: {goal}",
            ),
            reasoning="Fallback: Bing search",
        )
