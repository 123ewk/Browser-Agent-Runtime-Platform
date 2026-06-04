# 技术选型决策:为什么自造这些轮子

> 状态:Phase 0 完成后首版;Phase 1+ 涉及自造组件时增量更新。
> 范围:**只覆盖"自造/手写"组件**。纯"用现成库"的选型(FastAPI / SQLAlchemy / Redis 客户端等)不在此文档范围 —— 那些决策见 `docs/phase_0_design.md`。
> 用途:每次 Codex 在新 Phase 给出"我打算自己写 X"的方案前,先回到这份文档,确认"自造"决策是否还成立、是否有更新过的平替。

---

## 0. 阅读指引

每节统一五段式:

| 段落 | 回答的问题 |
|---|---|
| 选了什么 | 当前实现的核心 API / 文件位置 |
| 平替候选 | 业界现成的轮子(列 2-4 个,带版本/体量/最新动态) |
| 选它的理由 | 我们项目场景下,自造带来什么具体收益 |
| 否决平替的理由 | 为什么当下不能直接引,要列"真实痛点",不是"看起来不优雅" |
| 何时该反转 | 列出 3-5 个**具体可观察信号**,触达就回退到用平替 |

**最后两节**:
- §4 给出"造轮子"的 4 条判定原则(项目级硬约束)
- §5 给出"反转"决策的流程(避免自造后死撑)

---

## 1. 自造清单(总览)

| 组件 | Phase | 状态 | 文件 / 计划位置 |
|---|---|---|---|
| LLM Provider 抽象 | 0 | ✅ 已重构(2026-06-04 反转) 引 LangChain 全家桶 + LangSmith | `backend/app/infra/llm.py` |
| Logging 配置封装 | 0 | ✅ 已实现 | `backend/app/core/logging.py` |
| Browser Context 池 | 1 | 🕐 计划中 | `backend/app/infra/browser_pool.py` |
| Skill 注册表 + Backend Protocol | 1 | 🕐 计划中 | `backend/app/runtime/skills/registry.py` |
| 浏览器会话级错误恢复 | 1 | 🕐 计划中 | `backend/app/infra/playwright_browser.py` |
| Agent StateGraph 自定义节点 | 2 | 🕐 计划中 | `backend/app/runtime/nodes/*` |
| Human-in-the-loop Gate | 3 | 🕐 计划中 | `backend/app/runtime/nodes/human_input_gate.py` |
| WebSocket 消息协议 | 4 | 🕐 计划中 | `backend/app/api/ws/protocol.py` |
| 事件总线(本地) | 4 | 🕐 计划中 | `backend/app/infra/event_bus.py` |
| 任务队列抽象 | 5 | 🕐 计划中 | `backend/app/infra/task_queue.py` |

下面对**Phase 0 已实现**的两项做详尽对比,Phase 1+ 项只列平替和决策要点(留待对应 Phase 落地时细化)。

---

## 2. Phase 0 已自造

### 2.1 LLM Provider 抽象(`backend/app/infra/llm.py`)

> **2026-06-04 反转决策记录**:
> 原决策"自建轻量 Provider"经 §8.0 全局需求分析 + §10 反问协议,
> 识别出 5 项必做能力被错列为"何时该反转"信号,触发了反转流程。
> 现决策:**引 LangChain 全家桶 + LangSmith**。理由见下。

**选了什么**

- `LLMProvider(Protocol)` —— 业务层只依赖此接口(不依赖 LangChain 类型),分层契约稳定
- `LLMResponse(BaseModel)` —— 项目自有 DTO,与 LangChain `AIMessage` 解耦
- `MiMo` 类 —— 用 `langchain_openai.ChatOpenAI` 包装,MiMo 走 OpenAI 兼容协议
- `create_mimo_provider()` 工厂 —— 从 `Settings` 注入配置,业务层 `Depends` 拿
- **LangSmith trace** —— env 变量 `LANGCHAIN_TRACING_V2=true` 激活,业务代码零改动

**全局能力清单(§8.0 输出)**

