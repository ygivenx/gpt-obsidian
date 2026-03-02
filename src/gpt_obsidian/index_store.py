from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from .models import ImportRecord


class IndexError(RuntimeError):
    pass


class IndexStore:
    def __init__(self, vault_path: Path) -> None:
        self.vault_path = vault_path
        self.index_dir = vault_path / ".gpt-obsidian"
        self.index_file = self.index_dir / "index.json"

    def load(self) -> dict[str, ImportRecord]:
        if not self.index_file.exists():
            return {}

        try:
            raw = json.loads(self.index_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise IndexError(f"Invalid JSON in {self.index_file}: {exc}") from exc

        if not isinstance(raw, dict):
            raise IndexError("Index file must contain an object at top level")

        records: dict[str, ImportRecord] = {}
        for conv_id, row in raw.items():
            if not isinstance(row, dict):
                continue
            try:
                records[conv_id] = ImportRecord(
                    conversation_id=str(row["conversation_id"]),
                    note_path=str(row["note_path"]),
                    content_hash=str(row["content_hash"]),
                    last_imported_at=str(row["last_imported_at"]),
                    source_updated_at=(
                        str(row["source_updated_at"]) if row.get("source_updated_at") else None
                    ),
                )
            except KeyError:
                continue
        return records

    def save(self, records: dict[str, ImportRecord]) -> None:
        self.index_dir.mkdir(parents=True, exist_ok=True)
        serialized = {
            conv_id: asdict(record)
            for conv_id, record in sorted(records.items(), key=lambda item: item[0])
        }
        self.index_file.write_text(
            json.dumps(serialized, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def now_iso() -> str:
        return datetime.now(tz=UTC).isoformat()
