# 待开发功能清单(Pending Features)

> **编写日期**:2026-06-10
> **范围**:Phase 2 收尾 → Phase 5 → Phase 8 → Phase 9
> **显式排除**:Phase 6(Skill Marketplace / 上传接口 / 元数据管理)、Phase 7(数据分析 Skill / pandas / PDF / Excel / 内容生成)
> **配套阅读**:
> - [2026-06-06-phase1-data-layer-design.md](plans/2026-06-06-phase1-data-layer-design.md)
> - [2026-06-08-browser-agent-execution-engine-design.md](plans/2026-06-08-browser-agent-execution-engine-design.md)
> - [2026-06-09-memory-system-design.md](plans/2026-06-09-memory-system-design.md)

---

## 一、当前进度快照

- **已完成**:`Phase 0`(基础准备) / `Phase 1`(Browser Agent 核心) / `Phase 1.5`(Browser Agent 执行引擎) / 长期记忆系统(2026-06-09)
- **当前瓶颈**:
  - V1 简化的 Checkpoint 未真正实现
  - Watchdog 仅做被动 `proc.wait()`,无心跳超时
  - Pause/Resume 只切状态机,不会拉起新 Worker
  - Token / Cost 字段在 `stats` 接口返回 0(数据已落库,未聚合)
  - `memories` 向量检索是占位
- **端到端可演示链路已通**:任务创建 → Worker 执行 → Timeline WebSocket 推送 → 前端展示
- **已知已修复的线上 bug**:`docs/issues/2026-06-10-task-status-stuck-pending.md`、`docs/issues/2026-06-10-workspace-input-locked-by-stale-task.md`

---

## 二、待开发项分级

> 工作量为粗略相对量级:S=1-2 小时 / M=半天 / L=1-2 天 / XL=3 天+

### 🔴 P0 — 必须补(影响核心链路正确性)

#### #1 CheckpointManager 真正实现

- **设计来源**:[browser-agent-execution-engine-design §4.6](plans/2026-06-08-browser-agent-execution-engine-design.md)
- **当前状态**:`[model/checkpoint.py](../../../backend/app/model/checkpoint.py)` 仅有 ORM,无 Manager 类;`CheckpointRepository` 在,无"何时保存 / 何时加载"的业务逻辑
- **要做什么**:
  1. 定义 `state_data` 序列化 schema(任务级 / 步骤级 / worker 进程级)
  2. 触发器:关键步骤完成 / 子目标完成 / 人工确认前 / 任务结束
  3. Resume 时从 `latest checkpoint` 反序列化并恢复 worker 状态
- **阻塞 / 依赖**:决策点见 §四(序列化方案)
- **工作量**:M-L

#### #2 ProcessWatchdog 基于心跳的超时检测

- **设计来源**:[browser-agent-execution-engine-design §4.4](plans/2026-06-08-browser-agent-execution-engine-design.md)
- **当前状态**:`[task_runner.py:452-485](../../../backend/app/runtime/task_runner.py)` 的 `_process_monitor_loop` 仅在 `proc.wait()` 之后才检测,无"运行中无心跳"的兜底
- **要做什么**:
  1. 解析 Worker 的 `WORKER_HEARTBEAT`(协议已有,Worker 未发)
  2. 维护"最后心跳时间",超时阈值默认 120s
  3. 超时后发布 `WATCHDOG_TIMEOUT` 事件,触发 `[task_state.py](../../../backend/app/runtime/task_state.py)` 的强制失败路径
  4. Worker 侧补 `WORKER_HEARTBEAT` 发送协程(每 30s)
- **阻塞 / 依赖**:Worker 改心跳 + Runtime 侧加 Watchdog 类
- **工作量**:S-M

#### #3 Pause/Resume 真正续跑

- **设计来源**:`backend/app/api/tasks.py` 第 514-587 行 V2 TODO 注释
- **当前状态**:Pause = 状态机切到 `PAUSED` + 给 Worker 发 `STOP`(Worker 实际退出);Resume = 状态机切回 `RUNNING`,**不拉起新 Worker**
- **要做什么**:
  1. 依赖 #1 Checkpoint(Resume 时需要恢复现场)
  2. 依赖 #2 Watchdog(防止 Pause 后残留僵尸)
  3. `[resume_task](../../../backend/app/api/tasks.py)` 内启动新 `BrowserTaskRunner` + 加载 Checkpoint
  4. Worker 侧补 `PAUSE` 命令处理(挂起当前 step,保留内存状态)
