"""PII guard — deterministic scan for common Chinese/English identifiers.

Per arch.md §安全、隐私: PII detection must NOT be delegated to a free agent —
it is a deterministic component. We treat phone, email, ID card, and bank card
patterns as findings and offer a redact helper.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List


_PATTERNS = {
    # CN mobile: 1[3-9]xxxxxxxxx
    "phone_cn": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    # generic email
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    # CN id card: 17 digits + (digit|X)
    "id_card_cn": re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"),
    # bank card (rough): 13–19 digit run
    "bank_card": re.compile(r"(?<!\d)\d{13,19}(?!\d)"),
}


@dataclass
class PIIFinding:
    kind: str
    span: tuple[int, int]
    value: str

    @staticmethod
    def redact_all(text: str, findings: List["PIIFinding"]) -> str:
        # Sort descending by start so spans don't shift while we replace
        out = text
        for f in sorted(findings, key=lambda x: x.span[0], reverse=True):
            s, e = f.span
            out = out[:s] + f"[REDACTED:{f.kind}]" + out[e:]
        return out


def scan_pii(text: str) -> List[PIIFinding]:
    findings: List[PIIFinding] = []
    seen_spans: set[tuple[int, int]] = set()
    # We want id_card_cn to win over bank_card on overlap
    ordered = ["phone_cn", "email", "id_card_cn", "bank_card"]
    for kind in ordered:
        pat = _PATTERNS[kind]
        for m in pat.finditer(text):
            span = m.span()
            # skip if covered by a higher-priority hit
            if any(_overlaps(span, s) for s in seen_spans):
                continue
            findings.append(PIIFinding(kind=kind, span=span, value=m.group(0)))
            seen_spans.add(span)
    return findings


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return not (a[1] <= b[0] or b[1] <= a[0])
