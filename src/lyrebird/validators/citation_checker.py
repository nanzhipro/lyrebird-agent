"""Citation checker — enforces the 3-tier evidence chain from arch.md.

Layer 1 = raw source (resume span, conversation turn)
Layer 2 = EvidenceCard
Layer 3 = MechanismCard / ReportClaim

Every layer-3 must point to >=1 layer-2; every layer-2 should point to >=1
layer-1 (resume span). This check is a deterministic gate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Set

from lyrebird.schemas import EvidenceCard, MechanismCard


@dataclass
class CitationResult:
    ok: bool
    missing_resume_refs: List[str] = field(default_factory=list)
    dangling_evidence_ids: List[str] = field(default_factory=list)
    detail: str = ""


def check_evidence_citations(
    evidences: Iterable[EvidenceCard],
    known_resume_span_ids: Set[str],
) -> CitationResult:
    missing: List[str] = []
    for e in evidences:
        rs = e.source_ref.resume_span_ref
        if rs is None:
            continue  # allowed for conversation-only evidence
        if rs not in known_resume_span_ids:
            missing.append(rs)
    return CitationResult(
        ok=not missing,
        missing_resume_refs=missing,
        detail=f"{len(missing)} evidence card(s) reference unknown resume spans" if missing else "",
    )


def check_mechanism_citations(
    mechanisms: Iterable[MechanismCard],
    known_evidence_ids: Set[str],
) -> CitationResult:
    dangling: List[str] = []
    for m in mechanisms:
        for eid in m.evidence_ids:
            if eid not in known_evidence_ids:
                dangling.append(eid)
        for eid in m.anti_evidence_ids:
            if eid not in known_evidence_ids:
                dangling.append(eid)
    return CitationResult(
        ok=not dangling,
        dangling_evidence_ids=dangling,
        detail=(
            f"{len(dangling)} dangling evidence_id reference(s)" if dangling else ""
        ),
    )
