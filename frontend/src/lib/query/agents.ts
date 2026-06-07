"use client";

import { useQuery } from "@tanstack/react-query";
import { listAgents } from "@/lib/api/agents";
import { queryKeys } from "./keys";

/** Agent 列表查询 —— Dashboard 健康卡片使用 */
export function useAgents() {
  return useQuery({
    queryKey: queryKeys.agents.list(),
    queryFn: listAgents,
  });
}
