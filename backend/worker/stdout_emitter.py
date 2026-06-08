"""StdoutEmitter —— 将 RuntimeEvent 序列化为 JSON Lines 写入 stdout

设计要点:
- 每条事件一行 JSON,不含换行符,以 \n 分隔
- print() 默认会加 \n,正好符合 JSON Lines 规范
- flush 确保 Runtime 立即收到(不用等缓冲区满)
- JSON 序列化失败时记录日志但不中断 Worker
"""

from __future__ import annotations

import sys

from app.runtime.protocol.schemas import RuntimeEvent


def emit_event(event: RuntimeEvent) -> None:
    """将事件写为一行 JSON 到 stdout 并立即 flush

    这是 Worker 与 Runtime 的唯一通信通道。
    stdout 被 Runtime 的 stdout_reader_loop 消费。
    """
    try:
        line = event.model_dump_json()
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
    except Exception:
        # 序列化失败不应该让 Worker 崩溃,写一条错误到 stderr
        print(
            f"[stdout_emitter] 事件序列化失败: event_id={event.event_id}",
            file=sys.stderr,
            flush=True,
        )
