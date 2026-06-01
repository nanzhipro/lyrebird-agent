"""Run the full extraction pipeline against a resume file."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from lyrebird.agents.base import AgentContext
from lyrebird.agents.orchestrator import Pipeline
from lyrebird.artifact_store import ArtifactStore
from lyrebird.llm.client import LLMClient
from lyrebird.skills import SkillsLibrary


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Quiet the SDK
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)


def main() -> int:
    parser = argparse.ArgumentParser(description="Lyrebird: cognitive mechanism extraction")
    parser.add_argument("--resume", type=Path, required=True, help="path to candidate resume (.md)")
    parser.add_argument("--target-role", type=str, default=None)
    parser.add_argument("--candidate-id", type=str, default="cand_L")
    parser.add_argument("--turns", type=int, default=6, help="number of interview turns")
    parser.add_argument("--min-incidents", type=int, default=3)
    parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    parser.add_argument("--run-out", type=Path, default=Path("runs"))
    parser.add_argument("--skills-root", type=Path, default=Path("skills"))
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    load_dotenv()
    configure_logging(args.verbose)
    console = Console()

    if not args.resume.exists():
        console.print(f"[red]resume not found: {args.resume}")
        return 2

    resume_text = args.resume.read_text(encoding="utf-8")
    artifact_root = args.artifact_root
    artifact_root.mkdir(parents=True, exist_ok=True)
    args.run_out.mkdir(parents=True, exist_ok=True)

    ctx = AgentContext(
        llm=LLMClient(),
        skills=SkillsLibrary(root=args.skills_root),
        run_id="cli",
    )
    pipeline = Pipeline(
        ctx=ctx,
        store=ArtifactStore(root=artifact_root),
        candidate_id=args.candidate_id,
        n_interview_turns=args.turns,
        min_incidents=args.min_incidents,
    )

    console.print(Panel.fit(
        f"[bold]Lyrebird[/bold] run_id=[cyan]{pipeline.run_id}[/cyan]\n"
        f"resume={args.resume}\n"
        f"target_role={args.target_role}\n"
        f"turns={args.turns}",
        title="starting",
    ))

    result = pipeline.run(
        resume_text=resume_text,
        target_role=args.target_role,
        resume_id=args.resume.name,
    )

    # Persist a complete run transcript
    out_path = args.run_out / f"{pipeline.run_id}.json"
    transcript = {
        "run_id": pipeline.run_id,
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
    }
    out_path.write_text(
        json.dumps(transcript, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    _render_summary(console, result, out_path, ctx)
    return 0


def _render_summary(console: Console, result, out_path: Path, ctx: AgentContext) -> None:
    console.print(f"\n[green]✓ run complete[/green] transcript={out_path}\n")

    t = Table(title="Gates")
    t.add_column("gate"); t.add_column("passed"); t.add_column("reasons")
    for g in result.gates:
        t.add_row(g.name, "✓" if g.passed else "✗", "; ".join(g.reasons) or "-")
    console.print(t)

    t2 = Table(title="Mechanisms (post-review)")
    t2.add_column("id"); t2.add_column("status"); t2.add_column("conf"); t2.add_column("name")
    for m in result.mechanisms_post_review:
        t2.add_row(m.mechanism_id, m.status.value, f"{m.confidence:.2f}", m.name)
    console.print(t2)

    rep = result.report
    console.print(Panel(
        f"[bold]validated[/bold]: {rep.summary.validated_mechanisms}\n"
        f"[bold]probable[/bold]: {rep.summary.probable_mechanisms}\n"
        f"[bold]needs more evidence[/bold]: {rep.summary.needs_more_evidence}",
        title="Extraction Report Summary",
    ))

    for vm in rep.validated_mechanisms:
        console.print(Panel(
            f"[bold]{vm.name}[/bold]\n\n"
            f"why_it_matters: {vm.why_it_matters}\n\n"
            f"resume_rewrite: {vm.resume_rewrite}\n\n"
            f"interview_narrative: {vm.interview_narrative}\n\n"
            f"evidence: {vm.evidence_ids}  conf={vm.confidence:.2f}",
            title=f"VALIDATED · {vm.mechanism_id}",
            border_style="green",
        ))

    for pm in rep.probable_mechanisms:
        console.print(Panel(
            f"[bold]{pm.name}[/bold]\n\n"
            f"why_it_matters: {pm.why_it_matters}\n\n"
            f"resume_rewrite: {pm.resume_rewrite}\n\n"
            f"interview_narrative: {pm.interview_narrative}\n\n"
            f"evidence: {pm.evidence_ids}  conf={pm.confidence:.2f}",
            title=f"PROBABLE · {pm.mechanism_id}",
            border_style="yellow",
        ))

    console.print(f"\n[cyan]LLM usage: input={ctx.llm.stats.input_tokens} "
                  f"output={ctx.llm.stats.output_tokens} calls={ctx.llm.stats.n_calls}[/cyan]")


if __name__ == "__main__":
    sys.exit(main())
