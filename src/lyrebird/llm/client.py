"""DeepSeek-via-Anthropic LLM client.

Per memo/01: DeepSeek exposes an Anthropic-compatible endpoint at
`https://api.deepseek.com/anthropic`. We wrap it so callers ask for a *role*
(HEAVY / STANDARD / FAST) instead of a model name — the role map is the only
place that needs to change if model availability shifts.

The key responsibility of this client is `complete_json`: send a prompt, parse
the response as JSON, validate against a Pydantic schema, retry on failure.
This is the lowest-rent way to get "structured output" out of an API that
doesn't currently expose a strict JSON-schema tool.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Type, TypeVar

from anthropic import Anthropic
from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class Role(str, Enum):
    """Cost/capability tier used by callers — see memo/01."""
    HEAVY = "heavy"        # reasoning-heavy synthesis (Orchestrator, Mechanism Modeler)
    STANDARD = "standard"  # most agents
    FAST = "fast"          # high-frequency structured extraction


# V4 model IDs per https://api-docs.deepseek.com (pricing/quick-start, Mar 2026):
# - deepseek-v4-pro:    heavy reasoning, replaces deepseek-reasoner
# - deepseek-v4-flash:  general chat, replaces deepseek-chat (which is now an alias)
#
# Both models default to thinking-mode on the Anthropic-compatible endpoint:
# msg.content arrives as [ThinkingBlock, TextBlock] and the ThinkingBlock
# consumes part of the max_tokens budget. Budgets MUST be sized to fit
# (thinking_tokens + json_output) — see complete_json's truncation handling.
_MODEL_MAP = {
    Role.HEAVY: "deepseek-v4-pro",
    Role.STANDARD: "deepseek-v4-flash",
    Role.FAST: "deepseek-v4-flash",
}


def extract_text_blocks(msg) -> str:
    """deepseek-reasoner returns [ThinkingBlock, TextBlock]; just stitch text."""
    parts = []
    for block in msg.content:
        if hasattr(block, "text"):
            parts.append(block.text)
    return "".join(parts)


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def strip_json_fence(raw: str) -> str:
    """Strip ```json``` fences and surrounding prose, return the JSON payload.

    Strategy:
    1. If there's a fenced code block, take its inner contents.
    2. Otherwise, find the first balanced { ... } or [ ... ] and return that.
    3. Otherwise, return raw stripped.
    """
    raw = raw.strip()
    m = _FENCE_RE.search(raw)
    if m:
        return m.group(1).strip()

    # find first '{' or '[' and walk to matching close
    start = -1
    for i, ch in enumerate(raw):
        if ch in "{[":
            start = i
            break
    if start == -1:
        return raw

    open_ch = raw[start]
    close_ch = "}" if open_ch == "{" else "]"
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(raw)):
        ch = raw[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return raw[start:i + 1]
    return raw


@dataclass
class CallStats:
    input_tokens: int = 0
    output_tokens: int = 0
    n_calls: int = 0

    def add(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.n_calls += 1


@dataclass
class LLMClient:
    """Thin wrapper over Anthropic SDK pointed at DeepSeek."""
    api_key: Optional[str] = None
    base_url: str = "https://api.deepseek.com/anthropic"
    max_retries: int = 3
    retry_backoff_seconds: float = 1.5
    stats: CallStats = field(default_factory=CallStats)
    _sdk: Any = None  # injectable for tests

    def __post_init__(self):
        if self._sdk is None:
            api_key = self.api_key or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "DEEPSEEK_API_KEY not set. Put it in .env or env."
                )
            self._sdk = Anthropic(base_url=self.base_url, api_key=api_key)

    @staticmethod
    def model_for(role: Role) -> str:
        # Allow per-role override via env, e.g.:
        #   LYREBIRD_MODEL_HEAVY=deepseek-v4-pro
        #   LYREBIRD_MODEL_STANDARD=deepseek-v4-flash
        env_key = f"LYREBIRD_MODEL_{role.value.upper()}"
        return os.environ.get(env_key) or _MODEL_MAP[role]

    # ---------- raw text completion ----------
    def complete_text(
        self,
        *,
        role: Role,
        system: str,
        user: str,
        max_tokens: int = 4096,
        temperature: float = 0.4,
    ) -> str:
        model = self.model_for(role)
        msg = self._sdk.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        if getattr(msg, "usage", None):
            self.stats.add(msg.usage.input_tokens or 0, msg.usage.output_tokens or 0)
        return extract_text_blocks(msg)

    # ---------- JSON-schema-validated completion ----------
    # Max single-request output cap for v4 models. Anthropic SDK accepts up to
    # ~64k; DeepSeek practically tops out lower. We cap conservatively.
    MAX_TOKENS_CAP = 16000

    def complete_json(
        self,
        *,
        role: Role,
        system: str,
        user: str,
        schema: Type[T],
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> T:
        """Call LLM, parse JSON, validate against Pydantic schema. Retries on failure.

        Truncation handling: v4 reasoning models emit a ThinkingBlock that
        consumes part of max_tokens. If the model returns stop_reason="max_tokens",
        we treat the failure as budget-related and bump max_tokens 1.6x on the
        next attempt (rather than naively re-asking the same way).
        """
        json_schema_hint = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        full_system = (
            f"{system}\n\n"
            f"YOU MUST RETURN ONLY VALID JSON, NO MARKDOWN FENCES, NO PROSE.\n"
            f"The JSON MUST validate against this JSON Schema:\n{json_schema_hint}\n"
        )

        last_err: Optional[Exception] = None
        last_raw = ""
        current_max_tokens = max_tokens
        original_user = user
        for attempt in range(1, self.max_retries + 1):
            try:
                model = self.model_for(role)
                msg = self._sdk.messages.create(
                    model=model,
                    max_tokens=current_max_tokens,
                    temperature=temperature,
                    system=full_system,
                    messages=[{"role": "user", "content": user}],
                )
                if getattr(msg, "usage", None):
                    self.stats.add(msg.usage.input_tokens or 0, msg.usage.output_tokens or 0)

                stop_reason = getattr(msg, "stop_reason", None)
                raw = extract_text_blocks(msg)
                last_raw = raw

                # If model hit the budget, do NOT try to parse a half JSON — bump and retry.
                if stop_reason == "max_tokens":
                    raise _Truncated(
                        f"hit max_tokens={current_max_tokens}; text len={len(raw)}"
                    )

                payload = strip_json_fence(raw)
                data = json.loads(payload)
                return schema.model_validate(data)

            except _Truncated as e:
                last_err = e
                bumped = min(int(current_max_tokens * 1.6), self.MAX_TOKENS_CAP)
                log.warning(
                    "complete_json attempt %d/%d truncated (%s); "
                    "bumping max_tokens %d → %d",
                    attempt, self.max_retries, e, current_max_tokens, bumped,
                )
                current_max_tokens = bumped
                if attempt < self.max_retries:
                    time.sleep(self.retry_backoff_seconds * attempt)

            except (json.JSONDecodeError, ValidationError) as e:
                last_err = e
                # Common cause of "Unterminated string": the output looks complete
                # but isn't — e.g. ended mid-string without stop_reason set.
                # Treat very long output ending in suspicious ways as truncated too.
                looks_truncated = isinstance(e, json.JSONDecodeError) and (
                    "Unterminated" in str(e) or "Expecting" in str(e)
                )
                if looks_truncated and current_max_tokens < self.MAX_TOKENS_CAP:
                    bumped = min(int(current_max_tokens * 1.6), self.MAX_TOKENS_CAP)
                    log.warning(
                        "complete_json attempt %d/%d parse-failure looks like truncation (%s); "
                        "bumping max_tokens %d → %d",
                        attempt, self.max_retries, e, current_max_tokens, bumped,
                    )
                    current_max_tokens = bumped
                else:
                    log.warning(
                        "complete_json attempt %d/%d failed: %s",
                        attempt, self.max_retries, e,
                    )
                    user = (
                        f"Your previous reply could not be parsed: {e}\n"
                        f"Reply ONLY with JSON matching the schema. No prose.\n\n"
                        f"Original request:\n{original_user}"
                    )
                if attempt < self.max_retries:
                    time.sleep(self.retry_backoff_seconds * attempt)

            except Exception as e:  # transport/timeout
                last_err = e
                log.warning("complete_json transport error %d/%d: %s",
                            attempt, self.max_retries, e)
                if attempt < self.max_retries:
                    time.sleep(self.retry_backoff_seconds * attempt)

        raise RuntimeError(
            f"complete_json exhausted {self.max_retries} retries. "
            f"Last error: {last_err}. Last raw: {last_raw[:400]!r}"
        )


class _Truncated(Exception):
    """Internal marker: model output hit max_tokens. Distinguished from parse failure."""
    pass
