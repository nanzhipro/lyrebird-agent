"""Dialogic Interviewer — asks one critical-incident question per turn."""
from __future__ import annotations

from typing import List

from lyrebird.agents.base import AgentContext, BaseAgent
from lyrebird.llm.client import Role
from lyrebird.schemas import (
    CandidateProfile,
    InterviewQuestion,
    InterviewTurn,
)


PERSONA = """你是关键事件追问者. 你的工作不是收集信息, 是逼近候选人当时的认知过程.

规则:
1. 永远围绕一个具体事件 (a single critical incident)
2. 每轮只问一个问题, 最多 80 字
3. 优先追的缺口: cues > constraints > judgment > tradeoffs > actions > verification > counterfactual
4. 如果候选人开始抽象总结 ("我一般 / 我擅长"), 立刻把他拉回具体事件
5. 如果候选人讲了一个新事件, 先把已开的事件追完再切换
6. 不要给候选人选项, 不要"友好确认", 不要"很好的回答!"

不要问的:
- "你的优点是什么"
- "你擅长什么"
- "你怎么看自己"
"""


class InterviewerAgent(BaseAgent):
    pass


def make_interviewer_agent() -> InterviewerAgent:
    return InterviewerAgent(
        name="interviewer",
        role=Role.STANDARD,
        skill_names=["incident-probing"],
        persona=PERSONA,
        temperature=0.5,
        # V4-flash thinking commonly runs 1000-1500 tokens before the final
        # one-sentence question. Anything ≤2000 forces the auto-bump path on
        # nearly every turn. 3000 keeps headroom; output never exceeds ~200.
        max_tokens=3000,
    )


def next_question(
    ctx: AgentContext,
    *,
    profile: CandidateProfile,
    history: List[InterviewTurn],
    turn_id: str,
) -> InterviewQuestion:
    agent = make_interviewer_agent()
    hist_str = "\n".join(
        f"<turn id=\"{t.turn_id}\" target_hyp=\"{t.target_hypothesis_id or ''}\">"
        f"\nQ: {t.question}\nA: {t.answer}\n</turn>"
        for t in history
    ) or "(no prior turns)"

    hyps = "\n".join(
        f" - {h.hypothesis_id} [{h.priority.value}] {h.label}: {'; '.join(h.basis)}"
        for h in profile.hypothesis_list
    )
    exps = "\n".join(
        f" - {e.experience_id}: {e.company} {e.title} ({e.start}->{e.end})"
        for e in profile.core_experiences
    )

    # Strategy hint: track how many turns each hypothesis has consumed, push to switch when ≥2
    counts: dict[str, int] = {}
    for t in history:
        if t.target_hypothesis_id:
            counts[t.target_hypothesis_id] = counts.get(t.target_hypothesis_id, 0) + 1
    strategy_hint = ""
    if counts:
        used = sorted(counts.items(), key=lambda x: -x[1])
        most_used_hyp, most_used_n = used[0]
        unused = [h.hypothesis_id for h in profile.hypothesis_list if h.hypothesis_id not in counts]
        if most_used_n >= 2 and unused:
            strategy_hint = (
                f"\n<strategy_hint>\n"
                f"hypothesis {most_used_hyp} 已经追了 {most_used_n} 轮足够深入. "
                f"下一轮请切到 {unused[0]} 或其他未覆盖的 hypothesis, "
                f"问一个新的具体事件 — 不再追当前事件.\n"
                f"</strategy_hint>"
            )

    user = (
        f"<turn_id>{turn_id}</turn_id>\n"
        f"<hypotheses>\n{hyps}\n</hypotheses>\n"
        f"<experiences>\n{exps}\n</experiences>\n"
        f"<history>\n{hist_str}\n</history>{strategy_hint}\n\n"
        f"基于上面的进展, 输出下一轮提问. "
        f"target_hypothesis_id 必须从已有 hypothesis_id 中选; "
        f"cue_target 从 [cues, constraints, judgment, tradeoffs, actions, verification, counterfactual] 中选一个."
    )
    return agent.run(ctx, user_prompt=user, schema=InterviewQuestion)
