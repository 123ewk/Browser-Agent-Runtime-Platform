import type { Agent } from "./agent";

/**
 * Dashboard 统计聚合 —— 后端从 Redis 实时聚合
 *
 * `window` 字段说明数据时间窗(默认 "24h"),
 * 后续切到 7d / 30d 不需要前端再聚合。
 */
export interface DashboardStats {
  readonly window: "1h" | "24h" | "7d" | "30d";
  readonly tasksToday: number;
  readonly tasksTodayDeltaPct: number;
  readonly running: number;
  readonly successRate: number; // 0..1
  readonly tokensToday: number;
  readonly tokensTodayDeltaPct: number;
  readonly costTodayUsd: number;
  readonly estimatedMonthlyCostUsd: number;
  readonly agents: readonly Agent[];
}
