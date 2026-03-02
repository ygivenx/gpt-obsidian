from __future__ import annotations

from datetime import UTC
from pathlib import Path

from .models import Conversation, ConversationInsights


def render_conversation_markdown(
    conversation: Conversation,
    note_rel_path: Path,
    attachment_rel_paths: dict[str, str],
    insights: ConversationInsights,
    imported_at_iso: str,
    summary_provider: str,
    tag_provider: str,
    topic_link_map: dict[str, str],
) -> str:
    lines: list[str] = []

    created_iso = _format_dt(conversation.created_at)
    updated_iso = _format_dt(conversation.updated_at)

    lines.append("---")
    lines.append(f"id: {conversation.id}")
    lines.append(f'title: "{_escape_yaml(conversation.title)}"')
    lines.append(f"created: {created_iso or ''}")
    lines.append(f"updated: {updated_iso or ''}")
    lines.append("source: chatgpt")
    lines.append("note_type: conversation")
    lines.append("content_domain: research")
    lines.append(f"message_count: {insights.message_count}")
    lines.append(f"has_images: {str(insights.contains_images).lower()}")
    lines.append(f"has_code: {str(insights.contains_code).lower()}")
    lines.append(f"imported_at: {imported_at_iso}")
    lines.append(f"summary_provider: {summary_provider}")
    lines.append(f"tag_provider: {tag_provider}")
    lines.append("topic_tags:")
    if insights.topic_tags:
        for tag in insights.topic_tags:
            lines.append(f"  - {tag}")
    else:
        lines.append("  - untagged")
    lines.append("tags:")
    lines.append("  - chatgpt")
    for tag in insights.topic_tags[:8]:
        lines.append(f"  - {tag}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {conversation.title}")
    lines.append("")

    lines.append("## At a Glance")
    lines.append("")
    lines.append(f"- Conversation ID: `{conversation.id}`")
    lines.append(f"- Messages: {insights.message_count}")
    lines.append(f"- Updated: {updated_iso or 'unknown'}")
    lines.append(f"- Has code: {insights.contains_code}")
    lines.append(f"- Has images: {insights.contains_images}")
    lines.append("")
    if insights.summary_bullets:
        for bullet in insights.summary_bullets:
            lines.append(f"- {bullet}")
    else:
        lines.append("- No summary extracted.")
    lines.append("")

    lines.append("## Key Decisions")
    lines.append("")
    _append_bullets(lines, insights.key_decisions, "No explicit decisions extracted.")
    lines.append("")

    lines.append("## Action Items")
    lines.append("")
    _append_bullets(lines, insights.action_items, "No explicit action items extracted.")
    lines.append("")

    lines.append("## Open Questions")
    lines.append("")
    _append_bullets(lines, insights.open_questions, "No open questions extracted.")
    lines.append("")

    lines.append("## Topic Tags")
    lines.append("")
    if insights.topic_tags:
        lines.append("Tags:")
        lines.append("")
        lines.append(" ".join(insights.topic_tags))
        lines.append("")
        lines.append("Topic Notes:")
        lines.append("")
        for tag in insights.topic_tags:
            rel = topic_link_map.get(tag)
            label = tag
            if rel:
                lines.append(f"- [[{rel}|{label}]]")
            else:
                lines.append(f"- {tag}")
    else:
        lines.append("- untagged")
    lines.append("")

    lines.append("## Transcript")
    lines.append("")
    for idx, msg in enumerate(conversation.messages, start=1):
        role = (msg.role or "unknown").lower()
        timestamp = _format_dt(msg.timestamp) or "unknown-time"
        lines.append(f"### {idx}. {role} ({timestamp})")
        lines.append("")
        if msg.text_markdown:
            lines.append(msg.text_markdown)
            lines.append("")
        if msg.attachments:
            lines.append("Attachments:")
            for att in msg.attachments:
                rel_target = attachment_rel_paths.get(att.display_name)
                if rel_target:
                    rel = Path(rel_target)
                    lines.append(f"- [[{rel.as_posix()}|{att.display_name}]]")
                    if _is_previewable_attachment(rel.name):
                        lines.append(f"- ![[{rel.as_posix()}]]")
                else:
                    lines.append(f"- {att.display_name} (missing in export source)")
            lines.append("")

    lines.append("## Conversation Attachments")
    lines.append("")
    if conversation.attachments:
        for att in conversation.attachments:
            rel_target = attachment_rel_paths.get(att.display_name)
            if rel_target:
                lines.append(f"- [[{Path(rel_target).as_posix()}|{att.display_name}]]")
            else:
                lines.append(f"- {att.display_name} (missing in export source)")
    else:
        lines.append("- No attachments")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _append_bullets(lines: list[str], values: list[str], empty_text: str) -> None:
    if values:
        for value in values:
            lines.append(f"- {value}")
    else:
        lines.append(f"- {empty_text}")


def _format_dt(value) -> str | None:
    if value is None:
        return None
    if value.tzinfo:
        return value.astimezone(UTC).isoformat()
    return value.replace(tzinfo=UTC).isoformat()


def _escape_yaml(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _is_previewable_attachment(name: str) -> bool:
    ext = Path(name).suffix.lower()
    return ext in {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".svg",
        ".bmp",
        ".mp4",
        ".mov",
        ".webm",
        ".mp3",
        ".wav",
        ".m4a",
        ".ogg",
        ".pdf",
    }
