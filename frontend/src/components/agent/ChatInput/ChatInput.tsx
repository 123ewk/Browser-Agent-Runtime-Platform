"use client";

import { ModeToggle } from "./ModeToggle";
import { ChatTextField } from "./ChatTextField";
import { ChatSendButton } from "./ChatSendButton";
import { useChatSubmit } from "./use-chat-submit";

/**
 * 底部固定输入栏 —— 容器只做组合,业务逻辑在 useChatSubmit
 * 子组件 ≤ 50 行,便于单测和样式调整
 */
export function ChatInput(): React.ReactElement {
  const { disabled, isPending, error, onSend, clearError } = useChatSubmit();

  return (
    <div className="flex flex-col border-t border-outline-variant bg-surface-container-lowest px-4 py-3">
      <div className="flex items-center gap-2">
        <ModeToggle />
        <ChatTextField
          disabled={disabled}
          hasError={error !== null}
          onSubmit={onSend}
          onInput={clearError}
        />
        <ChatSendButton
          disabled={disabled}
          loading={isPending}
          onClick={onSend}
        />
      </div>
      {error !== null && (
        <p className="mt-1.5 pl-11 text-xs text-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
