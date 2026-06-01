"""Mechanism Modeler — clusters EvidenceCards and names cognitive mechanisms."""
from __future__ import annotations

from typing import List

from lyrebird.agents.base import AgentContext, BaseAgent
from lyrebird.llm.client import Role
from lyrebird.schemas import (
    EvidenceCard,
    MechanismBatch,
    CandidateProfile,
)


PERSONA = """你是认知机制命名者. 你的工作是从 evidence_card 聚类中, 抽取并命名候选人的高价值认知机制.

铁律:
- 每个 mechanism 必须由 >= 2 张 distinct evidence_card 支撑
- 至少 1 张支撑证据必须是 critical_incident (来自对话, 不是 resume_claim)
- 命名风格: 动宾结构, 不要"能力/思维/力"后缀; 不要"沟通能力 / 执行力 / 责任心"
- 必须能拆成 cue_pattern -> decision_rule -> action_principle (写入 verification_style 字段一并体现) 的四段结构
- boundary_conditions: 明确在什么情境下这个机制不适用
- status:
  - validated 需要 confidence >= 0.80 — 默认你**不**给 validated, 由 Skeptic 评审后再升
  - probable 需要 confidence >= 0.60
  - 其他用 hypothesis
- mechanism_id 从 mech_001 开始
"""


class MechanismModelerAgent(BaseAgent):
    pass


def make_mechanism_modeler() -> MechanismModelerAgent:
    return MechanismModelerAgent(
        name="mechanism_modeler",
        role=Role.HEAVY,
        skill_names=["mechanism-taxonomy"],
        persona=PERSONA,
        temperature=0.35,
        max_tokens=8000,  # heaviest reasoning: Pro thinking can be 2-3k
    )


def model_mechanisms(
    ctx: AgentContext,
    *,
    profile: CandidateProfile,
    evidences: List[EvidenceCard],
) -> MechanismBatch:
    agent = make_mechanism_modeler()
    ev_str = "\n".join(
        f"<evidence id=\"{e.evidence_id}\" type=\"{e.type.value}\" conf=\"{e.confidence}\">\n"
        f"situation: {e.situation}\n"
        f"goal: {e.goal}\n"
        f"constraints: {e.constraints}\n"
        f"cues: {e.cues}\n"
        f"judgment: {e.judgment}\n"
        f"actions: {e.actions}\n"
        f"outcome: {e.outcome}\n"
        f"</evidence>"
        for e in evidences
    )
    hyps = "\n".join(f" - {h.hypothesis_id} [{h.priority.value}] {h.label}" for h in profile.hypothesis_list)
    user = (
        f"<initial_hypotheses>\n{hyps}\n</initial_hypotheses>\n\n"
        f"<evidence_cards>\n{ev_str}\n</evidence_cards>\n\n"
        f"基于 evidence_cards 聚类 + 命名 2-4 个 mechanism_card. "
        f"宁可少而精, 不要凑数. status 默认 hypothesis 或 probable."
    )
    return agent.run(ctx, user_prompt=user, schema=MechanismBatch)
