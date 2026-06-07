"use client";

import { useTasks } from "@/lib/query/tasks";
import { useAgentWorkspaceStore } from "@/lib/store/agent-workspace";
import { TaskListItem } from "./TaskListItem";

/**
 * 左栏:该用户的任务列表
 *
 * 行为:
 *  - 默认展示最近 20 条,按 updatedAt 倒序
 *  - 点击切换 active task,触发中/右栏重新拉取数据
 *  - 数据加载/空态/错误三态都内联处理,避免页面级弹窗
 */
export function TaskList(): React.ReactElement {
  const { data, isLoading, isError } = useTasks({ pageSize: 20 });
  const activeId = useAgentWorkspaceStore((s) => s.activeTaskId);
  const setActive = useAgentWorkspaceStore((s) => s.setActiveTaskId);

  if (isLoading) {
    return (
      <div className="p-4 text-sm text-on-surface-variant">加载任务中…</div>
    );
  }
  if (isError) {
    return (
      <div className="p-4 text-sm text-error">任务列表加载失败</div>
    );
  }
  const items = data?.items ?? [];
  if (items.length === 0) {
    return <div className="p-4 text-sm text-on-surface-variant">暂无任务</div>;
  }

  return (
    <ul className="flex flex-col gap-2 p-3" role="list">
      {items.map((t) => (
        <TaskListItem
          key={t.id}
          task={t}
          active={t.id === activeId}
          onClick={() => setActive(t.id)}
        />
      ))}
    </ul>
  );
}
