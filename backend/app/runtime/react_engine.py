"""ReAct 决策引擎 —— Observe → Think → Decide 三阶段管道。

基于 ReAct (Reasoning + Acting) 框架, 替代 PolicyEngine 作为默认决策引擎:
- PolicyEngine: (goal + trajectory) → next action (纯反应式)
- ReActEngine:   (goal + trajectory + page_state) → reasoning → decision (认知式)

决策输出三种类型:
- ACT: 执行浏览器动作
- ASK_HUMAN: 遇到登录/验证码等阻塞, 需要人类介入
- DONE: 目标已达成 (is_terminal=True)

LLM 失败时 fallback 链: ReActEngine LLM 失败 → PolicyEngine.decide() → regex URL 提取
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog

from app.infra.llm import ChatLLM
from app.runtime.event_bus import EventBus
from app.runtime.protocol.constants import REACT_DEFAULT_MODEL, REACT_LLM_TIMEOUT
from app.runtime.protocol.schemas import ActionDetail, DecisionResponse, RuntimeEvent
from app.runtime.protocol.types import EventType, ReActDecisionType
from app.runtime.trajectory import Trajectory

logger = structlog.get_logger(__name__)

# ── ReAct System Prompt (英文, LLM 训练数据更多) ──
_REACT_PROMPT_TEMPLATE = """You are a browser automation agent using the ReAct (Reasoning + Acting) framework.

## CURRENT OBSERVATION
- URL: {url}
- Page Title: {title}
- Page Content Summary: {dom_summary}
- Visible Text: {visible_text}
- Recent Errors: {recent_errors}

## GOAL
{goal}

## EXECUTION HISTORY
{trajectory_summary}

## USER PREFERENCES
{user_preferences}

## INSTRUCTIONS
Think step by step:
1. OBSERVE: What do you see on the current page? Is it relevant to the goal?
2. REASON: What should be the next step? Are there any blockers?
3. DECIDE: Choose ONE of the following:

**ACT**: Execute a browser action. Output:
{{"decision":"ACT","action":{{"type":"navigate|click|input_text|screenshot|extract","target":"...","value":"...","description":"..."}},"reasoning":"I see X, therefore I should do Y"}}

**ASK_HUMAN**: You cannot proceed without human help (login required, captcha, paywall, ambiguous choice). Output:
{{"decision":"ASK_HUMAN","block_type":"login|captcha|paywall|consent|other","question":"What should the human do?","reasoning":"I'm blocked because..."}}

**DONE**: The goal has been achieved. Output:
{{"decision":"DONE","reasoning":"The goal is achieved because..."}}

