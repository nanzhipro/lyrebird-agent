"""Evidence Mapper — compresses interview turns into EvidenceCards."""
from __future__ import annotations

from typing import List

from lyrebird.agents.base import AgentContext, BaseAgent
from lyrebird.llm.client import Role
from lyrebird.schemas import (
    EvidenceBatch,
    InterviewTurn,
    CandidateProfile,
)


PERSONA = """你是证据结构化专家. 你从对话片段里压缩出 EvidenceCard, 不解释, 不命名, 不评价.

铁律:
- 不发明结果 (outcome 必须来自候选人原话)
- 不把"候选人的自我评价"当 critical_incident
- 同一段对话产出 1 张 evidence_card, 除非候选人讲了两个独立事件
- 如果 cues / judgment / actions / outcome 缺一项, confidence 不得超过 0.65, 并填 insufficiency_reason
- evidence_id 形如 'ev_001', 'ev_002', 按顺序排
- source_ref.conversation_turn_ids 必须从输入的 turn_id 中选, 不要造
- source_ref.resume_span_ref 可填一个 experience_id (如 exp_01) 表示这个事件发生在哪段经历, 没有就留 null
"""


class EvidenceMapperAgent(BaseAgent):
    pass


def make_evidence_mapper() -> EvidenceMapperAgent:
    return EvidenceMapperAgent(
        name="evidence_mapper",
        role=Role.STANDARD,
        skill_names=["evidence-schema"],
        persona=PERSONA,
        temperature=0.2,
        max_tokens=6000,  # v4 thinking + N evidence cards
    )


def map_interview_to_evidence(
    ctx: AgentContext,
    *,
    profile: CandidateProfile,
    history: List[InterviewTurn],
    starting_evidence_index: int = 1,
) -> EvidenceBatch:
    agent = make_evidence_mapper()
    hist_str = "\n".join(
        f"<turn id=\"{t.turn_id}\">\nQ: {t.question}\nA: {t.answer}\n</turn>"
        for t in history
    )
    exps = "\n".join(
        f" - {e.experience_id}: {e.company} {e.title}"
        for e in profile.core_experiences
    )
    user = (
        f"<experiences>\n{exps}\n</experiences>\n"
        f"<interview>\n{hist_str}\n</interview>\n\n"
        f"压缩为 EvidenceCard 列表. evidence_id 从 ev_{starting_evidence_index:03d} 开始递增. "
        f"如果整段对话不包含具体事件 (没有时间/动作), 可以只产出 0 张 — 输出空列表."
    )
    return agent.run(ctx, user_prompt=user, schema=EvidenceBatch)
