"use client";

import { useTaskStreamInvalidation } from "@/lib/ws/use-task-stream";
import { useAgentWorkspaceStore } from "@/lib/store/agent-workspace";
import { useTask } from "@/lib/query/tasks";
import { BrowserHeader } from "./BrowserHeader";
import { BrowserScreenshot } from "./BrowserScreenshot";
import { ScreenshotHistory } from "./ScreenshotHistory";

/**
 * 右栏:浏览器预览 + 截图历史
 *
 * 数据:
 *  - 当前截图 URL 从 task detail.screenshots 取最后一条
 *  - 历史缩略图取前 8 条
 *  - WS 推送触发 detail 重新拉取,缩略图自动刷新
 */
export function BrowserPreview(): React.ReactElement {
  const activeId = useAgentWorkspaceStore((s) => s.activeTaskId);
  useTaskStreamInvalidation(activeId);
  const { data } = useTask(activeId);
  const historyOpen = useAgentWorkspaceStore((s) => s.historyOpen);

  const screenshots = data?.screenshots ?? [];
  const current = screenshots[screenshots.length - 1] ?? null;

  return (
    <div className="flex h-full flex-col">
      <BrowserHeader url={current?.pageUrl ?? "—"} />
      <BrowserScreenshot screenshot={current} />
      {historyOpen && <ScreenshotHistory items={screenshots} />}
    </div>
  );
}
