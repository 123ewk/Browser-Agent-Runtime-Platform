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
- chat_stream 把 AIMessageChunk 增量转成 LLMChunk(Phase 1 接入)
- aclose 释放 ChatOpenAI 内部 httpx 连接池

LangSmith 配置(可选,env 变量,业务代码无感):
    LANGCHAIN_TRACING_V2=true
    LANGCHAIN_API_KEY=<your-langsmith-key>
    LANGCHAIN_PROJECT=browser-agent-runtime
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any, Protocol

import structlog
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    UsageMetadata,
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


class LLMChunk(BaseModel):
    """LLM 流式响应块 — chat_stream 每次 yield 一块,服务层用于打字机 + 实时成本。

    设计要点(为什么这样):
    - content 是 delta(增量)而不是 cumulative(累计):LangChain ChatOpenAI.astream
      协议就是增量,业务层 `content += chunk.content` 拼接;若是累计会重复
    - prompt_tokens / completion_tokens 仅 is_final=True 的块非 0:OpenAI / MiMo
      协议只在末块附带 usage_metadata,中间块保持 0 避免误导
    - is_final 是显式终态:部分上游(异常路径)可能不发 finish_reason,1-chunk
      buffer + 末块强制 is_final=True 兜底(见 chat_stream 实现)
    - raw 保留 AIMessageChunk.model_dump():排错和 LangSmith trace 用
    """

    content: str  # 本次增量文本
    prompt_tokens: int  # 仅最终块非 0
    completion_tokens: int  # 仅最终块非 0
    model: str  # 实际命中模型
    finish_reason: str | None  # "stop" / "length" / None
    is_final: bool  # 末块 True
    raw: dict  # 原始 AIMessageChunk


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


