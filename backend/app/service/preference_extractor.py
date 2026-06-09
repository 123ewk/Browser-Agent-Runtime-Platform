"""PreferenceExtractor —— LLM 压缩自然语言 → 结构化用户偏好。

职责:
- 接收一句自然语言(e.g. "以后回答尽量简洁,用中文")
- LLM 提取结构化偏差 → key/content/category 列表
- 归一化 key 保证 upsert 幂等
- 无效输入返回空列表(不强行提取)
"""

from __future__ import annotations

import json

import structlog

from app.infra.llm import ChatLLM

logger = structlog.get_logger(__name__)

_EXTRACTION_PROMPT = """你是一个用户偏好提取器。从用户输入中提取结构化偏好。

规则:
1. key 必须是归一化的短标签,使用 snake_case,不超过 32 字符
2. content 是压缩后的精华,去掉冗余,保留核心含义,不超过 200 字符
3. category 从以下选择: PREFERENCE / BEHAVIOR / INSTRUCTION
4. 如果一句话包含多个偏好,拆成多条
5. 如果输入没有明确的偏好信息,返回空数组 []

预定义 key 参考(不限于此):
- language: 回复语言
- answer_style: 回答风格(简洁/详细/幽默/正式)
- code_preference: 代码偏好(先代码后解释/只解释/只代码)
- explanation_depth: 解释深度(浅/中/深)
- tech_stack: 技术栈
- work_habit: 工作习惯
- review_habit: review 习惯
- career_focus: 职业方向

示例:
输入: "以后回答尽量简洁,优先给代码,用中文回复"
输出: [{"key": "answer_style", "content": "回答简洁", "category": "PREFERENCE"}, {"key": "code_preference", "content": "优先给代码", "category": "PREFERENCE"}, {"key": "language", "content": "回复使用中文", "category": "PREFERENCE"}]

输入: "今天天气不错"
输出: []

输出 ONLY 有效 JSON 数组,不要其他文字。"""


class PreferenceExtractor:
    """LLM 偏好提取器 —— 自然语言 → 结构化偏好列表"""

    def __init__(self, llm: ChatLLM, model: str | None = None) -> None:
        self._llm = llm
        self._model = model

    async def extract(self, raw_content: str) -> list[dict]:
        """从自然语言中提取偏好, 失败返回空列表"""
        messages = [
            {"role": "system", "content": _EXTRACTION_PROMPT},
            {"role": "user", "content": raw_content},
        ]

        try:
            response = await self._llm.chat(
                messages,
                model=self._model,
                temperature=0.0,  # 提取任务需要确定性
                max_tokens=500,
            )
            result = json.loads(response.content)
            if not isinstance(result, list):
                logger.warning(
                    "preference_extractor.unexpected_result",
                    result_type=type(result).__name__,
                )
                return []
            return result
        except json.JSONDecodeError:
            logger.warning("preference_extractor.json_parse_failed")
            return []
        except Exception:
            logger.warning("preference_extractor.llm_failed", exc_info=True)
            return []