- **阻塞 / 依赖**:必须先完成 #1
- **工作量**:M(只 Runtime 侧)/ L(端到端)

#### #4 Token 统计 + Cost 字段

- **设计来源**:`[stats.py:7,41](../../../backend/app/api/stats.py)` 注释明确"tracking 未实现"
- **当前状态**:`task_steps.tokens_used` 字段在 `TaskStepRepository.create()` 已写入,`task_runner._stderr_collector_loop` 还没回填到 `LLM` 调用侧
- **要做什么**:
  1. `[infra/llm.py](../../../backend/app/infra/llm.py)` 在 `chat()` 内部读取 provider 返回的 usage,结构化记录
  2. Worker 侧 LLM 调用节点(PolicyEngine / ActionPlanner)回传 tokens 给 Runtime
  3. `[stats.py](../../../backend/app/api/stats.py)` 聚合 `SUM(tokens_used)` 按窗口返回
  4. Cost 用模型单价表(可放 `core/config.py`)计算
- **阻塞 / 依赖**:无
- **工作量**:S

#### #5 memories 向量检索骨架

- **设计来源**:[memory-system-design §一(数据模型)](plans/2026-06-09-memory-system-design.md)
- **当前状态**:表 + `Vector(1024)` 列 + `metadata` JSONB 列已就位,`[repository/memory.py](../../../backend/app/repository/memory.py)` 只有占位类
- **要做什么**:
  1. Alembic 加 `ivfflat` 索引(可选,小数据量可省)
  2. `MemoryRepository` 补:`insert()` / `similar_search(user_id, vector, top_k)`
  3. Embedding 写入流程:任务结束 / `/remember` 时调用 embedding 模型 → 写入 `embedding` 列
  4. 检索调用方:PolicyEngine system prompt 拼装阶段加载 top-5
- **阻塞 / 依赖**:Embedding 模型选型(自造 / 调云 API)— 见 §四
- **工作量**:M

### 🟡 P1 — 应该补(影响完整性 / 演示效果)

#### #6 截图存 S3 完整链路

- **设计来源**:[browser-agent-execution-engine-design §5.6](plans/2026-06-08-browser-agent-execution-engine-design.md)
- **当前状态**:`[infra/s3.py](../../../backend/app/infra/s3.py)` 在,`SCREENSHOT` 事件 payload 含 `s3_key`,但 Worker 侧截图是否真上传 S3 未确认
- **要做什么**:
  1. `[worker/screenshot_manager.py](../../../backend/worker)` 加 S3 客户端调用
  2. Runtime 端 WS 推送时把 `s3_key` 换成预签名 URL(避免前端直连 S3)
  3. `[frontend/src/components/agent/BrowserPreview](../../../frontend/src/components/agent/BrowserPreview)` 适配新 URL
- **工作量**:S-M

#### #7 Phase 5 多任务调度

- **设计来源**:[开发流程.md §阶段 5](../../../开发流程.md)
- **当前状态**:`[tasks.py:58](../../../backend/app/api/tasks.py)` 已有 `_active_runners: dict[task_id, BrowserTaskRunner]`,支持多任务并发执行;**无** Scheduler / Browser Context 复用策略
- **要做什么**:
  1. Browser Context 池化策略:每任务独占 / 池化复用 / 按域路由
  2. 资源限制:最大并发 Worker 数 / 内存监控
  3. 公平调度:排队 vs 并发抢占
- **工作量**:L(策略 + 测试)

#### #8 Phase 8 端到端测试

- **设计来源**:[开发流程.md §阶段 8](../../../开发流程.md)
- **当前状态**:`backend/tests/` 已有模型/仓库/服务/部分 API 单测,无端到端用例
- **要做什么**:
  1. Playwright E2E:启动后端 → 创建任务 → 验 Timeline 推送
  2. 异常恢复:Worker 崩溃 → Watchdog 触发 → Checkpoint 恢复
  3. 并发任务测试:同用户 5 任务同时跑,验证状态机无串扰
- **工作量**:XL

### 🟢 P2 — 锦上添花(作品集加分项)

