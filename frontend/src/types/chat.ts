/**
 * Chat / 实时通信类型 —— Agent Workspace 底部输入区使用
 *
 * 运行模式语义:
 *   yolo:  Agent 全自动执行,不需要人工确认
 *   semi:  关键步骤(表单提交 / 删除)前弹人工确认
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

/** WebSocket 推送事件 —— 服务端 → 客户端 */
export type AgentStreamEvent =
  | { readonly type: "step"; readonly stepId: string }
  | { readonly type: "screenshot"; readonly url: string }
  | { readonly type: "status"; readonly status: "running" | "paused" | "done" }
  | { readonly type: "human_required"; readonly question: string }
  | { readonly type: "error"; readonly message: string };
