"""Skeptic Reviewer — stress-tests mechanism_cards against a fixed checklist."""
from __future__ import annotations

from typing import List

from lyrebird.agents.base import AgentContext, BaseAgent
from lyrebird.llm.client import Role
from lyrebird.schemas import (
    EvidenceCard,
    MechanismCard,
    ReviewFindings,
)


PERSONA = """你是怀疑者. 你不创造新机制, 不替候选人辩护. 你只找问题.

你要逐项过 skeptic-checklist 里的每个 kind:
- evidence_duplication
- overclaim
- misattribution
- causal_leap
- simpler_alternative
- no_anti_evidence
- self_flattery

输出 ReviewFindings:
- findings 列表 (允许空, 但通常会有 1-3 条)
- repair_actions 列表 (具体到 "rename to X" 或 "downgrade to 0.65" 这种可执行指令)
- confidence_delta: 范围 [-0.5, +0.1]
  - 没问题 = 0.0 或 +0.05
  - 范围过宽 / 缺反证 = -0.05 ~ -0.15
  - 因果跳跃 / 归因偏差 = -0.15 ~ -0.30
  - 简单替代解释更合理 = -0.20 ~ -0.40

诚实下手, 不要客套.
"""


class SkepticAgent(BaseAgent):
    pass


def make_skeptic() -> SkepticAgent:
    return SkepticAgent(
        name="skeptic",
        role=Role.STANDARD,
        skill_names=["skeptic-checklist"],
        persona=PERSONA,
        temperature=0.3,
        max_tokens=3000,  # v4 thinking + findings list
    )


def review_mechanism(
    ctx: AgentContext,
    *,
    mechanism: MechanismCard,
    evidences: List[EvidenceCard],
) -> ReviewFindings:
    agent = make_skeptic()
    relevant_ids = set(mechanism.evidence_ids) | set(mechanism.anti_evidence_ids)
    ev_str = "\n".join(
        f"<evidence id=\"{e.evidence_id}\" type=\"{e.type.value}\">\n"
        f"situation: {e.situation}\n"
        f"cues: {e.cues}\n"
        f"judgment: {e.judgment}\n"
        f"actions: {e.actions}\n"
        f"outcome: {e.outcome}\n"
        f"</evidence>"
        for e in evidences if e.evidence_id in relevant_ids
    )
    mech_str = (
        f"id: {mechanism.mechanism_id}\n"
        f"name: {mechanism.name}\n"
        f"definition: {mechanism.definition}\n"
        f"cue_pattern: {mechanism.pattern.cue_pattern}\n"
        f"decision_rule: {mechanism.pattern.decision_rule}\n"
        f"verification_style: {mechanism.pattern.verification_style}\n"
        f"boundary_conditions: {mechanism.boundary_conditions}\n"
        f"confidence: {mechanism.confidence}\n"
        f"status: {mechanism.status.value}\n"
        f"evidence_ids: {mechanism.evidence_ids}\n"
        f"anti_evidence_ids: {mechanism.anti_evidence_ids}\n"
    )
    user = (
        f"<mechanism_under_review>\n{mech_str}\n</mechanism_under_review>\n\n"
        f"<supporting_evidence>\n{ev_str}\n</supporting_evidence>\n\n"
        f"请按 skeptic-checklist 逐项检查并输出 ReviewFindings."
    )
    return agent.run(ctx, user_prompt=user, schema=ReviewFindings)
