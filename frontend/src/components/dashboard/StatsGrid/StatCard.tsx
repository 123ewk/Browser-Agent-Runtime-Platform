import { cn } from "@/lib/cn";

/** 单个指标卡 —— 复用 Dashboard 5 个统计位 */
export interface StatCardProps {
  readonly label: string;
  readonly value: string;
  readonly deltaPct?: number;
  readonly deltaLabel?: string;
  readonly icon: React.ReactNode;
  readonly accent?: "primary" | "secondary" | "tertiary";
}

const ACCENT_BG: Record<NonNullable<StatCardProps["accent"]>, string> = {
  primary: "bg-primary-container/15 text-primary-container",
  secondary: "bg-secondary-container/40 text-secondary",
  tertiary: "bg-tertiary-container/30 text-tertiary",
};

/** Delta 颜色:正负都按 DESIGN.md 调色板(>0 secondary,<0 error) */
function DeltaTag({ pct, label }: { readonly pct: number; readonly label?: string }) {
  const positive = pct >= 0;
  return (
    <span
      className={cn(
        "text-xs font-semibold",
        positive ? "text-secondary" : "text-error",
      )}
    >
      {positive ? "↑" : "↓"} {Math.abs(pct).toFixed(0)}%{" "}
      <span className="font-normal text-on-surface-variant">
        {label ?? "vs 昨日"}
      </span>
    </span>
  );
}

export function StatCard({
  label,
  value,
  deltaPct,
  deltaLabel,
  icon,
  accent = "primary",
}: StatCardProps) {
  return (
    <div className="card-base p-5">
      <div className="flex items-center justify-between">
        <span className="text-sm text-on-surface-variant">{label}</span>
        <span
          className={cn(
            "flex h-8 w-8 items-center justify-center rounded",
            ACCENT_BG[accent],
          )}
        >
          {icon}
        </span>
      </div>
      <div className="mt-3 text-3xl font-bold leading-none text-on-surface">
        {value}
      </div>
      {deltaPct !== undefined ? (
        <div className="mt-2">
          <DeltaTag pct={deltaPct} label={deltaLabel} />
        </div>
      ) : null}
    </div>
  );
}
