import { apiClient } from "./client";
import type { HealthResponse, ReadyResponse } from "@/types/health";

/**
 * 健康检查 API 调用层 —— 与后端 /health /ready 端点对应
 *
 * 后端实现:
 * - GET /health: 200 + { status: "ok" }(存活探针,不需要认证)
 * - GET /ready: 200 + { status, deps }(就绪探针,不需要认证)
 *
 * 注:健康检查端点不需要 Bearer token,后端未加认证依赖。
 */

/** GET /health —— 存活探针 */
export async function getHealth(): Promise<HealthResponse> {
  const { data } = await apiClient.get<HealthResponse>("/health");
  return data;
}

/** GET /ready —— 就绪探针(并行探测 PG/Redis/S3/LLM) */
export async function getReady(): Promise<ReadyResponse> {
  const { data } = await apiClient.get<ReadyResponse>("/ready");
  return data;
}
