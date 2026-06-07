import type { AgentStreamEvent } from "@/types/chat";
import { buildWsUrl } from "./ws-url";
import { createBackoffScheduler } from "./backoff";

/**
 * 订阅指定任务的实时事件流
 *
 * - onEvent 由调用方提供,内部仅做消息分发,不做业务缓存
 * - 自动重连(指数退避,上限 5 次),避免瞬时断网导致页面卡死
 * - 返回 unsubscribe,组件卸载时必须调用以释放 socket
 */
export function subscribeTaskStream(
  taskId: string,
  onEvent: (e: AgentStreamEvent) => void,
): () => void {
  let socket: WebSocket | null = null;
  let closed = false;
  const backoff = createBackoffScheduler();

  const open = (): void => {
    if (closed) return;
    socket = new WebSocket(buildWsUrl(taskId));
    socket.onmessage = (msg) => {
      try {
        const parsed = JSON.parse(msg.data) as AgentStreamEvent;
        onEvent(parsed);
      } catch {
        // 解析失败:忽略单条坏消息,不断连以免影响后续推送
      }
    };
    socket.onclose = () => {
      if (closed) return;
      backoff.schedule(open);
    };
    socket.onerror = () => socket?.close();
  };
  open();

  return () => {
    closed = true;
    backoff.cancel();
    socket?.close();
  };
}
