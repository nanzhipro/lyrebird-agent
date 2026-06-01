"""Base Agent abstraction.

All worker agents share the same shape:
  - a name
  - an LLM role (HEAVY/STANDARD/FAST)
  - one or more skills loaded from SkillsLibrary
  - a strict Pydantic output schema
  - a system prompt assembled from skill bodies + agent persona
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional, Type, TypeVar

from pydantic import BaseModel

from lyrebird.llm.client import LLMClient, Role
from lyrebird.observability import EventBus, EventType
from lyrebird.skills import SkillsLibrary

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


@dataclass
class AgentContext:
    """Runtime context passed to every agent invocation.

    `bus` is optional — when None (e.g. unit tests, CLI), agents stay silent.
    """
    llm: LLMClient
    skills: SkillsLibrary
    run_id: str
    bus: Optional[EventBus] = None
    current_stage: Optional[str] = None  # set by Pipeline; tagged on agent events


@dataclass
class BaseAgent:
    name: str
    role: Role
    skill_names: List[str] = field(default_factory=list)
    persona: str = ""  # short role description, prepended to skills
    max_tokens: int = 4096
    temperature: float = 0.3

    def build_system_prompt(self, ctx: AgentContext, extras: Optional[str] = None) -> str:
        parts: List[str] = []
        if self.persona:
            parts.append(f"<role>\n{self.persona}\n</role>")
        for skill_name in self.skill_names:
            body = ctx.skills.load_body(skill_name)
            parts.append(f"<skill name=\"{skill_name}\">\n{body}\n</skill>")
        if extras:
            parts.append(extras)
        parts.append(
            "<output_contract>\n"
            "Reply with ONLY valid JSON, no markdown fences, no prose. "
            "Schema is given separately by the runtime.\n"
            "</output_contract>"
        )
        return "\n\n".join(parts)

    def run(
        self,
        ctx: AgentContext,
        *,
        user_prompt: str,
        schema: Type[T],
        extras: Optional[str] = None,
    ) -> T:
        system = self.build_system_prompt(ctx, extras=extras)
        log.info("[agent=%s role=%s] running", self.name, self.role.value)

        # Snapshot token counters so we can attribute usage to this call
        tokens_in_before = ctx.llm.stats.input_tokens
        tokens_out_before = ctx.llm.stats.output_tokens
        t0 = time.time()

        if ctx.bus is not None:
            ctx.bus.emit(
                EventType.AGENT_STARTED,
                agent=self.name,
                role=self.role.value,
                model=LLMClient.model_for(self.role),
                stage=ctx.current_stage,
            )

        try:
            result = ctx.llm.complete_json(
                role=self.role,
                system=system,
                user=user_prompt,
                schema=schema,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
        except Exception as e:
            if ctx.bus is not None:
                ctx.bus.emit(
                    EventType.AGENT_FAILED,
                    agent=self.name,
                    stage=ctx.current_stage,
                    error=str(e),
                    duration_ms=int((time.time() - t0) * 1000),
                )
            raise

        if ctx.bus is not None:
            ctx.bus.emit(
                EventType.AGENT_COMPLETED,
                agent=self.name,
                stage=ctx.current_stage,
                duration_ms=int((time.time() - t0) * 1000),
                tokens_in=ctx.llm.stats.input_tokens - tokens_in_before,
                tokens_out=ctx.llm.stats.output_tokens - tokens_out_before,
            )
        return result
