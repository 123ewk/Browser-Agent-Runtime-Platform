"use client";

import {
  Activity,
  CircleDollarSign,
  Coins,
  Gauge,
  type LucideIcon,
  Play,
} from "lucide-react";
import { useDashboardStats } from "@/lib/query/stats";
import { useUIStore } from "@/lib/store/ui";
import { formatCompactNumber } from "@/lib/format/number";
import { formatUsd } from "@/lib/format/currency";
import { StatCard } from "./StatCard";

/** 5 个统计指标的定义 —— 集中配置,改文案/图标只改这里 */
interface StatMeta {
  readonly key:
    | "tasksToday"
    | "running"
    | "successRate"
    | "tokensToday"
    | "costTodayUsd";
  readonly label: string;
  readonly icon: LucideIcon;
  readonly accent: "primary" | "secondary" | "tertiary";
}

const STATS: readonly StatMeta[] = [
  { key: "tasksToday", label: "今日任务", icon: Activity, accent: "primary" },
  { key: "running", label: "运行中", icon: Play, accent: "primary" },
  { key: "successRate", label: "成功率", icon: Gauge, accent: "secondary" },
  { key: "tokensToday", label: "今日 Tokens", icon: Coins, accent: "primary" },
  {
    key: "costTodayUsd",
    label: "今日成本",
    icon: CircleDollarSign,
    accent: "tertiary",
  },
];

/** 格式映射:后端 number → 前端显示字符串 */
function renderValue(
  key: StatMeta["key"],
  v: number,
): string {
  if (key === "successRate") return `${(v * 100).toFixed(1)}%`;
  if (key === "costTodayUsd") return formatUsd(v);
  if (key === "tokensToday") return formatCompactNumber(v);
  return String(v);
}

export function StatsGrid() {
  const window = useUIStore((s) => s.statsWindow);
  const { data, isLoading, isError } = useDashboardStats(window);

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
        {STATS.map((s) => (
          <div key={s.key} className="card-base h-28 animate-pulse" />
        ))}
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="card-base p-6 text-sm text-error">
        统计加载失败,请稍后重试。
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
      {STATS.map((s) => {
        const icon = <s.icon className="h-4 w-4" />;
        if (s.key === "tasksToday") {
          return (
            <StatCard
              key={s.key}
              label={s.label}
              value={renderValue(s.key, data.tasksToday)}
              deltaPct={data.tasksTodayDeltaPct}
              icon={icon}
              accent={s.accent}
            />
          );
        }
        if (s.key === "tokensToday") {
          return (
            <StatCard
              key={s.key}
              label={s.label}
              value={renderValue(s.key, data.tokensToday)}
              deltaPct={data.tokensTodayDeltaPct}
              icon={icon}
              accent={s.accent}
            />
          );
        }
        if (s.key === "costTodayUsd") {
          return (
            <StatCard
              key={s.key}
              label={s.label}
              value={renderValue(s.key, data.costTodayUsd)}
              deltaLabel={`预估 $${data.estimatedMonthlyCostUsd.toFixed(2)}/月`}
              icon={icon}
              accent={s.accent}
            />
          );
        }
        return (
          <StatCard
            key={s.key}
            label={s.label}
            value={renderValue(s.key, data[s.key])}
            icon={icon}
            accent={s.accent}
          />
        );
      })}
    </div>
  );
}
