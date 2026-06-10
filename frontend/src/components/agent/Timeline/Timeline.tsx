"use client";

import { useTaskStream } from "@/lib/ws/use-task-stream";
import { useTask } from "@/lib/query/tasks";
import { useAgentWorkspaceStore } from "@/lib/store/agent-workspace";
import { TimelineHeader } from "./TimelineHeader";
import { TimelineStepRow } from "./TimelineStepRow";
import { TaskControlBar } from "../TaskControlBar/TaskControlBar";
import type { TaskStatus } from "@/types/task";

/**
 * 中栏: Agent 执行时间轴
 *
 * 数据源: WebSocket 实时流(RuntimeEvent),不走 TanStack Query。
 * 行为: 未选中任务时显示空态引导;已选任务实时渲染事件。
 *
 * 空态分支(2026-06-10 bug 修复, 至少 4 种):
 * - 未选中任务: "请从左侧选择一个任务"
 * - 选中但 WS 未连接 + 无事件: "正在连接 Worker…"
 * - 选中 + WS 已连 + 无事件 + 任务未结束: "等待 Worker 就绪…"
 * - 选中 + WS 已连 + 无事件 + 任务已结束: "任务已结束,共 N 条事件"(新)
 *   修复用户看到"等待 Worker 就绪"但 Worker 早已退出的误导
 */
const TERMINAL_STATUSES: ReadonlySet<TaskStatus> = new Set<TaskStatus>([
  "completed",
  "failed",
  "cancelled",
]);

export function Timeline(): React.ReactElement {
  const activeId = useAgentWorkspaceStore((s) => s.activeTaskId);
  const { events, isConnected } = useTaskStream(activeId);
  // 任务状态: 用于判断 "任务已结束" 状态, 显示第三种空态文案
  // enabled 跟随 activeId(已由 useTask 内部处理, 这里只是取状态)
  const { data: taskDetail } = useTask(activeId);
  const taskStatus = taskDetail?.status as TaskStatus | undefined;
  const isTaskTerminal =
    taskStatus !== undefined && TERMINAL_STATUSES.has(taskStatus);

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
      {/* 任务控制条: 停止/暂停/继续 (2026-06-10 新增逃生通道) */}
      <TaskControlBar />
      <div className="flex-1 overflow-y-auto p-4">
        {!isConnected && events.length === 0 && (
          <div className="text-sm text-on-surface-variant">正在连接 Worker…</div>
        )}
        {isConnected && events.length === 0 && !isTaskTerminal && (
          <div className="text-sm text-on-surface-variant">
            等待 Worker 就绪…
          </div>
        )}
        {isConnected && events.length === 0 && isTaskTerminal && (
          <div className="text-sm text-on-surface-variant">
            任务已结束,共 {events.length} 条事件
          </div>
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
