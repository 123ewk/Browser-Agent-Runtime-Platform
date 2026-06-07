"use client";

import { ModeToggle } from "./ModeToggle";
import { ChatTextField } from "./ChatTextField";
import { ChatSendButton } from "./ChatSendButton";
import { useChatSubmit } from "./use-chat-submit";

/**
 * 底部固定输入栏 —— 容器只做组合,业务逻辑在 useChatSubmit
 * 各子组件 ≤ 50 行,便于单测和样式调整
 */
export function ChatInput(): React.ReactElement {
  const { disabled, onSend } = useChatSubmit();
  return (
    <div className="flex items-center gap-2 border-t border-outline-variant bg-surface-container-lowest px-4 py-3">
      <ModeToggle />
      <ChatTextField disabled={disabled} onSubmit={onSend} />
      <ChatSendButton disabled={disabled} onClick={onSend} />
    </div>
  );
}
