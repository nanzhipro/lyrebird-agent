"""Simulated candidate — for autonomous eval only.

In the real product this role is played by a human. For self-tests, we let
another model role-play the candidate by reading the resume. This is honest
synthetic data: it's grounded in the resume text, and the simulation prompt
forbids inventing facts the resume does not support.
"""
from __future__ import annotations

from typing import List

from lyrebird.agents.base import AgentContext, BaseAgent
from lyrebird.llm.client import Role
from lyrebird.schemas import (
    InterviewTurn,
    InterviewQuestion,
    SimulatedAnswer,
)


PERSONA = """你正在扮演一位候选人, 接受认知机制萃取访谈. 你必须基于下面给定的简历来回答, 风格朴实真实.

允许:
- 在简历事实范围内合理回忆细节 (例如具体场景、约束、动作步骤)
- 用工程师/技术人员的口吻
- 承认"不太记得了"或"那不是我直接负责的"

禁止:
- 编造简历中没有的公司、产品、项目
- 编造具体数字 (如转化率 +40%) 除非简历里就有
- 用 MBA 腔或自我美化语言
- 回答超过 200 字

如果被问到不擅长的领域, 诚实说不擅长. 如果被追问 cues, 给出 2-3 个具体的信号, 不是结论.
"""


class SimulatedCandidateAgent(BaseAgent):
    pass


def make_simulated_candidate() -> SimulatedCandidateAgent:
    return SimulatedCandidateAgent(
        name="simulated_candidate",
        role=Role.STANDARD,
        skill_names=[],
        persona=PERSONA,
        temperature=0.6,
        max_tokens=3000,  # same logic as interviewer — V4 thinking dominates the budget
    )


def answer(
    ctx: AgentContext,
    *,
    resume_text: str,
    history: List[InterviewTurn],
    question: InterviewQuestion,
) -> SimulatedAnswer:
    agent = make_simulated_candidate()
    hist_str = "\n".join(
        f"Q{t.turn_id}: {t.question}\nA{t.turn_id}: {t.answer}"
        for t in history
    ) or "(no prior turns)"
    user = (
        f"<resume>\n{resume_text}\n</resume>\n\n"
        f"<history>\n{hist_str}\n</history>\n\n"
        f"<current_question turn_id=\"{question.turn_id}\" cue=\"{question.cue_target or ''}\">"
        f"\n{question.question}\n</current_question>\n\n"
        f"以候选人身份回答 (第一人称). 输出 JSON: turn_id 与上方一致, "
        f"refers_to_experience_id 若适用就填 exp_XX, 不适用填 null."
    )
    return agent.run(ctx, user_prompt=user, schema=SimulatedAnswer)
