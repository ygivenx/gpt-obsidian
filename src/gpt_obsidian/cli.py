from __future__ import annotations

import argparse
import concurrent.futures
import os
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from .attachments import extract_attachments_for_conversation
from .bases import write_default_bases
from .export_reader import ExportReadError, load_export
from .index_store import IndexError as ImportIndexError
from .index_store import IndexStore
from .indexes import MonthIndexBuilder, write_month_indexes
from .insights import InsightError, build_heuristic_insights, build_insights
from .markdown_renderer import render_conversation_markdown
from .models import Conversation, ConversationInsights, ImportIssue, ImportRecord, ImportStats
from .reporting import build_import_report, make_report_paths, write_report_json, write_report_markdown
from .topics import TopicBacklinkBuilder
from .transform import conversation_content_hash, note_relative_path
from .utils import ensure_parent, to_iso


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gpt-obsidian",
        description="Convert ChatGPT export archives into informative Obsidian vault notes.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    import_cmd = subparsers.add_parser("import", help="Import ChatGPT export into an Obsidian vault")
    import_cmd.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Path to chatgpt export ZIP or extracted export directory",
    )
    import_cmd.add_argument("--vault", required=True, type=Path, help="Path to Obsidian vault")
    import_cmd.add_argument("--assets-dir", default="Assets/ChatGPT", help="Assets directory inside vault")
    import_cmd.add_argument("--chats-dir", default="Chats", help="Chats directory inside vault")
    import_cmd.add_argument("--since", type=str, help="Import only conversations updated on/after YYYY-MM-DD")
    import_cmd.add_argument("--dry-run", action="store_true", help="Print import plan without writing files")
    import_cmd.add_argument(
        "--force",
        action="store_true",
        help="Re-render all conversations even if unchanged by hash",
    )
    import_cmd.add_argument(
        "--summary-provider",
        choices=["heuristic", "openai", "vllm"],
        default="heuristic",
        help="Summary generation mode",
    )
    import_cmd.add_argument(
        "--summary-model",
        type=str,
        default=None,
        help="Model name for --summary-provider openai",
    )
    import_cmd.add_argument(
        "--summary-max-bullets",
        type=int,
        default=5,
        help="Maximum bullets for summary/decisions/actions/questions sections",
    )
    import_cmd.add_argument(
        "--enable-topic-tags",
        action="store_true",
        default=True,
        help="Enable inferred topic tags (default: enabled)",
    )
    import_cmd.add_argument(
        "--disable-topic-tags",
        action="store_false",
        dest="enable_topic_tags",
        help="Disable inferred topic tags",
    )
    import_cmd.add_argument(
        "--topic-tag-limit",
        type=int,
        default=8,
        help="Maximum inferred topic tags per conversation",
    )
    import_cmd.add_argument(
        "--tag-provider",
        choices=["heuristic", "openai", "vllm"],
        default="heuristic",
        help="Topic tag generation mode",
    )
    import_cmd.add_argument(
        "--tag-model",
        type=str,
        default=None,
        help="Model name for --tag-provider openai",
    )
    import_cmd.add_argument(
        "--generate-indexes",
        action="store_true",
        default=True,
        help="Generate monthly index notes (default: enabled)",
    )
    import_cmd.add_argument(
        "--disable-indexes",
        action="store_false",
        dest="generate_indexes",
        help="Disable monthly index generation",
    )
    import_cmd.add_argument(
        "--generate-bases",
        action="store_true",
        default=True,
        help="Generate Obsidian Bases definition files (default: enabled)",
    )
    import_cmd.add_argument(
        "--disable-bases",
        action="store_false",
        dest="generate_bases",
        help="Disable Obsidian Bases file generation",
    )
    import_cmd.add_argument(
        "--report-dir",
        type=str,
        default="Reports/ChatGPT Imports",
        help="Directory inside vault for import reports",
    )
    import_cmd.add_argument(
        "--report-format",
        choices=["md", "json", "both"],
        default="both",
        help="Import report output format",
    )
    import_cmd.add_argument(
        "--cost-estimate",
        action="store_true",
        help="Print rough OpenAI summary cost estimate for this import run",
    )
    import_cmd.add_argument(
        "--batch-size",
        type=int,
        default=1,
        help="Conversations to process in parallel for insight generation (default: 1)",
    )
    import_cmd.add_argument(
        "--allow-openai-fallback",
        action="store_true",
        help="Allow heuristic fallback when OpenAI summary/tag calls fail",
    )

    doctor_cmd = subparsers.add_parser("doctor", help="Validate export source and vault for import")
    doctor_cmd.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Path to chatgpt export ZIP or extracted export directory",
    )
    doctor_cmd.add_argument("--vault", required=True, type=Path, help="Path to Obsidian vault")

    sync_cmd = subparsers.add_parser("init-sync", help="Initialize Git sync helpers in vault")
    sync_cmd.add_argument("--vault", required=True, type=Path, help="Path to Obsidian vault")
    sync_cmd.add_argument("--remote", required=True, type=str, help="Private Git remote URL")

    return parser


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "import":
        return import_command(args)
    if args.command == "doctor":
        return doctor_command(args)
    if args.command == "init-sync":
        return init_sync_command(args)
    parser.error("Unknown command")
    return 2


