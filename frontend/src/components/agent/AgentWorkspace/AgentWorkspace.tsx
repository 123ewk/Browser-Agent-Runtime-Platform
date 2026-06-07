"use client";

import { TaskList } from "../TaskList";
import { Timeline } from "../Timeline";
import { BrowserPreview } from "../BrowserPreview";
import { ChatInput } from "../ChatInput";

/**
 * Agent Workspace 整体布局
 *
 * 桌面端:固定 3 列宽 (320 / 1fr / 420),底部输入栏跨满
 * 移动端:堆叠为单列,任务列表折叠为顶部选择器(后续在移动端布局里再处理)
 */
export function AgentWorkspace(): React.ReactElement {
  return (
    <div className="flex h-[calc(100vh-56px)] flex-col">
      <div className="grid flex-1 min-h-0 grid-cols-1 lg:grid-cols-[320px_1fr_420px]">
        <aside className="hidden border-r border-outline-variant bg-surface-container-low lg:block">
          <div className="border-b border-outline-variant px-4 py-3 text-sm font-semibold text-on-surface">
            活动任务
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
