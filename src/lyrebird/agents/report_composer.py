"""Report Composer — produces the final ExtractionReport."""
from __future__ import annotations

from typing import List

from lyrebird.agents.base import AgentContext, BaseAgent
from lyrebird.llm.client import Role
from lyrebird.schemas import (
    CandidateProfile,
    EvidenceCard,
    ExtractionReport,
    MechanismCard,
    MechanismStatus,
)


PERSONA = """你是职业化表达编辑器. 你的工作是把 mechanism_cards 翻译成候选人**真正能用**的报告.

规则:
- validated_mechanisms: 只放 status == "validated" 的机制
- probable_mechanisms: 只放 status == "probable" 的机制
- 每个 mechanism 必带 evidence_ids — 没有引用的机制不得入报告
- resume_rewrite: < 50 字, 含一个动作 + 一个可观察结果
- interview_narrative: < 120 字, 第一人称, 以"我"开头, 不要总结句, 不要"这件事让我..."
- 不写胜任力评分, 不写人格描述, 不堆叠形容词
- privacy_notes: 列已遮蔽的 PII 类型; 没有就 ["未发现 PII"]
- open_questions: 2-4 个具体可追问的问题, 不是哲学问题
- summary 的三个计数, 必须与上面列表长度严格一致
"""


class ReportComposerAgent(BaseAgent):
    pass


def make_report_composer() -> ReportComposerAgent:
    return ReportComposerAgent(
        name="report_composer",
        role=Role.HEAVY,
        skill_names=["report-authoring"],
        persona=PERSONA,
        temperature=0.4,
        max_tokens=6000,  # Pro thinking + report body
    )


def compose_report(
    ctx: AgentContext,
    *,
    profile: CandidateProfile,
    mechanisms: List[MechanismCard],
    evidences: List[EvidenceCard],
    report_id: str,
    privacy_notes: List[str],
) -> ExtractionReport:
    agent = make_report_composer()

    validated = [m for m in mechanisms if m.status == MechanismStatus.VALIDATED]
    probable = [m for m in mechanisms if m.status == MechanismStatus.PROBABLE]
    needs_more = [m for m in mechanisms if m.status == MechanismStatus.HYPOTHESIS]

    mech_summary = []
    for m in mechanisms:
        mech_summary.append(
            f"<mechanism id=\"{m.mechanism_id}\" status=\"{m.status.value}\" conf=\"{m.confidence}\">\n"
            f"name: {m.name}\n"
            f"definition: {m.definition}\n"
            f"evidence_ids: {m.evidence_ids}\n"
            f"boundary: {m.boundary_conditions}\n"
            f"</mechanism>"
        )
    mech_str = "\n".join(mech_summary)

    target_role = profile.target_role or "未指定岗位"
    user = (
        f"<candidate_id>{profile.candidate_id}</candidate_id>\n"
        f"<target_role>{target_role}</target_role>\n"
        f"<report_id>{report_id}</report_id>\n"
        f"<privacy_notes>{privacy_notes}</privacy_notes>\n\n"
        f"<mechanisms>\n{mech_str}\n</mechanisms>\n\n"
        f"已分类: validated={len(validated)}, probable={len(probable)}, "
        f"needs_more_evidence={len(needs_more)}.\n"
        f"summary 的三个计数必须严格等于上述数字. "
        f"validated_mechanisms 列表长度 = {len(validated)}, "
        f"probable_mechanisms 列表长度 = {len(probable)}. "
        f"为每个 mechanism 写 why_it_matters / resume_rewrite / interview_narrative. "
        f"generated_at 字段不要填, 由系统自动设置."
    )
    return agent.run(ctx, user_prompt=user, schema=ExtractionReport)
