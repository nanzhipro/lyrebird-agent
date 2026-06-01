"""Core data contracts per arch.md §通信协议与数据契约.

Design principles encoded here:
1. evidence-before-naming: a MechanismCard must reference >=2 distinct evidence_ids.
2. publish-gate: any high-confidence ValidatedMechanism must carry evidence_ids.
3. confidence tiers are business rules, not raw probabilities.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------- enums ----------

class Priority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EvidenceType(str, Enum):
    CRITICAL_INCIDENT = "critical_incident"
    RESUME_CLAIM = "resume_claim"
    SELF_ASSESSMENT = "self_assessment"


class MechanismStatus(str, Enum):
    VALIDATED = "validated"
    PROBABLE = "probable"
    HYPOTHESIS = "hypothesis"


class CareerStage(str, Enum):
    JUNIOR = "junior"
    MID = "mid"
    MID_SENIOR = "mid_senior"
    SENIOR = "senior"
    STAFF = "staff"
    UNKNOWN = "unknown"


class ConfidenceTier(str, Enum):
    """Business rule from arch.md §质量门控与置信度规则."""
    VALIDATED = "validated"        # 0.80–1.00
    PROBABLE = "probable"          # 0.60–0.79
    PRELIMINARY = "preliminary"    # 0.40–0.59
    INSUFFICIENT = "insufficient"  # <0.40

    @classmethod
    def from_score(cls, score: float) -> "ConfidenceTier":
        if score >= 0.80:
            return cls.VALIDATED
        if score >= 0.60:
            return cls.PROBABLE
        if score >= 0.40:
            return cls.PRELIMINARY
        return cls.INSUFFICIENT


# ---------- shared models ----------

class StrictBase(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=False,
    )


class SourceRef(StrictBase):
    conversation_turn_ids: List[str] = Field(default_factory=list)
    resume_span_ref: Optional[str] = None


# ---------- candidate_profile ----------

class CoreExperience(StrictBase):
    experience_id: str
    company: str
    title: str
    start: str
    end: str
    domains: List[str] = Field(default_factory=list)
    claimed_outcomes: List[str] = Field(default_factory=list)


class Hypothesis(StrictBase):
    hypothesis_id: str
    label: str
    basis: List[str] = Field(default_factory=list)
    priority: Priority


class CandidateProfile(StrictBase):
    candidate_id: str
    source_resume_id: str
    target_role: Optional[str] = None
    career_stage: str
    core_experiences: List[CoreExperience]
    hypothesis_list: List[Hypothesis]
    unknowns: List[str] = Field(default_factory=list)


# ---------- evidence_card ----------

class EvidenceCard(StrictBase):
    evidence_id: str
    type: EvidenceType
    source_ref: SourceRef
    situation: str
    goal: str
    constraints: List[str]
    cues: List[str]
    judgment: str
    actions: List[str]
    outcome: str
    confidence: float = Field(ge=0.0, le=1.0)
    insufficiency_reason: Optional[str] = None


# ---------- mechanism_card ----------

class MechanismPattern(StrictBase):
    cue_pattern: List[str]
    decision_rule: str
    verification_style: str


class MechanismCard(StrictBase):
    mechanism_id: str
    name: str
    aliases: List[str] = Field(default_factory=list)
    definition: str
    evidence_ids: List[str]
    anti_evidence_ids: List[str] = Field(default_factory=list)
    pattern: MechanismPattern
    boundary_conditions: List[str]
    confidence: float = Field(ge=0.0, le=1.0)
    status: MechanismStatus

    @model_validator(mode="after")
    def _naming_gate(self):
        # arch.md §命名门: at least 2 non-duplicate evidence_ids
        unique = set(self.evidence_ids)
        if len(unique) < 2:
            raise ValueError("naming-gate: mechanism needs >=2 distinct evidence_ids")
        # arch.md §发布策略: validated -> confidence >= 0.80
        if self.status == MechanismStatus.VALIDATED and self.confidence < 0.80:
            raise ValueError("publish-gate: validated requires confidence>=0.80")
        if self.status == MechanismStatus.PROBABLE and self.confidence < 0.60:
            raise ValueError("status-gate: probable requires confidence>=0.60")
        return self


# ---------- extraction_report ----------

class ValidatedMechanism(StrictBase):
    mechanism_id: str
    name: str
    why_it_matters: str
    resume_rewrite: str
    interview_narrative: str
    evidence_ids: List[str]
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _publish_gate(self):
        # arch.md §发布门: high-confidence claim must have evidence_ids
        if self.confidence >= 0.60 and not self.evidence_ids:
            raise ValueError("publish-gate: confident claim missing evidence_ids")
        return self


class ReportSummary(StrictBase):
    validated_mechanisms: int
    probable_mechanisms: int
    needs_more_evidence: int


class ExtractionReport(StrictBase):
    report_id: str
    candidate_id: str
    summary: ReportSummary
    validated_mechanisms: List[ValidatedMechanism]
    probable_mechanisms: List[ValidatedMechanism]
    open_questions: List[str] = Field(default_factory=list)
    privacy_notes: List[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("generated_at", mode="before")
    @classmethod
    def _coerce_empty_or_null_to_now(cls, v):
        # Models occasionally return "" or None — treat as "let the system set it"
        if v is None or (isinstance(v, str) and not v.strip()):
            return datetime.now(timezone.utc)
        return v


# ---------- agent IO helpers ----------

class InterviewQuestion(StrictBase):
    """Output of Dialogic Interviewer per turn."""
    turn_id: str
    question: str = Field(min_length=4, max_length=400)
    target_hypothesis_id: Optional[str] = None
    cue_target: Optional[str] = None  # which CTA cue we're chasing


class SimulatedAnswer(StrictBase):
    """For autonomous eval: candidate role-plays from resume."""
    turn_id: str
    answer: str
    refers_to_experience_id: Optional[str] = None


class InterviewTurn(StrictBase):
    turn_id: str
    question: str
    answer: str
    target_hypothesis_id: Optional[str] = None


class EvidenceBatch(StrictBase):
    evidence_cards: List[EvidenceCard]


class MechanismBatch(StrictBase):
    mechanism_cards: List[MechanismCard]


class SkepticSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SkepticFinding(StrictBase):
    kind: str
    severity: SkepticSeverity
    detail: str
    affected_evidence_ids: List[str] = Field(default_factory=list)


class ReviewFindings(StrictBase):
    mechanism_id: str
    findings: List[SkepticFinding] = Field(default_factory=list)
    repair_actions: List[str] = Field(default_factory=list)
    confidence_delta: float = Field(ge=-0.5, le=0.1)


__all__ = [
    "Priority",
    "EvidenceType",
    "MechanismStatus",
    "CareerStage",
    "ConfidenceTier",
    "SourceRef",
    "CoreExperience",
    "Hypothesis",
    "CandidateProfile",
    "EvidenceCard",
    "MechanismPattern",
    "MechanismCard",
    "ValidatedMechanism",
    "ReportSummary",
    "ExtractionReport",
    "InterviewQuestion",
    "SimulatedAnswer",
    "InterviewTurn",
    "EvidenceBatch",
    "MechanismBatch",
    "SkepticSeverity",
    "SkepticFinding",
    "ReviewFindings",
]
