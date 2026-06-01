"""LLM client tests — mostly unit (no network) + extract helpers."""
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from lyrebird.llm.client import (
    strip_json_fence,
    extract_text_blocks,
    LLMClient,
    Role,
)


def test_strip_json_fence_handles_plain_json():
    assert strip_json_fence('{"a": 1}') == '{"a": 1}'


def test_strip_json_fence_strips_markdown_fence():
    raw = '```json\n{"a": 1}\n```'
    assert strip_json_fence(raw) == '{"a": 1}'


def test_strip_json_fence_strips_bare_fence():
    raw = '```\n{"a": 1}\n```'
    assert strip_json_fence(raw) == '{"a": 1}'


def test_strip_json_fence_strips_surrounding_prose():
    raw = 'Here is the JSON:\n```json\n{"a": 1}\n```\nHope that helps.'
    assert strip_json_fence(raw) == '{"a": 1}'


def test_strip_json_fence_finds_first_object():
    raw = 'Sure, here:\n{"a": 1, "b": [1,2]}\nand done.'
    assert strip_json_fence(raw) == '{"a": 1, "b": [1,2]}'


def test_extract_text_blocks_handles_thinking_blocks():
    """deepseek-reasoner returns [ThinkingBlock, TextBlock]."""
    thinking = MagicMock(spec=["thinking"])
    thinking.thinking = "internal"
    text_block = MagicMock(spec=["text"])
    text_block.text = "hello"
    msg = MagicMock()
    msg.content = [thinking, text_block]
    assert extract_text_blocks(msg) == "hello"


def test_extract_text_blocks_concatenates_multiple():
    b1 = MagicMock(spec=["text"]); b1.text = "foo"
    b2 = MagicMock(spec=["text"]); b2.text = "bar"
    msg = MagicMock()
    msg.content = [b1, b2]
    assert extract_text_blocks(msg) == "foobar"


def test_role_maps_to_v4_models():
    assert LLMClient.model_for(Role.HEAVY) == "deepseek-v4-pro"
    assert LLMClient.model_for(Role.STANDARD) == "deepseek-v4-flash"
    assert LLMClient.model_for(Role.FAST) == "deepseek-v4-flash"


def test_role_model_overridable_via_env(monkeypatch):
    monkeypatch.setenv("LYREBIRD_MODEL_HEAVY", "deepseek-v4-flash")
    assert LLMClient.model_for(Role.HEAVY) == "deepseek-v4-flash"
    # Other roles untouched
    assert LLMClient.model_for(Role.STANDARD) == "deepseek-v4-flash"


def test_complete_json_parses_into_pydantic():
    """End-to-end with a mocked transport: schema-validated parse."""
    class Out(BaseModel):
        ok: bool
        n: int

    mock_sdk = MagicMock()
    text_block = MagicMock(spec=["text"])
    text_block.text = '```json\n{"ok": true, "n": 42}\n```'
    mock_msg = MagicMock()
    mock_msg.content = [text_block]
    mock_msg.usage = MagicMock(input_tokens=10, output_tokens=5)
    mock_msg.stop_reason = "end_turn"
    mock_sdk.messages.create.return_value = mock_msg

    client = LLMClient(_sdk=mock_sdk)
    out = client.complete_json(
        role=Role.STANDARD,
        system="x",
        user="y",
        schema=Out,
    )
    assert isinstance(out, Out)
    assert out.ok is True
    assert out.n == 42


def test_complete_json_retries_on_validation_error():
    class Out(BaseModel):
        n: int

    mock_sdk = MagicMock()
    bad = MagicMock(); bad.content = [MagicMock(spec=["text"], text="not json")]
    bad.usage = MagicMock(input_tokens=1, output_tokens=1); bad.stop_reason = "end_turn"
    bad.content[0].text = "totally not json"

    good = MagicMock()
    tb = MagicMock(spec=["text"]); tb.text = '{"n": 7}'
    good.content = [tb]
    good.usage = MagicMock(input_tokens=1, output_tokens=1); good.stop_reason = "end_turn"

    mock_sdk.messages.create.side_effect = [bad, good]

    client = LLMClient(_sdk=mock_sdk, max_retries=2)
    out = client.complete_json(role=Role.STANDARD, system="x", user="y", schema=Out)
    assert out.n == 7
    assert mock_sdk.messages.create.call_count == 2


def test_complete_json_bumps_max_tokens_on_truncation():
    """When the model hits max_tokens (stop_reason=max_tokens), retry with a larger budget.

    Reasoning models (deepseek-v4) emit a ThinkingBlock that consumes tokens
    before the TextBlock; a budget that just barely fit V3 will truncate V4.
    The retry must bump max_tokens, not just re-ask politely.
    """
    class Out(BaseModel):
        n: int

    truncated = MagicMock()
    truncated.content = [MagicMock(spec=["text"], text='{"n": 1')]
    truncated.content[0].text = '{"n": 1'  # unterminated
    truncated.usage = MagicMock(input_tokens=1, output_tokens=1)
    truncated.stop_reason = "max_tokens"

    full = MagicMock()
    tb = MagicMock(spec=["text"]); tb.text = '{"n": 42}'
    full.content = [tb]
    full.usage = MagicMock(input_tokens=1, output_tokens=1)
    full.stop_reason = "end_turn"

    mock_sdk = MagicMock()
    mock_sdk.messages.create.side_effect = [truncated, full]

    client = LLMClient(_sdk=mock_sdk, max_retries=2)
    out = client.complete_json(
        role=Role.STANDARD, system="x", user="y", schema=Out, max_tokens=1000,
    )
    assert out.n == 42
    # Verify second call asked for MORE tokens
    first_kwargs = mock_sdk.messages.create.call_args_list[0].kwargs
    second_kwargs = mock_sdk.messages.create.call_args_list[1].kwargs
    assert second_kwargs["max_tokens"] > first_kwargs["max_tokens"], (
        f"expected bumped max_tokens on truncation retry; "
        f"got {first_kwargs['max_tokens']} → {second_kwargs['max_tokens']}"
    )


def test_complete_json_raises_after_max_retries():
    class Out(BaseModel):
        n: int

    bad = MagicMock()
    bad.content = [MagicMock(spec=["text"], text="not json")]
    bad.content[0].text = "garbage"
    bad.usage = MagicMock(input_tokens=1, output_tokens=1); bad.stop_reason = "end_turn"

    mock_sdk = MagicMock()
    mock_sdk.messages.create.return_value = bad

    client = LLMClient(_sdk=mock_sdk, max_retries=2)
    with pytest.raises(Exception):
        client.complete_json(role=Role.STANDARD, system="x", user="y", schema=Out)
    assert mock_sdk.messages.create.call_count == 2
