/**
 * WebSocket 端点构造 —— 与 axios 共享 baseURL 但协议升级
 * 走 NEXT_PUBLIC_WS_BASE_URL,缺省回退到当前 origin
 *
 * 对应后端路由: GET /tasks/{task_id}/ws?token=xxx
 * token 通过 query param 传递(浏览器 WebSocket 不支持自定义请求头)
 */
export function buildWsUrl(taskId: string, token?: string): string {
  const base =
    process.env.NEXT_PUBLIC_WS_BASE_URL ??
    (typeof window !== "undefined" ? window.location.origin : "");
  const url = `${base}/tasks/${taskId}/ws`;
  return token ? `${url}?token=${encodeURIComponent(token)}` : url;
}
