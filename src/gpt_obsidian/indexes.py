from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from .models import Conversation, ConversationInsights
from .utils import ensure_parent


class MonthIndexBuilder:
    def __init__(self) -> None:
        self._rows: dict[str, list[dict]] = defaultdict(list)

    def add(self, conversation: Conversation, note_rel_path: Path, insights: ConversationInsights) -> None:
        dt = conversation.created_at or conversation.updated_at
        if dt is None:
            return
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        else:
            dt = dt.astimezone(UTC)

        month_key = dt.strftime("%Y-%m")
        self._rows[month_key].append(
            {
                "date": dt,
                "title": conversation.title,
                "note": note_rel_path.as_posix(),
                "tags": insights.topic_tags,
            }
        )

    def month_keys(self) -> list[str]:
        return sorted(self._rows.keys())

    def build_markdown(self, month_key: str, report_links: list[str]) -> str:
        rows = sorted(self._rows.get(month_key, []), key=lambda r: (-r["date"].timestamp(), r["title"].lower()))
        tag_counter = Counter()
        by_day: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            by_day[row["date"].strftime("%Y-%m-%d")].append(row)
            tag_counter.update(row.get("tags") or [])

        lines = [f"# ChatGPT Index: {month_key}", "", f"- Total chats: {len(rows)}", ""]

        if tag_counter:
            lines.append("## Top Topics")
            lines.append("")
            for tag, count in sorted(tag_counter.items(), key=lambda t: (-t[1], t[0]))[:20]:
                lines.append(f"- `{tag}` ({count})")
            lines.append("")

        if report_links:
            lines.append("## Import Reports")
            lines.append("")
            for report in sorted(report_links, reverse=True):
                lines.append(f"- [[{report}]]")
            lines.append("")

        lines.append("## Chats by Day")
        lines.append("")
        for day in sorted(by_day.keys(), reverse=True):
            lines.append(f"### {day}")
            for row in by_day[day]:
                lines.append(f"- [[{row['note']}|{row['title']}]]")
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"


def write_month_indexes(
    vault_path: Path,
    builder: MonthIndexBuilder,
    report_rel_path: str | None,
) -> list[str]:
    written: list[str] = []
    for month_key in builder.month_keys():
        rel = Path("Indexes") / "ChatGPT" / f"{month_key}.md"
        abs_path = vault_path / rel
        ensure_parent(abs_path)
        report_links = [report_rel_path] if report_rel_path else []
        abs_path.write_text(builder.build_markdown(month_key, report_links), encoding="utf-8")
        written.append(rel.as_posix())
    return written
