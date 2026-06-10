# Bug 复盘:Workspace 输入框被"已结束但没标完成"的任务锁死

> 日期: 2026-06-10
> 严重等级: P1(用户被锁出核心交互面,无法新建任何任务)
> 影响范围: 整个 Agent Workspace 页面 (`/agent`)
> 状态: 已定位根因,待修复(前/后端均有缺陷)

---

## 一、概述

用户报告:**只要工作区里还残留一条之前的任务,即使它明显已经失败,新建任务按钮也用不了**。进一步看,这条残留任务的 status 显示"未知",时间轴里堆了 3 条 ERROR 且时间戳是 "Invalid Date",右栏一直停留在"等待 Worker 就绪…"。

经排查,这是一个**前/后端协同失灵**的复合 bug:

- 前端把"任何非终态"都当成"还在跑"来禁用输入
- 后端进程重启 / Worker 崩溃后,内存里的 `TaskStateManager` 会清空,但 DB 没有补偿机制把"应该 FAILED"的状态写回去
- 前端没有任何"逃生通道"——没有"取消任务"按钮,没有"新建对话"清空 activeId 的入口
- 还顺带暴露出时间戳容错、WS 死连后的空态文案、StatusBadge 兜底值等多个 UI 健壮性问题

---

## 二、现象(Symptom)

### 2.1 用户操作
1. 18 小时前,用户创建了任务 `b39aac16-b666-4ff9-b504-bfa53c13fccb`("帮我登录学习通")
2. 该任务大概率跑挂了——时间轴里出现 3 条 ERROR 事件
3. 用户回到 `/agent` 页面,左栏依然挂着这条任务,状态显示**"未知"**
4. 底部输入框被锁,无法新建任务

### 2.2 截图观察

| 区域 | 现象 |
|---|---|
| 左栏任务卡片 | status 徽章显示"未知"(`StatusBadge` 兜底) |
| 中栏 Timeline | 3 条 `ERROR` 事件,时间戳均为 `Invalid Date` |
| 中栏空态 | 显示"等待 Worker 就绪…"(误导性,Worker 早已退出) |
| 右栏 BrowserPreview | 空白,无截图 |
| 底部 ChatInput | 输入框与发送按钮均 `disabled` |

### 2.3 报错信息
无显式错误 toast。所有"错误"都是隐式的:状态显示不对、时间显示不对、按钮点了没反应。

---

## 三、根因分析(Root Cause Analysis)

### 3.1 P1 — 前端 `use-chat-submit.ts` 状态判定过严且无逃生通道

