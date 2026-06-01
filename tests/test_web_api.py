"""API tests — most use a fake registry that completes synchronously.

Real-LLM end-to-end is in test_web_e2e.py (gated on LYREBIRD_E2E=1).
"""
import json
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from lyrebird.observability import EventBus, EventType


# ----- helpers: a fake pipeline that emits a canned sequence then completes -----

class _FakePipeline:
    def __init__(self, ctx, store, run_id, n_interview_turns, min_incidents, candidate_id):
        self.ctx = ctx
        self.store = store
        self.run_id = run_id
        self.candidate_id = candidate_id

    def run(self, *, resume_text, target_role, resume_id):
        bus = self.ctx.bus
        bus.emit(EventType.RUN_STARTED, run_id=self.run_id, target_role=target_role)
        bus.emit(EventType.STAGE_STARTED, stage="intake")
        bus.emit(EventType.AGENT_STARTED, agent="intake", role="standard", stage="intake")
        bus.emit(EventType.AGENT_COMPLETED, agent="intake", stage="intake",
                 duration_ms=12, tokens_in=100, tokens_out=20)
        bus.emit(EventType.STAGE_COMPLETED, stage="intake", duration_ms=15)
        bus.emit(EventType.GATE_EVALUATED, gate="sufficiency", passed=True, reasons=[])
        bus.emit(EventType.RUN_COMPLETED, run_id=self.run_id,
                 summary={"validated_mechanisms": 0, "probable_mechanisms": 1, "needs_more_evidence": 0})

        # Synthesize a minimal PipelineResult-ish object
        from lyrebird.schemas import (
            CandidateProfile, CoreExperience, Hypothesis, Priority,
            ExtractionReport, ReportSummary,
        )
        from lyrebird.agents.orchestrator import PipelineResult, GateResult

        profile = CandidateProfile(
            candidate_id=self.candidate_id, source_resume_id=resume_id,
            target_role=target_role, career_stage="senior",
            core_experiences=[CoreExperience(
                experience_id="exp_01", company="X", title="Y", start="2020", end="2023",
                domains=[], claimed_outcomes=[],
            )],
            hypothesis_list=[Hypothesis(
                hypothesis_id="hyp_01", label="x", basis=[], priority=Priority.HIGH,
            )],
            unknowns=[],
        )
        report = ExtractionReport(
            report_id=f"rep_{self.run_id}", candidate_id=self.candidate_id,
            summary=ReportSummary(validated_mechanisms=0, probable_mechanisms=1, needs_more_evidence=0),
            validated_mechanisms=[], probable_mechanisms=[],
        )
        return PipelineResult(
            profile=profile, turns=[], evidences=[],
            mechanisms_pre_review=[], mechanisms_post_review=[],
            review_findings=[], report=report,
            gates=[GateResult("sufficiency", passed=True)],
        )


@pytest.fixture
def client(monkeypatch, tmp_path):
    # Point project paths at tmp so we don't pollute the real ./runs and ./artifacts
    monkeypatch.setenv("DEEPSEEK_API_KEY", "dummy")  # silence the warning
    # Patch the Pipeline used by RunRegistry
    monkeypatch.setattr("lyrebird.web.registry.Pipeline", _FakePipeline)
    # Avoid touching real LLM
    monkeypatch.setattr("lyrebird.web.registry.LLMClient", lambda: _FakeLLM())

    # Reroute artifact + runs dirs
    from lyrebird.web import app as app_mod
    monkeypatch.setattr(app_mod, "ARTIFACTS_ROOT", tmp_path / "artifacts")
    monkeypatch.setattr(app_mod, "RUNS_ROOT", tmp_path / "runs")

    app = app_mod.create_app()
    with TestClient(app) as c:
        yield c


class _FakeLLM:
    def __init__(self):
        class _S:
            input_tokens = 0
            output_tokens = 0
            n_calls = 0
        self.stats = _S()


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_sample_resume(client):
    r = client.get("/api/sample-resume")
    assert r.status_code == 200
    body = r.json()
    assert "resume_text" in body
    assert len(body["resume_text"]) > 100


