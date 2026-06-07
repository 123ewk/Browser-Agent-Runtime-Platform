/**
 * WebSocket 端点构造 —— 与 axios 共享 baseURL 但协议升级
 * 走 NEXT_PUBLIC_WS_BASE_URL,缺省回退到当前 origin
 */
export function buildWsUrl(taskId: string): string {
  const base =
    process.env.NEXT_PUBLIC_WS_BASE_URL ??
    (typeof window !== "undefined" ? window.location.origin : "");
  return `${base}/api/tasks/${taskId}/stream`;
}
