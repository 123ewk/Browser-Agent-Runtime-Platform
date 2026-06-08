"use client";

import { useTaskStream } from "@/lib/ws/use-task-stream";
import { useAgentWorkspaceStore } from "@/lib/store/agent-workspace";
import { TimelineHeader } from "./TimelineHeader";
import { TimelineStepRow } from "./TimelineStepRow";

/**
 * 中栏: Agent 执行时间轴
 *
 * 数据源: WebSocket 实时流(RuntimeEvent),不走 TanStack Query。
 * 行为: 未选中任务时显示空态引导;已选任务实时渲染事件。
 */
export function Timeline(): React.ReactElement {
  const activeId = useAgentWorkspaceStore((s) => s.activeTaskId);
  const { events, isConnected } = useTaskStream(activeId);

  if (!activeId) {
    return (
      <div className="flex h-full flex-col">
        <TimelineHeader eventCount={0} />
        <div className="flex flex-1 items-center justify-center p-6 text-sm text-on-surface-variant">
          请从左侧选择一个任务,查看 Agent 执行时间轴
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <TimelineHeader
        eventCount={events.length}
        isConnected={isConnected}
      />
      <div className="flex-1 overflow-y-auto p-4">
        {!isConnected && events.length === 0 && (
          <div className="text-sm text-on-surface-variant">正在连接 Worker…</div>
        )}
        {isConnected && events.length === 0 && (
          <div className="text-sm text-on-surface-variant">等待 Worker 就绪…</div>
        )}
        <ol className="flex flex-col gap-3">
          {events.map((e) => (
            <TimelineStepRow key={e.event_id} event={e} />
          ))}
        </ol>
      </div>
    </div>
  );
}
