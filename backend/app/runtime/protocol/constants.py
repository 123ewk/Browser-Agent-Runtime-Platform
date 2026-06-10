"""协议常量 —— 版本号、超时、缓冲区大小等"""

from __future__ import annotations

# 协议版本 —— 嵌入每条 RuntimeEvent.version
# Worker 启动时 Runtime 校验兼容性:主版本不同 → 拒绝连接
PROTOCOL_VERSION = "1.0"

# ── 超时配置 ──
WORKER_READY_TIMEOUT = 10.0  # 等待 WORKER_READY 事件的超时(秒)
WORKER_HEARTBEAT_INTERVAL = 30.0  # Worker 心跳间隔(秒)
HEARTBEAT_LOST_TIMEOUT = 120.0  # 心跳丢失判定超时(秒) = 4 个心跳周期,容忍 3 次连续丢失
HEARTBEAT_SCAN_INTERVAL = 15.0  # Watchdog 扫描间隔(秒),约超时的 1/8
WORKER_STOP_TIMEOUT = 5.0  # 发 STOP 命令后等待 Worker 退出的超时(秒)
WORKER_KILL_TIMEOUT = 2.0  # SIGKILL 后等待进程死亡的超时(秒)

# ── 缓冲区大小 ──
STDIN_QUEUE_MAXSIZE = 100  # Command Queue 最大容量
STDOUT_BUFFER_LIMIT = 1_048_576  # stdout 单行最大字节数(1MB)

# ── Worker 配置 ──
DEFAULT_MAX_STEPS = 20  # 默认最大执行步数
DEFAULT_TIMEOUT_SECONDS = 120  # 默认任务超时(秒)
