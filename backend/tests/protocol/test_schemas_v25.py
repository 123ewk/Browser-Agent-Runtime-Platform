"""V2.5 新增 Payload 序列化/反序列化测试"""

from __future__ import annotations

from app.runtime.protocol.schemas import (
    InterruptPayload,
    ObserveCompletePayload,
    ResumePayload,
    StepCompletePayload,
    ThinkCompletePayload,
)
from app.schema.agent import AgentPauseResumeOut


class TestThinkCompletePayload:
    def test_minimal(self) -> None:
        p = ThinkCompletePayload(step_index=1, reasoning="test", decision="ACT")
        d = p.model_dump()
        assert d["step_index"] == 1
        assert d["decision"] == "ACT"

    def test_full(self) -> None:
        p = ThinkCompletePayload(
            step_index=3,
            reasoning="I should navigate to Google",
            decision="ACT",
            confidence=0.95,
            tokens_used=150,
            llm_latency_ms=320,
        )
        d = p.model_dump()
        assert d["confidence"] == 0.95
        assert d["tokens_used"] == 150
        assert d["llm_latency_ms"] == 320


class TestObserveCompletePayload:
    def test_empty_observation(self) -> None:
        p = ObserveCompletePayload(step_index=1)
        assert p.url is None
        assert p.dom_summary == ""

    def test_full_observation(self) -> None:
        p = ObserveCompletePayload(
            step_index=2,
            url="https://example.com",
            title="Example Page",
            dom_summary="<button>Click me</button>",
            visible_text="Hello World",
        )
        d = p.model_dump()
        assert d["url"] == "https://example.com"
        assert d["title"] == "Example Page"


class TestInterruptPayload:
    def test_user_interrupt(self) -> None:
        p = InterruptPayload(
            reason="user_interrupt", user_message="stop and search for cats instead"
        )
        d = p.model_dump()
        assert d["reason"] == "user_interrupt"
        assert d["user_message"] == "stop and search for cats instead"

    def test_agent_ask_human(self) -> None:
        p = InterruptPayload(
            reason="agent_ask_human",
            ask_human_block_type="login",
            ask_human_question="Please log in",
        )
        d = p.model_dump()
        assert d["reason"] == "agent_ask_human"
        assert d["ask_human_block_type"] == "login"


class TestResumePayload:
    def test_empty_resume(self) -> None:
        """纯恢复,无反馈 (PAUSE 路径)"""
        p = ResumePayload()
        assert p.feedback == ""
        assert p.ask_human_block_type == ""

    def test_with_feedback(self) -> None:
        """INTERRUPT 路径带用户消息"""
        p = ResumePayload(
            feedback="login info: user=admin",
            ask_human_block_type="login",
            ask_human_question="Please log in",
        )
        d = p.model_dump()
        assert d["feedback"] == "login info: user=admin"
        assert d["ask_human_block_type"] == "login"


class TestStepCompletePayloadV25:
    """V2.5 扩展字段测试"""

    def test_v25_fields_default(self) -> None:
        p = StepCompletePayload(index=1, action="click", summary="clicked")
        assert p.dom_summary == ""
        assert p.visible_text == ""
        assert p.step_type == "act"
        assert p.aborted is False
        assert p.abort_reason == ""

    def test_aborted_step(self) -> None:
        p = StepCompletePayload(
            index=3,
            action="click",
            summary="interrupted",
            aborted=True,
            abort_reason="user_interrupt",
        )
        assert p.aborted is True
        assert p.abort_reason == "user_interrupt"

    def test_with_dom(self) -> None:
        p = StepCompletePayload(
            index=2,
            action="navigate",
            summary="navigated",
            dom_summary="<button>Click</button>",
            visible_text="Welcome to Example",
            duration_ms=1500,
        )
        d = p.model_dump()
        assert d["dom_summary"] == "<button>Click</button>"
        assert d["visible_text"] == "Welcome to Example"
        assert d["duration_ms"] == 1500


class TestAgentPauseResume:
    def test_pause_success(self) -> None:
        p = AgentPauseResumeOut(success=True, agent_id="uuid-1", status="drained")
        d = p.model_dump()
        assert d["success"] is True
        assert d["status"] == "drained"

    def test_resume_failure(self) -> None:
        p = AgentPauseResumeOut(success=False, agent_id="uuid-1", status="active")
        d = p.model_dump()
        assert d["success"] is False
