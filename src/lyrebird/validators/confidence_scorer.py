"""Confidence scorer — explicit business rule, NOT a model probability.

Per arch.md §质量门控与置信度规则:
> 把置信度拆解为五个子维度:证据丰富度、跨情境复现度、内部一致性、
> 候选人认可度、结果链接强度

Weights (sum = 1.0):
- evidence_richness: 0.30      # how many distinct evidence cards back it
- cross_context_replication: 0.25  # appears in >1 different situation
- internal_consistency: 0.15   # no internal contradictions among cards
- candidate_endorsement: 0.10  # candidate agrees with the naming
- outcome_link_strength: 0.20  # mechanism is causally linked to outcomes

Rationale: evidence-first wins (per arch.md "证据先于命名"), endorsement is the
lightest weight so the system can't be flattered into a high score.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ConfidenceComponents:
    evidence_richness: float
    cross_context_replication: float
    internal_consistency: float
    candidate_endorsement: float
    outcome_link_strength: float


_WEIGHTS = {
    "evidence_richness": 0.30,
    "cross_context_replication": 0.25,
    "internal_consistency": 0.15,
    "candidate_endorsement": 0.10,
    "outcome_link_strength": 0.20,
}


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def score_mechanism_confidence(c: ConfidenceComponents) -> float:
    score = (
        _clamp01(c.evidence_richness) * _WEIGHTS["evidence_richness"]
        + _clamp01(c.cross_context_replication) * _WEIGHTS["cross_context_replication"]
        + _clamp01(c.internal_consistency) * _WEIGHTS["internal_consistency"]
        + _clamp01(c.candidate_endorsement) * _WEIGHTS["candidate_endorsement"]
        + _clamp01(c.outcome_link_strength) * _WEIGHTS["outcome_link_strength"]
    )
    return _clamp01(score)