def test_start_run_returns_run_id_and_urls(client):
    resp = client.post("/api/runs", json={
        "resume_text": "x" * 200,
        "target_role": "PM",
        "candidate_id": "cand_t",
        "turns": 3,
        "min_incidents": 2,
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["run_id"].startswith("run_")
    assert body["events_url"].endswith("/events")
    assert body["snapshot_url"].endswith("/snapshot")


def test_start_run_validates_short_resume(client):
    resp = client.post("/api/runs", json={
        "resume_text": "too short",
        "candidate_id": "cand_t",
        "turns": 3,
    })
    assert resp.status_code == 422


def test_start_run_validates_candidate_id_pattern(client):
    resp = client.post("/api/runs", json={
        "resume_text": "x" * 200,
        "candidate_id": "has spaces and 漢字",
        "turns": 3,
    })
    assert resp.status_code == 422


def test_run_status_progresses_to_completed(client):
    r = client.post("/api/runs", json={
        "resume_text": "x" * 200,
        "candidate_id": "cand_t",
        "turns": 3,
    })
    run_id = r.json()["run_id"]

    # The fake pipeline finishes near-instantly; poll briefly
    deadline = time.time() + 3
    status = None
    while time.time() < deadline:
        info = client.get(f"/api/runs/{run_id}").json()
        status = info["status"]
        if status in ("completed", "failed"):
            break
        time.sleep(0.05)
    assert status == "completed"


def test_snapshot_returns_events_in_seq_order(client):
    r = client.post("/api/runs", json={
        "resume_text": "x" * 200,
        "candidate_id": "cand_t",
        "turns": 3,
    })
    run_id = r.json()["run_id"]
    deadline = time.time() + 3
    while time.time() < deadline:
        info = client.get(f"/api/runs/{run_id}").json()
        if info["status"] == "completed":
            break
        time.sleep(0.05)

    snap = client.get(f"/api/runs/{run_id}/snapshot").json()
    seqs = [e["seq"] for e in snap["events"]]
    assert seqs == sorted(seqs)
    types = [e["type"] for e in snap["events"]]
    assert types[0] == "run.started"
    assert types[-1] == "run.completed"


def test_snapshot_after_seq_filters(client):
    r = client.post("/api/runs", json={
        "resume_text": "x" * 200,
        "candidate_id": "cand_t",
        "turns": 3,
    })
    run_id = r.json()["run_id"]
    deadline = time.time() + 3
    while time.time() < deadline:
        if client.get(f"/api/runs/{run_id}").json()["status"] == "completed":
            break
        time.sleep(0.05)
    full = client.get(f"/api/runs/{run_id}/snapshot").json()
    if len(full["events"]) >= 3:
        partial = client.get(f"/api/runs/{run_id}/snapshot?after_seq=2").json()
        assert all(e["seq"] > 2 for e in partial["events"])


def test_get_report_after_completion(client):
    r = client.post("/api/runs", json={
        "resume_text": "x" * 200,
        "candidate_id": "cand_t",
        "turns": 3,
    })
    run_id = r.json()["run_id"]
    deadline = time.time() + 3
    while time.time() < deadline:
        if client.get(f"/api/runs/{run_id}").json()["status"] == "completed":
            break
        time.sleep(0.05)
    rep = client.get(f"/api/runs/{run_id}/report")
    assert rep.status_code == 200
    body = rep.json()
    assert body["report_id"].startswith("rep_")
    assert "summary" in body


def test_404_on_unknown_run(client):
    r = client.get("/api/runs/run_nope/snapshot")
    assert r.status_code == 404


def test_list_runs(client):
    client.post("/api/runs", json={"resume_text": "x" * 200, "candidate_id": "cand_t", "turns": 3})
    client.post("/api/runs", json={"resume_text": "x" * 200, "candidate_id": "cand_t", "turns": 3})
    runs = client.get("/api/runs").json()
    assert len(runs) >= 2


def test_sse_replay_honors_last_event_id_header(client):
    """A reconnecting browser sends Last-Event-ID; server must NOT replay past events."""
    r = client.post("/api/runs", json={
        "resume_text": "x" * 200, "candidate_id": "cand_t", "turns": 3,
    })
    run_id = r.json()["run_id"]
    deadline = time.time() + 3
    while time.time() < deadline:
        if client.get(f"/api/runs/{run_id}").json()["status"] == "completed":
            break
        time.sleep(0.05)

    full = client.get(f"/api/runs/{run_id}/snapshot").json()
    last_seq = full["events"][-1]["seq"]

    # Now simulate reconnect by setting Last-Event-ID equal to the final seq
    with client.stream(
        "GET",
        f"/api/runs/{run_id}/events",
        headers={"Last-Event-ID": str(last_seq)},
    ) as resp:
        assert resp.status_code == 200
        body = b""
        for chunk in resp.iter_bytes():
            body += chunk
            if len(body) > 4096:
                break
        text = body.decode("utf-8")
        # No event lines should appear — we asked for "after the last one"
        event_lines = [
            l for l in text.splitlines()
            if l.startswith("event:") and "ping" not in l
        ]
        assert event_lines == [], f"unexpected replay: {event_lines}"


def test_sse_stream_yields_typed_events(client):
    """Subscribe to SSE and confirm the canned sequence of event types arrives."""
    r = client.post("/api/runs", json={
        "resume_text": "x" * 200,
        "candidate_id": "cand_sse",
        "turns": 3,
    })
    run_id = r.json()["run_id"]

    # Give pipeline time to run (it's near-instant with the fake)
    deadline = time.time() + 3
    while time.time() < deadline:
        if client.get(f"/api/runs/{run_id}").json()["status"] == "completed":
            break
        time.sleep(0.05)

    # Now request the SSE stream; since the run is already terminal, the snapshot
    # replay will emit all events and the stream will close.
    with client.stream("GET", f"/api/runs/{run_id}/events") as resp:
        assert resp.status_code == 200
        # Collect all events from the stream
        types_seen = []
        body = b""
        for chunk in resp.iter_bytes():
            body += chunk
            if b"run.completed" in body:
                break
        text = body.decode("utf-8")
        # SSE format: "event: <type>\ndata: <json>\n\n"
        for line in text.splitlines():
            if line.startswith("event:"):
                types_seen.append(line.split(":", 1)[1].strip())
    assert "run.started" in types_seen
    assert "stage.started" in types_seen
    assert "agent.completed" in types_seen
    assert "run.completed" in types_seen
