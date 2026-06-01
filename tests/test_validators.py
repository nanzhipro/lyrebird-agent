"""Deterministic validators — these are scripts, not agents (per arch.md §架构原则二)."""
import pytest

from lyrebird.validators.pii_guard import scan_pii, PIIFinding
from lyrebird.validators.citation_checker import (
    check_evidence_citations,
    check_mechanism_citations,
)
from lyrebird.validators.confidence_scorer import (
    score_mechanism_confidence,
    ConfidenceComponents,
)
from lyrebird.schemas import (
    EvidenceCard, EvidenceType, SourceRef,
    MechanismCard, MechanismPattern, MechanismStatus,
)


# ---------- PII Guard ----------

def test_pii_guard_phone():
    findings = scan_pii("联系电话 13800138000")
    assert any(f.kind == "phone_cn" for f in findings)


def test_pii_guard_email():
    findings = scan_pii("e-mail: alice.smith@example.com please")
    assert any(f.kind == "email" for f in findings)


def test_pii_guard_id_card():
    findings = scan_pii("身份证: 110101199001011234")
    assert any(f.kind == "id_card_cn" for f in findings)


def test_pii_guard_clean_text():
    assert scan_pii("终端安全架构师, 20 年经验") == []


def test_pii_guard_redact():
    text = "phone 13800138000 and mail x@y.com"
    findings = scan_pii(text)
    redacted = PIIFinding.redact_all(text, findings)
    assert "13800138000" not in redacted
    assert "x@y.com" not in redacted


# ---------- Citation Checker ----------

def _ev(eid: str, resume_ref: str = "exp_01") -> EvidenceCard:
    return EvidenceCard(
        evidence_id=eid,
        type=EvidenceType.CRITICAL_INCIDENT,
        source_ref=SourceRef(conversation_turn_ids=["t_1"], resume_span_ref=resume_ref),
        situation="s", goal="g", constraints=["c"], cues=["cue"],
        judgment="j", actions=["a"], outcome="o", confidence=0.7,
    )


def test_citation_checker_evidence_pointing_to_known_resume_span():
    ev = _ev("ev_001", resume_ref="exp_01")
    result = check_evidence_citations([ev], known_resume_span_ids={"exp_01", "exp_02"})
    assert result.ok
    assert result.missing_resume_refs == []


def test_citation_checker_flags_unknown_resume_span():
    ev = _ev("ev_001", resume_ref="exp_99")
    result = check_evidence_citations([ev], known_resume_span_ids={"exp_01"})
    assert not result.ok
    assert "exp_99" in result.missing_resume_refs


def test_citation_checker_mechanism_evidence_ids_resolve():
    ev1, ev2 = _ev("ev_001"), _ev("ev_002")
    m = MechanismCard(
        mechanism_id="mech_1", name="x", aliases=[], definition="x",
        evidence_ids=["ev_001", "ev_002"], anti_evidence_ids=[],
        pattern=MechanismPattern(cue_pattern=[], decision_rule="x", verification_style="x"),
        boundary_conditions=[], confidence=0.5, status=MechanismStatus.HYPOTHESIS,
    )
    result = check_mechanism_citations([m], {"ev_001", "ev_002"})
    assert result.ok


def test_citation_checker_flags_dangling_evidence_ref():
    ev1 = _ev("ev_001")
    m = MechanismCard(
        mechanism_id="mech_1", name="x", aliases=[], definition="x",
        evidence_ids=["ev_001", "ev_missing"], anti_evidence_ids=[],
        pattern=MechanismPattern(cue_pattern=[], decision_rule="x", verification_style="x"),
        boundary_conditions=[], confidence=0.5, status=MechanismStatus.HYPOTHESIS,
    )
    result = check_mechanism_citations([m], {"ev_001"})
    assert not result.ok
    assert "ev_missing" in result.dangling_evidence_ids


# ---------- Confidence Scorer ----------

def test_confidence_scorer_full_strength():
    c = ConfidenceComponents(
        evidence_richness=1.0,
        cross_context_replication=1.0,
        internal_consistency=1.0,
        candidate_endorsement=1.0,
        outcome_link_strength=1.0,
    )
    assert abs(score_mechanism_confidence(c) - 1.0) < 1e-9


def test_confidence_scorer_balanced_mid():
    c = ConfidenceComponents(0.5, 0.5, 0.5, 0.5, 0.5)
    assert abs(score_mechanism_confidence(c) - 0.5) < 1e-9


def test_confidence_scorer_weighted_priority():
    """Evidence richness should weigh more than candidate endorsement."""
    high_ev = ConfidenceComponents(1.0, 0.0, 0.0, 0.0, 0.0)
    high_endorse = ConfidenceComponents(0.0, 0.0, 0.0, 1.0, 0.0)
    assert score_mechanism_confidence(high_ev) > score_mechanism_confidence(high_endorse)


def test_confidence_scorer_clamps_in_unit():
    c = ConfidenceComponents(2.0, -1.0, 0.5, 0.5, 0.5)  # garbage in
    s = score_mechanism_confidence(c)
    assert 0.0 <= s <= 1.0
