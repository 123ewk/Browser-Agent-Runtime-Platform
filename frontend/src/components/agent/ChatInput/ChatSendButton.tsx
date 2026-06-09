"use client";

import { Send, Loader2 } from "lucide-react";

interface ChatSendButtonProps {
  readonly disabled: boolean;
  readonly loading: boolean;
  readonly onClick: () => void;
}

/** 发送按钮 —— loading 时显示旋转动画,disabled 时降透明度 */
export function ChatSendButton({
  disabled,
  loading,
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
      {loading ? (
        <Loader2 size={16} className="animate-spin" />
      ) : (
        <Send size={16} />
      )}
    </button>
  );
}
