# Bug: 任务结束后状态仍卡在"等待中"(Pending)不更新

> **复盘日期**: 2026-06-10
> **影响范围**: 任务列表(TaskList)、任务详情页、Dashboard 最近任务
> **严重度**: 中(用户感知明显,但不阻塞创建新任务)
> **状态**: 已修复(WS 推送 + 轮询兜底)

---

## 1. 现象

用户在 Browser Agent Runtime Platform 中创建一个浏览器任务(例如"帮我登录学习通"),
任务实际在 Worker 中已经跑完,但前端 `TaskList` 卡片上 `StatusBadge` 一直显示
"等待中"(对应后端 `pending` 状态),不切换到"成功 / 失败 / 已取消"。

截图佐证(2026-06-10):
- 任务 A(`e2777214-...`, "帮我登录学习通", 6 分钟前): 状态卡在 **等待中**
- 任务 B(`b39aac16-...`, "帮我登录学习通", 20 小时前): 状态显示 **未知**
  (本次先不处理,见 §7 后续)

执行时间轴右栏"任务已结束,共 0 条事件",说明任务确实结束了,
但左侧状态没切。

---

## 2. 复现路径

1. 登录前端,进入 Agent Workspace
2. 在 ChatInput 发送一个浏览器任务(例如"帮我登录学习通")
3. 任务被后端接收,Worker 执行若干步
4. Worker 发出 `TASK_FINISHED` 事件,任务真正结束
5. 观察左侧任务列表卡片:`status` 字段停留在 `pending`,没有变成
   `running → completed/failed/cancelled` 中的任何一个终态

---

## 3. 根因分析

### 3.1 后端状态机本身是正常的

后端 `TaskStateManager.transition()` 在以下三个时机都正常发出了
`TASK_STATE_CHANGED` 事件:

- `_run_task` 启动时:`pending → running`
- Worker 报告 `TASK_FINISHED` 时:`running → completed/failed/cancelled`
- 用户调 `/stop` `/pause` `/resume` 时

事件流也经 `TimelineRecorder._on_state_changed` 异步写回了 `tasks.status`
字段(见 `backend/app/runtime/timeline_recorder.py:154`)。

**所以"任务结束后 status 还是 pending"不是后端状态机的 bug**。

### 3.2 真正的问题在前端事件 → 缓存的链路

前端 `useTaskStreamInvalidation` 只 invalidate 了当前激活任务的 detail 缓存,
**没有 invalidate 任务列表缓存**:

```ts
// frontend/src/lib/ws/use-task-stream.ts:20-22
const off = subscribeTaskStream(taskId, () => {
  qc.invalidateQueries({ queryKey: queryKeys.tasks.detail(taskId) });
});
```

后果:

- 用户没有点开(激活)那个任务时,WS 根本没订阅,任务列表永远不更新
- 即使用户点开了,任务列表 `["tasks", "list", params]` 缓存也不会失效
  → 列表卡片 `status` 字段永远停留在 `pending` 那一帧
- 即使用户重新点了列表卡片,React Query 命中缓存,仍不会重新拉

### 3.3 WS 失联时缺乏兜底

`useTasks` 没有 `refetchInterval`,所以:

- WS 重连超过 5 次(backoff 上限)后,前端彻底失去事件流
- 浏览器标签页后台休眠 / 弱网时 WS 断开,前端不会主动轮询补数据
- 这两种场景下,任务状态彻底不会更新

### 3.4 综合结论

**根因**: 前端 WS 推送链路只覆盖了"激活任务的 detail",既不覆盖"列表",
也没有轮询兜底覆盖"WS 失联"。

后端协议、状态机、TimelineRecorder、REST API 都正常,问题纯前端。

---

## 4. 影响面

| 场景 | 是否受影响 |
| --- | --- |
| 用户激活某个任务后,detail 页 status 实时变化 | ❌ 不受影响 |
| 任务列表卡片 status 实时变化 | ✅ 受影响(本 bug) |
| 任务列表卡片 status 在 WS 失联后最终一致 | ✅ 受影响(本 bug) |
| Dashboard"最近任务"列表 status | ✅ 受影响(共用 useTasks) |
| 用户调 `/stop` `/pause` `/resume` 后的反馈 | 部分受影响(只覆盖 detail) |

---

## 5. 修复方案(已选 C:B + A 兜底)

候选方案:

- **A. 仅轮询(refetchInterval)**: 实现简单,但 latency 取决于轮询间隔(3-5s),
  且对活跃任务浪费请求
