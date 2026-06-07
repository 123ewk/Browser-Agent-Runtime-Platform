"use client";

import { useQuery } from "@tanstack/react-query";
import { getDashboardStats } from "@/lib/api/stats";
import type { DashboardStats } from "@/types/stats";
import { queryKeys } from "./keys";

/** Dashboard 顶部统计查询 */
export function useDashboardStats(
  window: DashboardStats["window"] = "24h",
) {
  return useQuery({
    queryKey: queryKeys.stats.dashboard(window),
    queryFn: () => getDashboardStats(window),
  });
}
