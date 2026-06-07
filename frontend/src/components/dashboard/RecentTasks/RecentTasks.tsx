"use client";

import Link from "next/link";
import { Card } from "@/components/shared/Card";
import { useTasks } from "@/lib/query/tasks";
import { RecentTaskRow } from "./RecentTaskRow";

/** Dashboard 的"最近任务"模块 —— 只取前 8 条,避免接口返回过大 */
export function RecentTasks() {
  const { data, isLoading, isError } = useTasks({ page: 1, pageSize: 8 });

  return (
    <Card>
      <div className="flex items-center justify-between border-b border-outline-variant bg-surface-bright px-6 py-4">
        <h3 className="text-base font-semibold text-on-surface">最近任务</h3>
        <Link
          href="/tasks"
          className="text-sm font-medium text-primary hover:underline"
        >
          查看全部
        </Link>
      </div>

      {isLoading ? (
        <div className="space-y-2 p-6">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="h-12 animate-pulse rounded bg-surface-container-low"
            />
          ))}
        </div>
      ) : isError || !data ? (
        <div className="p-6 text-sm text-error">任务加载失败</div>
      ) : data.items.length === 0 ? (
        <div className="p-6 text-sm text-on-surface-variant">暂无任务</div>
      ) : (
        <table className="w-full text-left">
          <thead className="bg-surface text-[11px] font-semibold uppercase tracking-wide text-on-surface-variant">
            <tr>
              <th className="px-4 py-3">目标</th>
              <th className="px-4 py-3">状态</th>
              <th className="px-4 py-3">创建时间</th>
              <th className="px-4 py-3 text-right">成本</th>
              <th className="px-2 py-3 text-right" colSpan={2} />
            </tr>
          </thead>
          <tbody>
            {data.items.map((t) => (
              <RecentTaskRow key={t.id} task={t} />
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}
