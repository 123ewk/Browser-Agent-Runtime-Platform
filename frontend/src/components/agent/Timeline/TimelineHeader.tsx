import { Activity, Zap } from "lucide-react";

interface TimelineHeaderProps {
  readonly tokens: number;
}

/**
 * Timeline 顶部:步骤流标题 + Token 统计
 *
 * Tokens 用 JetBrains Mono 显示,符合 DESIGN.md "技术元数据" 规范
 */
export function TimelineHeader({
  tokens,
}: TimelineHeaderProps): React.ReactElement {
  return (
    <div className="flex items-center justify-between border-b border-outline-variant px-4 py-3">
      <div className="flex items-center gap-2 text-sm font-semibold text-on-surface">
        <Activity size={16} className="text-primary" />
        <span>执行时间轴</span>
      </div>
      <div className="flex items-center gap-1 font-mono text-xs text-on-surface-variant">
        <Zap size={12} />
        <span>Tokens: {tokens.toLocaleString()}</span>
      </div>
    </div>
  );
}
