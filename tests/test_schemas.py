"""TDD for core data contracts (per arch.md §数据契约)."""
import pytest
from pydantic import ValidationError

from lyrebird.schemas import (
    CandidateProfile,
    CoreExperience,
    Hypothesis,
    EvidenceCard,
    SourceRef,
    MechanismCard,
    MechanismPattern,
    ExtractionReport,
    ValidatedMechanism,
    ReportSummary,
    ConfidenceTier,
    EvidenceType,
    MechanismStatus,
)


# ---------- CandidateProfile ----------

def test_candidate_profile_minimum():
    p = CandidateProfile(
        candidate_id="cand_001",
        source_resume_id="file_001",
        target_role="高级产品经理",
        career_stage="mid_senior",
        core_experiences=[
            CoreExperience(
                experience_id="exp_01",
                company="Example",
                title="PM",
                start="2022-01",
                end="2025-01",
                domains=["B2B"],
                claimed_outcomes=["上线"],
            )
        ],
        hypothesis_list=[
            Hypothesis(
                hypothesis_id="hyp_01",
                label="约束建模驱动推进",
                basis=["跨部门"],
                priority="high",
            )
        ],
        unknowns=["是否独立判断"],
    )
    assert p.candidate_id == "cand_001"
    assert len(p.hypothesis_list) == 1
    assert p.hypothesis_list[0].priority == "high"


def test_hypothesis_priority_enum():
    with pytest.raises(ValidationError):
        Hypothesis(hypothesis_id="h", label="x", basis=[], priority="bogus")


# ---------- EvidenceCard ----------

def test_evidence_card_full():
    e = EvidenceCard(
        evidence_id="ev_001",
        type=EvidenceType.CRITICAL_INCIDENT,
        source_ref=SourceRef(
            conversation_turn_ids=["t_12"],
            resume_span_ref="exp_01",
        ),
        situation="上线前两周口径不一致",
        goal="不延迟发布修正口径",
        constraints=["时间短", "跨团队"],
        cues=["dashboard 与周报数字不一致"],
        judgment="问题根因是事实基础缺失",
        actions=["先统一口径", "再排执行"],
        outcome="如期发布",
        confidence=0.78,
    )
    assert e.confidence == 0.78
    assert e.insufficiency_reason is None


def test_evidence_card_confidence_bounds():
    base = dict(
        evidence_id="ev",
        type=EvidenceType.CRITICAL_INCIDENT,
        source_ref=SourceRef(conversation_turn_ids=[], resume_span_ref="x"),
        situation="x", goal="x", constraints=[], cues=[],
        judgment="x", actions=[], outcome="x",
    )
    with pytest.raises(ValidationError):
        EvidenceCard(**base, confidence=1.5)
    with pytest.raises(ValidationError):
        EvidenceCard(**base, confidence=-0.1)


def test_evidence_card_marks_insufficiency():
    """When insufficient, must say why — design rule."""
    e = EvidenceCard(
        evidence_id="ev",
        type=EvidenceType.RESUME_CLAIM,
        source_ref=SourceRef(conversation_turn_ids=[], resume_span_ref="exp_01"),
        situation="只有简历自述,无对话佐证",
        goal="x", constraints=[], cues=[],
        judgment="", actions=[], outcome="",
        confidence=0.2,
        insufficiency_reason="lacks_corroborating_incident",
    )
    assert e.insufficiency_reason == "lacks_corroborating_incident"


# ---------- MechanismCard ----------

def test_mechanism_card_requires_evidence():
    """Per arch.md naming gate: at least 2 non-duplicate evidence_ids."""
    with pytest.raises(ValidationError):
        MechanismCard(
            mechanism_id="m1",
            name="x",
            aliases=[],
            definition="x",
            evidence_ids=["ev_001"],  # only 1 — should fail
            anti_evidence_ids=[],
            pattern=MechanismPattern(cue_pattern=[], decision_rule="x", verification_style="x"),
            boundary_conditions=[],
            confidence=0.5,
            status=MechanismStatus.PROBABLE,
        )


def test_mechanism_card_valid():
    m = MechanismCard(
        mechanism_id="mech_001",
        name="约束建模后再推进执行",
        aliases=["先统一事实底座再推进"],
        definition="先识别约束与事实分歧,再决定推进路径",
        evidence_ids=["ev_001", "ev_007"],
        anti_evidence_ids=["ev_021"],
        pattern=MechanismPattern(
            cue_pattern=["事实不一致"],
            decision_rule="先建模再排序",
            verification_style="减少返工",
        ),
        boundary_conditions=["高依赖任务"],
        confidence=0.84,
        status=MechanismStatus.VALIDATED,
    )
    assert m.confidence == 0.84
    assert m.status == MechanismStatus.VALIDATED


def test_mechanism_validated_needs_high_confidence():
    """Status validated requires confidence >= 0.80 (publish-gate rule)."""
    with pytest.raises(ValidationError):
        MechanismCard(
            mechanism_id="m",
            name="x",
            aliases=[],
            definition="x",
            evidence_ids=["a", "b"],
            anti_evidence_ids=[],
            pattern=MechanismPattern(cue_pattern=[], decision_rule="x", verification_style="x"),
            boundary_conditions=[],
            confidence=0.5,
            status=MechanismStatus.VALIDATED,
        )


# ---------- ExtractionReport ----------

def test_extraction_report_minimum():
    r = ExtractionReport(
        report_id="rep_001",
        candidate_id="cand_001",
        summary=ReportSummary(validated_mechanisms=1, probable_mechanisms=0, needs_more_evidence=0),
        validated_mechanisms=[
            ValidatedMechanism(
                mechanism_id="mech_001",
                name="约束建模后再推进执行",
                why_it_matters="适合高依赖岗位",
                resume_rewrite="...",
                interview_narrative="...",
                evidence_ids=["ev_001", "ev_007"],
                confidence=0.84,
            )
        ],
        probable_mechanisms=[],
        open_questions=[],
        privacy_notes=[],
    )
    assert r.report_id == "rep_001"
    assert r.generated_at is not None  # auto-set


def test_extraction_report_publish_gate():
    """Per arch.md publish-gate: any high-confidence claim must have evidence_ids."""
    with pytest.raises(ValidationError):
        ValidatedMechanism(
            mechanism_id="m1",
            name="x",
            why_it_matters="x",
            resume_rewrite="x",
            interview_narrative="x",
            evidence_ids=[],  # publish-gate breach
            confidence=0.9,
        )


# ---------- Confidence tier helper ----------

def test_extraction_report_coerces_empty_generated_at():
    """Models sometimes return generated_at='' — must coerce to now, not raise."""
    r = ExtractionReport.model_validate({
        "report_id": "rep",
        "candidate_id": "c",
        "summary": {"validated_mechanisms": 0, "probable_mechanisms": 0, "needs_more_evidence": 0},
        "validated_mechanisms": [],
        "probable_mechanisms": [],
        "open_questions": [],
        "privacy_notes": [],
        "generated_at": "",
    })
    assert r.generated_at is not None


def test_extraction_report_coerces_null_generated_at():
    r = ExtractionReport.model_validate({
        "report_id": "rep",
        "candidate_id": "c",
        "summary": {"validated_mechanisms": 0, "probable_mechanisms": 0, "needs_more_evidence": 0},
        "validated_mechanisms": [],
        "probable_mechanisms": [],
        "open_questions": [],
        "privacy_notes": [],
        "generated_at": None,
    })
    assert r.generated_at is not None


def test_confidence_tier_mapping():
    assert ConfidenceTier.from_score(0.95) == ConfidenceTier.VALIDATED
    assert ConfidenceTier.from_score(0.70) == ConfidenceTier.PROBABLE
    assert ConfidenceTier.from_score(0.50) == ConfidenceTier.PRELIMINARY
    assert ConfidenceTier.from_score(0.20) == ConfidenceTier.INSUFFICIENT