文件: [use-chat-submit.ts](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/frontend/src/components/agent/ChatInput/use-chat-submit.ts#L33-L47)

```ts
const isActive =
  taskStatus !== undefined &&
  taskStatus !== "completed" &&
  taskStatus !== "failed" &&
  taskStatus !== "cancelled";

const disabled =
  createTask.isPending ||
  (Boolean(activeId) && (isActive || !taskStatus));
```

**问题 1(逻辑):** 任何非 3 个终态的 status(包括 `pending` / `running` / `unknown` / `""` / `null`)都让 `isActive === true`,输入框被锁。这假设了"只要后端没标终态,任务就还在跑"——但实际后端有 N 种路径会让状态卡在非终态(见 §3.2 / §3.3)。

**问题 2(死锁):** 配合 [TaskList.tsx](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/frontend/src/components/agent/TaskList/TaskList.tsx#L23-L28) 的"自动选中第一条"副作用:

```ts
useEffect(() => {
  if (!activeId && data?.items && data.items.length > 0) {
    const first = data.items[0];
    if (first) setActive(first.id);
  }
}, [data, activeId, setActive]);
```

只要列表里有一条任务,**进入页面就必然锁死输入框**。用户没有 UI 路径可以清空 `activeId`(`agent-workspace.ts` store 只暴露 `setActiveTaskId` 一种 setter,没有 `clearActive` 方法)。

### 3.2 P1 — 后端无重启补偿:进程重启后 DB status 永久卡在 "pending"

文件: [timeline_recorder.py](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/backend/app/runtime/timeline_recorder.py#L131-L157)

```python
async def _on_state_changed(self, event: RuntimeEvent) -> None:
    """同步任务状态到 tasks 表"""
    payload = event.payload
    to_state = payload.get("to_state")
    ...
    await repo.update_status(task_uuid, TaskUpdate(status=to_state))
```

`tasks.status` 的 DB 写盘**只发生在 `TASK_STATE_CHANGED` 事件触发时**。该事件由 [task_state.py L74-L94](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/backend/app/runtime/task_state.py#L74-L94) 的 `transition()` 方法发布,而 `TaskStateManager` 是**纯内存**的:

```python
class TaskStateManager:
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._states: dict[str, TaskState] = {}  # ← 进程重启即清空
```

**因此:**
1. Worker 进程崩溃 → `_run_task` 跳循环 → transition 到 FAILED → TASK_STATE_CHANGED 事件发出 → DB 写 FAILED
2. **但只要后端 FastAPI 进程在这之后重启过**(开发期常态),`TaskStateManager._states` 被清空
3. 之后任何 `/tasks/{id}` 查询:
   - `runtime_state = _task_state_mgr.get_state(task_id)` → 返回 `PENDING`(默认值)
   - 走分支 `runtime_state != TaskState.PENDING` → False
   - 返回 `db_task.status`,而 DB 里这条任务**可能从未被 transition 写过**(因为 Worker 崩得早,或者崩溃时的 transition 事件还没落 DB 后端就重启了)
4. API 返回 `"pending"`(或更糟,见 §3.4 的非法值)

**这直接破坏了前端"非终态 = 在跑"的假设**:用户看到的是 `pending`(或"未知"),而这条任务实际上已经死了 18 小时。

### 3.3 P2 — Worker 崩溃的 ERROR 事件不会落 `task_steps` 表

文件: [timeline_recorder.py](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/backend/app/runtime/timeline_recorder.py#L107-L113)

```python
async def _on_error(self, event: RuntimeEvent) -> None:
    """ERROR: 写入错误步骤行"""
    payload = event.payload
    step_index = payload.get("step_index")
    if step_index is None:
        return  # 非步骤级错误(如系统级), 跳过
```

`task_runner.py` 的两个 ERROR 源 (`_process_monitor_loop` L455-L468 的 `WORKER_CRASHED` 和 `_stderr_collector_loop` L425-L437 的 `WORKER_STDERR`) **都不带 `step_index`**。

后果:Worker 进程崩了 → 3 条 ERROR 进 EventBus → `_run_task` 收到后递增 `consecutive_errors` → 第 3 次触发 transition 到 FAILED —— **这条路本身没问题**。但 ERROR 本身**不落 task_steps 表**,调试时无法从 timeline 表看到崩溃痕迹,只能看 WS 实时流(而 WS 重连后历史事件是丢的)。

### 3.4 P2 — DB status 列无 enum 约束,可写入任意 20 字符字符串

文件: [alembic 6dbf55](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/backend/alembic/versions/6dbf55_phase1_initial_tables.py#L62)

```python
sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
```

只有 `nullable=False` + `server_default="pending"`,**没有 CHECK 约束**。`TaskUpdate.status` 是 `str | None`,repository 写入时也不做白名单校验。

后果:任何把非 enum 字符串写入 DB 的代码路径都会污染 status。一旦前端拿到这种值,`StatusBadge` 走 [UNKNOWN_STYLE 兜底](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/frontend/src/components/shared/StatusBadge/StatusBadge.tsx#L70-L76),显示"未知"。

> 用户截图里的"未知"具体来源尚未 100% 锁定(可能为 DB 中残留的历史非法值、可能为运行时序列化问题),需要 DevTools Network 抓 `GET /tasks` 响应里的 `status` 字段原始值才能确认。

### 3.5 P3 — `TimelineStepRow.formatTime` 无容错

文件: [TimelineStepRow.tsx](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/frontend/src/components/agent/Timeline/TimelineStepRow.tsx#L11-L14)

```ts
function formatTime(isoTs: string): string {
  const d = new Date(isoTs);
  return d.toLocaleTimeString("zh-CN", { hour12: false });
}
```

`new Date("")` / `new Date(undefined)` 都返回 `Invalid Date`,`toLocaleTimeString` 在其上返回 `"Invalid Date"`。WS 事件只要 `ts` 字段是空串、缺失、或非 ISO 字符串(例如时间戳是 number 而非 string,或被 JSON 序列化成 `[Object: null]`)都会触发。

### 3.6 P3 — WS 重连后的"等待 Worker 就绪"是误导性空态

文件: [Timeline.tsx](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/frontend/src/components/agent/Timeline/Timeline.tsx#L36-L41)

```ts
{!isConnected && events.length === 0 && <div>正在连接 Worker…</div>}
{isConnected && events.length === 0 && <div>等待 Worker 就绪…</div>}
```

[subscribeTaskStream](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/frontend/src/lib/ws/task-stream.ts#L40-L48) 的指数退避重连机制会让 WS 在断线后**自动恢复 `isConnected=true`**,但服务端(任务已死)再也不会推任何事件。

UI 只有两种空态文案——"正在连接"和"等待 Worker 就绪",**没有"任务已结束,不会再有新事件"这个第三态**。用户看到"等待 Worker 就绪"会误以为 Worker 还在启动,实际进程已死 18 小时。

### 3.7 P3 — `useTask` API 失败也会让输入框被锁

文件: [use-chat-submit.ts](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/frontend/src/components/agent/ChatInput/use-chat-submit.ts#L44-L47)

`disabled` 的条件里有一项是 `!taskStatus`(即 task 数据尚未加载)。如果 `/tasks/{id}` 接口 500/网络失败,TanStack Query 的 `data` 是 `undefined`,`taskStatus` 是 `undefined`,**`disabled === true`**。

这意味着:**任何一次后端 API 抖动都能锁死用户的输入框**。这是设计上的过度防御。

---

## 四、影响范围(Impact)

| 维度 | 影响 |
|---|---|
| 用户面 | 任何"任务未正常结束"的场景都会锁死输入;典型场景:Worker 崩溃、网络抖动、后端重启、跨进程任务 |
| 频率 | 每次后端 dev 重启都会触发(开发期常态);Worker 崩溃也会触发 |
| 数据面 | 任务卡在非终态,统计/历史/复盘全都失真;`task_steps` 表里看不到 ERROR 痕迹 |
| 调试面 | 没有任何 toast/error 提示,用户不知道为啥按钮不响应;只能看 Console(还看不到,因为是 UI 状态问题) |

---

## 五、触发条件(Trigger Conditions)

以下任一条件即可触发:

1. **后端进程重启后**,用户访问 `/agent` 页面看到旧任务列表 → activeId 自动选中 → 任务 status 在 DB 里仍是 "pending" 或历史非法值 → 输入框锁死
2. **Worker 进程崩溃**(`returncode != 0`)且后端在该崩溃被处理完之前重启 → DB 永远是 "pending" 或无更新
3. **历史上某次代码路径写入了非 enum 的 status 字符串**到 DB(例如:旧版 enum 切换、空字符串、手工改库)
4. **`/tasks/{id}` API 失败**(网络/5xx),`useTask` 返回 undefined,`!taskStatus` 分支触发
5. **WS 事件 `ts` 字段缺失/非法**(后端 Pydantic 模型与 WS 序列化不一致),触发 "Invalid Date"

---

## 六、修复方案(Fix Plan)

按优先级 P1 → P3。**P1 必修,P2 应修,P3 建议修**。

### 6.1 P1-A:前端加"新建任务"按钮,清空 activeId

文件: [agent-workspace.ts](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/frontend/src/lib/store/agent-workspace.ts)

```ts
setActiveTaskId: (id: string | null) => void;
// 新增:显式清空,不等同于"选中 null"——避免列表 useEffect 误回填
clearActiveTask: () => void;
```

UI: [AgentWorkspace.tsx](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/frontend/src/components/agent/AgentWorkspace/AgentWorkspace.tsx) 顶部加 `+ 新建任务` 按钮(已有 `NewWorkflowButton` 类似物,可复用样式)。点击后 `clearActiveTask()` + 清空 `draft`,输入框立即可用,新任务创建成功后自动切到新任务。

### 6.2 P1-B:后端启动时重建内存状态

文件: [lifespan.py](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/backend/app/core/lifespan.py) 的 `startup` 阶段,加一个 `rehydrate_task_states()`:

```python
async def rehydrate_task_states() -> None:
    """进程启动时从 DB 重建内存 TaskStateManager。

    逻辑:扫描 status ∈ {pending, running, waiting_confirm, paused, stopping}
    的非终态任务(进程重启前还活着的),按 DB 状态回填到 TaskStateManager。
    同时启动一个 watchdog,30s 内若没有收到对应任务的 TASK_STATE_CHANGED
    / STEP_COMPLETE,主动 transition 到 FAILED("后端重启,任务中断")。
    """
    ...
```

这一改直接消灭 §3.2 的"重启后状态卡死"问题。

### 6.3 P1-C:`use-chat-submit` 放宽 disabled 判定

文件: [use-chat-submit.ts](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/frontend/src/components/agent/ChatInput/use-chat-submit.ts#L33-L47)

新规则:
- **只在 `taskStatus` 明确是 `running` / `waiting_confirm` / `paused` / `stopping` 这 4 个真正"在跑"状态时锁输入**
- `pending` / `unknown` / `undefined` / 任何非常量都视为"可新建"(配合 §6.1 的清空按钮)
- `createTask.isPending` 期间继续锁
- 后端 `POST /tasks` 已经在 [create_task](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/backend/app/api/tasks.py#L88-L165) 实现里做了多任务并发(`_active_runners: dict`),所以"新建"和"旧任务运行"可以共存,前端无需独占

### 6.4 P2-A:DB 加 CHECK 约束 + repository 写入白名单校验

```sql
ALTER TABLE tasks ADD CONSTRAINT chk_task_status
CHECK (status IN ('pending','running','waiting_confirm','paused','stopping','completed','failed','cancelled'));
```

文件: [task.py repository](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/backend/app/repository/task.py#L69-L78) 的 `update_status` 加 `if dto.status not in {allowed}` 校验,非法值直接抛错并打 warn。

迁移:新建 `alembic/versions/<hash>_add_task_status_check.py` 即可。

### 6.5 P2-B:`_on_error` 也要落 task_steps

文件: [timeline_recorder.py L107-L113](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/backend/app/runtime/timeline_recorder.py#L107-L113)

不带 `step_index` 的 ERROR(系统级、Worker 崩溃)也写一行到 `task_steps`,`step_index = -1` 或 `0` 表示"任务级错误",`action = error_type`,`result = {error: true, error_type, message, retryable}`。这样崩溃痕迹不会丢。

### 6.6 P3-A:`formatTime` 容错

```ts
function formatTime(isoTs: string | undefined | null): string {
  if (!isoTs) return "—";
  const d = new Date(isoTs);
  return Number.isNaN(d.getTime())
    ? "—"
    : d.toLocaleTimeString("zh-CN", { hour12: false });
}
```

### 6.7 P3-B:Timeline 加"任务已结束"第三态

文件: [Timeline.tsx](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/frontend/src/components/agent/Timeline/Timeline.tsx)

当 `useTask(activeId).data?.status` 是终态(completed/failed/cancelled)时,空态文案改为"任务已结束,共 N 条事件",明确告诉用户"不会再有新事件"。

### 6.8 P3-C:StatusBadge 在 `status` 为 `undefined` / `null` / `""` 时降级显示"加载中"

避免刚加载时一闪而过"未知"。

---

## 七、防御措施(Defense in Depth)

1. **协议层防御**:后端 schema 端用 `Literal[...]` 限定 status,OpenAPI 自动生成前端类型,**前后端共用一份 enum 定义**(用 codegen 或手写同步脚本)
2. **DB 层防御**:加 CHECK 约束(§6.4),即使应用层有 bug 也兜底
3. **观测层防御**:`TimelineRecorder` 落库失败时增加 `metric counter` + `alert`,不要只 log
4. **可恢复性**:`TaskStateManager` 改成可选的 Redis 持久化,重启不丢状态(Phase 2)
5. **UI 逃生通道**:任何"全局锁定"型状态都配一个显式 reset 按钮(§6.1)
6. **空态文案**:`{isLoading / isConnected / isEmpty / isError}` 至少 4 种状态分支,不要只 2 种

---

## 八、验证(Verification)

### 8.1 单元测试
- `use-chat-submit`:mock `useTask` 返回各种 status,断言 `disabled` 行为
- `StatusBadge`:传入 8 个合法 status + 5 个非法值(undefined / null / "" / "PENDING" / "unknown"),断言渲染结果
- `TaskList` `useEffect`:列表为空时不主动 setActive;列表非空时不重复 setActive
- `TimelineStepRow.formatTime`:"" / undefined / 合法 ISO / 非 ISO 字符串

### 8.2 集成测试(后端)
- 模拟"创建任务 → 后端重启 → 重启后查任务"流程,断言 status 一致
- 模拟"Worker 崩溃但没 TASK_FINISHED",断言 _run_task 仍能 transition 到 FAILED
- 模拟"DB 写入非法 status",断言 repository 拒绝并打 warn

### 8.3 手动验收
- 在前端 `/agent` 页面:
  - [ ] 任务列表空时进入 → 输入框可用
  - [ ] 任务列表非空时进入 → 输入框可用(只要旧任务不是 running)
  - [ ] 旧任务在 running 时,新任务按钮被锁,提示"当前任务进行中,完成后可新建"
  - [ ] 点 `+ 新建任务` → 旧任务保持,输入框可用
  - [ ] 后端重启后,旧任务 status 自动显示正确(不会卡 pending/未知)
  - [ ] 错误事件时间戳显示为 "—" 而非 "Invalid Date"
  - [ ] 终态任务的时间轴空态显示"任务已结束"

---

## 九、复盘总结(Lessons Learned)

### 9.1 学生向的核心教训

1. **"防御性编程"的反例**:`disabled = (activeId && (isActive || !taskStatus))` 看起来"宁可锁不可放",实际上把"网络抖动"和"任务在跑"混为一谈。**正确的防御是"白名单"而非"黑名单"**——明确列出"在跑"的 4 个状态,其余都放行。教学点:**显式优于隐式**(规则要列得出来,不能写"!=terminal 就是 running")。

2. **状态机单一真相源原则被破坏**:`TaskStateManager`(内存)和 `tasks.status`(DB)是**两个真相源**,需要持续同步(由 `TimelineRecorder` 桥接)。一旦桥接路径出错(进程重启、事件丢失),就出现"两边不一致"的 bug。**单一真相源要么纯内存但接受重启丢失,要么纯 DB 接受延迟**——本项目选的是前者,却没接受"重启即丢",而是默默积累了脏数据。**教学点:分布式/多副本系统的一致性取舍,要在设计阶段就写明"重启后状态如何恢复",不能等出 bug 再补**。

3. **UI 逃生通道的工业级标准**:任何"全局锁定"型交互(模态、必填、独占),都必须配显式的 cancel/reset 入口,这是 UX 铁律。**没有逃生通道 = 用户被绑架**。本项目违反了这条标准,直接后果就是"按钮死了但没报错"。

4. **空态文案是产品的一部分**:`isConnected=true && events.length=0` 跟"任务已死"完全是两种产品语义,但被合并成同一句"等待 Worker 就绪"。**空态至少要分清:加载中 / 连接中 / 等待中 / 已结束 / 错误** 5 种,每种文案 + 引导动作不同。

5. **DB schema 是最后一道防线**:enum 字段在应用层校验不够,DB CHECK 约束才是工业级兜底(参考 PostgreSQL 官方推荐)。本项目缺这一道,任何应用层 bug 都能污染 DB。

### 9.2 对应 AGENTS.md 哪些规则
- §2 硬约束 "不写万能 utils.py"——反向应用:不要写万能的 `disabled` 判定
- §2 硬约束 "严格分层"——本 bug 暴露分层不严:`use-chat-submit`(UI 业务)对后端状态机做了隐式假设,违反"UI 不知道后端细节"
- §2 硬约束 "注释写 为什么不写做了什么"——`use-chat-submit` 第 14 行注释写的是"为什么"("有活动任务且已结束 → 可创建下一个任务"),但**实际行为没实现这个意图**,注释和代码不同步
- §3 6 步结构中【核心逻辑】"为什么这样设计"——`disabled` 判定当初为什么这么写?有文档吗?大概率没有,所以改动时要补 ADR

---

## 十、后续行动(Follow-up Actions)

### 10.1 待用户确认的信息(必须拿到才能 100% 锁定 §3.4)
- [ ] 浏览器 DevTools → Network → `GET /tasks` 响应里 `status` 的原始值
- [ ] Postgres: `SELECT id, status, updated_at FROM tasks WHERE id = 'b39aac16-b666-4ff9-b504-bfa53c13fccb';` 的输出
- [ ] DevTools → WS 帧,3 条 ERROR 事件的 `ts` 字段原始值(看是 `""` / `null` / 还是合法 ISO)
- [ ] 后端进程 18 小时期间是否重启过

### 10.2 待补的设计文档
- [ ] `docs/architecture.md` 加一节 "状态机持久化策略",明确"重启即丢"的取舍
- [ ] `docs/issues/` 目录建好后,本文件作为第一篇
- [ ] `docs/interview_questions.md` 加 3 题(状态机单一真相源、UI 逃生通道、DB CHECK 约束的工业级价值)

### 10.3 暂不修但记下来
- `TaskStateManager` 改 Redis 持久化(Phase 2 范围)
- 前端"取消任务"按钮(等 V2 引入显式 `POST /tasks/{id}/cancel` API 后再加)
- LLM Provider 切换 / 多任务并发 UI(与本 bug 无关,但同属"workspace 设计待补")

### 10.4 关键 ADR(Architecture Decision Record)草稿

> **ADR-XXX: TaskStateManager 持久化策略**
>
> **Context:** 任务状态机是 UI 禁用输入、DB 状态回填、统计/历史查询的唯一真相源。目前在内存 dict,进程重启即丢。
>
> **Decision:** 短期保留内存实现,启动时从 DB 重建(§6.2 的 rehydrate 模式);长期(Phase 2)切到 Redis。
>
> **Consequences:**
> - (+) 短期改动小,1-2 个 PR 可解
> - (-) 30s watchdog 期间 UI 仍可能短暂显示错误状态
> - (-) 极端情况(DB 损坏、迁移失败)需要手动干预
> - (+) Phase 2 切换 Redis 时,rehydrate 逻辑可以原样保留作为"冷启动降级"

---

> **复盘人:** Codex
> **对应用户问题:** "我前端的工作空间里面只要存在之前的任务就不可以创建新的任务了"
> **根因一句话总结:** 前端把"非终态"等价于"在跑",后端重启后 DB status 不补偿,UI 没有逃生通道,三者合谋把用户锁出核心交互面。

---

## 十一、修复记录(Post-mortem Implementation Log)

> 时间: 2026-06-10 当日
> 范围: 完成 §6 全部 P1-P3 修复,新增任务控制三件套(stop / pause / resume)

### 11.1 修复清单

| # | 等级 | 标题 | 涉及文件 |
|---|---|---|---|
| 1 | P1-A | `agent-workspace` store 加 `clearActiveTask` | [agent-workspace.ts](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/frontend/src/lib/store/agent-workspace.ts) |
| 2 | P1-A | AgentWorkspace 左栏顶部加「+ 新建任务」按钮 | [AgentWorkspace.tsx](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/frontend/src/components/agent/AgentWorkspace/AgentWorkspace.tsx) |
| 3 | P1-C | `use-chat-submit` 改用 4 个状态白名单判定 disabled | [use-chat-submit.ts](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/frontend/src/components/agent/ChatInput/use-chat-submit.ts) |
| 4 | P1-B | 后端 `TaskStateManager` 加 `restore_state` / `force_fail` / `start_watchdog` | [task_state.py](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/backend/app/runtime/task_state.py) |
| 5 | P1-B | 新增 `app/runtime/rehydrate.py` 启动时从 DB 重建内存 | [rehydrate.py](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/backend/app/runtime/rehydrate.py) |
| 6 | P1-B | `lifespan.py` 接入 rehydrate + watchdog | [lifespan.py](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/backend/app/core/lifespan.py) |
| 7 | P2-A | 新增 alembic 迁移 `4f8a2c1b3d5e` 加 CHECK 约束 | [4f8a2c1b3d5e_add_task_status_check_constraint.py](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/backend/alembic/versions/4f8a2c1b3d5e_add_task_status_check_constraint.py) |
| 8 | P2-A | `TaskRepository.update_status` 加白名单校验 | [task.py](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/backend/app/repository/task.py) |
| 9 | P2-B | `TimelineRecorder._on_error` 写 task 级错误(用 step_index=-1) | [timeline_recorder.py](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/backend/app/runtime/timeline_recorder.py) |
| 10 | P3-A | `TimelineStepRow.formatTime` 加 null/Invalid Date 容错 | [TimelineStepRow.tsx](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/frontend/src/components/agent/Timeline/TimelineStepRow.tsx) |
| 11 | P3-B | `Timeline` 加「任务已结束」第三态空态 | [Timeline.tsx](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/frontend/src/components/agent/Timeline/Timeline.tsx) |
| 12 | P3-C | `StatusBadge` 加载中/未定义态降级 | [StatusBadge.tsx](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/frontend/src/components/shared/StatusBadge/StatusBadge.tsx) |

### 11.2 新增任务控制三件套(用户追加需求)

用户反馈 §1 的修复虽然解决"卡死后无法新建",但仍然**没有主动控制任务的能力**——任务在跑时只能等它跑完,或者到时间轴里去分析日志。补三个接口 + 前端按钮:

| 接口 | 行为 | 状态转换 | V1 Worker 实际行为 |
|---|---|---|---|
| `POST /tasks/{id}/stop` | 终止任务 | 任意非终态 → STOPPING → CANCELLED | Worker 退出,不可恢复 |
| `POST /tasks/{id}/pause` | 暂停任务 | RUNNING/WAITING_CONFIRM → PAUSED | Worker 退出(协议未实现),状态保留 |
| `POST /tasks/{id}/resume` | 继续任务 | PAUSED → RUNNING | 仅状态机恢复,V1 不重启 Worker |

**后端:**
- [tasks.py](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/backend/app/api/tasks.py) 新增三个 `@router.post` 端点
- [task.py schema](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/backend/app/schema/task.py) 加 `TaskActionResponse` 通用 DTO
- 三个接口都**幂等**:对终态任务调用返回 `accepted=False, reason=...`,不抛 4xx

**前端:**
- [api/tasks.ts](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/frontend/src/lib/api/tasks.ts) 加 `stopTask / pauseTask / resumeTask`
- [query/tasks.ts](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/frontend/src/lib/query/tasks.ts) 加 `useStopTask / usePauseTask / useResumeTask` mutations
- **新组件 [TaskControlBar.tsx](file:///g:/my/my_file/Browser%20Agent%20Runtime%20Platform/frontend/src/components/agent/TaskControlBar/TaskControlBar.tsx)** —— 渲染在 TimelineHeader 下方,根据 `taskStatus` 切换按钮:
  - `running / waiting_confirm / pending`:显示「暂停」「停止」
  - `paused`:显示「继续」「停止」
  - `stopping`:「停止中…」disabled
  - 终态:整个条隐藏

### 11.3 V1 vs V2 边界(避免预期不符)

| 行为 | V1 实际 | V2 应该 |
|---|---|---|
| 暂停 | 状态转 PAUSED,**Worker 退出** | Worker 实现 PAUSE 协议(挂起 step,保留内存) |
| 继续 | 仅状态机 PAUSED→RUNNING | 加载 Checkpoint,拉起新 Worker 续跑 |
| 停止 | 标准路径(STOPPING→CANCELLED) | 同 V1 |

V1 选择"暂停 = 停止 + 保留状态"是因为:Worker 协议层未实现 PAUSE,**强行实现只能 mock,反而误导用户**。前端按钮的 `title` 文案明确说明"V1 Worker 退出,状态保留"。

### 11.4 当前 UI 逃生通道全景

| 场景 | 解决方案 |
|---|---|
| 任务卡死,想新建 | 1) 点左栏「+ 新建任务」清空 activeId<br>2) 点中栏「停止」彻底结束旧任务 |
| 任务跑一半想暂停 | 点中栏「暂停」(状态 PAUSED,Worker 退出,V2 续跑) |
| 想续跑暂停的任务 | 点中栏「继续」(状态机恢复,V1 不真续跑,需 V2 Checkpoint) |
| 输入框禁用 | 现在通过「+ 新建任务」或「停止」都能解 |
| 时间轴里看到 "Invalid Date" | 改用「—」 |
| 状态显示「未知」 | 后端 status 不在白名单时,降级「未知」并 warn(用于定位协议漂移) |
