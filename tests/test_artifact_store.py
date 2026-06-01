"""Artifact store — the cross-agent fact bus (per arch.md §通信协议)."""
from pathlib import Path

import pytest

from lyrebird.artifact_store import ArtifactStore
from lyrebird.schemas import (
    CandidateProfile, CoreExperience, Hypothesis, Priority,
    EvidenceCard, EvidenceType, SourceRef,
)


@pytest.fixture
def store(tmp_path: Path) -> ArtifactStore:
    return ArtifactStore(root=tmp_path)


def _profile() -> CandidateProfile:
    return CandidateProfile(
        candidate_id="c1", source_resume_id="r1",
        target_role="PM", career_stage="senior",
        core_experiences=[CoreExperience(
            experience_id="exp_01", company="X", title="Y",
            start="2020-01", end="2023-01",
            domains=["a"], claimed_outcomes=["b"],
        )],
        hypothesis_list=[Hypothesis(
            hypothesis_id="hyp_01", label="x", basis=["b"], priority=Priority.HIGH,
        )],
        unknowns=[],
    )


def _evidence(eid: str) -> EvidenceCard:
    return EvidenceCard(
        evidence_id=eid,
        type=EvidenceType.CRITICAL_INCIDENT,
        source_ref=SourceRef(conversation_turn_ids=["t1"], resume_span_ref="exp_01"),
        situation="s", goal="g", constraints=["c"], cues=["q"],
        judgment="j", actions=["a"], outcome="o", confidence=0.7,
    )


def test_store_put_and_get_roundtrip(store):
    p = _profile()
    store.put("candidate_profile", "c1", p)
    fetched = store.get("candidate_profile", "c1", CandidateProfile)
    assert fetched == p


def test_store_persists_to_disk(tmp_path):
    s1 = ArtifactStore(root=tmp_path)
    p = _profile()
    s1.put("candidate_profile", "c1", p)
    # Re-open
    s2 = ArtifactStore(root=tmp_path)
    fetched = s2.get("candidate_profile", "c1", CandidateProfile)
    assert fetched.candidate_id == "c1"


def test_store_list_returns_all_ids(store):
    store.put("evidence_card", "ev_001", _evidence("ev_001"))
    store.put("evidence_card", "ev_002", _evidence("ev_002"))
    ids = store.list_ids("evidence_card")
    assert set(ids) == {"ev_001", "ev_002"}


def test_store_load_all_returns_validated_models(store):
    store.put("evidence_card", "ev_001", _evidence("ev_001"))
    store.put("evidence_card", "ev_002", _evidence("ev_002"))
    items = store.load_all("evidence_card", EvidenceCard)
    assert len(items) == 2
    assert all(isinstance(i, EvidenceCard) for i in items)


def test_store_get_missing_returns_none(store):
    assert store.get("candidate_profile", "nope", CandidateProfile) is None


def test_store_records_provenance(store):
    p = _profile()
    store.put("candidate_profile", "c1", p, agent="intake", run_id="r-1")
    prov = store.get_provenance("candidate_profile", "c1")
    assert prov["agent"] == "intake"
    assert prov["run_id"] == "r-1"
    assert "written_at" in prov