| 能力 | 是否必做 | 触发 Phase | 自建覆盖率 | LangChain 覆盖 |
|---|---|---|---|---|
| 多轮对话(messages 历史) | ✅ | 0 | ✅ | ✅ |
| 流式响应(streaming) | ✅ | 1 | ❌(需 +150 行 SSE) | ✅(内置 astream) |
| Tool Call | ✅ | 1 | ❌(需 +200 行 JSON-RPC) | ✅(内置 bind_tools) |
| 结构化输出(response_format) | ✅ | 2 | ❌(需 +100 行) | ✅(内置 with_structured_output) |
| Token 计数 | ✅ | 0 | ✅ | ✅ |
| 可观测性(LangSmith trace) | ✅ | 4 | ❌(需 +200 行 OpenTelemetry) | ✅(env 激活全自动) |
| 长上下文 / 摘要 | 🕐 | 3 | ❌ | ✅(LangChain 生态) |
| **总覆盖率** | | | **~30%(2/7)** | **~100%(7/7)** |

**平替候选(本次重评)**

| 候选 | 体量 | 关键差异 | 必做能力覆盖率 | 与本项目契合度 |
|---|---|---|---|---|
| **A. 自建轻量 Provider**(原决策) | 0 额外依赖 | 5 项必做靠手写补丁,总计 +750 行 | ~30% | ❌ 后续每个 Phase 都要补 |
| **B. `langchain-openai` only** | +~10MB | 拿 chat / streaming / tool call,**无 trace** | ~70% | 🟡 可观测性仍要自建 |
| **C. LangChain 全家桶 + LangSmith**(本次选) | +~30MB | 上述 + trace + 生态(各类 tool / memory / output parser) | ~100% | ✅ 一次到位,Phase 1+ 零成本启用 |
| D. LlamaIndex | +~25MB | 偏 RAG / Agent framework,LLM 抽象弱 | ~50% | ❌ 与 LangChain 生态割裂,社区小一个量级 |

**选 C 的理由**

1. **必做能力覆盖率 100%** vs A 的 30% —— 不用每个 Phase 打补丁
2. **返工成本 = 0** —— Phase 1+ 启用 `.astream() / .bind_tools() / .with_structured_output()` 零成本
3. **故障透明度** —— LangSmith trace 自动串联 LLM ↔ Browser ↔ Agent,排查多步任务中间态
4. **多租户可观测性** —— Phase 4 多租户时,LangSmith 的 project 隔离天然支持
5. **学习价值仍在** —— LangChain 源码就是最好的 LLM 抽象教学,看 `BaseChatModel` / `ChatOpenAI` 实现

**否决 A / B / D 的理由**

- **A 自建**:5 项必做靠手写补丁,预计 +750 行;Phase 0 学到的"LLM HTTP 细节"够用,后面 8 个 Phase 还要重复造同样轮子,学习边际收益递减
- **B langchain-openai only**:可观测性(LangSmith trace)需要 LangChain 全套回调机制,只引 `langchain-openai` 反而要再叠 OpenTelemetry 自建 trace,半自造状态
- **D LlamaIndex**:LLM 抽象弱(偏 RAG framework),社区生态比 LangChain 小一个量级;与本项目"Browser Agent"语义错位

**何时该进一步反转(逃出 LangChain)**

出现以下任一,评估"自建 / 换框架":

1. LangChain 出现严重 breaking change 且 6 个月内无修复(2024-2025 1.0 大改已吸收,要监控)
2. LangSmith 价格 / 政策变化,自建 trace 收益更高
3. 项目需要模型微调 / 多模态视频理解,LangChain 抽象成为瓶颈
4. 团队迁移到 LlamaIndex / Haystack / 全新框架,且生态健康(过去 6 个月 commit 活跃)

当前:**0 个信号**,LangChain 仍是优解。

**反转流程记录(对应 AGENTS.md §5)**

| 步骤 | 时间 | 内容 |
|---|---|---|
| 触发 | 2026-06-04 | 用户指出"何时该反转"信号列表 = 必做能力误判 |
| §8.0 全局分析 | 2026-06-04 | 列出 7 项必做能力,自建覆盖率 30% |
| §10 反问 | 2026-06-04 | AskUserQuestion: 自建 / langchain-openai / LangChain 全家桶 |
| 决策 | 2026-06-04 | 选 C,引 LangChain 全家桶 + LangSmith |
| 重构 | 2026-06-04 | `infra/llm.py` 用 `ChatOpenAI` 包装,删除手写 retry / HTTP |
| 文档同步 | 2026-06-04 | 本节重写,§1 表格状态更新 |

---

### 2.2 Logging 配置封装(`backend/app/core/logging.py`)

**选了什么**

- 用 `structlog` 做日志引擎
- 自写 `_shared_processors()` 链 + `_add_app_metadata` 注入 `app/env`
- 自写 `configure_logging()`,dev 彩色 / prod JSON 切换

