"use client";

import { Activity, Zap } from "lucide-react";

interface TimelineHeaderProps {
  readonly eventCount: number;
  readonly isConnected?: boolean;
}

/**
 * Timeline 顶部: 步骤流标题 + Event/连接状态
 */
export function TimelineHeader({
  eventCount,
  isConnected,
}: TimelineHeaderProps): React.ReactElement {
  return (
    <div className="flex items-center justify-between border-b border-outline-variant px-4 py-3">
      <div className="flex items-center gap-2 text-sm font-semibold text-on-surface">
        <Activity size={16} className="text-primary" />
        <span>执行时间轴</span>
        {isConnected !== undefined && (
          <span
            className={`ml-1 h-2 w-2 rounded-full ${isConnected ? "bg-green-500" : "bg-gray-400"}`}
            title={isConnected ? "已连接" : "未连接"}
          />
        )}
      </div>
      <div className="flex items-center gap-1 font-mono text-xs text-on-surface-variant">
        <Zap size={12} />
        <span>Events: {eventCount.toLocaleString()}</span>
      </div>
    </div>
  );
}
