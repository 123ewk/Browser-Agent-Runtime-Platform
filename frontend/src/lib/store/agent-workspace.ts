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
  /**
   * 显式清空当前选中任务 —— 不等同于 setActiveTaskId(null)。
   *
   * 为什么单独暴露一个方法: 用户点「+ 新建任务」时,意图是"跳出当前任务,
   * 进入新任务输入态",此时清空 activeTaskId 同时清空 draft 即可;
   * 而 setActiveTaskId(null) 也清空 draft(语义相同),但需要一个独立命名
   * 让调用方(AgentWorkspace 顶部按钮)能明确表达"用户主动清空"这个意图,
   * 避免后续 PR 在两个 setter 之间加差异时引入副作用。
   */
  clearActiveTask: () => void;

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
  clearActiveTask: () => set({ activeTaskId: null, draft: "" }),

  runMode: "semi",
  setRunMode: (runMode) => set({ runMode }),

  historyOpen: true,
  toggleHistory: () =>
    set((s) => ({ historyOpen: !s.historyOpen })),

  draft: "",
  setDraft: (draft) => set({ draft }),
  clearDraft: () => set({ draft: "" }),
}));
