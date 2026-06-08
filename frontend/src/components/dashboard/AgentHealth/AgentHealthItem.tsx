import { cn } from "@/lib/cn";
import { HealthIndicator } from "@/components/shared/TopBar";
import { formatRelativeTime } from "@/lib/format/time";
import type { Agent } from "@/types/agent";

/** 单个 Agent 健康条目 —— 左侧 8px 状态条 + 名称 + 指标 */
export function AgentHealthItem({ agent }: { readonly agent: Agent }) {
  return (
    <div className="flex items-center gap-4 border-b border-outline-variant/60 py-3 last:border-b-0">
      <span
        aria-hidden
        className={cn(
          "h-10 w-1 rounded",
          agent.health === "healthy" && "bg-status-healthy",
          agent.health === "degraded" && "bg-status-degraded",
          agent.health === "down" && "bg-status-down",
        )}
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium text-on-surface">
            {agent.name}
          </span>
          <HealthIndicator status={agent.health} className="!px-2 !py-0.5 !text-[11px]" />
        </div>
        <div className="mt-0.5 text-[11px] text-on-surface-variant">
          {agent.description}
        </div>
      </div>
      <div className="text-right text-[11px] text-on-surface-variant">
        <div>
          24h 成功率:{" "}
          <span className="font-mono text-on-surface">
            {(agent.successRate24h * 100).toFixed(0)}%
          </span>
        </div>
        <div>
          {agent.lastTaskAt
            ? `最近 ${formatRelativeTime(agent.lastTaskAt)}`
            : "尚无任务"}
        </div>
      </div>
    </div>
  );
}
