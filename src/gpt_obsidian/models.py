from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(slots=True)
class Attachment:
    id: str | None
    display_name: str
    source_path: str | None = None
    source_token: str | None = None
    mime_type: str | None = None


@dataclass(slots=True)
class Message:
    id: str
    role: str
    timestamp: datetime | None
    text_markdown: str
    raw_parts: list[str] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)


@dataclass(slots=True)
class Conversation:
    id: str
    title: str
    created_at: datetime | None
    updated_at: datetime | None
    messages: list[Message] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    tags: list[str] = field(default_factory=lambda: ["chatgpt"])


@dataclass(slots=True)
class ConversationInsights:
    summary_bullets: list[str] = field(default_factory=list)
    key_decisions: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    topic_tags: list[str] = field(default_factory=list)
    contains_code: bool = False
    contains_images: bool = False
    message_count: int = 0


@dataclass(slots=True)
class ImportIssue:
    conversation_id: str | None
    note_path: str | None
    severity: str
    kind: str
    detail: str


@dataclass(slots=True)
class ImportRecord:
    conversation_id: str
    note_path: str
    content_hash: str
    last_imported_at: str
    source_updated_at: str | None


@dataclass(slots=True)
class ImportStats:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0


@dataclass(slots=True)
class ImportReport:
    run_started_at: str
    run_completed_at: str
    duration_seconds: float
    input_path: str
    vault_path: str
    summary_provider: str
    summary_model: str | None
    created: int
    updated: int
    skipped: int
    errors: int
    issues: list[ImportIssue] = field(default_factory=list)
    top_topics: list[tuple[str, int]] = field(default_factory=list)


@dataclass(slots=True)
class ExportBundle:
    source_path: Path
    source_kind: str
    conversations: list[Conversation]
    members: set[str]


@dataclass(slots=True)
class AttachmentExtractionResult:
    paths_by_display_name: dict[str, str] = field(default_factory=dict)
    missing_display_names: list[str] = field(default_factory=list)