class StreamableLLMProvider(Protocol):
    """Phase 1 流式接口 — 与 LLMProvider 平级,不污染原 Protocol。

    为什么独立 Protocol 而非把 chat_stream 加到 LLMProvider:
    - 尊重既有"不污染本 Protocol"的设计原则,新能力扩边界而不是改契约
    - service 层按需注入(打字机场景用流式,分类/打分场景用非流),类型系统表达力更高
    - 单元测试可以单独 mock 流式 Provider,不依赖非流路径

    chat_stream 用 async def + AsyncGenerator 返回值,这是 Python typing 推荐的写法:
    Protocol 侧用 `def` 接受任意可返回 AsyncGenerator 的 callable(更精确),
    实现侧用 `async def`(更明确)。
    注意:AsyncGenerator 是 AsyncIterator 的子类型,改窄到 AsyncGenerator
    不会失去任何 mock/测试能力(单测仍可写 AsyncGenerator[LLMChunk] mock),
    但能让 mypy 检查到 .aclose() 等 generator 专属方法(消费者中途 break
    时的清理路径依赖 aclose(),类型错会漏掉)。
    """

    def chat_stream(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = 3000,
        timeout: int | None = 30,
    ) -> AsyncGenerator[LLMChunk, None]: ...


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
        # ChatOpenAI 内部已带:超时 / 重试 / LangSmith trace(env 激活时)
        # temperature / max_tokens / timeout 走 per-call 覆盖,不动 self._client 配置
        # timeout=None 时不传,沿用构造期的 settings.llm_timeout_seconds,
        # 这样默认行为不变;调用方传了 timeout 就 per-call 生效。
        # 用 .bind() 而非 ainvoke(**kwargs):langchain 的 ainvoke 有多个重载,
        # **dict[str, object] 在 mypy 严格模式下会被错配到 RunnableConfig | None
        # / list[str] | None 任一重载的位置(实际是 **kwargs: Any,运行时没问题,
        # 但 mypy 静态分析认不出)。.bind() 是 langchain 官方推荐的等价写法,
        # 类型干净,而且 RunnableBinding 的 __getattr__ 转发让覆盖选项
        # 对后续 ainvoke 调用生效,语义和 ainvoke(**kwargs) 完全一致。
        bind_kwargs: dict[str, Any] = {
            "temperature": temperature,
            "max_tokens": effective_max_tokens,
        }
        if timeout is not None:
            bind_kwargs["timeout"] = timeout
        response = await self._client.bind(**bind_kwargs).ainvoke(lc_messages)
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

    @staticmethod
    def _chunk_to_dto(
        chunk: BaseMessage,
        *,
        is_final: bool,
        usage: UsageMetadata | None,
        model: str,
    ) -> LLMChunk:
        """AIMessageChunk → LLMChunk 转换器 — 抽离出来便于单测覆盖边界。

        content 优先按 str 处理(LLM 文本路径);list 路径(Multi-modal)
        仅抽 text 片段,image 跳过(Phase 1 不接多模态,真碰到再说)。
        """
        raw_content = chunk.content
        if isinstance(raw_content, str):
            text = raw_content
        elif isinstance(raw_content, list):
            # Multi-modal:仅抽 {"type": "text"} 片段,image 暂不处理
            text = "".join(
                part.get("text", "")
                for part in raw_content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        else:
            text = str(raw_content)
        chunk_meta = getattr(chunk, "response_metadata", None) or {}
        # finish_reason 只在末块披露:中间块即便上游带了 finish_reason,业务层
        # 也只关心"最终结束原因",中间块一律返回 None(避免消费者误判流已结束)
        finish_reason = chunk_meta.get("finish_reason") if is_final else None
        if is_final and usage:
            prompt_tokens = int(usage.get("input_tokens", 0))
            completion_tokens = int(usage.get("output_tokens", 0))
        else:
            prompt_tokens = 0
            completion_tokens = 0
        return LLMChunk(
            content=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model=model,
            finish_reason=finish_reason,
            is_final=is_final,
            raw=chunk.model_dump(),
        )

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = 3000,
        timeout: int | None = 30,
    ) -> AsyncGenerator[LLMChunk, None]:
        """流式 chat — 每块是 token 级增量,业务层逐块消费做打字机 / 实时成本。

        与 chat() 的语义差异:
        - 返回 AsyncGenerator[LLMChunk] 而非 LLMResponse,首字延迟更低(无需等全量)
        - 默认 per-call .bind(streaming=True):ChatOpenAI 默认 streaming=None,
          部分上游会 fallback 到单块输出,显式 bind 强制流式;不污染 self._client
        - 1-chunk buffer:非末块先 yield,末块等循环结束后挂 is_final=True 单独 yield,
          兜底"上游不发 finish_reason"导致 is_final 永远不触发的边界
        - LangSmith trace(env 激活时)由 LangChain 自动处理,业务代码无感
        """
        chosen_model = model or self._default_model
        # 用 is None 判定而非 `or 3000`:若调用方显式传 max_tokens=0(OpenAI 协议
        # 0 = 不限制输出),`or` 兜底会把它吞成 3000,违反调用方意图
        effective_max_tokens = 3000 if max_tokens is None else max_tokens
        self._log.info(
            "llm.chat_stream.start",
            model=chosen_model,
            message_count=len(messages),
            temperature=temperature,
            max_tokens=effective_max_tokens,
            timeout=timeout,
        )
        lc_messages = self._to_lc_messages(messages)
        # 合并所有 per-call options 到一次 .bind():
        # - streaming=True 强制流式,避免上游 fallback 到单块输出
        # - temperature / max_tokens / timeout 走 per-call 覆盖
        # 不动 self._client 内部状态,后续 chat() 调用仍用默认非流配置
        # 用 .bind() 而非 astream(**kwargs) 的理由和 chat() 一致:
        # astream 的 **kwargs 在 mypy 严格模式下也会被错配到重载位。
        stream_bind: dict[str, Any] = {
            "temperature": temperature,
            "max_tokens": effective_max_tokens,
            "streaming": True,
        }
        if timeout is not None:
            stream_bind["timeout"] = timeout
        streaming_client = self._client.bind(**stream_bind)
        # pending_chunk 用 BaseMessage 而非 BaseMessageChunk:
        # langchain 的 astream 静态类型返回 AIMessage(mypy 严格模式),
        # 但运行时是 AIMessageChunk — BaseMessage 是两者公共父类,
        # 类型签名更宽松,匹配实际行为;_chunk_to_dto 内部只用
        # chunk.content / response_metadata / model_dump() 三个方法,
        # BaseMessage 已全包,无需窄化。
        pending_chunk: BaseMessage | None = None
        # final_usage 用 UsageMetadata TypedDict(不是 dict):
        # langchain-core 1.x 把 chunk.usage_metadata 标注成 UsageMetadata,
        # 严格模式下 dict | None 不接受 TypedDict 赋值。TypedDict 在
        # 运行时就是 dict,.get("input_tokens", 0) 等操作都正常工作,
        # 所以这里类型收窄到 TypedDict,语义和原来一致。
        final_usage: UsageMetadata | None = None
        actual_model = chosen_model
        chunk_count = 0
        async for chunk in streaming_client.astream(lc_messages):
            chunk_count += 1
            if pending_chunk is not None:
                # 非末块:1-chunk buffer 触发 yield,is_final=False
                yield self._chunk_to_dto(
                    pending_chunk,
                    is_final=False,
                    usage=None,
                    model=actual_model,
                )
            pending_chunk = chunk
            # 实时收集末态信息(usage 通常在末块附带;model_name 可能在中间块)
            if getattr(chunk, "usage_metadata", None):
                final_usage = chunk.usage_metadata
            chunk_meta = getattr(chunk, "response_metadata", None) or {}
            if chunk_meta.get("model_name"):
                actual_model = str(chunk_meta["model_name"])
        # 循环结束:yield 末块强制 is_final=True(兜底"上游不发 finish_reason")
        if pending_chunk is not None:
            yield self._chunk_to_dto(
                pending_chunk,
                is_final=True,
                usage=final_usage,
                model=actual_model,
            )
        self._log.info(
            "llm.chat_stream.end",
            model=actual_model,
            chunk_count=chunk_count,
        )

    async def aclose(self) -> None:
        """FastAPI lifespan shutdown 时调用,释放 ChatOpenAI 底层 httpx 连接池。

        不调用会导致 httpx 连接池里的 socket 句柄泄漏,
        在 K8s / 频繁 reload 场景下会触发 'Too many open files'。

        实现细节:ChatOpenAI.async_client 只是 openai.AsyncCompletions 包装,
        真正的 httpx 连接池在 root_async_client(openai.AsyncOpenAI 实例)上;
        BaseChatModel 自身没 aclose 方法(原代码 .aclose() 是错的,会 AttributeError),
        要直接调 root_async_client.close() 释放底层 httpx client。
        """
        await self._client.root_async_client.close()


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
