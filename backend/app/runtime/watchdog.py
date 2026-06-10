"""ProcessWatchdog —— 基于心跳的 Worker 存活监控

职责:
  1. 接收 Worker 心跳事件,记录最后心跳时间
  2. 定期扫描注册表,检测超时 Worker
  3. 超时后发布 WATCHDOG_TIMEOUT 事件到 EventBus
  4. 维护 task_id → WorkerHeartbeatState 注册表

架构定位:
  - Runtime 侧全局单例,与 EventBus / TaskStateManager 同级
  - 不绑定到某个具体的 BrowserTaskRunner,多个 runner 共享
  - 通过 register/unregister 接口与 TaskRunner 生命周期绑定

并发安全:
  - _registry 被 EventBus publish gather 和后台扫描协程并发访问
  - 使用 asyncio.Lock 保护所有读写操作

与 TaskStateManager._watchdog_loop 的区别:
  - TaskStateManager.watchdog 检测"进程重启后 rehydrated 任务是否真活着"
  - ProcessWatchdog 检测"正在运行的 Worker 是否还在发心跳"
  - 两者职责正交,不冲突

Multi-Worker 支持:
  - 注册表是 dict[str, WorkerHeartbeatState],每个 task_id 独立跟踪
  - 未来可通过 worker_id 扩展为多 Worker 并发跟踪
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

import structlog

from app.runtime.event_bus import EventBus
from app.runtime.protocol.constants import HEARTBEAT_LOST_TIMEOUT, HEARTBEAT_SCAN_INTERVAL
from app.runtime.protocol.schemas import RuntimeEvent, WatchdogTimeoutPayload
from app.runtime.protocol.types import EventType, WorkerStatus

logger = structlog.get_logger(__name__)


@dataclass
class WorkerHeartbeatState:
    """单个 Worker 的心跳跟踪状态"""

    task_id: str
    last_seq: int = 0
    last_heartbeat_at: float = 0.0  # time.monotonic()
    status: WorkerStatus = WorkerStatus.RUNNING
    pid: int | None = None
    registered_at: float = field(default_factory=time.monotonic)


class ProcessWatchdog:
    """心跳监控器 —— 接收 WORKER_HEARTBEAT,超时判定,发布 WATCHDOG_TIMEOUT

    用法:
        watchdog = ProcessWatchdog(event_bus)
        watchdog.start()                        # 启动扫描协程
        watchdog.register(task_id, pid)          # Worker 启动时
        event_bus.subscribe(WORKER_HEARTBEAT, watchdog.on_heartbeat)
        ...
        watchdog.unregister(task_id)             # Worker 退出时
        watchdog.stop()                          # 停止扫描协程
    """

    def __init__(
        self,
        event_bus: EventBus,
        *,
        timeout: float | None = None,
        scan_interval: float | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._timeout = timeout if timeout is not None else HEARTBEAT_LOST_TIMEOUT
        self._scan_interval = (
            scan_interval if scan_interval is not None else HEARTBEAT_SCAN_INTERVAL
        )

        # 注册表: task_id → WorkerHeartbeatState
        self._registry: dict[str, WorkerHeartbeatState] = {}
        self._lock = asyncio.Lock()
        self._scan_task: asyncio.Task[None] | None = None

        # 已发布超时的事件(task_id 集合),防止重复触发
        self._fired: set[str] = set()

    # ═══════════════════════════════════════════════════════════
    # 生命周期
    # ═══════════════════════════════════════════════════════════

    def start(self) -> None:
        """启动后台扫描协程(幂等)"""
        if self._scan_task is not None and not self._scan_task.done():
            return
        self._scan_task = asyncio.create_task(
            self._scan_loop(),
            name="process-watchdog",
        )
        logger.info(
            "watchdog.started",
            timeout_s=self._timeout,
            scan_interval_s=self._scan_interval,
        )

    async def stop(self) -> None:
        """停止后台扫描协程(幂等)"""
        if self._scan_task is None:
            return
        self._scan_task.cancel()
        try:
            await self._scan_task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("watchdog.stop_error")
        finally:
            self._scan_task = None
        logger.info("watchdog.stopped")

    # ═══════════════════════════════════════════════════════════
    # 注册表操作
    # ═══════════════════════════════════════════════════════════

    async def register(self, task_id: str, pid: int | None = None) -> None:
        """注册一个 Worker 到监控列表

        幂等: 已存在的 task_id 会重置心跳状态(适用于 Worker 重启后重新注册)
        """
        async with self._lock:
            now = time.monotonic()
            self._registry[task_id] = WorkerHeartbeatState(
                task_id=task_id,
                last_heartbeat_at=now,
                pid=pid,
                registered_at=now,
            )
            self._fired.discard(task_id)
        logger.debug("watchdog.registered", task_id=task_id, pid=pid)

    async def unregister(self, task_id: str) -> None:
        """从监控列表移除一个 Worker

        在 Worker 正常退出/cleanup 时调用,防止 Watchdog 误报超时。
        """
        async with self._lock:
            self._registry.pop(task_id, None)
            self._fired.discard(task_id)
        logger.debug("watchdog.unregistered", task_id=task_id)

    async def update_heartbeat(
        self,
        task_id: str,
        seq: int,
        status: WorkerStatus = WorkerStatus.RUNNING,
        pid: int | None = None,
    ) -> None:
        """更新心跳时间戳

        由 on_heartbeat 调用,也暴露为公共接口方便测试。
        若 Worker 在超时触发后恢复心跳,清除 _fired 标记以允许再次检测超时。
        """
        async with self._lock:
            state = self._registry.get(task_id)
            if state is None:
                return
            state.last_seq = seq
            state.last_heartbeat_at = time.monotonic()
            state.status = status
            if pid is not None:
                state.pid = pid
            # Worker 恢复心跳,清除超时标记(允许未来再次检测到超时)
            self._fired.discard(task_id)

    # ═══════════════════════════════════════════════════════════
    # EventBus Handler
    # ═══════════════════════════════════════════════════════════

    async def on_heartbeat(self, event: RuntimeEvent) -> None:
        """EventBus WORKER_HEARTBEAT 事件处理

        从事件 payload 提取 seq/status/pid,更新对应 task 的心跳状态。
        """
        payload = event.payload
        seq = payload.get("seq", 0)
        status_str = payload.get("status", WorkerStatus.RUNNING.value)
        pid = payload.get("pid")
        try:
            status = WorkerStatus(status_str)
        except ValueError:
            status = WorkerStatus.RUNNING

        await self.update_heartbeat(
            task_id=event.task_id,
            seq=seq,
            status=status,
            pid=pid,
        )

    # ═══════════════════════════════════════════════════════════
    # 查询接口
    # ═══════════════════════════════════════════════════════════

    def get_state(self, task_id: str) -> WorkerHeartbeatState | None:
        """获取指定 Worker 的心跳状态

        注意: 此方法无锁保护,仅在 asyncio 单线程事件循环上下文中调用安全。
        若未来引入多线程(如监控指标采集线程),需改为 async + Lock。
        """
        return self._registry.get(task_id)

    @property
    def active_count(self) -> int:
        """当前监控的 Worker 数量(仅限 asyncio 单线程上下文调用)"""
        return len(self._registry)

    # ═══════════════════════════════════════════════════════════
    # 内部: 超时扫描
    # ═══════════════════════════════════════════════════════════

    async def _scan_loop(self) -> None:
        """后台扫描主循环

        每 scan_interval 秒遍历注册表,检查超时 Worker。
        单次扫描异常不影响下次扫描(CancelledError 除外)。
        """
        try:
            while True:
                await asyncio.sleep(self._scan_interval)
                try:
                    await self._sweep()
                except Exception:
                    logger.exception("watchdog.sweep_error")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.critical("watchdog.scan_loop_crashed", exc_info=True)
            raise

    async def _sweep(self) -> None:
        """遍历注册表,超时 Worker 发布 WATCHDOG_TIMEOUT

        三步:
        1. 快照注册表(在锁内复制引用)
        2. 逐条判断超时
        3. 超时则发布事件

        TOCTOU 说明:
        快照时刻未超时但二次确认时已超时的 task,会在下次扫描被捕获,
        延迟最多一个 scan_interval(15s),可接受。
        快照时刻已超时但二次确认时已被 unregister 的 task,会被跳过(正确行为)。
        """
        now = time.monotonic()

        # 在锁内快照
        async with self._lock:
            snapshot = dict(self._registry)

        # 锁外交互(EventBus.publish 可能阻塞,不应在锁内执行)
        to_fire: list[tuple[str, WorkerHeartbeatState]] = []
        for task_id, state in snapshot.items():
            elapsed = now - state.last_heartbeat_at
            if elapsed >= self._timeout:
                # 二次确认:还在注册表中(没有被其他路径先处理掉)
                async with self._lock:
                    if task_id in self._fired:
                        continue
                    if task_id not in self._registry:
                        continue
                    self._fired.add(task_id)
                to_fire.append((task_id, state))
                logger.warning(
                    "watchdog.timeout",
                    task_id=task_id,
                    last_seq=state.last_seq,
                    seconds_since_last=round(elapsed, 1),
                    pid=state.pid,
                )

        for task_id, state in to_fire:
            await self._fire_timeout(task_id, state)

    async def _fire_timeout(self, task_id: str, state: WorkerHeartbeatState) -> None:
        """发布 WATCHDOG_TIMEOUT 事件并清理注册表"""
        elapsed = time.monotonic() - state.last_heartbeat_at

        event = RuntimeEvent(
            event_id=f"evt-{uuid4().hex[:12]}",
            event=EventType.WATCHDOG_TIMEOUT,
            ts=datetime.now(UTC),
            task_id=task_id,
            payload=WatchdogTimeoutPayload(
                last_heartbeat_seq=state.last_seq,
                seconds_since_last=round(elapsed, 1),
                task_id=task_id,
                worker_pid=state.pid,
                status_at_last=state.status.value,
            ).model_dump(),
        )

        await self._event_bus.publish(event)

        # 不从注册表移除:若 Worker 恢复心跳,update_heartbeat 会清除 _fired 标记,
        # Watchdog 可再次检测到超时。真正的清理由 TaskRunner.cleanup() → unregister 完成。
