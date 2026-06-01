"""BaseAgent should emit AGENT_STARTED/COMPLETED through bus when present."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from lyrebird.agents.base import AgentContext, BaseAgent
from lyrebird.llm.client import LLMClient, Role
from lyrebird.observability import EventBus, EventType
from lyrebird.skills import SkillsLibrary


class Tiny(BaseModel):
    ok: bool


@pytest.fixture
def ctx_with_bus():
    skills = SkillsLibrary(root=Path(__file__).resolve().parent.parent / "skills")
    mock_sdk = MagicMock()
    text_block = MagicMock(spec=["text"]); text_block.text = '{"ok": true}'
    mock_msg = MagicMock()
    mock_msg.content = [text_block]
    mock_msg.usage = MagicMock(input_tokens=20, output_tokens=5)
    mock_msg.stop_reason = "end_turn"
    mock_sdk.messages.create.return_value = mock_msg
    llm = LLMClient(_sdk=mock_sdk)
    bus = EventBus(run_id="test_run")
    return AgentContext(llm=llm, skills=skills, run_id="test_run", bus=bus), bus


def test_agent_emits_started_and_completed(ctx_with_bus):
    ctx, bus = ctx_with_bus
    agent = BaseAgent(name="tester", role=Role.STANDARD)
    agent.run(ctx, user_prompt="x", schema=Tiny)
    types = [e.type for e in bus.snapshot()]
    assert EventType.AGENT_STARTED in types
    assert EventType.AGENT_COMPLETED in types


def test_agent_completed_carries_token_attribution(ctx_with_bus):
    ctx, bus = ctx_with_bus
    agent = BaseAgent(name="tester", role=Role.STANDARD)
    agent.run(ctx, user_prompt="x", schema=Tiny)
    completed = [e for e in bus.snapshot() if e.type == EventType.AGENT_COMPLETED][0]
    assert completed.payload["agent"] == "tester"
    assert completed.payload["tokens_in"] == 20
    assert completed.payload["tokens_out"] == 5
    assert "duration_ms" in completed.payload


def test_agent_emits_failed_on_error():
    skills = SkillsLibrary(root=Path(__file__).resolve().parent.parent / "skills")
    mock_sdk = MagicMock()
    bad = MagicMock()
    bad.content = [MagicMock(spec=["text"], text="garbage")]
    bad.content[0].text = "garbage"
    bad.usage = MagicMock(input_tokens=1, output_tokens=1); bad.stop_reason = "end_turn"
    mock_sdk.messages.create.return_value = bad
    llm = LLMClient(_sdk=mock_sdk, max_retries=1)
    bus = EventBus(run_id="test_run")
    ctx = AgentContext(llm=llm, skills=skills, run_id="test_run", bus=bus)
    agent = BaseAgent(name="tester", role=Role.STANDARD)
    with pytest.raises(Exception):
        agent.run(ctx, user_prompt="x", schema=Tiny)
    types = [e.type for e in bus.snapshot()]
    assert EventType.AGENT_STARTED in types
    assert EventType.AGENT_FAILED in types


def test_agent_silent_when_bus_is_none():
    """Backward-compat: ctx without bus must not raise and must not crash."""
    skills = SkillsLibrary(root=Path(__file__).resolve().parent.parent / "skills")
    mock_sdk = MagicMock()
    text_block = MagicMock(spec=["text"]); text_block.text = '{"ok": true}'
    mock_msg = MagicMock()
    mock_msg.content = [text_block]
    mock_msg.usage = MagicMock(input_tokens=1, output_tokens=1)
    mock_msg.stop_reason = "end_turn"
    mock_sdk.messages.create.return_value = mock_msg
    llm = LLMClient(_sdk=mock_sdk)
    ctx = AgentContext(llm=llm, skills=skills, run_id="x", bus=None)
    agent = BaseAgent(name="tester", role=Role.STANDARD)
    # Just confirm no exception
    out = agent.run(ctx, user_prompt="x", schema=Tiny)
    assert out.ok is True
