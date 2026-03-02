from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from .models import ImportIssue, ImportReport
from .utils import ensure_parent


def make_report_paths(report_dir: str, run_started_at: datetime) -> tuple[Path, Path]:
    stamp = run_started_at.astimezone(UTC).strftime("%Y-%m-%d_%H-%M-%S")
    base = Path(report_dir) / f"{stamp}-import"
    return base.with_suffix(".md"), base.with_suffix(".json")


def build_import_report(
    run_started_at: datetime,
    run_completed_at: datetime,
    input_path: Path,
    vault_path: Path,
    summary_provider: str,
    summary_model: str | None,
    created: int,
    updated: int,
    skipped: int,
    errors: int,
    issues: list[ImportIssue],
    topic_tags: list[str],
) -> ImportReport:
    counter = Counter(topic_tags)
    top_topics = sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:20]
    return ImportReport(
        run_started_at=run_started_at.astimezone(UTC).isoformat(),
        run_completed_at=run_completed_at.astimezone(UTC).isoformat(),
        duration_seconds=round((run_completed_at - run_started_at).total_seconds(), 3),
        input_path=str(input_path),
        vault_path=str(vault_path),
        summary_provider=summary_provider,
        summary_model=summary_model,
        created=created,
        updated=updated,
        skipped=skipped,
        errors=errors,
        issues=issues,
        top_topics=top_topics,
    )


def write_report_markdown(vault_path: Path, report_rel_path: Path, report: ImportReport) -> str:
    abs_path = vault_path / report_rel_path
    ensure_parent(abs_path)
    lines: list[str] = []
    lines.append(f"# ChatGPT Import Report ({report.run_started_at})")
    lines.append("")
    lines.append(f"- Input: `{report.input_path}`")
    lines.append(f"- Vault: `{report.vault_path}`")
    lines.append(f"- Summary provider: `{report.summary_provider}`")
    lines.append(f"- Model: `{report.summary_model or 'n/a'}`")
    lines.append(f"- Duration (s): {report.duration_seconds}")
    lines.append("")
    lines.append("## Stats")
    lines.append("")
    lines.append(f"- Created: {report.created}")
    lines.append(f"- Updated: {report.updated}")
    lines.append(f"- Skipped: {report.skipped}")
    lines.append(f"- Errors: {report.errors}")
    lines.append("")

    lines.append("## Top Topics")
    lines.append("")
    if report.top_topics:
        for topic, count in report.top_topics:
            lines.append(f"- `{topic}` ({count})")
    else:
        lines.append("- None")
    lines.append("")

    lines.append("## Issues")
    lines.append("")
    if report.issues:
        for issue in report.issues:
            conv = issue.conversation_id or "n/a"
            note = issue.note_path or "n/a"
            lines.append(
                f"- [{issue.severity}] `{issue.kind}` conversation=`{conv}` note=`{note}`: {issue.detail}"
            )
    else:
        lines.append("- None")
    lines.append("")

    abs_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return report_rel_path.as_posix()


def write_report_json(vault_path: Path, report_rel_path: Path, report: ImportReport) -> str:
    abs_path = vault_path / report_rel_path
    ensure_parent(abs_path)
    payload = asdict(report)
    payload["issues"] = [asdict(issue) for issue in report.issues]
    abs_path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return report_rel_path.as_posix()
