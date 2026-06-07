import type { Agent } from "@/types/agent";
import { apiClient } from "./client";

/** GET /api/agents —— 列出当前用户可见的 Agent */
export async function listAgents(): Promise<readonly Agent[]> {
  const { data } = await apiClient.get<readonly Agent[]>("/api/agents");
  return data;
}