**平替候选**

| 候选 | 体量 | 关键差异 |
|---|---|---|
| `loguru` | 60KB | API 简洁,但与 stdlib `logging` 整合差,uvicorn/sqlalchemy 日志接管麻烦;JSON 需手写 serializer |
| `python-json-logger` | 20KB | 给 stdlib 加 JSON 输出,但**无 processor 链**,字段注入靠 `extra={}` 拼接,async 场景 request_id 难传 |
| stdlib `logging` + 自写 `Formatter` | 0 依赖 | 灵活但全是手写,维护成本高 |

**选它的理由**

- 跨 asyncio 任务自动传 `request_id`(contextvars 原生支持),不用显式透参
- 与 stdlib `logging` 完全兼容,uvicorn/sqlalchemy/alembic 日志一并接管
- dev 彩色 / prod JSON **同一套代码**,renderer 切换即可
- processor 链像中间件可组合,字段注入/格式化/异常渲染交给 processor,业务侧只关心"打日志"

**否决平替的理由**

- `loguru` 破坏 JSON handler 接管,uvicorn 日志格式不一致 → 排查时切两份格式
- `python-json-logger` 没有 processor 链,加一个字段(如 `app` / `env`)要改 3 处 `extra={}`

**何时该反转**

- structlog 出现严重 bug 或停更(过去 5 年没出现过,但列入风险)
- 业务需要 OpenTelemetry trace 自动注入(structlog 集成度一般,可能换 OpenTelemetry SDK 自带 logger)

当前 Phase 0:**0 个信号**,自造 + 选用 structlog 合理。

> 注:严格说"logging 配置封装"是**轻量定制**而非完整自造,核心引擎是 structlog。归到"自造清单"是因为 `_shared_processors / configure_logging` 是项目级代码,review 时要看。

---

## 3. Phase 1+ 计划自造(决策要点)

下面这些是**计划**而非已实现,写在这里是为了让"造轮子"决策留痕,落到对应 Phase 时回来细化。

### 3.1 Browser Context 池(Phase 1)

**平替候选**

- Playwright 自带 `BrowserContext` —— 单 context 也能用,但无池化
- `browserbase` / `browserless` —— 商业服务,多租户隔离
- `playwright-pool` 三方库 —— 社区维护,体量小但更新慢

**选它的理由(预期)**

- 多任务并发时,需控制同时打开的 context 数(配置 `browser_max_contexts`),避免内存爆炸
- 空闲 context 回收(`browser_context_idle_timeout`),与 Redis 配合做分布式清理
- 池化策略与"任务取消/超时"耦合,是项目专属

**否决平替的理由(预期)**

- Playwright 自带无池化,要自己写
- `playwright-pool` 三方库不支持我们的"任务结束 → 主动 close"语义

**何时该反转**

- context 池维护成本持续高于 1 人天 / Phase
- 出现商业化浏览器服务需求(browserless 之类)

---

### 3.2 Skill 注册表 + Backend Protocol(Phase 1)

**平替候选**

- LangChain `Tool` 装饰器 + `BaseTool` —— 注册和管理二合一
- `pluggy`(pytest 用的插件系统)—— 通用插件框架
- `stevedore` —— OpenStack 同款插件框架

**选它的理由(预期)**

- Skill 的"Backend Protocol"需要约束输入输出 schema(URL/截图/文本),与 LangChain `Tool` 的 `args_schema` 不完全对齐
- Skill 注册要走 FastAPI `Depends` 注入,LangChain Tool 是自包含的
- Phase 6 计划"Skill 动态加载",需注册表支持热插拔

**否决平替的理由(预期)**

- LangChain Tool 与我们的 backend(playwright/requests/...)语义错位
- `pluggy` 是通用插件框架,加进来要学它一套 EntryPoint 体系,边际收益不高

**何时该反转**

- Skill 数 ≥ 20,且要对外开放(类似 MCP Server)
- 需要与 LangChain 生态共享(比如 skill 可被 LangChain Agent 调用)

---

### 3.3 WebSocket 消息协议(Phase 4)

**平替候选**

- `python-socketio` —— Socket.IO 协议,带房间/重连
- `fastapi-websocket-pubsub` —— 发布订阅封装
- 原生 `fastapi.WebSocket` —— 最薄,自己写协议

**选它的理由(预期)**

