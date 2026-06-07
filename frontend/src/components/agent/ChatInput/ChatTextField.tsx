"use client";

import { useAgentWorkspaceStore } from "@/lib/store/agent-workspace";

interface ChatTextFieldProps {
  readonly disabled: boolean;
  readonly onSubmit: () => void;
}

/** 输入框 —— 受控,Enter 触发提交 */
export function ChatTextField({
  disabled,
  onSubmit,
}: ChatTextFieldProps): React.ReactElement {
  const draft = useAgentWorkspaceStore((s) => s.draft);
  const setDraft = useAgentWorkspaceStore((s) => s.setDraft);
  return (
    <input
      type="text"
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          onSubmit();
        }
      }}
      disabled={disabled}
      placeholder="告诉 Agent 接下来该做什么,或提出问题…"
      className="flex-1 rounded-md border border-outline-variant bg-surface-container-lowest px-3 py-2 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/30 disabled:opacity-50"
    />
  );
}
