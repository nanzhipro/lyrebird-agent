"""RunRegistry — in-memory registry of active and recent pipeline runs.

Per memo/07: runs live in memory while active; reports persist to disk via
ArtifactStore + run-transcript JSON. After a run terminates, the bus is kept
in the registry for a grace period so late SSE clients can still grab the
final events via /snapshot.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from lyrebird.agents.base import AgentContext
from lyrebird.agents.orchestrator import Pipeline, PipelineResult
from lyrebird.artifact_store import ArtifactStore
from lyrebird.llm.client import LLMClient
from lyrebird.observability import EventBus, EventType
from lyrebird.skills import SkillsLibrary

log = logging.getLogger(__name__)


@dataclass
class RunHandle:
    """One handle per pipeline run. Bus + future + final report (if done)."""
    run_id: str
    bus: EventBus
    future: Future
    started_at: datetime
    params: dict
    result: Optional[PipelineResult] = None
    error: Optional[str] = None
    finished_at: Optional[datetime] = None

    @property
    def status(self) -> str:
        if self.future.done():
            if self.error:
                return "failed"
            if self.result is not None:
                return "completed"
            return "unknown"
        return "running"


@dataclass
class RunRegistry:
    """Owns the thread pool that runs pipelines, and the lookup table."""
    skills_root: Path
    artifact_root: Path
    runs_root: Path
    max_concurrent_runs: int = 4
    retention_seconds: int = 3600  # keep finished runs for 1h after completion

    def __post_init__(self):
        self._lock = threading.Lock()
        self._runs: Dict[str, RunHandle] = {}
        self._id_counter = 0  # tie-breaker if two POSTs land in the same ms
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_concurrent_runs,
            thread_name_prefix="lyrebird-pipeline",
        )
        self.skills = SkillsLibrary(root=self.skills_root)
        self.artifact_store = ArtifactStore(root=self.artifact_root)
        self.runs_root.mkdir(parents=True, exist_ok=True)

    # ---------- public ----------

    def start_run(
        self,
        *,
        resume_text: str,
        target_role: Optional[str],
        candidate_id: str,
        turns: int,
        min_incidents: int,
        resume_id: str = "user_input.md",
    ) -> RunHandle:
        run_id = self._make_run_id()
        bus = EventBus(run_id=run_id)
        ctx = AgentContext(
            llm=LLMClient(),
            skills=self.skills,
            run_id=run_id,
            bus=bus,
        )
        pipeline = Pipeline(
            ctx=ctx,
            store=self.artifact_store,
            run_id=run_id,
            n_interview_turns=turns,
            min_incidents=min_incidents,
            candidate_id=candidate_id,
        )

        future = self._executor.submit(
            self._run_one,
            pipeline=pipeline,
            resume_text=resume_text,
            target_role=target_role,
            resume_id=resume_id,
            ctx=ctx,
        )

        handle = RunHandle(
            run_id=run_id,
            bus=bus,
            future=future,
            started_at=datetime.now(timezone.utc),
            params={
                "target_role": target_role,
                "candidate_id": candidate_id,
                "turns": turns,
                "min_incidents": min_incidents,
                "resume_chars": len(resume_text),
            },
        )

        # Hook to capture result and write transcript
        def _on_done(fut: Future):
            try:
                result = fut.result()
                handle.result = result
                self._persist_transcript(handle, result, ctx)
            except Exception as e:
                handle.error = f"{type(e).__name__}: {e}"
                log.exception("run %s failed", run_id)
            finally:
                handle.finished_at = datetime.now(timezone.utc)

        future.add_done_callback(_on_done)

        with self._lock:
            self._runs[run_id] = handle

        self._evict_expired()
        return handle

    def get(self, run_id: str) -> Optional[RunHandle]:
        with self._lock:
            return self._runs.get(run_id)

    def list_runs(self) -> list[RunHandle]:
        with self._lock:
            return list(self._runs.values())

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    # ---------- internals ----------

    def _make_run_id(self) -> str:
        with self._lock:
            self._id_counter += 1
            n = self._id_counter
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:-3]
        # Suffix a monotonic counter so rapid-fire POSTs never collide
        return f"run_{stamp}_{n:04d}"

    @staticmethod
    def _run_one(
        *,
        pipeline: Pipeline,
        resume_text: str,
        target_role: Optional[str],
        resume_id: str,
        ctx: AgentContext,
    ) -> PipelineResult:
        return pipeline.run(
            resume_text=resume_text,
            target_role=target_role,
            resume_id=resume_id,
        )

    def _persist_transcript(self, handle: RunHandle, result: PipelineResult, ctx: AgentContext) -> None:
        import json
        transcript = {
            "run_id": handle.run_id,
            "params": handle.params,
            "candidate_profile": result.profile.model_dump(mode="json"),
            "turns": [t.model_dump(mode="json") for t in result.turns],
            "evidences": [e.model_dump(mode="json") for e in result.evidences],
            "mechanisms_pre_review": [m.model_dump(mode="json") for m in result.mechanisms_pre_review],
            "mechanisms_post_review": [m.model_dump(mode="json") for m in result.mechanisms_post_review],
            "review_findings": [r.model_dump(mode="json") for r in result.review_findings],
            "report": result.report.model_dump(mode="json"),
            "gates": [{"name": g.name, "passed": g.passed, "reasons": g.reasons} for g in result.gates],
            "llm_stats": {
                "input_tokens": ctx.llm.stats.input_tokens,
                "output_tokens": ctx.llm.stats.output_tokens,
                "n_calls": ctx.llm.stats.n_calls,
            },
            "events": [e.to_dict() for e in handle.bus.snapshot()],
        }
        out = self.runs_root / f"{handle.run_id}.json"
        out.write_text(json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8")

    def _evict_expired(self) -> None:
        now = time.time()
        with self._lock:
            to_drop = [
                rid for rid, h in self._runs.items()
                if h.finished_at and (now - h.finished_at.timestamp()) > self.retention_seconds
            ]
            for rid in to_drop:
                del self._runs[rid]