Rules:
- Always output exactly ONE decision
- For navigation: use full URLs with https://
- For clicking: use CSS selectors when possible, fall back to visible text
- If you see a login form and have no credentials → ASK_HUMAN
- If you see a captcha → ASK_HUMAN
- Do NOT attempt to brute-force logins or bypass captchas"""

# ── Fallback blocker patterns (LLM 不可用时检测 ASK_HUMAN 场景) ──
_BLOCKER_PATTERNS: dict[str, str] = {
    r"captcha|verify.*human|prove.*you.*human": "captcha",
    r"sign.?in|log.?in|please.*authenticate": "login",
    r"subscribe|upgrade.*plan|payment.*required": "paywall",
    r"accept.*cookies|cookie.*consent|gdpr": "consent",
}


@dataclass
class ObservationState:
    """当前页面状态 —— ReAct 的"观察"输入"""

    url: str | None = None
    title: str | None = None
    dom_summary: str = ""  # 压缩后的 DOM/可见文本 (前 3000 字符)
    visible_text: str = ""  # 页面可见文本 (前 2000 字符)
    recent_errors: list[str] = field(default_factory=list)
    step_index: int = 0


def _format_observation(obs: ObservationState) -> dict[str, str]:
    """把 ObservationState 转为 prompt 模板参数"""
    url = obs.url or "(unknown)"
    title = obs.title or "(unknown)"
    dom = obs.dom_summary[:3000] if obs.dom_summary else "(empty)"
    visible = obs.visible_text[:2000] if obs.visible_text else "(empty)"
    errors = "\n".join(f"- {e}" for e in obs.recent_errors) if obs.recent_errors else "(none)"
    return {
        "url": url,
        "title": title,
        "dom_summary": dom,
        "visible_text": visible,
        "recent_errors": errors,
    }


class ReActEngine:
    """ReAct 决策引擎: Observe → Think → Decide

    与 PolicyEngine 的区别:
    - PolicyEngine: (goal + trajectory) → next action (纯反应式)
    - ReActEngine:   (goal + trajectory + page_state) → reasoning → decision (认知式)
    """

    def __init__(
        self,
        llm: ChatLLM,
        event_bus: EventBus,
        *,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 800,
        react_timeout: float = REACT_LLM_TIMEOUT,
    ) -> None:
        self._llm = llm
        self._event_bus = event_bus
        self._model = model or REACT_DEFAULT_MODEL
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._react_timeout = react_timeout

    async def decide(
        self,
        goal: str,
        trajectory: Trajectory,
        observation: ObservationState,
        task_id: str = "",
        preferences: list | None = None,  # list[UserPreference] — ORM 对象, 有 .key/.content
    ) -> DecisionResponse:
        """完整 Observe→Think→Decide 管道

        Args:
            goal: 用户原始目标
            trajectory: 累积操作轨迹
            observation: 当前页面状态快照
            task_id: 任务 ID (用于事件关联)
            preferences: 用户偏好列表

        Returns:
            DecisionResponse with extended V2.5 fields
        """
        # task_id 由调用方传入, THINK_START/THINK_COMPLETE 事件携带正确 task_id

        # 1. Observe: 格式化页面上下文
        obs_vars = _format_observation(observation)

        # 2. 构造 prompt
        traj_summary = (
            trajectory.summary_for_prompt()
            if trajectory and not trajectory.is_empty
            else "(empty - this is the first step)"
        )
        pref_lines = (
            "\n".join(f"- {p.key}: {p.content}" for p in preferences) if preferences else "(none)"
        )

        # 使用 format_map 一次性替换, 避免链式 replace 的二次替换风险
        # (用户 goal 中若含 {url} 等占位符文本, replace 会误替换)
        template_vars = {
            "goal": goal,
            "trajectory_summary": traj_summary,
            "user_preferences": pref_lines,
            **obs_vars,  # url, title, dom_summary, visible_text, recent_errors
        }
        prompt = _REACT_PROMPT_TEMPLATE.format_map(template_vars)

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": goal},
        ]

        # 3. Think: LLM 推理 (记录 token + 延迟)
        step_index = observation.step_index
        start_time = time.monotonic()

        # 发布 THINK_START 事件
        await self._event_bus.publish(
            RuntimeEvent(
                version="2.0.0",
                event_id=f"think-start-{step_index}",
                event=EventType.THINK_START,
                ts=datetime.now(UTC),
                task_id=task_id,
                payload={"step_index": step_index},
            )
        )

        try:
            response = await self._llm.chat(
                messages,
                model=self._model,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )
            llm_latency_ms = int((time.monotonic() - start_time) * 1000)

            # 提取 token 消耗 (从 LLM response 中尽可能提取)
            tokens_used = _extract_tokens(response)
            decision = self._parse_react_response(response.content, goal, observation)

            # 发布 THINK_COMPLETE 事件
            await self._event_bus.publish(
                RuntimeEvent(
                    version="2.0.0",
                    event_id=f"think-complete-{step_index}",
                    event=EventType.THINK_COMPLETE,
                    ts=datetime.now(UTC),
                    task_id=task_id,
                    payload={
                        "step_index": step_index,
                        "reasoning": decision.reasoning,
                        "decision": decision.decision_type,
                        "confidence": decision.confidence,
                        "tokens_used": tokens_used,
                        "llm_latency_ms": llm_latency_ms,
                    },
                )
            )

            decision.tokens_used = tokens_used
            decision.llm_latency_ms = llm_latency_ms
            decision.model_used = self._model
            return decision

        except Exception:
            logger.warning(
                "react_engine.llm_failed_fallback",
                goal=goal[:80],
                exc_info=True,
            )
            # Fallback: 尝试 regex 检测 ASK_HUMAN 场景
            return self._fallback_decide(goal, observation)

    # ═══════════════════════════════════════════════════════════
    # 内部: JSON 解析 + 回退
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _parse_react_response(
        content: str, goal: str, observation: ObservationState
    ) -> DecisionResponse:
        """解析 LLM 返回的 JSON → DecisionResponse (扩展 V2.5 字段)"""
        json_str = content.strip()

        # 移除 markdown 代码块
        if json_str.startswith("```"):
            start = json_str.find("{")
            end = json_str.rfind("}")
            if start != -1 and end != -1:
                json_str = json_str[start : end + 1]

        try:
            data = json.loads(json_str)
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("react_engine.json_parse_failed", content=content[:200], error=str(e))
            return ReActEngine._fallback_decide(goal, observation)

        decision_type = data.get("decision", "ACT")

        try:
            if decision_type == "DONE":
                return DecisionResponse(
                    skill="browser",
                    action=ActionDetail(type="done", description="Goal achieved"),
                    reasoning=data.get("reasoning", ""),
                    is_terminal=True,
                    decision_type=ReActDecisionType.DONE.value,
                    confidence=1.0,
                )

            elif decision_type == "ASK_HUMAN":
                block_type = data.get("block_type", "other")
                question = data.get("question", "")
                reasoning = data.get("reasoning", "")
                # ASK_HUMAN 决定: 发送一个占位 action, is_terminal=False
                # Runtime 侧 _run_task 检测到 decision_type=ASK_HUMAN 后走 WAITING_USER 路径
                return DecisionResponse(
                    skill="browser",
                    action=ActionDetail(
                        type="ask_human",
                        value=question,
                        description=f"Need human: {block_type}",
                    ),
                    reasoning=reasoning,
                    is_terminal=False,
                    decision_type=ReActDecisionType.ASK_HUMAN.value,
                )

            else:  # ACT
                action_data = data.get("action", {})
                return DecisionResponse(
                    skill="browser",
                    action=ActionDetail(
                        type=action_data.get("type", "navigate"),
                        target=action_data.get("target"),
                        value=action_data.get("value"),
                        description=action_data.get("description", ""),
                    ),
                    reasoning=data.get("reasoning", ""),
                    is_terminal=False,
                    decision_type=ReActDecisionType.ACT.value,
                )

        except (KeyError, TypeError) as e:
            logger.warning("react_engine.parse_error", error=str(e))
            return ReActEngine._fallback_decide(goal, observation)

    @staticmethod
    def _fallback_decide(goal: str, observation: ObservationState) -> DecisionResponse:
        """LLM 不可用时的 fallback: 检测已知阻塞模式 → ASK_HUMAN, 否则回退到 PolicyEngine 式策略"""
        # 1. 检查 observation 中的页面文本是否有已知阻塞模式
        visible_lower = (observation.visible_text + observation.dom_summary).lower()
        for pattern, block_type in _BLOCKER_PATTERNS.items():
            if re.search(pattern, visible_lower):
                return DecisionResponse(
                    skill="browser",
                    action=ActionDetail(
                        type="ask_human",
                        value=f"Blocked by {block_type}",
                        description=f"Fallback: detected {block_type}",
                    ),
                    reasoning=f"Fallback blocker detection: matched '{pattern}'",
                    decision_type=ReActDecisionType.ASK_HUMAN.value,
                )

        # 2. 没有阻塞模式 → 返回 ACT navigates to bing search (同 PolicyEngine fallback)
        from urllib.parse import quote

        return DecisionResponse(
            skill="browser",
            action=ActionDetail(
                type="navigate",
                target=f"https://www.bing.com/search?q={quote(goal)}",
                description="Fallback: search for goal",
            ),
            reasoning="Fallback: LLM unavailable, defaulting to search",
            decision_type=ReActDecisionType.ACT.value,
        )


def _extract_tokens(response: object) -> int:
    """从 LLM response 中提取 token 消耗 (兼容不同 LLM provider)"""
    # 尝试 langchain-openai 格式: response_metadata
    if hasattr(response, "response_metadata"):
        meta = response.response_metadata
        if isinstance(meta, dict):
            usage = meta.get("token_usage", {})
            if isinstance(usage, dict):
                return usage.get("total_tokens", 0)

    # 尝试 llm_output 格式
    if hasattr(response, "llm_output") and isinstance(response.llm_output, dict):
        usage = response.llm_output.get("token_usage", {})
        if isinstance(usage, dict):
            return usage.get("total_tokens", 0)

    # 尝试 usage_metadata (langchain >=0.3)
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        return getattr(response.usage_metadata, "total_tokens", 0)

    return 0
