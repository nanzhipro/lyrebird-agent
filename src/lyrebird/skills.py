"""Skills library — filesystem-based progressive disclosure.

Per arch.md §与 Anthropic Skills 的整合要点: each Skill is a directory with
SKILL.md (frontmatter + body). Metadata is cheap to scan; body is loaded on
demand and injected into an agent's prompt.

We intentionally avoid putting candidate-private data into Skills. Skills hold
procedural knowledge (how to ask, how to structure, how to skeptic) — instance
data flows through the ArtifactStore.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


@dataclass
class SkillMetadata:
    name: str
    description: str
    when_to_use: str = ""


class SkillsLibrary:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        if not self.root.exists():
            raise FileNotFoundError(f"skills root not found: {self.root}")
        self._meta_cache: Dict[str, SkillMetadata] = {}
        self._scan()

    def _scan(self) -> None:
        for entry in sorted(self.root.iterdir()):
            skill_md = entry / "SKILL.md"
            if not skill_md.exists():
                continue
            head = self._read_frontmatter(skill_md)
            if head is None:
                continue
            self._meta_cache[entry.name] = head

    def _read_frontmatter(self, path: Path) -> SkillMetadata | None:
        text = path.read_text(encoding="utf-8")
        m = _FRONTMATTER_RE.match(text)
        if not m:
            return None
        head_block = m.group(1)
        fields: Dict[str, str] = {}
        for line in head_block.splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                fields[k.strip()] = v.strip()
        return SkillMetadata(
            name=fields.get("name", path.parent.name),
            description=fields.get("description", ""),
            when_to_use=fields.get("when_to_use", ""),
        )

    def list(self) -> List[str]:
        return list(self._meta_cache.keys())

    def metadata(self, name: str) -> SkillMetadata:
        if name not in self._meta_cache:
            raise KeyError(f"skill not found: {name}")
        return self._meta_cache[name]

    def load_body(self, name: str) -> str:
        """Return the body (post-frontmatter) of SKILL.md."""
        if name not in self._meta_cache:
            raise KeyError(f"skill not found: {name}")
        path = self.root / name / "SKILL.md"
        text = path.read_text(encoding="utf-8")
        m = _FRONTMATTER_RE.match(text)
        if not m:
            return text
        return m.group(2).strip()
