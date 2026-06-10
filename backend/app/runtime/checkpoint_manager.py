"""CheckpointManager —— Checkpoint 生命周期管理 + EventBus 集成

职责:
1. 通过 EventBus 订阅自动触发: ERROR / TASK_FINISHED / NEED_CONFIRM 场景
2. 对外暴露 save_task_checkpoint() 供 auto-loop 在 STEP_COMPLETE 后调用
3. 对外暴露 resume_from_latest() 供 resume API 使用

为什么 STEP_COMPLETE 走显式调用而非 EventBus:
- Checkpoint 需要积累态(trajectory 历史),不能从单次事件重建
- TimelineRecorder 的 STEP_COMPLETE handler 是单步独立的,不需要积累态

数据流:
  _run_task() 循环
    → STEP_COMPLETE
    → trajectory.add_step()
    → checkpoint_manager.save_task_checkpoint(task_id, state_data)
    → PolicyEngine.decide()

  CheckpointManager._on_event (EventBus)
    → ERROR → save_checkpoint(type="error")
    → TASK_FINISHED → save_checkpoint(type="final")
    → NEED_CONFIRM → save_checkpoint(type="manual")
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

import structlog

from app.infra.postgres import PostgresClient
from app.repository.checkpoint import CheckpointRepository
from app.runtime.event_bus import EventBus
from app.runtime.protocol.schemas import RuntimeEvent
from app.runtime.protocol.types import EventType
from app.runtime.task_state import TaskStateManager
from app.schema.checkpoint import FullCheckpointState

logger = structlog.get_logger(__name__)

# auto-save 间隔:每 N 步存一次(避免每步都写 DB)
AUTO_SAVE_INTERVAL = 5

# 触发 save 的关键动作关键词(含任一即存)
CRITICAL_ACTIONS = {"submit", "login", "pay", "delete", "confirm", "purchase"}


class CheckpointManager:
    """Checkpoint 管理器 —— 统一的 Checkpoint 生命周期

    用法:
        mgr = CheckpointManager(event_bus, pg_client, task_state_mgr)
        await mgr.subscribe_all()           # 启动时订阅事件
        await mgr.save_task_checkpoint(...)  # auto-loop 调用
        state = await mgr.resume_from_latest(task_id)  # resume API 调用
    """

    def __init__(
        self,
        event_bus: EventBus,
        pg_client: PostgresClient,
        task_state_mgr: TaskStateManager,
    ) -> None:
        self._event_bus = event_bus
        self._pg_client = pg_client
        self._task_state_mgr = task_state_mgr

    async def subscribe_all(self) -> None:
        """订阅 EventBus 事件 —— 在 lifespan startup 时调用

        为什么不在 __init__ 里订阅: CheckpointManager 初始化可能在 EventBus
        就绪之前,延迟订阅避免竞态。
        """
        self._event_bus.subscribe(EventType.ERROR, self._on_error)
        self._event_bus.subscribe(EventType.TASK_FINISHED, self._on_task_finished)
        self._event_bus.subscribe(EventType.NEED_CONFIRM, self._on_need_confirm)
        logger.info("checkpoint_manager.subscribed")

    async def unsubscribe_all(self) -> None:
        """取消订阅 —— cleanup 时使用"""
        self._event_bus.unsubscribe(EventType.ERROR, self._on_error)
        self._event_bus.unsubscribe(EventType.TASK_FINISHED, self._on_task_finished)
        self._event_bus.unsubscribe(EventType.NEED_CONFIRM, self._on_need_confirm)
        logger.info("checkpoint_manager.unsubscribed")

    @staticmethod
    def _compute_hash(state: FullCheckpointState) -> str:
        """计算 state 的 SHA256(用于完整性校验)

        必须与 _verify_integrity 使用相同算法(json.dumps sort_keys),
        否则存储和校验用的 hash 不一致,导致每次 resume 都触发哈希不匹配。
        """
        raw = json.dumps(state.model_dump(), sort_keys=True).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    # ═══════════════════════════════════════════════════════════
    # 公共 Save 接口
    # ═══════════════════════════════════════════════════════════

    async def save_task_checkpoint(
        self,
        task_id: str,
        goal: str,
        step_index: int,
        trajectory_summary: str,
        *,
        checkpoint_type: str = "auto",
        current_subgoal: str = "",
        action_result: str = "",
        action_url: str | None = None,
        page_title: str | None = None,
        reasoning_context: str = "",
        preferences: list | None = None,
    ) -> None:
        """保存一次 Checkpoint —— 供 auto-loop 在 STEP_COMPLETE 后调用

        构建 FullCheckpointState → 写入 DB:
        - task 状态来自参数 + TaskStateManager
        - step/memory 状态来自执行上下文
        - worker 状态仅含 browser_storage_state(None = 未存)
        """
        if self._pg_client is None:
            logger.warning("checkpoint.save_skipped_no_db", task_id=task_id)
            return

        status = self._task_state_mgr.get_state(task_id).value

        pref_list = []
        if preferences:
            pref_list = [{"key": p.key, "content": p.content} for p in preferences]

        state = FullCheckpointState(
            version=1,
            task={
                "task_id": task_id,
                "status": status,
                "goal": goal,
                "current_subgoal": current_subgoal,
                "current_step_index": step_index,
                "max_steps": 20,
            },
            step={
                "current_action": "",
                "action_result": action_result,
                "action_url": action_url,
                "page_title": page_title,
            },
            memory={
                "trajectory_summary": trajectory_summary,
                "reasoning_context": reasoning_context,
                "user_preferences": pref_list,
            },
            meta={
                "schema_version": 1,
                "checkpoint_type": checkpoint_type,
                "created_at": datetime.now(UTC).isoformat(),
            },
        )

        session = self._pg_client.session()
        try:
            repo = CheckpointRepository(session)
            snapshot_hash = self._compute_hash(state)
            await repo.create(
                UUID(task_id),
                state.model_dump(),
                checkpoint_type=checkpoint_type,
                schema_version=1,
                snapshot_hash=snapshot_hash,
            )
            await session.commit()
            logger.info(
                "checkpoint.saved",
                task_id=task_id,
                step=step_index,
                cp_type=checkpoint_type,
            )
        except Exception:
            await session.rollback()
            logger.warning("checkpoint.save_failed", task_id=task_id, exc_info=True)
        finally:
            await session.close()

    # ═══════════════════════════════════════════════════════════
    # 公共 Resume 接口
    # ═══════════════════════════════════════════════════════════

    async def resume_from_latest(
        self,
        task_id: UUID,
    ) -> FullCheckpointState | None:
        """从最新 checkpoint 恢复 FullCheckpointState

        完整性校验:
        1. 取最新 checkpoint
        2. 校验 snapshot_hash(数据损坏检测)
        3. 损坏时尝试前一个

        Returns:
            FullCheckpointState 或 None(无可用 checkpoint)
        """
        if self._pg_client is None:
            logger.warning("checkpoint.resume_skipped_no_db", task_id=str(task_id))
            return None

        session = self._pg_client.session()
        try:
            repo = CheckpointRepository(session)
            cp = await repo.get_latest_by_task(task_id)
            if cp is None:
                logger.info("checkpoint.no_checkpoint", task_id=str(task_id))
                return None

            if not self._verify_integrity(cp.state_data, cp.snapshot_hash):
                logger.warning(
                    "checkpoint.hash_mismatch",
                    task_id=str(task_id),
                    cp_id=str(cp.id),
                )
                cp = await repo.get_previous_by_task(task_id, cp.id)
                if cp is None:
                    logger.error("checkpoint.no_valid_checkpoint", task_id=str(task_id))
                    return None
                logger.info("checkpoint.fell_back_to_previous", task_id=str(task_id))

            state = FullCheckpointState.model_validate(cp.state_data)
            await session.commit()
            logger.info(
                "checkpoint.resume_loaded",
                task_id=str(task_id),
                step=state.task.current_step_index,
                version=state.meta.schema_version,
            )
            return state
        except Exception:
            await session.rollback()
            logger.exception("checkpoint.resume_failed", task_id=str(task_id))
            return None
        finally:
            await session.close()

    # ═══════════════════════════════════════════════════════════
    # EventBus Handlers
    # ═══════════════════════════════════════════════════════════

    async def _on_error(self, event: RuntimeEvent) -> None:
        """ERROR 事件 → 保存 error 类型 checkpoint(不可恢复错误时)"""
        if not event.payload.get("retryable", True):
            await self._save_from_event(event, checkpoint_type="error")

    async def _on_task_finished(self, event: RuntimeEvent) -> None:
        """TASK_FINISHED 事件 → 保存 final 类型 checkpoint"""
        await self._save_from_event(event, checkpoint_type="final")

    async def _on_need_confirm(self, event: RuntimeEvent) -> None:
        """NEED_CONFIRM 事件 → 保存 manual 类型 checkpoint(人工确认前保险)"""
        await self._save_from_event(event, checkpoint_type="manual")

    async def _save_from_event(
        self,
        event: RuntimeEvent,
        checkpoint_type: str = "auto",
    ) -> None:
        """从 EventBus 事件构建并保存 checkpoint(非 auto-loop 场景)

        从事件 payload 提取可用的状态信息,缺失字段用默认值。
        """
        if self._pg_client is None:
            return
        step_index = event.payload.get("step_index", 0)
        message = event.payload.get("message") or event.payload.get("summary", "")
        url = event.payload.get("url") or event.payload.get("details", {}).get("url")

        await self.save_task_checkpoint(
            task_id=event.task_id,
            goal="",
            step_index=step_index,
            trajectory_summary="",
            checkpoint_type=checkpoint_type,
            action_result=message[:200],
            action_url=url,
        )

    # ═══════════════════════════════════════════════════════════
    # 触发策略判定
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def should_save_on_step(
        step_index: int,
        action_type: str = "",
    ) -> bool:
        """判断是否需要在 STEP_COMPLETE 后保存 checkpoint

        触发条件(任一):
        1. step_index 是 AUTO_SAVE_INTERVAL 的倍数(定期存)
        2. action_type 在 CRITICAL_ACTIONS 中(关键操作)
        3. step_index == 0(第一步,保存初始状态)
        """
        if step_index == 0:
            return True
        if step_index % AUTO_SAVE_INTERVAL == 0:
            return True
        return action_type.lower() in CRITICAL_ACTIONS

    # 内部辅助
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _verify_integrity(state_data: dict, snapshot_hash: str | None) -> bool:
        """校验 state_data 完整性(snapshot_hash 比对)

        snapshot_hash 为 None 时跳过校验(旧数据没有 hash 字段)
        """
        if snapshot_hash is None:
            return True
        raw = json.dumps(state_data, sort_keys=True).encode("utf-8")
        computed = hashlib.sha256(raw).hexdigest()
        return computed == snapshot_hash
