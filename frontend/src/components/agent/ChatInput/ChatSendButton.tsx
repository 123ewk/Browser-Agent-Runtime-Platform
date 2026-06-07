"use client";

import { Send } from "lucide-react";

interface ChatSendButtonProps {
  readonly disabled: boolean;
  readonly onClick: () => void;
}

/** 发送按钮 —— 方形 primary,disabled 时降透明度 */
export function ChatSendButton({
  disabled,
  onClick,
}: ChatSendButtonProps): React.ReactElement {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="inline-flex h-10 w-10 items-center justify-center rounded-md bg-primary text-on-primary transition-opacity hover:opacity-90 disabled:opacity-50"
      aria-label="send"
    >
      <Send size={16} />
    </button>
  );
}