def import_command(args: argparse.Namespace) -> int:
    _load_env_file(Path.cwd() / ".env")

    if args.summary_provider == "openai" and not args.summary_model:
        print("ERROR: --summary-model is required when --summary-provider openai", file=sys.stderr)
        return 1
    if args.tag_provider == "openai" and not args.tag_model:
        print("ERROR: --tag-model is required when --tag-provider openai", file=sys.stderr)
        return 1
    if args.batch_size < 1:
        print("ERROR: --batch-size must be >= 1", file=sys.stderr)
        return 1

    since_date = _parse_since(args.since) if args.since else None
    vault = args.vault
    vault.mkdir(parents=True, exist_ok=True)

    run_started_at = datetime.now(tz=UTC)

    try:
        bundle = load_export(args.input)
    except ExportReadError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    candidates = [c for c in bundle.conversations if not since_date or _is_after_since(c.updated_at, since_date)]
    total_candidates = len(candidates)
    if args.cost_estimate:
        _print_cost_estimate(
            conversations=candidates,
            summary_provider=args.summary_provider,
            summary_model=args.summary_model,
            summary_max_bullets=max(args.summary_max_bullets, 1),
            tag_provider=args.tag_provider,
            tag_model=args.tag_model,
            topic_tag_limit=max(args.topic_tag_limit, 1),
        )
    if (args.summary_provider == "openai" or args.tag_provider == "openai") and not os.getenv("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY is required when using OpenAI summary/tag providers", file=sys.stderr)
        return 1

    index_store = IndexStore(vault)
    try:
        existing = index_store.load()
    except ImportIndexError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    stats = ImportStats()
    issues: list[ImportIssue] = []
    all_topics: list[str] = []
    next_records = dict(existing)
    month_builder = MonthIndexBuilder()
    topic_builder = TopicBacklinkBuilder()

    summary_max_bullets = max(args.summary_max_bullets, 1)
    topic_tag_limit = max(args.topic_tag_limit, 1)

    for batch_start in range(0, total_candidates, args.batch_size):
        batch = candidates[batch_start : batch_start + args.batch_size]
        for offset, conversation in enumerate(batch, start=batch_start + 1):
            _print_progress(offset, total_candidates, conversation.title, conversation.id)

        batch_results = _build_insight_batch(
            conversations=batch,
            max_workers=min(args.batch_size, len(batch)),
            summary_provider=args.summary_provider,
            summary_model=args.summary_model,
            summary_max_bullets=summary_max_bullets,
            tag_provider=args.tag_provider,
            tag_model=args.tag_model,
            topic_tag_limit=topic_tag_limit,
            enable_topic_tags=args.enable_topic_tags,
            allow_openai_fallback=args.allow_openai_fallback,
        )

        for conversation, insight_result in zip(batch, batch_results):
            if insight_result.issue is not None:
                issues.append(insight_result.issue)
                if insight_result.issue.severity == "error":
                    conv = insight_result.issue.conversation_id or "n/a"
                    note = insight_result.issue.note_path or "n/a"
                    print(
                        f"ERROR: [{insight_result.issue.kind}] conversation=`{conv}` note=`{note}`: "
                        f"{insight_result.issue.detail}",
                        file=sys.stderr,
                    )
            if insight_result.insights is None:
                stats.errors += 1
                continue
            insights = insight_result.insights

            content_hash = conversation_content_hash(
                conversation=conversation,
                insights=insights,
                summary_provider=args.summary_provider,
                summary_model=args.summary_model,
                tag_provider=args.tag_provider,
                tag_model=args.tag_model,
            )

            existing_record = existing.get(conversation.id)
            note_rel = (
                Path(existing_record.note_path)
                if existing_record
                else note_relative_path(conversation, args.chats_dir)
            )
            note_abs = vault / note_rel
            month_builder.add(conversation=conversation, note_rel_path=note_rel, insights=insights)
            all_topics.extend(insights.topic_tags)
            for tag in insights.topic_tags:
                topic_builder.add(tag=tag, note_rel_path=note_rel.as_posix(), title=conversation.title)

            if existing_record and existing_record.content_hash == content_hash and not args.force:
                stats.skipped += 1
                _print_progress_state(stats)
                continue

            extraction = extract_attachments_for_conversation(
                source_path=bundle.source_path,
                source_kind=bundle.source_kind,
                members=bundle.members,
                conversation_id=conversation.id,
                attachments=conversation.attachments,
                vault_path=vault,
                assets_dir=args.assets_dir,
            )

            if extraction.missing_display_names:
                for missing in extraction.missing_display_names:
                    issues.append(
                        ImportIssue(
                            conversation_id=conversation.id,
                            note_path=note_rel.as_posix(),
                            severity="warning",
                            kind="missing_attachment",
                            detail=missing,
                        )
                    )

            imported_at = IndexStore.now_iso()
            markdown = render_conversation_markdown(
                conversation=conversation,
                note_rel_path=note_rel,
                attachment_rel_paths=extraction.paths_by_display_name,
                insights=insights,
                imported_at_iso=imported_at,
                summary_provider=args.summary_provider,
                tag_provider=args.tag_provider,
                topic_link_map=topic_builder.link_map(),
            )

            if not args.dry_run:
                try:
                    ensure_parent(note_abs)
                    note_abs.write_text(markdown, encoding="utf-8")
                except OSError as exc:
                    stats.errors += 1
                    issues.append(
                        ImportIssue(
                            conversation_id=conversation.id,
                            note_path=note_rel.as_posix(),
                            severity="error",
                            kind="note_write_failed",
                            detail=str(exc),
                        )
                    )
                    continue

            if existing_record:
                stats.updated += 1
            else:
                stats.created += 1
            _print_progress_state(stats)

            next_records[conversation.id] = ImportRecord(
                conversation_id=conversation.id,
                note_path=note_rel.as_posix(),
                content_hash=content_hash,
                last_imported_at=imported_at,
                source_updated_at=to_iso(conversation.updated_at),
            )

    if not args.dry_run:
        try:
            index_store.save(next_records)
        except OSError as exc:
            stats.errors += 1
            issues.append(
                ImportIssue(
                    conversation_id=None,
                    note_path=None,
                    severity="error",
                    kind="index_save_failed",
                    detail=str(exc),
                )
            )

    report_md_rel, report_json_rel = make_report_paths(args.report_dir, run_started_at)
    if args.generate_indexes and not args.dry_run:
        report_link = report_md_rel.as_posix() if args.report_format in {"md", "both"} else None
        try:
            written_indexes = write_month_indexes(vault_path=vault, builder=month_builder, report_rel_path=report_link)
            if written_indexes:
                print(f"Indexes updated: {len(written_indexes)}")
        except OSError as exc:
            stats.errors += 1
            issues.append(
                ImportIssue(
                    conversation_id=None,
                    note_path=None,
                    severity="warning",
                    kind="index_write_failed",
                    detail=str(exc),
                )
            )
    if not args.dry_run:
        try:
            written_topics = topic_builder.write(vault)
            if written_topics:
                print(f"Topic notes updated: {len(written_topics)}")
        except OSError as exc:
            stats.errors += 1
            issues.append(
                ImportIssue(
                    conversation_id=None,
                    note_path=None,
                    severity="warning",
                    kind="topic_write_failed",
                    detail=str(exc),
                )
            )
    if args.generate_bases and not args.dry_run:
        try:
            written_bases = write_default_bases(vault)
            if written_bases:
                print(f"Bases updated: {len(written_bases)}")
        except OSError as exc:
            stats.errors += 1
            issues.append(
                ImportIssue(
                    conversation_id=None,
                    note_path=None,
                    severity="warning",
                    kind="bases_write_failed",
                    detail=str(exc),
                )
            )

    run_completed_at = datetime.now(tz=UTC)
    report = build_import_report(
        run_started_at=run_started_at,
        run_completed_at=run_completed_at,
        input_path=args.input,
        vault_path=vault,
        summary_provider=args.summary_provider,
        summary_model=args.summary_model,
        created=stats.created,
        updated=stats.updated,
        skipped=stats.skipped,
        errors=stats.errors,
        issues=issues,
        topic_tags=all_topics,
    )

    if args.dry_run:
        if args.report_format in {"md", "both"}:
            print(f"Dry-run report (md): {(report_md_rel).as_posix()}")
        if args.report_format in {"json", "both"}:
            print(f"Dry-run report (json): {(report_json_rel).as_posix()}")
    else:
        try:
            if args.report_format in {"md", "both"}:
                write_report_markdown(vault, report_md_rel, report)
            if args.report_format in {"json", "both"}:
                write_report_json(vault, report_json_rel, report)
        except OSError as exc:
            stats.errors += 1
            issues.append(
                ImportIssue(
                    conversation_id=None,
                    note_path=None,
                    severity="warning",
                    kind="report_write_failed",
                    detail=str(exc),
                )
            )

    print(
        f"Import complete: created={stats.created} updated={stats.updated} "
        f"skipped={stats.skipped} errors={stats.errors}"
    )

    if not args.dry_run:
        if args.report_format in {"md", "both"}:
            print(f"Report (md): {report_md_rel.as_posix()}")
        if args.report_format in {"json", "both"}:
            print(f"Report (json): {report_json_rel.as_posix()}")

    if args.dry_run:
        print("Dry run mode enabled. No files were written.")

    return 0 if stats.errors == 0 else 1


