"use client";

import { useAgentWorkspaceStore } from "@/lib/store/agent-workspace";

interface ChatTextFieldProps {
  readonly disabled: boolean;
  readonly hasError: boolean;
  readonly onSubmit: () => void;
  readonly onInput: () => void;
}

/** 输入框 —— 受控,Enter 触发提交,错误态红框 */
export function ChatTextField({
  disabled,
  hasError,
  onSubmit,
  onInput,
}: ChatTextFieldProps): React.ReactElement {
  const draft = useAgentWorkspaceStore((s) => s.draft);
  const setDraft = useAgentWorkspaceStore((s) => s.setDraft);
  return (
    <input
      type="text"
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onInput={onInput}
      onKeyDown={(e) => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          if (!disabled) onSubmit();
        }
      }}
      disabled={disabled}
      placeholder="告诉浏览器 Agent 你想做什么…"
      className={`flex-1 rounded-md border bg-surface-container-lowest px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/30 disabled:opacity-50 ${
        hasError
          ? "border-error focus:border-error"
          : "border-outline-variant focus:border-primary"
      }`}
    />
  );
}
