"""app.infra.llm 单测 — 覆盖 _chunk_to_dto 转换器 + chat_stream 异步流。

测试策略:
- 不连真 LLM:用 FakeBinding 替换 self._client.bind(streaming=True) 的返回值,
  astream() 产出受控 AIMessageChunk 序列(等价于"用 FakeListChatModel 注入多个 token"思路,
  但能精确控制 usage / finish_reason 等元数据)
- 不依赖 .env:conftest.py 已注入 LLM_API_KEY 等必填 secrets
- async 测试:pyproject.toml 已设 asyncio_mode = "auto",async 函数自动识别,
  sync 函数不会被强加 asyncio mark(消除警告)
- 替换 Pydantic 模型上的方法用 object.__setattr__:ChatOpenAI 是 BaseModel,
  严格 setattr 拦截任意非字段赋值,普通 monkeypatch / setattr 会 ValueError,
  用 object.__setattr__ 绕开 Pydantic __setattr__ 走 __dict__ 直写
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import AIMessageChunk
from langchain_openai import ChatOpenAI

from app.infra.llm import LLMChunk, MiMo


# ---------- 测试夹具 ----------

class FakeBinding:
    """可注入的 _client.bind(streaming=True) 返回值。

    为什么不用 MagicMock:async for 协议 + 关键字参数容易踩 Mock 的 strict 模式;
    手写一个轻量 fake 更可控,代码也自解释。
    """

    def __init__(self, chunks: list[AIMessageChunk]) -> None:
        self._chunks = chunks
        self.received_kwargs: dict[str, Any] = {}

    def astream(self, *args: Any, **kwargs: Any) -> AsyncIterator[AIMessageChunk]:
        # 记录调用参数,验证 temperature / max_tokens / timeout 透传
        self.received_kwargs = {"args": args, "kwargs": kwargs}
        return self._aiter()

    async def _aiter(self) -> AsyncIterator[AIMessageChunk]:
        for c in self._chunks:
            yield c


def _make_chunk(
    content: str,
    *,
    finish_reason: str | None = None,
    usage: dict[str, int] | None = None,
    model_name: str = "test-model",
) -> AIMessageChunk:
    """构造受控 AIMessageChunk — 等价于 OpenAI SSE 一块。

    usage_metadata 是 langchain 的 UsageMetadata TypedDict(input / output / total 三件套),
    缺 total 会 ValidationError,自动补 total = input + output。
    """
    metadata: dict[str, Any] = {"model_name": model_name}
    if finish_reason is not None:
        metadata["finish_reason"] = finish_reason
    full_usage: dict[str, int] | None = None
    if usage is not None:
        full_usage = {
            "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
            "total_tokens": usage["input_tokens"] + usage["output_tokens"],
        }
    return AIMessageChunk(
        content=content,
        response_metadata=metadata,
        usage_metadata=full_usage,
    )


def _patch_bind(mimo: MiMo, binding: FakeBinding) -> None:
    """把 mimo._client.bind 替换为返回 binding 的 lambda。

    必须用 object.__setattr__:ChatOpenAI 是 Pydantic BaseModel,
    默认 __setattr__ 拦截 "非 pydantic 字段" 赋值(ValueError);
    普通 setattr / monkeypatch.setattr 都会炸。
    object.__setattr__ 走 __dict__ 直写,绕过 Pydantic 校验。
    """
    object.__setattr__(mimo._client, "bind", lambda *a, **kw: binding)


def _make_mimo() -> MiMo:
    """MiMo 实例(参数走测试值,避免依赖 settings)。"""
    return MiMo(
        api_key="test-key",
        base_url="http://test/v1",
        default_model="test-model",
        timeout_seconds=30,
        max_retries=0,
    )


# ---------- _chunk_to_dto 转换器单测 ----------

def test_chunk_to_dto_text_delta_is_passed_through() -> None:
    """content 为 str 时,直接透传(LLM 文本路径)。"""
    chunk = _make_chunk("hello")
    dto = MiMo._chunk_to_dto(chunk, is_final=False, usage=None, model="m")
    assert dto.content == "hello"
    assert dto.is_final is False
    assert dto.finish_reason is None
    assert dto.prompt_tokens == 0
    assert dto.completion_tokens == 0
    assert dto.model == "m"


def test_chunk_to_dto_final_populates_usage_and_finish_reason() -> None:
    """is_final=True 时,usage 和 finish_reason 必须从 chunk 抽出。"""
    chunk = _make_chunk(
        "end",
        finish_reason="stop",
        usage={"input_tokens": 12, "output_tokens": 7},
    )
    dto = MiMo._chunk_to_dto(
        chunk,
        is_final=True,
        usage={"input_tokens": 12, "output_tokens": 7},
        model="m",
    )
    assert dto.is_final is True
    assert dto.finish_reason == "stop"
    assert dto.prompt_tokens == 12
    assert dto.completion_tokens == 7


def test_chunk_to_dto_finish_reason_suppressed_on_non_final() -> None:
    """非末块即便上游带了 finish_reason,业务层也只关心"最终结束原因",中间块一律 None。"""
    chunk = _make_chunk("mid", finish_reason="stop")  # 异常:中间块带 finish_reason
    dto = MiMo._chunk_to_dto(chunk, is_final=False, usage=None, model="m")
    assert dto.finish_reason is None  # 被压制


def test_chunk_to_dto_multimodal_extracts_text_only() -> None:
    """Multi-modal content(list[dict])仅抽 text 片段,image 跳过。"""
    chunk = AIMessageChunk(
        content=[
            {"type": "text", "text": "你看"},
            {"type": "image_url", "image_url": "http://x"},
            {"type": "text", "text": "这张图"},
        ],
    )
    dto = MiMo._chunk_to_dto(chunk, is_final=False, usage=None, model="m")
    assert dto.content == "你看这张图"


# ---------- chat_stream 行为单测 ----------

async def test_chat_stream_accumulates_content() -> None:
    """4 个 token 拼接后 == 完整响应。"""
    mimo = _make_mimo()
    binding = FakeBinding(
        chunks=[
            _make_chunk("你"),
            _make_chunk("好"),
            _make_chunk("，"),
            _make_chunk("世界"),
            _make_chunk(
                "",  # 末块 content 可空(OpenAI 协议)
                finish_reason="stop",
                usage={"input_tokens": 5, "output_tokens": 4},
            ),
        ],
    )
    _patch_bind(mimo, binding)

    received: list[LLMChunk] = []
    async for chunk in mimo.chat_stream([{"role": "user", "content": "hi"}]):
        received.append(chunk)

    # 5 个输入 → 5 个 yield(前 4 个 is_final=False,末 1 个 is_final=True)
    assert len(received) == 5
    full_text = "".join(c.content for c in received)
    assert full_text == "你好，世界"


async def test_chat_stream_marks_exactly_one_final() -> None:
    """无论上游 yield 多少块,业务层只能看到恰好 1 个 is_final=True。"""
    mimo = _make_mimo()
    binding = FakeBinding(
        chunks=[
            _make_chunk("a"),
            _make_chunk("b"),
            _make_chunk("c", finish_reason="stop", usage={"input_tokens": 1, "output_tokens": 3}),
        ],
    )
    _patch_bind(mimo, binding)

    received: list[LLMChunk] = []
    async for chunk in mimo.chat_stream([{"role": "user", "content": "x"}]):
        received.append(chunk)

    final_chunks = [c for c in received if c.is_final]
    assert len(final_chunks) == 1
    assert final_chunks[0].finish_reason == "stop"
    assert final_chunks[0].prompt_tokens == 1
    assert final_chunks[0].completion_tokens == 3


async def test_chat_stream_usage_only_on_final_chunk() -> None:
    """usage 仅在 is_final=True 的块非 0,中间块为 0(避免误导消费者算累计成本)。"""
    mimo = _make_mimo()
    binding = FakeBinding(
        chunks=[
            _make_chunk("a"),
            _make_chunk("b"),
            _make_chunk("c", finish_reason="stop", usage={"input_tokens": 8, "output_tokens": 3}),
        ],
    )
    _patch_bind(mimo, binding)

    received: list[LLMChunk] = []
    async for chunk in mimo.chat_stream([{"role": "user", "content": "x"}]):
        received.append(chunk)

    non_finals = [c for c in received if not c.is_final]
    final = next(c for c in received if c.is_final)
    # 中间块 tokens 必须是 0(usage 抽离后才挂到末块)
    assert all(c.prompt_tokens == 0 and c.completion_tokens == 0 for c in non_finals)
    # 末块 tokens 必须是上游给的真实值
    assert final.prompt_tokens == 8
    assert final.completion_tokens == 3


async def test_chat_stream_safety_net_when_no_finish_reason() -> None:
    """兜底:上游全程不发 finish_reason,1-chunk buffer 仍要 mark 最后一块 is_final=True。"""
    mimo = _make_mimo()
    binding = FakeBinding(
        chunks=[
            _make_chunk("a"),
            _make_chunk("b"),
            _make_chunk("c"),  # 没 finish_reason 也没 usage
        ],
    )
    _patch_bind(mimo, binding)

    received: list[LLMChunk] = []
    async for chunk in mimo.chat_stream([{"role": "user", "content": "x"}]):
        received.append(chunk)

    # 即便上游没给 finish_reason,末块仍要被识别为 is_final
    assert received[-1].is_final is True
    # 因为没 usage,tokens 仍为 0
    assert received[-1].prompt_tokens == 0
    assert received[-1].completion_tokens == 0
    # finish_reason 缺省为 None
    assert received[-1].finish_reason is None


async def test_chat_stream_passes_per_call_kwargs() -> None:
    """temperature / max_tokens / timeout 必须透传到 astream(per-call 覆盖)。"""
    mimo = _make_mimo()
    binding = FakeBinding(chunks=[_make_chunk("x", finish_reason="stop")])
    _patch_bind(mimo, binding)

    async for _ in mimo.chat_stream(
        [{"role": "user", "content": "x"}],
        temperature=0.3,
        max_tokens=512,
        timeout=15,
    ):
        pass

    kwargs = binding.received_kwargs["kwargs"]
    assert kwargs["temperature"] == 0.3
    assert kwargs["max_tokens"] == 512
    assert kwargs["timeout"] == 15


async def test_chat_stream_max_tokens_zero_not_swallowed() -> None:
    """max_tokens=0 显式传(OpenAI 协议 0 = 不限制),不能被默认 3000 吞掉。"""
    mimo = _make_mimo()
    binding = FakeBinding(chunks=[_make_chunk("x", finish_reason="stop")])
    _patch_bind(mimo, binding)

    async for _ in mimo.chat_stream(
        [{"role": "user", "content": "x"}],
        max_tokens=0,
    ):
        pass

    assert binding.received_kwargs["kwargs"]["max_tokens"] == 0


async def test_chat_stream_timeout_none_not_passed() -> None:
    """timeout=None 显式传时,不传到 astream(让 ChatOpenAI 用构造期 settings 的超时)。

    注意:调用方必须显式传 timeout=None 才会触发此分支;函数默认 timeout=30 会走
    "per-call 覆盖"路径,与 chat() 行为一致。
    """
    mimo = _make_mimo()
    binding = FakeBinding(chunks=[_make_chunk("x", finish_reason="stop")])
    _patch_bind(mimo, binding)

    async for _ in mimo.chat_stream(
        [{"role": "user", "content": "x"}],
        timeout=None,  # 显式 None
    ):
        pass

    assert "timeout" not in binding.received_kwargs["kwargs"]


async def test_chat_stream_aclose_after_early_break() -> None:
    """消费者中途 break,async generator 显式 aclose 不应抛(streaming 路径清理)。

    不在本测试里调 mimo.aclose():那是 pre-existing 路径(基线就有),
    跟 streaming 改造无关,本测试只关心 streaming 自己的清理语义。
    """
    mimo = _make_mimo()
    binding = FakeBinding(chunks=[_make_chunk("only")])
    _patch_bind(mimo, binding)

    # 拿 async iter 出来后立刻 break(模拟用户取消)
    agen = mimo.chat_stream([{"role": "user", "content": "x"}])
    async for _ in agen:
        break
    # 显式关掉 async generator,触发 finally/aclose — 不应抛
    await agen.aclose()


# ---------- 回归保护:chat() 不被 stream 改造破坏 ----------

async def test_existing_chat_still_returns_llm_response() -> None:
    """回归保护:chat() 必须仍走 ainvoke 路径,返回 LLMResponse(非 AsyncIterator)。"""
    mimo = _make_mimo()
    # chat() 路径:patch 掉 ainvoke,验证它被调用(而不是 astream)
    from langchain_core.messages import AIMessage
    fake_response = AIMessage(
        content="hi",
        usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        response_metadata={"model_name": "test"},
    )

    async def fake_ainvoke(*args: Any, **kwargs: Any) -> AIMessage:
        return fake_response

    object.__setattr__(mimo._client, "ainvoke", fake_ainvoke)

    response = await mimo.chat([{"role": "user", "content": "x"}])
    assert response.content == "hi"
    assert response.prompt_tokens == 1
    assert response.completion_tokens == 1
    assert response.model == "test"


# ---------- 类型契约 ----------

def test_mimo_satisfies_streamable_protocol() -> None:
    """类型契约:MiMo 实例必须同时满足 LLMProvider 和 StreamableLLMProvider。"""
    mimo = _make_mimo()
    # 检查两个方法存在(不是严格的 Protocol 运行时检查,够用)
    assert hasattr(mimo, "chat")
    assert hasattr(mimo, "chat_stream")
    assert hasattr(mimo, "aclose")
    # ainvoke 路径仍可用(chat() 依赖)
    assert isinstance(mimo._client, ChatOpenAI)