- **B. 仅 WS 推送**: 实时最好,但 WS 失联后无任何兜底,会卡死
- **C. WS 推送 + 轮询兜底(本次采用)**: 实时靠 WS,WS 失效/事件丢失时
  靠 5s 轮询兜底,保证最终一致
- **D. SSE 替代 WS**: 单向流,适合事件广播但不适合双向命令(V1 仍是 WS,
  不动协议)

选 C 的理由:

- 用户体验:**绝大多数情况下** 状态切换延迟 < 100ms(WS)
- 健壮性: **失联场景** 5s 内自动恢复
- 实现成本: 只动前端 2 个文件,不动后端协议

---

## 6. 修复内容(本 PR)

### 6.1 `useTaskStreamInvalidation` 补全列表 invalidate

`frontend/src/lib/ws/use-task-stream.ts:16-25`

```ts
// 改前: 只 invalidate detail
qc.invalidateQueries({ queryKey: queryKeys.tasks.detail(taskId) });

// 改后: 收到任何任务事件 → 列表 + detail 都失效
qc.invalidateQueries({ queryKey: queryKeys.tasks.all });
```

为什么用 `tasks.all` 而不是单个 `tasks.detail`:
- 列表 key 是 `["tasks", "list", params]`,参数很多,失效单个 key 会漏
- `tasks.all` 包含 `list` + `detail` 两类,一次失效搞定
- 失效开销很小(只重发 query,不发业务请求),不会拖慢前端

### 6.2 `useTasks` 加轮询兜底

`frontend/src/lib/query/tasks.ts:13-18`

```ts
// 改前: 纯被动
return useQuery({
  queryKey: queryKeys.tasks.list(params),
  queryFn: () => listTasks(params),
});

// 改后: WS 推送 + 5s 轮询兜底
return useQuery({
  queryKey: queryKeys.tasks.list(params),
  queryFn: () => listTasks(params),
  refetchInterval: 5_000,        // WS 失联时仍能更新
  refetchIntervalInBackground: false,  // 后台标签页不浪费请求
});
```

为什么 5s 不是 3s / 10s:
- 3s: 请求太频繁,任务列表数据量起来后(20+ 条)会撑爆
- 10s: 用户感知明显(任务结束后 10s 才看到状态切)
- 5s: 折中,跟浏览器 SSE 经验值一致

`refetchIntervalInBackground: false` 是必须的:
- 用户切到别的标签页,5s 轮询就会停
- 回到页面时,React Query 默认会立刻 refetch 一次,补上错过的更新
- 避免后台空转

### 6.3 不动的部分(避免过度修复)

- 后端 TaskStateManager: 状态机本身正确,**不改**
- 后端 TimelineRecorder: DB 同步逻辑正确,**不改**
- 后端 WebSocketManager: 事件分发正确,**不改**
- 前端 `useTaskStream`(Timeline 用): 已经只追加事件数组,跟 status 无关,不动

---

## 7. 后续(本 PR 不处理)

### 7.1 第二个任务显示"未知"(`b39aac16-...`)

20 小时前的任务,DB 里 `tasks.status` 字段值不在前端 `STATUS_STYLES` 白名单里。
可能原因:

- 早期开发阶段手动改过 DB(没走 TaskStateManager 校验)
- Alembic 迁移前后的数据漂移
- 老任务用的是旧状态值(例如 `success` 而不是 `completed`)

**处理方案**(独立 issue):

1. 跑一次数据修复脚本: 列出所有 status 不在 `TaskState` enum 内的任务
2. 写一次性 migration 把它们映射到最近的合法状态
3. 加 DB 层 CHECK 约束(已有迁移 `4f8a2c1b3d5e` 加了,可能 V1 没启用)

### 7.2 还没加的能力

- `useTask(id)` 单任务 query 也要加轮询兜底(目前只有列表加了)
- 后端日志加日期 + 用户名(用户口头要求,跟本 bug 无关,独立 PR)

---

## 8. 自检 Checklist

- [x] 6 步结构: 先解释后编码 ✓
- [x] 不动后端协议 ✓
- [x] 不引入新依赖 ✓
- [x] 注释写"为什么"不写"做了什么" ✓
- [x] 中文注释 ✓
- [x] Type Hints 完整 ✓
- [x] 单一改动点不超过 2 个文件 ✓
- [x] 改动 < 50 行 ✓
