# 项目级假设与决策记录

> 维护人: Codex(学生项目)
> 触发规则: AGENTS.md §10.4 — Codex 在用户答"你看着办"/"随便" 或 用户同意"按 X 假设推进"时,必须把假设记入本文。
> 下次 Codex 会话开始时,先读本文,验证假设是否还成立。假设被推翻 → 回退决策,补"决策复盘"小节。

---

## A.1 ReActEngine 使用 LangChain(不自造)

**决策日期**: 2026-06-11
**关联文档**: [`docs/plans/2026-06-11-agent-runtime-v2.5-design.md`](plans/2026-06-11-agent-runtime-v2.5-design.md) §4 / §4.5
**决策形式**: 用户主动选择(问"用 langchain,能用第三方库的就用第三方库,尽量不用自造")

### 决策内容

V2.5 新增的 `ReActEngine` 改用 LangChain 抽象实现,**不**自造轻量 ReAct 循环。具体:

- 使用 `langchain.agents.create_react_agent(llm, tools, prompt)` 创建 ReAct agent
- 用 `langchain.callbacks` 订阅 `on_chain_start` / `on_chain_end` 提取 reasoning / tokens
- 工具定义:`@tool navigate / click / input_text / screenshot / extract / ask_human`
- LLM 失败 fallback 链:LangChain 内部 retry → `PolicyEngine.decide()` → regex URL 提取

### §8.0 全局能力清单评估

按 AGENTS.md §8.0 要求,先列 Runtime 维度"必做能力"(详见 `2026-06-11-agent-runtime-v2.5-design.md` §1):

| 能力 | 是否必做 | 评估 |
|---|---|---|
| ReAct 决策(Observe→Think→Act) | ✅ 必做 | 必做 |
| Tool Call 失败 → 推理 fallback | ✅ 必做 | 必做 |
| Token 计数 + 成本追踪 | ✅ 必做 | 必做 |
| 中间件 / callback 订阅(reasoning 提取) | ✅ 必做 | 必做 |
| Memory(短期 trajectory) | ✅ 必做 | 必做 |
| 自定义 tool 注册 | ✅ 必做 | 必做 |

**自造方案评估**: 必做能力覆盖率 < 20%。需要:
- 自实现 prompt 解析(JSON 抽取)
- 自实现 tool 调用路由
- 自实现 token 计数回调
- 自实现 trajectory memory
- 自实现中间件订阅机制
- **预估 500+ 行代码**

**LangChain 方案评估**: 必做能力覆盖率 ≥ 80%。需要:
- 引用 `langchain-core` + `langchain-openai` 已有能力
- 仅自写"LangChain agent ↔ V2.5 事件总线"桥接代码
- **预估 < 100 行代码**

### 否决条件检查(AGENTS.md §8.1)

- 命中"**重复造**": 业界有 ≥ 2 个成熟候选(LangChain / LlamaIndex / Haystack),LangChain 过去 6 个月 commit 活跃、issue 响应快
- 命中"**核心领域共识强**": Agent 编排是工业级共识领域,自造不带来新认知
- 命中"**性能不是瓶颈**": LLM 调用是秒级,框架 overhead 毫秒级,占比 < 0.1%

**结论**: 命中 3 条否决条件,不准自造。**通过**。

### 学习价值权衡(AGENTS.md §8.2 / §8.3)

虽然 §8.2 第 1 条"学习价值"是支持自造的条件,§8.3 学生向加分项也允许"只要能讲清为什么不引别人"算正向收益。

**学习价值的损失通过以下方式补回**:
1. **必读 LangChain 源码**: `create_react_agent` 实现 + `AgentExecutor` 调度逻辑
2. **必写对照实验**: PR2 期间在 `docs/learning/langchain-vs-custom.md` 写 200 行对比代码(纯 LLM 调用 + ReAct prompt + JSON 解析),作为"自造版本"留底,理解 LangChain 抽象了什么
3. **必读 LangChain callback 机制源码**: 理解 on_chain_start / on_llm_start / on_tool_start 三类回调的注册与传播
4. **必写自定义 callback**: 实现 `RuntimeBridgeCallback` 把 LangChain 事件映射到 V2.5 事件总线,理解中间件模式

> 这样既不重复造轮子,又通过"读源码 + 写桥接"获得等价的学习深度。

### 决策复盘检查点

未来需要反向评估的场景(任一命中 → 重新评估 LangChain 是否仍是最佳选择):

- [ ] V3 引入多 Agent 协作:LangChain 的 LangGraph 是否还合适?
- [ ] V3 引入 Vision Fallback:LangChain 的 multi-modal 抽象是否够用?
- [ ] 业务要求 on-prem 部署 + 网络隔离:LangChain 的云依赖能否剔除?

### 风险与缓解

| 风险 | 缓解 |
|---|---|
| LangChain 大版本破坏性变更 | 用 `langchain-core` API 稳定层,自定义 callback 不绑定 LangChain 内部类 |
| LangChain 引入传递依赖膨胀 | 仅引 `langchain-core` + `langchain-openai`,**不**引 `langchain` 全家桶 |
| 故障现场不透明 | 自定义 callback 桥接到 V2.5 事件总线,所有 LangChain 事件都能在 TimelineRecorder 中查到 |

---

## A.2 后续待补的假设

(暂无)
