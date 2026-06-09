/**
 * 健康检查类型定义 —— 与后端 schema/health.py 对齐
 *
 * 后端端点:
 * - GET /health: 存活探针(永远 200)
 * - GET /ready: 就绪探针(可能返回 degraded)
 */

/** 存活探针响应 */
export interface HealthResponse {
  readonly status: "ok";
}

/** 就绪探针响应 */
export interface ReadyResponse {
  readonly status: "ok" | "degraded";
  readonly deps: Readonly<Record<string, "ok" | "fail">>;
}