def doctor_command(args: argparse.Namespace) -> int:
    issues: list[str] = []

    try:
        bundle = load_export(args.input)
        print(
            f"OK: Export source readable ({len(bundle.conversations)} conversations, "
            f"kind={bundle.source_kind})"
        )
    except ExportReadError as exc:
        issues.append(f"Export validation failed: {exc}")

    vault = args.vault
    try:
        vault.mkdir(parents=True, exist_ok=True)
        probe = vault / ".gpt-obsidian" / "doctor.tmp"
        ensure_parent(probe)
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink()
        print(f"OK: Vault path writable: {vault}")
    except OSError as exc:
        issues.append(f"Vault path not writable ({vault}): {exc}")

    index_store = IndexStore(vault)
    try:
        index_store.load()
        print("OK: Import index is valid or not yet initialized")
    except ImportIndexError as exc:
        issues.append(f"Import index invalid: {exc}")

    if issues:
        for issue in issues:
            print(f"ERROR: {issue}", file=sys.stderr)
        print("Remediation: fix the errors above and re-run `gpt-obsidian doctor`.", file=sys.stderr)
        return 1
    return 0


def init_sync_command(args: argparse.Namespace) -> int:
    vault = args.vault
    vault.mkdir(parents=True, exist_ok=True)

    gitignore = vault / ".gitignore"
    entries = {
        ".DS_Store",
        "Thumbs.db",
        ".obsidian/workspace*.json",
        ".obsidian/cache",
        ".trash/",
    }
    existing_lines: set[str] = set()
    if gitignore.exists():
        existing_lines = {line.strip() for line in gitignore.read_text(encoding="utf-8").splitlines()}

    merged = sorted(existing_lines.union(entries))
    gitignore.write_text("\n".join([line for line in merged if line]) + "\n", encoding="utf-8")

    script = vault / "sync_vault.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "git pull --rebase\n"
        "git add -A\n"
        "git commit -m \"Vault sync: $(date -u +%Y-%m-%dT%H:%M:%SZ)\" || true\n"
        "git push\n",
        encoding="utf-8",
    )
    script.chmod(0o755)

    print(f"Initialized sync helpers at {vault}")
    print("Next steps:")
    print("1) cd into your vault")
    print("2) git init")
    print(f"3) git remote add origin {args.remote}")
    print("4) git add -A && git commit -m 'Initial vault import'")
    print("5) git push -u origin main")

    if _git_available():
        print("Git detected locally.")
    else:
        print("Warning: Git was not found on PATH.")
    return 0


