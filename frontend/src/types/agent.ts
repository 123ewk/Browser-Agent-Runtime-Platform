/**
 * Agent 健康状态 —— Dashboard / Workspace 使用
 *
 * 状态语义:
 *   healthy: 最近一次任务成功,且延迟 P95 < 阈值
 *   degraded: 成功但 P95 超阈值,或最近 1h 失败率 > 10%
 *   down: 最近一次任务失败,或心跳超时
 */
export type AgentHealth = "healthy" | "degraded" | "down";

export interface Agent {
  readonly id: string;
  readonly name: string;
  readonly description: string;
  readonly health: AgentHealth;
  readonly lastTaskAt: string | null;
  readonly successRate24h: number; // 0..1
}
