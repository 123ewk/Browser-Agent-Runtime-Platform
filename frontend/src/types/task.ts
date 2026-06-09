/**
 * 任务状态机 —— 与后端 `app/runtime/protocol/types.py` TaskState 枚举对齐
 *
 * 状态机: pending → running → (completed | failed | cancelled)
 *         running → waiting_confirm ⇄ running(半自动模式)
 *         running → paused ⇄ running
 *         running → stopping → cancelled
 */
export type TaskStatus =
  | "pending"
  | "running"
  | "waiting_confirm"
  | "paused"
  | "stopping"
  | "completed"
  | "failed"
  | "cancelled";

/** 任务摘要 —— 列表/卡片场景使用 */
export interface TaskSummary {
  readonly id: string;
  readonly goal: string;
  readonly agentName: string;
  readonly status: TaskStatus;
  readonly createdAt: string; // ISO 8601
  readonly updatedAt: string; // ISO 8601
  readonly costUsd: number;
}

/** 任务详情 —— /tasks/[id] 使用 */
export interface TaskDetail extends TaskSummary {
  readonly totalDurationSec: number;
  readonly totalTokens: number;
  readonly steps: readonly TaskStep[];
  readonly screenshots: readonly ScreenshotRef[];
  readonly skillCalls: readonly SkillCall[];
}

/** 单步执行记录 */
export interface TaskStep {
  readonly index: number;
  readonly kind: "think" | "tool" | "observe" | "human" | "complete";
  readonly title: string;
  readonly summary: string;
  readonly startedAt: string;
  readonly durationMs: number;
  readonly tokens: number;
}

/** 截图引用 —— S3 / OSS 预签名 URL */
export interface ScreenshotRef {
  readonly id: string;
  readonly url: string;
  readonly capturedAt: string;
  readonly pageUrl: string;
}

/** Skill 调用(用于 React Flow 渲染) */
export interface SkillCall {
  readonly id: string;
  readonly skillName: string;
  readonly inputs: Readonly<Record<string, unknown>>;
  readonly output: unknown;
  readonly startedAt: string;
  readonly durationMs: number;
}
