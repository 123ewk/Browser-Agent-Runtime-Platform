"use client";

import { useAgentWorkspaceStore } from "@/lib/store/agent-workspace";
import { useSendMessage } from "@/lib/query/timeline";

/**
 * 提交逻辑 hook —— 封装 disabled 计算 + 草稿发送
 * 单独抽出是为了让 ChatInput 纯做 UI 组合
 */
export function useChatSubmit(): {
  readonly disabled: boolean;
  readonly onSend: () => void;
} {
  const activeId = useAgentWorkspaceStore((s) => s.activeTaskId);
  const draft = useAgentWorkspaceStore((s) => s.draft);
  const clearDraft = useAgentWorkspaceStore((s) => s.clearDraft);
  const runMode = useAgentWorkspaceStore((s) => s.runMode);
  const send = useSendMessage(activeId ?? "");

  const disabled = !activeId || send.isPending;
  const onSend = (): void => {
    if (!activeId || draft.trim() === "") return;
    send.mutate(
      { content: draft.trim(), runMode },
      { onSuccess: clearDraft },
    );
  };
  return { disabled, onSend };
}
