"use client";

import { Card } from "@/components/shared/Card";
import { useAgents } from "@/lib/query/agents";
import { AgentHealthItem } from "./AgentHealthItem";

/** Dashboard 的 Agent 健康面板 —— 列出所有 Agent + 健康度 */
export function AgentHealth() {
  const { data, isLoading, isError } = useAgents();

  return (
    <Card>
      <div className="border-b border-outline-variant bg-surface-bright px-6 py-4">
        <h3 className="text-base font-semibold text-on-surface">
          Agent 健康状态
        </h3>
        <p className="mt-1 text-sm text-on-surface-variant">
          监控所有 Agent 的运行状况
        </p>
      </div>

      <div className="px-6 py-2">
        {isLoading ? (
          <div className="space-y-3 py-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <div
                key={i}
                className="h-12 animate-pulse rounded bg-surface-container-low"
              />
            ))}
          </div>
        ) : isError || !data ? (
          <div className="py-4 text-sm text-error">Agent 列表加载失败</div>
        ) : data.length === 0 ? (
          <div className="py-4 text-sm text-on-surface-variant">
            暂无可用 Agent
          </div>
        ) : (
          data.map((a) => <AgentHealthItem key={a.id} agent={a} />)
        )}
      </div>
    </Card>
  );
}
