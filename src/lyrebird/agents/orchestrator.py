"""Orchestrator — coordinates the seven-stage pipeline.

Per arch.md §推荐的生产架构选择: flat, single-tier delegation. The orchestrator
is NOT a free agent — it's a deterministic state machine that:
  1. Calls worker agents in order
  2. Persists every artifact to the ArtifactStore
  3. Enforces gates (sufficiency / naming / consistency / publish)
  4. Adjusts mechanism status based on Skeptic findings
  5. Computes mechanism confidence from explicit components (NOT model output)
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from lyrebird.agents.base import AgentContext
from lyrebird.agents import (
    intake, interviewer, simulated_candidate,
    evidence_mapper, mechanism_modeler, skeptic, report_composer,
)
from lyrebird.artifact_store import ArtifactStore
from lyrebird.observability import EventType
from lyrebird.schemas import (
    CandidateProfile,
    EvidenceCard,
    EvidenceType,
    ExtractionReport,
    InterviewTurn,
    MechanismCard,
    MechanismStatus,
    ReviewFindings,
    SkepticSeverity,
)
from lyrebird.validators.citation_checker import (
    check_evidence_citations,
    check_mechanism_citations,
)
from lyrebird.validators.confidence_scorer import (
    ConfidenceComponents,
    score_mechanism_confidence,
)
from lyrebird.validators.pii_guard import scan_pii, PIIFinding

log = logging.getLogger(__name__)


@dataclass
class GateResult:
    name: str
    passed: bool
    reasons: List[str] = field(default_factory=list)


@dataclass
class PipelineResult:
    profile: CandidateProfile
    turns: List[InterviewTurn]
    evidences: List[EvidenceCard]
    mechanisms_pre_review: List[MechanismCard]
    mechanisms_post_review: List[MechanismCard]
    review_findings: List[ReviewFindings]
    report: ExtractionReport
    gates: List[GateResult]


# ---------------- gates ----------------

def sufficiency_gate(profile: CandidateProfile) -> GateResult:
    """intake -> interview: at least 1 high-priority hypothesis + 1 experience."""
    reasons: List[str] = []
    has_high = any(h.priority.value == "high" for h in profile.hypothesis_list)
    if not has_high:
        reasons.append("no high-priority hypothesis")
    if len(profile.core_experiences) < 1:
        reasons.append("no core experiences")
    return GateResult("sufficiency", passed=not reasons, reasons=reasons)


def evidence_gate(evidences: List[EvidenceCard], min_incidents: int = 3) -> GateResult:
    reasons: List[str] = []
    incidents = [e for e in evidences if e.type == EvidenceType.CRITICAL_INCIDENT]
    if len(incidents) < min_incidents:
        reasons.append(
            f"only {len(incidents)} critical_incident(s); need >={min_incidents}"
        )
    for e in incidents:
        missing = []
        if not e.cues:
            missing.append("cues")
        if not e.judgment:
            missing.append("judgment")
        if not e.actions:
            missing.append("actions")
        if not e.outcome:
            missing.append("outcome")
        if missing:
            reasons.append(f"{e.evidence_id} missing: {missing}")
    return GateResult("evidence", passed=not reasons, reasons=reasons)


def naming_gate(
    mechanisms: List[MechanismCard],
    evidences: List[EvidenceCard],
) -> GateResult:
    reasons: List[str] = []
    ev_index = {e.evidence_id: e for e in evidences}
    for m in mechanisms:
        if len(set(m.evidence_ids)) < 2:
            reasons.append(f"{m.mechanism_id} <2 distinct evidence_ids")
        has_incident = any(
            ev_index.get(eid) and ev_index[eid].type == EvidenceType.CRITICAL_INCIDENT
            for eid in m.evidence_ids
        )
        if not has_incident:
            reasons.append(f"{m.mechanism_id} no critical_incident support")
    return GateResult("naming", passed=not reasons, reasons=reasons)


def consistency_gate(findings_by_mech: dict[str, ReviewFindings]) -> GateResult:
    """High-severity skeptic findings must be addressed (have repair_actions)."""
    reasons: List[str] = []
    for mid, rf in findings_by_mech.items():
        unresolved_high = [
            f for f in rf.findings if f.severity == SkepticSeverity.HIGH
        ]
        if unresolved_high and not rf.repair_actions:
            reasons.append(f"{mid} has {len(unresolved_high)} unresolved HIGH findings")
    return GateResult("consistency", passed=not reasons, reasons=reasons)


def publish_gate(report: ExtractionReport, redacted_pii: bool) -> GateResult:
    reasons: List[str] = []
    for vm in report.validated_mechanisms:
        if not vm.evidence_ids:
            reasons.append(f"validated {vm.mechanism_id} missing evidence_ids")
    if not redacted_pii:
        reasons.append("PII not fully scrubbed")
    return GateResult("publish", passed=not reasons, reasons=reasons)


# ---------------- skeptic-driven adjustment ----------------

def apply_review(m: MechanismCard, rf: ReviewFindings) -> MechanismCard:
    """Adjust confidence & status per Skeptic findings (deterministic, not LLM)."""
    new_conf = max(0.0, min(1.0, m.confidence + rf.confidence_delta))
    has_high = any(f.severity == SkepticSeverity.HIGH for f in rf.findings)
    if has_high:
        # arch.md §一致性门: strong unresolved counter-example -> cannot be validated
        new_status = MechanismStatus.PROBABLE if new_conf >= 0.6 else MechanismStatus.HYPOTHESIS
    elif new_conf >= 0.80:
        new_status = MechanismStatus.VALIDATED
    elif new_conf >= 0.60:
        new_status = MechanismStatus.PROBABLE
    else:
        new_status = MechanismStatus.HYPOTHESIS

    data = m.model_dump()
    data["confidence"] = new_conf
    data["status"] = new_status
    return MechanismCard.model_validate(data)


# ---------------- pipeline ----------------

@dataclass
class Pipeline:
    ctx: AgentContext
    store: ArtifactStore
    run_id: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("run_%Y%m%d_%H%M%S"))
    n_interview_turns: int = 6
    min_incidents: int = 3
    candidate_id: str = "cand_001"

    # ---- observability helpers ----

    def _emit(self, type: EventType, **payload):
        if self.ctx.bus is not None:
            self.ctx.bus.emit(type, **payload)

    def _stage(self, name: str):
        """Context manager-like helper: set current_stage and emit started/completed."""
        # Implemented as inline guards in run() because we need to emit on early
        # exit too. See _enter_stage / _exit_stage.
        raise NotImplementedError

    def _enter_stage(self, name: str) -> float:
        self.ctx.current_stage = name
        self._emit(EventType.STAGE_STARTED, stage=name)
        log.info("[%s] stage=%s", self.run_id, name)
        return time.time()

    def _exit_stage(self, name: str, t0: float, **extra):
        self._emit(
            EventType.STAGE_COMPLETED,
            stage=name,
            duration_ms=int((time.time() - t0) * 1000),
            **extra,
        )

    def _emit_gate(self, g: GateResult):
        self._emit(
            EventType.GATE_EVALUATED,
            gate=g.name,
            passed=g.passed,
            reasons=g.reasons,
        )

    def run(
        self,
        *,
        resume_text: str,
        target_role: Optional[str],
        resume_id: str = "resume_001",
    ) -> PipelineResult:
        gates: List[GateResult] = []
        self._emit(
            EventType.RUN_STARTED,
            run_id=self.run_id,
            candidate_id=self.candidate_id,
            target_role=target_role,
            turns=self.n_interview_turns,
            min_incidents=self.min_incidents,
        )

        try:
            # ---- stage 1: PII scan on resume (informational only — resume is already redacted) ----
            t0 = self._enter_stage("pii_scan")
            pii_initial = scan_pii(resume_text)
            if pii_initial:
                log.warning("resume PII findings (will be reported in privacy_notes): %s",
                            [f.kind for f in pii_initial])
                resume_for_agents = PIIFinding.redact_all(resume_text, pii_initial)
            else:
                resume_for_agents = resume_text
            self._exit_stage("pii_scan", t0, n_findings=len(pii_initial))

            # ---- stage 2: intake ----
            t0 = self._enter_stage("intake")
            profile = intake.run_intake(
                self.ctx,
                candidate_id=self.candidate_id,
                source_resume_id=resume_id,
                resume_text=resume_for_agents,
                target_role=target_role,
            )
            self.store.put("candidate_profile", profile.candidate_id, profile,
                           agent="intake", run_id=self.run_id)
            self._emit(EventType.ARTIFACT_WRITTEN,
                       artifact_type="candidate_profile",
                       artifact_id=profile.candidate_id)
            self._exit_stage("intake", t0,
                             n_experiences=len(profile.core_experiences),
                             n_hypotheses=len(profile.hypothesis_list))

            suff = sufficiency_gate(profile)
            gates.append(suff)
            self._emit_gate(suff)
            if not suff.passed:
                raise RuntimeError(f"sufficiency-gate failed: {suff.reasons}")

            # ---- stage 3: interview ----
            t0 = self._enter_stage("interview")
            turns: List[InterviewTurn] = []
            for i in range(self.n_interview_turns):
                tid = f"t_{i+1:02d}"
                q = interviewer.next_question(
                    self.ctx, profile=profile, history=turns, turn_id=tid,
                )
                a = simulated_candidate.answer(
                    self.ctx, resume_text=resume_for_agents, history=turns, question=q,
                )
                turn = InterviewTurn(
                    turn_id=tid,
                    question=q.question,
                    answer=a.answer,
                    target_hypothesis_id=q.target_hypothesis_id,
                )
                turns.append(turn)
                self.store.put("interview_turn", tid, turn,
                               agent="interviewer+candidate", run_id=self.run_id)
                self._emit(EventType.ARTIFACT_WRITTEN,
                           artifact_type="interview_turn",
                           artifact_id=tid,
                           question=q.question,
                           answer_preview=a.answer[:160])
            self._exit_stage("interview", t0, n_turns=len(turns))

            # ---- stage 4: evidence mapping ----
            t0 = self._enter_stage("evidence_mapping")
            batch = evidence_mapper.map_interview_to_evidence(
                self.ctx, profile=profile, history=turns, starting_evidence_index=1,
            )
            evidences = batch.evidence_cards
            for e in evidences:
                self.store.put("evidence_card", e.evidence_id, e,
                               agent="evidence_mapper", run_id=self.run_id)
                self._emit(EventType.ARTIFACT_WRITTEN,
                           artifact_type="evidence_card",
                           artifact_id=e.evidence_id,
                           evidence_type=e.type.value,
                           confidence=e.confidence)

            known_spans = {ex.experience_id for ex in profile.core_experiences}
            cite_e = check_evidence_citations(evidences, known_spans)
            if not cite_e.ok:
                log.warning("evidence citation issues: %s", cite_e.missing_resume_refs)

            eg = evidence_gate(evidences, min_incidents=self.min_incidents)
            gates.append(eg)
            self._emit_gate(eg)
            if not eg.passed:
                log.warning("evidence-gate soft-fail: %s — proceeding for MVP demo", eg.reasons)
            self._exit_stage("evidence_mapping", t0, n_evidences=len(evidences))

            # ---- stage 5: mechanism modeling ----
            t0 = self._enter_stage("mechanism_naming")
            mech_batch = mechanism_modeler.model_mechanisms(
                self.ctx, profile=profile, evidences=evidences,
            )
            mechs_pre = mech_batch.mechanism_cards
            for m in mechs_pre:
                self.store.put("mechanism_card_pre", m.mechanism_id, m,
                               agent="mechanism_modeler", run_id=self.run_id)
                self._emit(EventType.ARTIFACT_WRITTEN,
                           artifact_type="mechanism_card_pre",
                           artifact_id=m.mechanism_id,
                           name=m.name,
                           confidence=m.confidence)

            ng = naming_gate(mechs_pre, evidences)
            gates.append(ng)
            self._emit_gate(ng)
            if not ng.passed:
                log.warning("naming-gate soft-fail: %s — proceeding for MVP demo", ng.reasons)

            known_ev = {e.evidence_id for e in evidences}
            cite_m = check_mechanism_citations(mechs_pre, known_ev)
            if not cite_m.ok:
                log.warning("mechanism citation dangling: %s", cite_m.dangling_evidence_ids)

            mechs_pre_rescored: List[MechanismCard] = []
            for m in mechs_pre:
                components = self._estimate_components(m, evidences)
                new_conf = score_mechanism_confidence(components)
                blended = 0.5 * m.confidence + 0.5 * new_conf
                data = m.model_dump()
                data["confidence"] = round(blended, 3)
                if data["confidence"] >= 0.8:
                    data["status"] = MechanismStatus.VALIDATED.value
                elif data["confidence"] >= 0.6:
                    data["status"] = MechanismStatus.PROBABLE.value
                else:
                    data["status"] = MechanismStatus.HYPOTHESIS.value
                mechs_pre_rescored.append(MechanismCard.model_validate(data))
            self._exit_stage("mechanism_naming", t0, n_mechanisms=len(mechs_pre_rescored))

            # ---- stage 6: skeptic review ----
            t0 = self._enter_stage("skeptic_review")
            findings_by_mech: dict[str, ReviewFindings] = {}
            mechs_post: List[MechanismCard] = []
            review_findings: List[ReviewFindings] = []
            for m in mechs_pre_rescored:
                rf = skeptic.review_mechanism(self.ctx, mechanism=m, evidences=evidences)
                findings_by_mech[m.mechanism_id] = rf
                review_findings.append(rf)
                self.store.put("review_findings", m.mechanism_id, rf,
                               agent="skeptic", run_id=self.run_id)
                self._emit(EventType.ARTIFACT_WRITTEN,
                           artifact_type="review_findings",
                           artifact_id=m.mechanism_id,
                           n_findings=len(rf.findings),
                           confidence_delta=rf.confidence_delta)
                m_adj = apply_review(m, rf)
                mechs_post.append(m_adj)
                self.store.put("mechanism_card", m_adj.mechanism_id, m_adj,
                               agent="orchestrator(applied_review)", run_id=self.run_id)

            cg = consistency_gate(findings_by_mech)
            gates.append(cg)
            self._emit_gate(cg)
            self._exit_stage("skeptic_review", t0,
                             n_validated=sum(1 for m in mechs_post if m.status == MechanismStatus.VALIDATED),
                             n_probable=sum(1 for m in mechs_post if m.status == MechanismStatus.PROBABLE))

            # ---- stage 7: report composition ----
            t0 = self._enter_stage("publish")
            privacy_notes = (
                [f"已遮蔽 PII: {sorted({f.kind for f in pii_initial})}"]
                if pii_initial else ["未发现 PII"]
            )
            report = report_composer.compose_report(
                self.ctx,
                profile=profile,
                mechanisms=mechs_post,
                evidences=evidences,
                report_id=f"rep_{self.run_id}",
                privacy_notes=privacy_notes,
            )
            v = [m for m in mechs_post if m.status == MechanismStatus.VALIDATED]
            p = [m for m in mechs_post if m.status == MechanismStatus.PROBABLE]
            h = [m for m in mechs_post if m.status == MechanismStatus.HYPOTHESIS]
            data = report.model_dump()
            data["summary"] = {
                "validated_mechanisms": len(v),
                "probable_mechanisms": len(p),
                "needs_more_evidence": len(h),
            }
            valid_ids = {m.mechanism_id for m in v}
            prob_ids = {m.mechanism_id for m in p}
            data["validated_mechanisms"] = [
                vm for vm in data["validated_mechanisms"] if vm["mechanism_id"] in valid_ids
            ]
            data["probable_mechanisms"] = [
                vm for vm in data["probable_mechanisms"] if vm["mechanism_id"] in prob_ids
            ]
            report = ExtractionReport.model_validate(data)
            self.store.put("extraction_report", report.report_id, report,
                           agent="report_composer", run_id=self.run_id)
            self._emit(EventType.ARTIFACT_WRITTEN,
                       artifact_type="extraction_report",
                       artifact_id=report.report_id)

            pg = publish_gate(report, redacted_pii=True)
            gates.append(pg)
            self._emit_gate(pg)
            self._exit_stage("publish", t0)

            self._emit(
                EventType.RUN_COMPLETED,
                run_id=self.run_id,
                summary=report.summary.model_dump(),
                n_evidences=len(evidences),
                n_mechanisms=len(mechs_post),
                gates_passed=all(g.passed for g in gates),
                llm_calls=self.ctx.llm.stats.n_calls,
                tokens_in=self.ctx.llm.stats.input_tokens,
                tokens_out=self.ctx.llm.stats.output_tokens,
            )

            return PipelineResult(
                profile=profile,
                turns=turns,
                evidences=evidences,
                mechanisms_pre_review=mechs_pre_rescored,
                mechanisms_post_review=mechs_post,
                review_findings=review_findings,
                report=report,
                gates=gates,
            )

        except Exception as e:
            self._emit(EventType.RUN_FAILED, run_id=self.run_id, error=str(e),
                       error_type=type(e).__name__)
            raise

    # ---------------- internals ----------------

    @staticmethod
    def _estimate_components(
        m: MechanismCard, evidences: List[EvidenceCard]
    ) -> ConfidenceComponents:
        """Deterministic confidence-component estimator.

        We deliberately compute this in code, not via LLM, per arch.md:
        "把置信度计算交给确定性脚本而不是自由 Agent."
        """
        ev_index = {e.evidence_id: e for e in evidences}
        supports = [ev_index[i] for i in m.evidence_ids if i in ev_index]
        anti = [ev_index[i] for i in m.anti_evidence_ids if i in ev_index]

        # evidence_richness: more supports + higher avg confidence
        if not supports:
            er = 0.0
        else:
            avg_ev_conf = sum(e.confidence for e in supports) / len(supports)
            er = min(1.0, (len(supports) / 3.0) * 0.6 + avg_ev_conf * 0.4)

        # cross_context_replication: count distinct resume_span_refs in supports
        spans = {e.source_ref.resume_span_ref for e in supports if e.source_ref.resume_span_ref}
        if len(spans) >= 2:
            ccr = 1.0
        elif len(spans) == 1:
            ccr = 0.5
        else:
            ccr = 0.2

        # internal_consistency: fewer anti-evidences vs supports
        if not supports:
            ic = 0.0
        else:
            ic = max(0.0, 1.0 - 0.3 * len(anti) / max(1, len(supports)))

        # candidate_endorsement: proxy = anything from interview (critical_incident) counts
        endorse_count = sum(1 for e in supports if e.type == EvidenceType.CRITICAL_INCIDENT)
        ce = min(1.0, endorse_count / 2.0)

        # outcome_link_strength: how many supports have non-empty outcome
        with_outcome = sum(1 for e in supports if e.outcome.strip())
        ols = with_outcome / max(1, len(supports))

        return ConfidenceComponents(
            evidence_richness=er,
            cross_context_replication=ccr,
            internal_consistency=ic,
            candidate_endorsement=ce,
            outcome_link_strength=ols,
        )
