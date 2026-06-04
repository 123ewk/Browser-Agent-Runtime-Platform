"""
LLM Provider —— 基于 langchain-openai ChatOpenAI 包装 MiMo。

MiMo 走 OpenAI 兼容协议,ChatOpenAI 通过 base_url 切换即可直接复用。

为什么用 LangChain 全家桶 + LangSmith 而不是自建:
    详见 docs/tech_selection.md §2.1(2026-06-04 反转决策记录)。
    简述:按 §8.0 全局需求分析,本项目必做能力含 streaming / tool call /
    structured output / 可观测性,自建方案覆盖率 < 80%(预计 +500 行补丁),
    引 LangChain 是更优解。

LangChain 提供的能力(自动获得,无需手写):
- HTTP 客户端(httpx async + 连接池,base_url 注入,Authorization 头)
- 重试(tenacity,5xx/429 自动重试)
- 消息格式转换(dict ↔ BaseMessage)
- Token 计数(AIMessage.usage_metadata)
- LangSmith trace(env 变量 LANGCHAIN_TRACING_V2=true 激活后全自动)
- Phase 1+ 启用:.bind_tools() / .with_structured_output() / .astream()

本类只负责:
- 把 settings 注入 ChatOpenAI 构造参数
- 把 dict messages 转成 LangChain 消息对象
- 把 AIMessage 转回 LLMResponse(项目自有 DTO,保持 Protocol 稳定)
- aclose 释放 ChatOpenAI 内部 httpx 连接池

LangSmith 配置(可选,env 变量,业务代码无感):
    LANGCHAIN_TRACING_V2=true
    LANGCHAIN_API_KEY=<your-langsmith-key>
    LANGCHAIN_PROJECT=browser-agent-runtime
"""
from __future__ import annotations

from typing import Protocol

import structlog
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.core.config import settings


class LLMResponse(BaseModel):
    """统一 LLM 响应 DTO,与具体 provider(LangChain)解耦,业务层只依赖本类。"""
    content: str  # 模型回复文本
    prompt_tokens: int  # 提示词 token 数
    completion_tokens: int  # 回复 token 数
    model: str  # 实际命中的模型(可能与请求不同,如 fallback)
    raw: dict  # 原始响应,排查用


class LLMProvider(Protocol):
    """Phase 0 最小 chat 接口。

    流式 / tool call / structured output 通过 ChatOpenAI.bind_*() 在调用方组合,
    不污染本 Protocol(避免接口膨胀)。这样 service 层只依赖 chat(),后续扩展不破坏分层。
    """
    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = 3000,
        timeout: int | None = 30,
    ) -> LLMResponse: ...


class MiMo:
    """MiMo 大模型 Provider —— 基于 langchain-openai ChatOpenAI 包装。

    构造参数显式注入,settings 留到工厂方法 create_mimo_provider(),便于单测传 mock 值。
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        default_model: str,
        timeout_seconds: int,
        max_retries: int,
    ) -> None:
        self._default_model = default_model
        self._log = structlog.get_logger(__name__)
        # ChatOpenAI 内部统一处理:HTTP 客户端 / 重试 / LangSmith trace
        # MiMo 走 OpenAI 兼容协议,base_url 一切即用,无需 monkey-patch
        # streaming 留默认 False;Phase 1 切 .astream() 时,业务侧显式调用,不污染本接口
        self._client = ChatOpenAI(
            model=default_model,
            base_url=base_url,
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )

    @staticmethod
    def _to_lc_messages(messages: list[dict[str, str]]) -> list[BaseMessage]:
        """dict messages → LangChain BaseMessage 列表。

        支持 role: system / user / assistant;其他 role 一律降级为 user(防御性编程,
        上游万一传错不至于崩溃)。Phase 2+ 加 multi-modal 时,content 可能是
        list[dict](text + image_url),届时改用 langchain_core.messages.convert_to_messages
        或自定义 multi-modal 转换。
        """
        result: list[BaseMessage] = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "system":
                result.append(SystemMessage(content=content))
            elif role == "assistant":
                result.append(AIMessage(content=content))
            else:  # user / 其他 → 统一按 user 处理
                result.append(HumanMessage(content=content))
        return result

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = 3000,
        timeout: int | None = 30,
    ) -> LLMResponse:
        chosen_model = model or self._default_model
        # 用 is None 判定而非 `or 3000`:若调用方显式传 max_tokens=0(OpenAI 协议
        # 0 = 不限制输出),`or` 兜底会把它吞成 3000,违反调用方意图。
        effective_max_tokens = 3000 if max_tokens is None else max_tokens
        self._log.info(
            "llm.chat.start",
            model=chosen_model,
            message_count=len(messages),
            temperature=temperature,
            max_tokens=effective_max_tokens,
            timeout=timeout,
        )
        lc_messages = self._to_lc_messages(messages)
        # ChatOpenAI.ainvoke 内部已带:超时 / 重试 / LangSmith trace(env 激活时)
        # temperature / max_tokens / timeout 走 per-call 覆盖,不动 self._client 配置
        # timeout=None 时不传,沿用构造期的 settings.llm_timeout_seconds,
        # 这样默认行为不变;调用方传了 timeout 就 per-call 生效。
        invoke_kwargs: dict[str, object] = {
            "temperature": temperature,
            "max_tokens": effective_max_tokens,
        }
        if timeout is not None:
            invoke_kwargs["timeout"] = timeout
        response = await self._client.ainvoke(lc_messages, **invoke_kwargs)
        # 提取 token 计数:LangChain 1.x 把 usage 放进 AIMessage.usage_metadata
        # 不同上游/版本字段名可能不同(input_tokens vs prompt_tokens),
        # 用 getattr + or {} 兜底,避免字段缺失炸响应解析
        usage = getattr(response, "usage_metadata", None) or {}
        # response_metadata 部分 adapter(异常路径 / 流式片段)可能返回 None,
        # 用 getattr + or {} 防御,避免 AttributeError 炸响应解析
        metadata = getattr(response, "response_metadata", None) or {}
        return LLMResponse(
            content=str(response.content),
            prompt_tokens=int(usage.get("input_tokens", 0)),
            completion_tokens=int(usage.get("output_tokens", 0)),
            # response_metadata 里有实际命中的模型名(可能与请求不同,服务端 fallback 时)
            model=str(metadata.get("model_name", chosen_model)),
            raw=response.model_dump(),
        )

    async def aclose(self) -> None:
        """FastAPI lifespan shutdown 时调用,释放 ChatOpenAI 内部 httpx 连接池。

        不调用会导致 httpx 连接池里的 socket 句柄泄漏,
        在 K8s / 频繁 reload 场景下会触发 'Too many open files'。
        """
        await self._client.aclose()


def create_mimo_provider() -> MiMo:
    """工厂方法:从 settings 读配置,创建 MiMo 实例。

    不在模块级 `mimo = MiMo(...)` 的原因:
    1. 模块 import 时 settings 还未就绪(可能 .env 没就位),会污染冷启动
    2. service 层按需调用工厂,生命周期跟 FastAPI Depends 对齐,便于测试替换
    """
    return MiMo(
        api_key=settings.llm_api_key.get_secret_value(),
        base_url=settings.llm_base_url,
        default_model=settings.llm_default_model,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )