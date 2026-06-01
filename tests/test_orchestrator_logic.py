"""Gate logic + skeptic-driven adjustment — no LLM."""
import pytest

from lyrebird.agents.orchestrator import (
    sufficiency_gate, evidence_gate, naming_gate, consistency_gate,
    publish_gate, apply_review,
)
from lyrebird.schemas import (
    CandidateProfile, CoreExperience, Hypothesis, Priority,
    EvidenceCard, EvidenceType, SourceRef,
    MechanismCard, MechanismPattern, MechanismStatus,
    ReviewFindings, SkepticFinding, SkepticSeverity,
    ExtractionReport, ReportSummary, ValidatedMechanism,
)


def _profile(priority: Priority = Priority.HIGH, n_exp: int = 1) -> CandidateProfile:
    return CandidateProfile(
        candidate_id="c", source_resume_id="r", career_stage="senior",
        core_experiences=[
            CoreExperience(
                experience_id=f"exp_{i:02d}", company="X", title="Y",
                start="2020", end="2023", domains=[], claimed_outcomes=[],
            ) for i in range(1, n_exp + 1)
        ],
        hypothesis_list=[Hypothesis(hypothesis_id="h1", label="x", basis=[], priority=priority)],
        unknowns=[],
    )


def _evidence(eid: str, type=EvidenceType.CRITICAL_INCIDENT,
              cues=("c",), judgment="j", actions=("a",), outcome="o",
              resume_span="exp_01") -> EvidenceCard:
    return EvidenceCard(
        evidence_id=eid, type=type,
        source_ref=SourceRef(conversation_turn_ids=["t1"], resume_span_ref=resume_span),
        situation="s", goal="g", constraints=["k"],
        cues=list(cues), judgment=judgment, actions=list(actions), outcome=outcome,
        confidence=0.7,
    )


def _mechanism(mid="m1", evidence_ids=("ev_001", "ev_002"),
               status=MechanismStatus.PROBABLE, confidence=0.65) -> MechanismCard:
    return MechanismCard(
        mechanism_id=mid, name="约束建模后再推进执行",
        aliases=[], definition="d",
        evidence_ids=list(evidence_ids), anti_evidence_ids=[],
        pattern=MechanismPattern(cue_pattern=["x"], decision_rule="r", verification_style="v"),
        boundary_conditions=["b"], confidence=confidence, status=status,
    )


# ---------- sufficiency gate ----------

def test_sufficiency_gate_passes_with_high_hyp_and_exp():
    assert sufficiency_gate(_profile()).passed


def test_sufficiency_gate_fails_without_high_hypothesis():
    g = sufficiency_gate(_profile(priority=Priority.LOW))
    assert not g.passed
    assert "high-priority" in g.reasons[0]


# ---------- evidence gate ----------

def test_evidence_gate_passes_with_three_complete_incidents():
    evs = [_evidence(f"ev_{i:03d}") for i in range(1, 4)]
    assert evidence_gate(evs, min_incidents=3).passed


def test_evidence_gate_fails_with_two_incidents():
    evs = [_evidence(f"ev_{i:03d}") for i in range(1, 3)]
    g = evidence_gate(evs, min_incidents=3)
    assert not g.passed


def test_evidence_gate_flags_missing_fields():
    evs = [_evidence(f"ev_{i:03d}", cues=()) for i in range(1, 4)]
    g = evidence_gate(evs, min_incidents=3)
    assert not g.passed
    assert any("cues" in r for r in g.reasons)


# ---------- naming gate ----------

def test_naming_gate_requires_critical_incident():
    evs = [
        _evidence("ev_001", type=EvidenceType.RESUME_CLAIM),
        _evidence("ev_002", type=EvidenceType.RESUME_CLAIM),
    ]
    g = naming_gate([_mechanism()], evs)
    assert not g.passed
    assert any("no critical_incident" in r for r in g.reasons)


def test_naming_gate_passes_with_incident_support():
    evs = [_evidence("ev_001"), _evidence("ev_002", type=EvidenceType.RESUME_CLAIM)]
    g = naming_gate([_mechanism()], evs)
    assert g.passed


# ---------- consistency gate ----------

