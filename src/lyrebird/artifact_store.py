"""Artifact store — JSON-on-disk fact bus shared across agents.

Per arch.md §通信协议: agents do NOT pass context to each other through
conversation. They write structured artifacts here. Every read goes through a
Pydantic schema, so a corrupted file is caught at load time.

Layout:
    {root}/
        candidate_profile/
            c1.json              # payload
            c1.prov.json         # provenance: who wrote it, when, run_id
        evidence_card/
            ev_001.json
            ...
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Type, TypeVar, List

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class ArtifactStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # ---------- internals ----------
    def _dir(self, artifact_type: str) -> Path:
        d = self.root / artifact_type
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _payload_path(self, artifact_type: str, artifact_id: str) -> Path:
        return self._dir(artifact_type) / f"{artifact_id}.json"

    def _prov_path(self, artifact_type: str, artifact_id: str) -> Path:
        return self._dir(artifact_type) / f"{artifact_id}.prov.json"

    # ---------- public ----------
    def put(
        self,
        artifact_type: str,
        artifact_id: str,
        obj: BaseModel,
        *,
        agent: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> None:
        payload_path = self._payload_path(artifact_type, artifact_id)
        prov_path = self._prov_path(artifact_type, artifact_id)

        # Atomic-ish write: dump to tmp, then rename
        tmp = payload_path.with_suffix(".json.tmp")
        tmp.write_text(
            obj.model_dump_json(indent=2, exclude_none=False),
            encoding="utf-8",
        )
        tmp.replace(payload_path)

        prov = {
            "artifact_type": artifact_type,
            "artifact_id": artifact_id,
            "agent": agent,
            "run_id": run_id,
            "written_at": datetime.now(timezone.utc).isoformat(),
        }
        prov_path.write_text(json.dumps(prov, indent=2), encoding="utf-8")

    def get(
        self,
        artifact_type: str,
        artifact_id: str,
        schema: Type[T],
    ) -> Optional[T]:
        path = self._payload_path(artifact_type, artifact_id)
        if not path.exists():
            return None
        return schema.model_validate_json(path.read_text(encoding="utf-8"))

    def get_provenance(self, artifact_type: str, artifact_id: str) -> dict:
        path = self._prov_path(artifact_type, artifact_id)
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def list_ids(self, artifact_type: str) -> List[str]:
        d = self._dir(artifact_type)
        return sorted(
            p.stem
            for p in d.glob("*.json")
            if not p.name.endswith(".prov.json") and not p.name.endswith(".json.tmp")
        )

    def load_all(self, artifact_type: str, schema: Type[T]) -> List[T]:
        return [
            self.get(artifact_type, aid, schema)
            for aid in self.list_ids(artifact_type)
        ]
