from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from .utils import ensure_parent, safe_slug


class TopicBacklinkBuilder:
    def __init__(self) -> None:
        self._topics: dict[str, list[dict[str, str]]] = defaultdict(list)

    def add(self, tag: str, note_rel_path: str, title: str) -> None:
        self._topics[tag].append({"note": note_rel_path, "title": title})

    def link_map(self) -> dict[str, str]:
        return {tag: _topic_note_rel_path(tag).as_posix() for tag in self._topics.keys()}

    def write(self, vault_path: Path) -> list[str]:
        written: list[str] = []
        for tag, rows in sorted(self._topics.items(), key=lambda item: item[0]):
            rel = _topic_note_rel_path(tag)
            abs_path = vault_path / rel
            ensure_parent(abs_path)
            lines: list[str] = []
            lines.append(f"# Topic: {tag}")
            lines.append("")
            lines.append(f"- Tag: `{tag}`")
            lines.append("")
            lines.append("## Related Conversations")
            lines.append("")
            unique = {(row['note'], row['title']) for row in rows}
            for note, title in sorted(unique, key=lambda t: t[1].lower()):
                lines.append(f"- [[{note}|{title}]]")
            lines.append("")
            abs_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
            written.append(rel.as_posix())
        return written


def _topic_note_rel_path(tag: str) -> Path:
    return Path("Topics") / f"{safe_slug(tag, fallback='topic')}.md"