def test_consistency_gate_flags_unresolved_high_findings():
    rf = ReviewFindings(
        mechanism_id="m1",
        findings=[SkepticFinding(kind="overclaim", severity=SkepticSeverity.HIGH, detail="x")],
        repair_actions=[],  # no fix proposed
        confidence_delta=0.0,
    )
    g = consistency_gate({"m1": rf})
    assert not g.passed


def test_consistency_gate_ok_when_repair_actions_present():
    rf = ReviewFindings(
        mechanism_id="m1",
        findings=[SkepticFinding(kind="overclaim", severity=SkepticSeverity.HIGH, detail="x")],
        repair_actions=["rename to X"],
        confidence_delta=-0.1,
    )
    assert consistency_gate({"m1": rf}).passed


# ---------- apply_review ----------

def test_apply_review_downgrades_validated_on_high_severity():
    m = _mechanism(status=MechanismStatus.PROBABLE, confidence=0.85)
    # Actually create a validated one manually (bypassing factory above)
    m = MechanismCard(
        mechanism_id="m1", name="x", aliases=[], definition="d",
        evidence_ids=["ev_001", "ev_002"], anti_evidence_ids=[],
        pattern=MechanismPattern(cue_pattern=["x"], decision_rule="r", verification_style="v"),
        boundary_conditions=["b"], confidence=0.85, status=MechanismStatus.VALIDATED,
    )
    rf = ReviewFindings(
        mechanism_id="m1",
        findings=[SkepticFinding(kind="overclaim", severity=SkepticSeverity.HIGH, detail="x")],
        repair_actions=["downgrade"],
        confidence_delta=-0.1,
    )
    m2 = apply_review(m, rf)
    assert m2.status == MechanismStatus.PROBABLE
    assert m2.confidence == pytest.approx(0.75)


def test_apply_review_clean_review_keeps_status_consistent():
    m = MechanismCard(
        mechanism_id="m1", name="x", aliases=[], definition="d",
        evidence_ids=["ev_001", "ev_002"], anti_evidence_ids=[],
        pattern=MechanismPattern(cue_pattern=["x"], decision_rule="r", verification_style="v"),
        boundary_conditions=["b"], confidence=0.72, status=MechanismStatus.PROBABLE,
    )
    rf = ReviewFindings(mechanism_id="m1", findings=[], repair_actions=[], confidence_delta=0.05)
    m2 = apply_review(m, rf)
    assert m2.confidence == pytest.approx(0.77)
    assert m2.status == MechanismStatus.PROBABLE


def test_apply_review_promotes_to_validated_on_clean_high_confidence():
    m = MechanismCard(
        mechanism_id="m1", name="x", aliases=[], definition="d",
        evidence_ids=["ev_001", "ev_002"], anti_evidence_ids=[],
        pattern=MechanismPattern(cue_pattern=["x"], decision_rule="r", verification_style="v"),
        boundary_conditions=["b"], confidence=0.78, status=MechanismStatus.PROBABLE,
    )
    rf = ReviewFindings(mechanism_id="m1", findings=[], repair_actions=[], confidence_delta=0.05)
    m2 = apply_review(m, rf)
    assert m2.status == MechanismStatus.VALIDATED


# ---------- publish gate ----------

def test_publish_gate_requires_evidence_on_validated_claims():
    bad_vm = ValidatedMechanism(
        mechanism_id="m1", name="x", why_it_matters="x",
        resume_rewrite="x", interview_narrative="x",
        evidence_ids=["ev_001"], confidence=0.85,
    )
    rep = ExtractionReport(
        report_id="r1", candidate_id="c1",
        summary=ReportSummary(validated_mechanisms=1, probable_mechanisms=0, needs_more_evidence=0),
        validated_mechanisms=[bad_vm], probable_mechanisms=[],
    )
    assert publish_gate(rep, redacted_pii=True).passed


def test_publish_gate_fails_when_pii_not_redacted():
    rep = ExtractionReport(
        report_id="r1", candidate_id="c1",
        summary=ReportSummary(validated_mechanisms=0, probable_mechanisms=0, needs_more_evidence=0),
        validated_mechanisms=[], probable_mechanisms=[],
    )
    g = publish_gate(rep, redacted_pii=False)
    assert not g.passed
