"""协议常量 —— 版本号、超时、缓冲区大小等

V2.5 协议升级 (PROTOCOL_VERSION → "2.0.0"):
- SemVer 三段式: MAJOR.MINOR.PATCH
- MAJOR 不同 → 拒绝连接 (破坏性变更)
- MINOR 不同 → 新事件类型向后兼容读 (旧 Worker 忽略未知事件)
- PATCH 不同 → 完全兼容
"""

from __future__ import annotations

# 协议版本 —— 嵌入每条 RuntimeEvent.version
# Worker 启动时 Runtime 校验兼容性: 主版本 (第 1 段) 不同 → 拒绝连接
PROTOCOL_VERSION = "2.0.0"  # V2.5: SemVer 三段式, MAJOR=2 表达破坏性变更

# 兼容的协议版本列表 —— Runtime 启动时同时接受这些版本的 Worker 连接 (过渡期)
SUPPORTED_PROTOCOL_VERSIONS: list[str] = ["1.0.0", "2.0.0"]

# ── 超时配置 ──
WORKER_READY_TIMEOUT = 10.0  # 等待 WORKER_READY 事件的超时(秒)
WORKER_HEARTBEAT_INTERVAL = 30.0  # Worker 心跳间隔(秒)
HEARTBEAT_LOST_TIMEOUT = 120.0  # 心跳丢失判定超时(秒) = 4 个心跳周期,容忍 3 次连续丢失
HEARTBEAT_SCAN_INTERVAL = 15.0  # Watchdog 扫描间隔(秒),约超时的 1/8
WORKER_STOP_TIMEOUT = 5.0  # 发 STOP 命令后等待 Worker 退出的超时(秒)
WORKER_KILL_TIMEOUT = 2.0  # SIGKILL 后等待进程死亡的超时(秒)
WAITING_USER_TIMEOUT = 300.0  # V2.5: WAITING_USER 状态下等待用户响应的超时(秒), 超时后强制 FAILED

# ── 缓冲区大小 ──
STDIN_QUEUE_MAXSIZE = 100  # Command Queue 最大容量
STDOUT_BUFFER_LIMIT = 1_048_576  # stdout 单行最大字节数(1MB)

# ── Worker 配置 ──
DEFAULT_MAX_STEPS = 20  # 默认最大执行步数
DEFAULT_TIMEOUT_SECONDS = 120  # 默认任务超时(秒)

# ── V2.5 ReAct 配置 ──
REACT_MAX_ITERATIONS = 10  # ReAct agent 最大迭代次数, 防止 LLM 死循环
REACT_LLM_TIMEOUT = 30.0  # ReAct LLM 调用超时(秒), 超时 fallback 到 PolicyEngine
REACT_DEFAULT_MODEL = "deepseek-v4-pro"  # ReAct 默认模型, 需要推理能力
