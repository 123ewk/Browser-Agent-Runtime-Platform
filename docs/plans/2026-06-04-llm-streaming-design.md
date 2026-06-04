# 2026-06-04 LLM 流式输出设计

> **Phase**: Phase 0 → Phase 1 过渡(流式是 AGENTS.md §8.0 列出的 Phase 1 必做能力,
> 此设计是"先打地基"的渐进落地,**不引入新依赖,只复用 ChatOpenAI.astream**)。
>
> **状态**: 已通过用户三问对齐(API 形态 / Chunk 形状 / 测试方式)。

## 1. 背景

当前 `MiMo` 只暴露 `chat()` 同步返回 `LLMResponse`,无法满足:
- 浏览器任务长输出(规划/反思链)的"打字机"前端体验
- 用户中途取消任务的低延迟响应(< 200ms 首字)
- 流式成本可见(每块 token 累加 → 实时预算条)

详见 `docs/tech_selection.md` §2.1:LLM Provider 已引 LangChain,
`ChatOpenAI.astream()` 原生支持,无需自造。

## 2. 目标

| 目标 | 验收 |
|---|---|
| 新增 `chat_stream()` 返回 `AsyncIterator[LLMChunk]` | 单测验证拼接 = `chat()` 完整 content |
| 与 `chat()` 行为对齐(同参数语义) | 单测覆盖 timeout / max_tokens / model override |
| 抽离 Stream 接口到独立 Protocol | 不污染 `LLMProvider`(尊重既有注释) |
| 流中途异常不泄漏连接 | 验证 `aclose()` 仍可调用 |
| 测试用 `FakeListChatModel`,无外部网络 | CI 友好,无需真 key |

## 3. 设计

### 3.1 新增 DTO:`LLMChunk`

字段:
- `content: str` — 本次增量文本(打字机片段)
- `prompt_tokens: int` — 仅最终块非 0
- `completion_tokens: int` — 仅最终块非 0
- `model: str` — 实际命中模型(可能与请求不同,服务端 fallback 时)
- `finish_reason: str | None` — `"stop"` / `"length"` / `None`
- `is_final: bool` — 显式终态标志(比 `finish_reason is not None` 更稳)
- `raw: dict` — 原始 `AIMessageChunk.model_dump()`,排错用

### 3.2 新增 Protocol:`StreamableLLMProvider`

与 `LLMProvider` 平级,只声明 `chat_stream`。
`MiMo` 同时实现两个 Protocol,service 层按需注入(类型系统表达力更高)。

### 3.3 `MiMo.chat_stream()` 实现要点

- 调用 `self._client.astream(lc_messages, **kwargs)`,得 `AsyncIterator[AIMessageChunk]`
- per-call `.bind(streaming=True)`(注释已说"通过 bind_*() 在调用方组合,不污染接口"),
  ChatOpenAI 默认 `streaming=None`,部分上游会因此 fallback 到单块,显式 bind 强制流式
- 逐块转换:`AIMessageChunk` → `LLMChunk`
  - `content` 直接取 `chunk.content`(str 路径;multi-modal list 路径预留 text 抽取)
  - `is_final` = 块 `response_metadata.finish_reason is not None`
  - `finish_reason` = 同上字段
  - token 计数:扫到 `usage_metadata` 字段的块记下,在**最终块**填充(其余块为 0)
- 结构化日志:`llm.chat_stream.start` / `.end`,含 chunk_count / final_model / total_tokens
- 异常路径:不主动捕获,沿用 LangChain 默认重试;FastAPI lifespan 调 `aclose()` 兜底

### 3.4 与既有契约的兼容

- `LLMProvider` Protocol / `chat()` / `LLMResponse` 全部不动
- 注释"流式 / tool call / structured output 通过 ChatOpenAI.bind_*() 在调用方组合"——本设计正是这条注释的实现,只多了一步"对外暴露为 Provider 方法"
- `Phase 0 最小 chat 接口`注释保持不变(因 Protocol 没扩)

## 4. 否决方案

| 方案 | 否决理由 |
|---|---|
| 替换 `chat()` 为 `chat_stream()` | 非流场景(分类/打分)无路,违反 §2 不破坏现有接口 |
| 暴露 `AIMessageChunk` | 业务层耦合 LangChain,违反 §2 严格分层 |
| 在 `LLMProvider` 加 stream 方法 | 与"不污染 Protocol"注释矛盾,要改契约成本高 |

## 5. 测试

`backend/tests/infra/test_llm.py`,纯单元 + `FakeListChatModel`:

| 用例 | 覆盖 |
|---|---|
| `test_chat_stream_yields_increments` | 注入 4 个 token,验证拼接 == 完整内容 |
| `test_chat_stream_marks_only_one_final` | 恰好 1 个 `is_final=True` |
| `test_chat_stream_extracts_usage_on_final` | mock 带 `usage_metadata` 的块,验证仅最终块非 0 |
| `test_chat_stream_respects_max_tokens_zero` | `max_tokens=0` 不被默认值吞(同 chat 行为) |
| `test_chat_stream_aclose_after_partial` | 中途 break,再 `aclose()` 不抛 |
| `test_chat_stream_timeout_propagates` | per-call timeout 传到 astream |

## 6. 不在本设计范围

- tool call 流式(Phase 1 单独设计)
- structured output 流式(Phase 2)
- LangSmith trace 字段映射(已由 LangChain 自动处理,不重复)
- 前端 SSE 转发(本设计只到 Provider 层,API 层是 Phase 1 下一设计)
