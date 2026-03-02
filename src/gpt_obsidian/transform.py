from __future__ import annotations

from dataclasses import asdict
from datetime import UTC
from pathlib import Path

from .models import Conversation, ConversationInsights
from .utils import safe_slug, stable_hash, to_iso


def conversation_content_hash(
    conversation: Conversation,
    insights: ConversationInsights,
    summary_provider: str,
    summary_model: str | None,
    tag_provider: str,
    tag_model: str | None,
) -> str:
    return stable_hash(_conversation_serial(conversation))


def legacy_conversation_content_hash(
    conversation: Conversation,
    insights: ConversationInsights,
    summary_provider: str,
    summary_model: str | None,
    tag_provider: str,
    tag_model: str | None,
) -> str:
    serial = _conversation_serial(conversation)
    serial.update(
        {
            "insights": asdict(insights),
            "summary_provider": summary_provider,
            "summary_model": summary_model,
            "tag_provider": tag_provider,
            "tag_model": tag_model,
        }
    )
    return stable_hash(serial)


def note_relative_path(conversation: Conversation, chats_dir: str) -> Path:
    ts = conversation.created_at or conversation.updated_at
    if ts is None:
        year = "unknown"
        month = "00"
    else:
        ts = ts.astimezone(UTC) if ts.tzinfo else ts.replace(tzinfo=UTC)
        year = f"{ts.year:04d}"
        month = f"{ts.month:02d}"

    slug = safe_slug(conversation.title, fallback="untitled-chat")
    filename = f"{slug}--{conversation.id}.md"
    return Path(chats_dir) / year / month / filename


def _conversation_serial(conversation: Conversation) -> dict:
    return {
        "id": conversation.id,
        "title": conversation.title,
        "created_at": to_iso(conversation.created_at),
        "updated_at": to_iso(conversation.updated_at),
        "messages": [
            {
                "id": msg.id,
                "role": msg.role,
                "timestamp": to_iso(msg.timestamp),
                "text_markdown": msg.text_markdown,
                "attachments": [asdict(att) for att in msg.attachments],
            }
            for msg in conversation.messages
        ],
        "attachments": [asdict(att) for att in conversation.attachments],
    }
