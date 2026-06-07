/**
 * Query Keys 工厂 —— 集中管理所有 query key
 *
 * 用工厂模式避免散落各处的字符串数组,保证 invalidate / prefetch
 * 时类型安全。修改 key 只需要改这里。
 */
export const queryKeys = {
  stats: {
    all: ["stats"] as const,
    dashboard: (window: string) =>
      [...queryKeys.stats.all, "dashboard", window] as const,
  },
  tasks: {
    all: ["tasks"] as const,
    list: (params: object) =>
      [...queryKeys.tasks.all, "list", params] as const,
    detail: (id: string) =>
      [...queryKeys.tasks.all, "detail", id] as const,
  },
  agents: {
    all: ["agents"] as const,
    list: () => [...queryKeys.agents.all, "list"] as const,
  },
  timeline: {
    all: ["timeline"] as const,
    byTask: (taskId: string) =>
      [...queryKeys.timeline.all, "byTask", taskId] as const,
  },
} as const;
