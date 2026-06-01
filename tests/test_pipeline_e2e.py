"""End-to-end smoke test against real DeepSeek API.

Marked as `slow` — runs only when env LYREBIRD_E2E=1 is set.
Costs ~10–20k tokens per run.
"""
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from lyrebird.agents.base import AgentContext
from lyrebird.agents.orchestrator import Pipeline
from lyrebird.artifact_store import ArtifactStore
from lyrebird.llm.client import LLMClient
from lyrebird.skills import SkillsLibrary


pytestmark = pytest.mark.skipif(
    os.environ.get("LYREBIRD_E2E") != "1",
    reason="Set LYREBIRD_E2E=1 to run real-API end-to-end test",
)


def test_full_pipeline_against_redacted_resume(tmp_path):
    load_dotenv()
    project_root = Path(__file__).resolve().parent.parent
    resume = (project_root / "resume.redacted.md").read_text(encoding="utf-8")

    ctx = AgentContext(
        llm=LLMClient(),
        skills=SkillsLibrary(root=project_root / "skills"),
        run_id="pytest_e2e",
    )
    pipeline = Pipeline(
        ctx=ctx,
        store=ArtifactStore(root=tmp_path / "artifacts"),
        candidate_id="cand_pytest",
        n_interview_turns=4,
        min_incidents=2,
    )
    result = pipeline.run(
        resume_text=resume,
        target_role="macOS 终端安全架构师",
        resume_id="resume.redacted.md",
    )

    # Basic invariants
    assert result.profile.candidate_id == "cand_pytest"
    assert len(result.turns) == 4
    assert len(result.evidences) >= 1
    assert result.report.report_id.startswith("rep_")
    # Every claim must carry evidence
    for vm in result.report.validated_mechanisms + result.report.probable_mechanisms:
        assert vm.evidence_ids, f"{vm.mechanism_id} missing evidence_ids"
    # Summary counts match list lengths
    assert result.report.summary.validated_mechanisms == len(result.report.validated_mechanisms)
    assert result.report.summary.probable_mechanisms == len(result.report.probable_mechanisms)
