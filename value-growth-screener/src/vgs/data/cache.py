"""Small, deterministic disk cache with atomic writes."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable


class DataStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    @staticmethod
    def cache_key(namespace: str, params: dict[str, Any]) -> str:
        payload = json.dumps(params, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]
        return f"{namespace}-{digest}"

    def path(self, area: str, name: str, suffix: str = ".json") -> Path:
        safe_name = "".join(char for char in name if char.isalnum() or char in "-_.")
        if not safe_name or safe_name != name or name in {".", ".."}:
            raise ValueError("invalid cache name")
        target = (self.root / area / f"{safe_name}{suffix}").resolve()
        expected = (self.root / area).resolve()
        if expected not in target.parents:
            raise ValueError("cache target escaped its data area")
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def read_json(self, area: str, name: str) -> Any | None:
        target = self.path(area, name)
        if not target.exists():
            return None
        return json.loads(target.read_text(encoding="utf-8"))

    def write_json(self, area: str, name: str, value: Any) -> Path:
        target = self.path(area, name)
        temp = target.with_suffix(target.suffix + ".tmp")
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, target)
        return target

    def write_jsonl(self, area: str, name: str, rows: Iterable[dict[str, Any]]) -> Path:
        target = self.path(area, name, ".jsonl")
        temp = target.with_suffix(target.suffix + ".tmp")
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        os.replace(temp, target)
        return target

    def read_bytes(self, area: str, name: str, suffix: str) -> bytes | None:
        target = self.path(area, name, suffix)
        return target.read_bytes() if target.exists() else None

    def write_bytes(self, area: str, name: str, suffix: str, value: bytes) -> Path:
        target = self.path(area, name, suffix)
        temp = target.with_suffix(target.suffix + ".tmp")
        temp.write_bytes(value)
        os.replace(temp, target)
        return target