| # | 功能 | 来源 | 工作量 |
|---|---|---|---|
| #9 | Selector 自修复(失败后自动重新查询 / 走 LLM 改 selector) | Phase 9 | M |
| #10 | Vision fallback(截图 + VLM 兜底) | Phase 9 | XL |
| #11 | Cost 优化(轻量任务用便宜模型,复杂任务用强模型) | Phase 9 | M |
| #12 | Replay 完善(基于 Timeline 重放操作) | Phase 9 | M |
| #13 | UI 优化(Loading 态 / 空状态 / 错误态) | Phase 9 | M |

> 决策点见 §四

---

## 三、推荐实现顺序

1. **#4 Token 统计** — 阻力最小,数据已就位
2. **#6 截图 S3 链路** — 顺带做,与 Timeline 联调
3. **#2 ProcessWatchdog** — 补可靠性,无外部依赖
4. **#5 memories 向量检索骨架** — 独立模块,适合技术深度展示
5. **#1 CheckpointManager** — 复杂,需先定 schema(见 §四)
6. **#3 Pause/Resume 续跑** — 依赖 #1
7. **#7 Phase 5 多任务调度** — 性能与扩展
8. **#8 端到端测试** — 持续
9. **P2 项** — 选做,作品集最后冲刺

---

## 四、关键决策点(需先确认再动手)

### D1. Checkpoint 序列化方案

- **候选 A:JSON**(人类可读 + 跨语言,代价是日期/UUID 需手工处理)
- **候选 B:pickle**(Python 原生,代价是版本敏感 + 不可读)
- **候选 C:MessagePack**(紧凑 + 跨语言,需引入 `msgpack` 依赖)
- **影响**:跨进程、跨语言兼容、未来 Worker 用非 Python 时的迁移成本
- **建议**:**A(JSON)** 为 V1 默认,Worker 全栈 Python 不必为兼容付出复杂度

### D2. Embedding 模型选型

- **候选 A:DeepSeek / 智源 等云 API**(零成本接入,代价是外部依赖)
- **候选 B:本地小模型**(无外部调用,代价是 GPU/内存要求)
- **影响**:`memories.embedding` 写入与检索两端必须用同一模型
- **建议**:与 AGENTS.md §8.0 自造 vs 引库判定原则一致 — 先看 `docs/tech_selection.md` 是否有现成判定

### D3. Vision fallback 是否真做

- VLM 调用本身不复杂,但**对齐失败 selector** 是个独立研究问题
- 建议:作品集中写"规划 + 失败原因",比"实现"更显工程能力

### D4. Browser Context 池化策略

- **每任务独占**:最简单,代价是 Browser 启动慢 / 内存高
- **池化复用**:同登录态任务共享,代价是状态污染风险
- **按域路由**:同一站点共享,折中

---

## 五、验证清单(每完成一项勾选)

### P0

- [ ] **#4 Token 统计**:`/stats/dashboard` 在有 LLM 调用的任务后,`tokens` 字段 > 0
- [ ] **#2 ProcessWatchdog**:Worker 进程 `kill -STOP` 模拟心跳停止,Runtime 在 120s 内发布 `WATCHDOG_TIMEOUT` 事件
- [ ] **#5 memories 向量检索**:写入 3 条记忆后,`similar_search` 拿相关 top-1
- [ ] **#1 CheckpointManager**:任务完成后 `checkpoints` 表有新增;Resume 后 worker 状态与暂停前一致
- [ ] **#3 Pause/Resume 续跑**:Pause 后 resume,任务从暂停时的 step 继续,无重复 step

### P1

- [ ] **#6 截图 S3**:Timeline 上的 `SCREENSHOT` 事件,前端能加载图片(走预签名 URL)
- [ ] **#7 多任务调度**:同用户 5 任务并发,内存稳定无 OOM,任务状态无串扰
- [ ] **#8 端到端测试**:CI 上 Playwright 跑通"创建任务 → 看 Timeline"

### P2(可选)

- [ ] #9 / #10 / #11 / #12 / #13

---

## 六、与其他文档的关系

- 完成后,在 `docs/architecture.md` 同步更新"组件清单"和"事件流向"
- 重大决策在 `docs/issues/YYYY-MM-DD-问题简述.md` 写 10 段结构化复盘(参照 [2026-06-10-task-status-stuck-pending.md](issues/2026-06-10-task-status-stuck-pending.md))
- 涉及"自造 vs 引库"决策时,先查 `docs/tech_selection.md`(AGENTS.md §8 硬约束)
- 与面试题相关的部分沉淀到 `docs/interview_questions.md`(AGENTS.md §6 文档沉淀约定)
