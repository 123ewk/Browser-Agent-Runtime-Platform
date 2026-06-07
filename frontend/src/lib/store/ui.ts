"use client";

import { create } from "zustand";

/**
 * UI 全局状态 —— 只放跟数据无关的"显示态"
 *
 * 数据状态(stasks/agents)放 TanStack Query,不进 store
 * (避免双源同步 / 缓存失效问题)。
 */

interface UIState {
  /** 侧边栏是否折叠(仅移动端有效,桌面端固定展开) */
  readonly sidebarCollapsed: boolean;
  toggleSidebar: () => void;

  /** 当前活跃的 Dashboard 时间窗 */
  readonly statsWindow: "1h" | "24h" | "7d" | "30d";
  setStatsWindow: (w: UIState["statsWindow"]) => void;
}

export const useUIStore = create<UIState>((set) => ({
  sidebarCollapsed: false,
  toggleSidebar: () =>
    set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),

  statsWindow: "24h",
  setStatsWindow: (statsWindow) => set({ statsWindow }),
}));
