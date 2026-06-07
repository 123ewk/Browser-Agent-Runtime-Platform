import type { DashboardStats } from "@/types/stats";
import { apiClient } from "./client";

/** GET /api/stats/dashboard —— Dashboard 顶部统计卡片 */
export async function getDashboardStats(
  window: DashboardStats["window"] = "24h",
): Promise<DashboardStats> {
  const { data } = await apiClient.get<DashboardStats>("/api/stats/dashboard", {
    params: { window },
  });
  return data;
}
