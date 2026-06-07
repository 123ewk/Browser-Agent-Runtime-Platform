"use client";

import { create } from "zustand";
import type { RunMode } from "@/types/chat";

/**
 * Agent Workspace 页面级状态
 *
 * 跟数据无关的"显示态"放这里,数据流(任务列表/timeline)走 TanStack Query。
 * 跨页面共享的 UI 状态(侧边栏/时间窗)放 lib/store/ui.ts,不在此混入。
 */

interface AgentWorkspaceState {
  /** 当前选中的任务 ID —— 决定中/右栏渲染内容 */
  readonly activeTaskId: string | null;
  setActiveTaskId: (id: string | null) => void;

  /** 运行模式:YOLO 全自动 / Semi 半自动(关键步骤弹人工确认) */
  readonly runMode: RunMode;
  setRunMode: (mode: RunMode) => void;

  /** 截图历史侧栏是否展开(右栏内部) */
  readonly historyOpen: boolean;
  toggleHistory: () => void;

  /** 用户草稿消息(切换任务时清空) */
  readonly draft: string;
  setDraft: (v: string) => void;
  clearDraft: () => void;
}

export const useAgentWorkspaceStore = create<AgentWorkspaceState>((set) => ({
  activeTaskId: null,
  setActiveTaskId: (activeTaskId) =>
    set({ activeTaskId, draft: "" }),

  runMode: "semi",
  setRunMode: (runMode) => set({ runMode }),

  historyOpen: true,
  toggleHistory: () =>
    set((s) => ({ historyOpen: !s.historyOpen })),

  draft: "",
  setDraft: (draft) => set({ draft }),
  clearDraft: () => set({ draft: "" }),
}));
