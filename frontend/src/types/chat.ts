/**
 * Chat / 实时通信类型 —— Agent Workspace 底部输入区 + Timeline 使用
 */

export type RunMode = "yolo" | "semi";

/** 用户发送给 Agent 的消息 */
export interface ChatMessage {
  readonly id: string;
  readonly taskId: string;
  readonly role: "user" | "agent";
  readonly content: string;
  readonly createdAt: string;
}

// ── 服务端 RuntimeEvent 类型(与 backend app/runtime/protocol/schemas.py 对齐) ──

export type EventType =
  | "WORKER_READY"
  | "WORKER_HEARTBEAT"
  | "STEP_START"
  | "STEP_COMPLETE"
  | "SCREENSHOT"
  | "PROGRESS"
  | "NEED_CONFIRM"
  | "ERROR"
  | "TASK_FINISHED"
  | "TASK_STATE_CHANGED"
  | "COMMAND_ACK"
  | "WATCHDOG_TIMEOUT";

export interface RuntimeEventPayload {
  // STEP_START
  index?: number;
  action?: string;
  description?: string;
  reasoning?: string;
  // STEP_COMPLETE
  summary?: string;
  url?: string;
  // SCREENSHOT
  file_key?: string;
  // PROGRESS
  current?: number;
  total?: number;
  // NEED_CONFIRM
  action_tag?: string;
  question?: string;
  severity?: "low" | "medium" | "high";
  // ERROR
  error_type?: string;
  message?: string;
  retryable?: boolean;
  // TASK_FINISHED
  status?: "completed" | "failed" | "cancelled";
  total_steps?: number;
  // HEARTBEAT
  seq?: number;
  // TASK_STATE_CHANGED
  from_state?: string;
  to_state?: string;
  reason?: string;
}

/** WebSocket 推送的 RuntimeEvent —— 与后端 protocol/schemas.py RuntimeEvent 对齐 */
export interface RuntimeEvent {
  readonly version: string;
  readonly event_id: string;
  readonly event: EventType;
  readonly ts: string;
  readonly task_id: string;
  readonly payload: RuntimeEventPayload;
}

/** 保持向后兼容: AgentStreamEvent 是 RuntimeEvent 的别名 */
export type AgentStreamEvent = RuntimeEvent;

/** 任务提交请求 */
export interface CreateTaskRequest {
  goal: string;
}

/** 任务提交响应 */
export interface CreateTaskResponse {
  task_id: string;
  state: string;
}
