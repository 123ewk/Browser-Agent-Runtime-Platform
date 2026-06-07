import { cn } from "@/lib/cn";

export type HealthStatus = "healthy" | "degraded" | "down";

/** 状态色映射 —— Tailwind 完整类名(不能动态拼,否则 purge 不到) */
const STATUS_STYLES: Record<HealthStatus, { dot: string; text: string; bg: string }> = {
  healthy: {
    dot: "bg-status-healthy",
    text: "text-secondary",
    bg: "bg-secondary-container text-on-secondary-container",
  },
  degraded: {
    dot: "bg-status-degraded",
    text: "text-tertiary",
    bg: "bg-tertiary-container text-on-tertiary-container",
  },
  down: {
    dot: "bg-status-down",
    text: "text-error",
    bg: "bg-error-container text-on-error-container",
  },
};

/**
 * Agent 平台健康状态徽章
 *
 * 状态语义:healthy(全绿) / degraded(降级) / down(宕机)
 * 显示在 TopBar 左上,等 Dashboard / Workspace 复用同一组件。
 */
export function HealthIndicator({
  status = "healthy",
  className,
}: {
  readonly status?: HealthStatus;
  readonly className?: string;
}) {
  const s = STATUS_STYLES[status];
  return (
    <span
      className={cn(
        "flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-semibold",
        s.bg,
        className,
      )}
    >
      <span className={cn("h-2 w-2 rounded-full", s.dot)} />
      {status === "healthy" ? "Healthy" : status === "degraded" ? "Degraded" : "Down"}
    </span>
  );
}
