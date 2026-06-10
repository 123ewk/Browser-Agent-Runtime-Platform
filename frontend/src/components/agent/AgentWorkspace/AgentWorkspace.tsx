"use client";

import { Plus } from "lucide-react";
import { TaskList } from "../TaskList";
import { Timeline } from "../Timeline";
import { BrowserPreview } from "../BrowserPreview";
import { ChatInput } from "../ChatInput";
import { useAgentWorkspaceStore } from "@/lib/store/agent-workspace";

/**
 * Agent Workspace 整体布局
 *
 * 桌面端:固定 3 列宽 (320 / 1fr / 420),底部输入栏跨满
 * 移动端:堆叠为单列,任务列表折叠为顶部选择器(后续在移动端布局里再处理)
 *
 * 「+ 新建任务」按钮:
 * 显式清空 activeTaskId,作为用户被「旧任务卡死」时的逃生通道。
 * 配合 use-chat-submit 的白名单 disabled 判定,任何状态下(除正在 running)
 * 用户都能切到新任务输入态。
 */
export function AgentWorkspace(): React.ReactElement {
  const clearActiveTask = useAgentWorkspaceStore((s) => s.clearActiveTask);

  return (
    <div className="flex h-[calc(100vh-56px)] flex-col">
      <div className="grid flex-1 min-h-0 grid-cols-1 lg:grid-cols-[320px_1fr_420px]">
        <aside className="hidden border-r border-outline-variant bg-surface-container-low lg:block">
          <div className="flex items-center justify-between border-b border-outline-variant px-4 py-3">
            <span className="text-sm font-semibold text-on-surface">
              活动任务
            </span>
            <button
              type="button"
              onClick={clearActiveTask}
              title="清空当前选中,准备新建任务"
              aria-label="新建任务"
              className="inline-flex items-center gap-1 rounded-md border border-outline-variant bg-surface-container-lowest px-2 py-1 text-xs font-medium text-on-surface-variant transition-colors hover:bg-primary-container/20 hover:text-primary hover:border-primary-container/40"
            >
              <Plus size={12} />
              新建任务
            </button>
          </div>
          <div className="h-[calc(100%-49px)] overflow-y-auto">
            <TaskList />
          </div>
        </aside>

        <section className="flex min-h-0 flex-col border-r border-outline-variant bg-surface-container-lowest">
          <Timeline />
        </section>

        <aside className="hidden min-h-0 flex-col bg-surface-container-lowest lg:flex">
          <BrowserPreview />
        </aside>
      </div>
      <ChatInput />
    </div>
  );
}
