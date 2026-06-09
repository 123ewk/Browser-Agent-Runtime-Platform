import { apiClient } from "./client";
import type { ChatMessage, RunMode } from "@/types/chat";
import type { TimelineStep } from "@/types/timeline";

/** GET /api/tasks/:id/timeline —— 单独拉取步骤流,允许高频刷新 */
export async function getTaskTimeline(
  taskId: string,
): Promise<readonly TimelineStep[]> {
  const { data } = await apiClient.get<readonly TimelineStep[]>(
    `/tasks/${taskId}/timeline`,
  );
  return data;
}

/** POST /api/tasks/:id/messages —— 用户向 Agent 发送指令 */
export async function postTaskMessage(
  taskId: string,
  content: string,
  runMode: RunMode,
): Promise<ChatMessage> {
  const { data } = await apiClient.post<ChatMessage>(
    `/tasks/${taskId}/messages`,
    { content, runMode },
  );
  return data;
}