def _parse_since(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise SystemExit(f"--since must be in YYYY-MM-DD format, got: {value}") from exc


def _is_after_since(updated_at, since: date) -> bool:
    if updated_at is None:
        return False
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    return updated_at.date() >= since


def _git_available() -> bool:
    try:
        return subprocess.run(["git", "--version"], capture_output=True, check=False).returncode == 0
    except OSError:
        return False


def _print_cost_estimate(
    conversations,
    summary_provider: str,
    summary_model: str | None,
    summary_max_bullets: int,
    tag_provider: str,
    tag_model: str | None,
    topic_tag_limit: int,
) -> None:
    if summary_provider != "openai" and tag_provider != "openai":
        print("Estimated OpenAI cost: $0.0000 (summary/tag providers are heuristic)")
        return

    estimated_input_tokens_summary = 0
    estimated_output_tokens_summary = 0
    estimated_input_tokens_tags = 0
    estimated_output_tokens_tags = 0
    for conv in conversations:
        char_count = sum(len(msg.text_markdown or "") for msg in conv.messages)
        if summary_provider == "openai":
            estimated_input_tokens_summary += int(char_count / 4) + 220
            estimated_output_tokens_summary += 70 + summary_max_bullets * 32
        if tag_provider == "openai":
            estimated_input_tokens_tags += int(char_count / 4) + 130
            estimated_output_tokens_tags += 40 + topic_tag_limit * 12

    total = 0.0
    unknown_models: list[str] = []
    if summary_provider == "openai":
        pricing = _model_pricing_usd_per_million(summary_model)
        if pricing is None:
            unknown_models.append(summary_model or "unknown")
        else:
            total += (estimated_input_tokens_summary / 1_000_000) * pricing["input"]
            total += (estimated_output_tokens_summary / 1_000_000) * pricing["output"]

    if tag_provider == "openai":
        pricing = _model_pricing_usd_per_million(tag_model)
        if pricing is None:
            unknown_models.append(tag_model or "unknown")
        else:
            total += (estimated_input_tokens_tags / 1_000_000) * pricing["input"]
            total += (estimated_output_tokens_tags / 1_000_000) * pricing["output"]

    if unknown_models:
        print(
            "Estimated OpenAI cost: unknown "
            f"(no local pricing table for model(s): {', '.join(sorted(set(unknown_models)))})"
        )
        return

    print(
        "Estimated OpenAI cost: "
        f"${total:.4f} (summary_model={summary_model or 'n/a'}, tag_model={tag_model or 'n/a'}, "
        f"chats={len(conversations)}, "
        f"input_tokens~{estimated_input_tokens_summary + estimated_input_tokens_tags}, "
        f"output_tokens~{estimated_output_tokens_summary + estimated_output_tokens_tags})"
    )


def _model_pricing_usd_per_million(model: str | None) -> dict[str, float] | None:
    # Keep this intentionally small and explicit; unknown models report "unknown".
    table = {
        "gpt-5-nano": {"input": 0.05, "output": 0.40},
        "gpt-5-mini": {"input": 0.25, "output": 2.00},
        "gpt-5": {"input": 1.25, "output": 10.00},
        "gpt-4o": {"input": 5.00, "output": 15.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    }
    if not model:
        return None
    return table.get(model)


def _print_progress(current: int, total: int, title: str, conversation_id: str) -> None:
    title_text = (title or "Untitled Chat").strip()
    if len(title_text) > 70:
        title_text = title_text[:67] + "..."
    print(f"[{current}/{total}] Processing: {title_text} ({conversation_id})")


def _print_progress_state(stats: ImportStats) -> None:
    print(
        f"    -> created={stats.created} updated={stats.updated} "
        f"skipped={stats.skipped} errors={stats.errors}"
    )


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if not key:
            continue
        if key in os.environ:
            continue
        os.environ[key] = value


class _InsightBuildResult:
    __slots__ = ("insights", "issue")

    def __init__(self, insights: ConversationInsights | None, issue: ImportIssue | None) -> None:
        self.insights = insights
        self.issue = issue


def _build_insight_for_conversation(
    conversation: Conversation,
    summary_provider: str,
    summary_model: str | None,
    summary_max_bullets: int,
    tag_provider: str,
    tag_model: str | None,
    topic_tag_limit: int,
    enable_topic_tags: bool,
    allow_openai_fallback: bool,
) -> _InsightBuildResult:
    try:
        insights = build_insights(
            conversation=conversation,
            summary_provider=summary_provider,
            summary_model=summary_model,
            summary_max_bullets=summary_max_bullets,
            tag_provider=tag_provider,
            tag_model=tag_model,
            topic_tag_limit=topic_tag_limit,
            enable_topic_tags=enable_topic_tags,
        )
        return _InsightBuildResult(insights=insights, issue=None)
    except InsightError as exc:
        openai_enabled = summary_provider == "openai" or tag_provider == "openai"
        if openai_enabled and allow_openai_fallback:
            fallback = build_heuristic_insights(
                conversation=conversation,
                summary_max_bullets=summary_max_bullets,
                topic_tag_limit=topic_tag_limit,
                enable_topic_tags=enable_topic_tags,
            )
            return _InsightBuildResult(
                insights=fallback,
                issue=ImportIssue(
                    conversation_id=conversation.id,
                    note_path=None,
                    severity="warning",
                    kind="openai_fallback",
                    detail=str(exc),
                ),
            )
        if openai_enabled:
            return _InsightBuildResult(
                insights=None,
                issue=ImportIssue(
                    conversation_id=conversation.id,
                    note_path=None,
                    severity="error",
                    kind="openai_error",
                    detail=f"{exc} (set --allow-openai-fallback to continue with heuristic fallback)",
                ),
            )
        return _InsightBuildResult(
            insights=None,
            issue=ImportIssue(
                conversation_id=conversation.id,
                note_path=None,
                severity="error",
                kind="insight_error",
                detail=str(exc),
            ),
        )


def _build_insight_batch(
    conversations: list[Conversation],
    max_workers: int,
    summary_provider: str,
    summary_model: str | None,
    summary_max_bullets: int,
    tag_provider: str,
    tag_model: str | None,
    topic_tag_limit: int,
    enable_topic_tags: bool,
    allow_openai_fallback: bool,
) -> list[_InsightBuildResult]:
    if max_workers <= 1 or len(conversations) <= 1:
        return [
            _build_insight_for_conversation(
                conversation=conversation,
                summary_provider=summary_provider,
                summary_model=summary_model,
                summary_max_bullets=summary_max_bullets,
                tag_provider=tag_provider,
                tag_model=tag_model,
                topic_tag_limit=topic_tag_limit,
                enable_topic_tags=enable_topic_tags,
                allow_openai_fallback=allow_openai_fallback,
            )
            for conversation in conversations
        ]

    ordered: dict[str, _InsightBuildResult] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _build_insight_for_conversation,
                conversation=conversation,
                summary_provider=summary_provider,
                summary_model=summary_model,
                summary_max_bullets=summary_max_bullets,
                tag_provider=tag_provider,
                tag_model=tag_model,
                topic_tag_limit=topic_tag_limit,
                enable_topic_tags=enable_topic_tags,
                allow_openai_fallback=allow_openai_fallback,
            ): conversation.id
            for conversation in conversations
        }
        for future in concurrent.futures.as_completed(futures):
            ordered[futures[future]] = future.result()
    return [ordered[conversation.id] for conversation in conversations]


if __name__ == "__main__":
    raise SystemExit(run())
