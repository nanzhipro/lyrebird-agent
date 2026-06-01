"""Intake & Hypothesis Agent — resume → CandidateProfile + hypothesis list."""
from __future__ import annotations

from lyrebird.agents.base import AgentContext, BaseAgent
from lyrebird.llm.client import Role
from lyrebird.schemas import CandidateProfile


PERSONA = """你是简历理解与假设生成专家.

你的任务:
1. 从候选人简历中提取核心经历 (core_experiences) 与领域
2. 找出"反复出现的任务类型"和"决策密度高的经历"
3. 生成 2-5 个 hypothesis, 每个 hypothesis 是对候选人**可能存在的高价值认知机制**的初步猜测
4. 列出 2-4 个 unknowns — 你目前还不能从简历判断的关键问题

你不要做的事:
- 不要给人格评价 ("他很细致")
- 不要给录用建议 ("适合 P7")
- 不要发明简历里没有的经历
- 不要把 "沟通能力 / 执行力" 这类空泛软技能写进 hypothesis

hypothesis 的命名风格:
- 「约束建模驱动推进」 ✓
- 「以反例反推问题边界」 ✓
- 「沟通能力强」 ✗
- 「技术功底扎实」 ✗
"""


class IntakeAgent(BaseAgent):
    pass


def make_intake_agent() -> IntakeAgent:
    return IntakeAgent(
        name="intake",
        role=Role.STANDARD,
        skill_names=[],
        persona=PERSONA,
        temperature=0.3,
        max_tokens=5000,  # v4 thinking block + 4-5 hypotheses + experiences
    )


def run_intake(
    ctx: AgentContext,
    *,
    candidate_id: str,
    source_resume_id: str,
    resume_text: str,
    target_role: str | None = None,
) -> CandidateProfile:
    agent = make_intake_agent()
    target = target_role or "未指定"
    user = (
        f"<candidate_id>{candidate_id}</candidate_id>\n"
        f"<source_resume_id>{source_resume_id}</source_resume_id>\n"
        f"<target_role>{target}</target_role>\n\n"
        f"<resume>\n{resume_text}\n</resume>\n\n"
        f"请输出符合 schema 的 JSON. candidate_id 和 source_resume_id 必须照搬上面的值. "
        f"experience_id 形如 'exp_01'/'exp_02', hypothesis_id 形如 'hyp_01'/'hyp_02'."
    )
    return agent.run(ctx, user_prompt=user, schema=CandidateProfile)