- 消息 schema 与"Agent 状态变更"强耦合,需要类型安全的双向协议
- 客户端可能不止浏览器(CLI / 第三方集成),Socket.IO 的"长连接专属"反而是约束
- 自己定协议便于跨语言(未来 Node 端 worker)

**否决平替的理由(预期)**

- Socket.IO 协议绑 Web 浏览器,非浏览器客户端要再装一层适配
- `fastapi-websocket-pubsub` 是 publish/subscribe 抽象,与我们"request/response + 事件流"双工不匹配

**何时该反转**

- 客户端 100% 是 Web 浏览器
- 需要房间/广播/历史消息等高级特性

---

### 3.4 任务队列抽象(Phase 5)

**平替候选**

- `Celery` —— 老牌,但与 FastAPI 异步生态整合一般
- `ARQ` —— asyncio 原生,基于 Redis
- `Dramatiq` / `SAQ` —— 中量级
- `Temporal` —— 工作流引擎,过重

**选它的理由(预期)**

- 任务 = Browser 任务 + LLM 任务 + 混合任务,生命周期比"发邮件"复杂
- 需要支持"长任务 + 中途暂停恢复"(配合 LangGraph checkpoint)
- 与我们的 logging/observability 体系强整合

**否决平替的理由(预期)**

- Celery 同步 worker 模型,异步友好差
- ARQ 是好候选,但任务 schema 自由度低,定制时要绕开它的限制

**何时该反转**

- 任务调度逻辑 < 200 行,引 ARQ 反而省事
- 团队不熟 asyncio 队列,引 Celery 上手快

---

## 4. 造轮子的判定原则(项目级硬约束)

任一**否决条件**命中,**不准自造**:

1. **重复造** —— 业界有 ≥ 2 个成熟候选(每个 ≥ 1k GitHub stars,过去 12 个月有 commit)
2. **核心领域共识强** —— 比如 HTTP 客户端、ORM、序列化,共识明确,自造不会带来新认知
3. **业务逻辑的"非创新部分"** —— 比如表单解析、CSV 处理、邮件发送
4. **性能不是瓶颈** —— 瓶颈在 I/O,不在代码,引库节省的人力 > 自造的 0.01ms 优化

任一**支持条件**命中,**优先自造**:

1. **学习价值** —— 学生项目,自造能"知其所以然"(本项目硬约束)
2. **故障透明度** —— 自造代码的故障现场能 grep 到原始信息,排查路径 ≤ 3 跳
3. **依赖膨胀风险** —— 候选会拉 ≥ 10MB 传递依赖,或月度大版本更新
4. **业务专属定制** —— 自造代码包含"业务专属决策"(如状态码白名单、空闲回收策略),库的默认行为对不上

> **本项目特殊加分项**:学生向 —— 即便自造没有工程价值,**只要能讲清"为什么不引别人"**,也算正向收益。这是学习导向的例外。

---

## 5. 反转流程(避免自造后死撑)

触发"何时该反转"中 ≥ 3 个信号时,**不要立刻重写**,按下面 3 步走:

1. **开 issue / 写进本节** —— 记录"现在什么信号命中了,什么场景下自造不再划算"
2. **跑 1 周 spike** —— 把平替候选引进来,跑通主流程,**和自造版本同时维护**一段
3. **做对照评测** —— 对比:
   - 代码行数(自造 vs 引入)
   - 启动时间(`python -X importtime` 对比)
   - 镜像体积
   - 排查一次真实故障的平均时长
4. **写决策记录** —— 保留或反转,**都要更新本节"选了什么 / 平替候选表 / 选它的理由"**

**禁止行为**:
- 单纯因为"现在不顺手"就反转(那是写烂了,不是自造错了)
- 反转时偷偷换技术栈不留痕(违反 AGENTS.md 规则 13 Git 规范)

---

## 6. 文档维护规则

- 任何 Phase 引入新的"自造"组件 → **在 §1 表格加一行 + 在 §3 增一节细化**
- 任何 Phase 触发反转 → **在对应节的"何时该反转"补具体案例 + 记录决策时间**
- 任何"我们引入了 X 库"的新决策 → **不在本文件记录**(那是 `phase_X_design.md` 的范围)

---

## 7. 一句话总结

> 自造 = 学习 + 透明 + 可控;引库 = 效率 + 生态 + 抗变更。
> 本项目学生属性 + 强分层架构 + 故障排查要求,让"自造"在 §1 表里占了 10 项。
> 但每项都列了"反转信号"和"反转流程" —— 避免自造成路径依赖。
