from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

from .models import Attachment, Conversation, ExportBundle, Message
from .utils import normalize_markdown, parse_timestamp


class ExportReadError(RuntimeError):
    pass


def load_export(zip_path: Path) -> ExportBundle:
    if not zip_path.exists():
        raise ExportReadError(f"Input path not found: {zip_path}")

    if zip_path.is_dir():
        return _load_export_dir(zip_path)
    if zipfile.is_zipfile(zip_path):
        return _load_export_zip(zip_path)

    raise ExportReadError(f"Input must be a ZIP archive or extracted export directory: {zip_path}")


def _load_export_zip(zip_path: Path) -> ExportBundle:
    with zipfile.ZipFile(zip_path, "r") as zf:
        members = {name for name in zf.namelist() if not name.endswith("/")}
        conversation_names = _find_conversation_json_files(members)
        if not conversation_names:
            raise ExportReadError(
                "Could not find conversation JSON in export ZIP. "
                "Expected conversations.json or conversations-*.json"
            )

        raw_rows: list[object] = []
        for conversation_name in conversation_names:
            try:
                payload = json.loads(zf.read(conversation_name))
            except json.JSONDecodeError as exc:
                raise ExportReadError(f"Invalid JSON in {conversation_name}: {exc}") from exc
            raw_rows.extend(_coerce_payload_to_rows(payload))

    conversations = _parse_conversations(raw_rows)
    return ExportBundle(
        source_path=zip_path,
        source_kind="zip",
        conversations=conversations,
        members=members,
    )


def _load_export_dir(input_dir: Path) -> ExportBundle:
    members = {
        str(path.relative_to(input_dir).as_posix())
        for path in input_dir.rglob("*")
        if path.is_file()
    }
    conversation_names = _find_conversation_json_files(members)
    if not conversation_names:
        raise ExportReadError(
            "Could not find conversation JSON in export directory. "
            "Expected conversations.json or conversations-*.json"
        )

    raw_rows: list[object] = []
    for conversation_name in conversation_names:
        conversation_file = input_dir / conversation_name
        try:
            payload = json.loads(conversation_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ExportReadError(f"Invalid JSON in {conversation_name}: {exc}") from exc
        raw_rows.extend(_coerce_payload_to_rows(payload))

    conversations = _parse_conversations(raw_rows)
    return ExportBundle(
        source_path=input_dir,
        source_kind="dir",
        conversations=conversations,
        members=members,
    )


def _find_conversation_json_files(members: set[str]) -> list[str]:
    preferred = ["conversations.json", "chat.html.json", "chatgpt/conversations.json"]
    for name in preferred:
        if name in members:
            return [name]

    shard_pattern = re.compile(r"(^|.*/)conversations-\d+\.json$")
    shard_candidates = [name for name in members if shard_pattern.search(name)]
    if shard_candidates:
        return sorted(shard_candidates)

    candidates = [name for name in members if name.endswith("conversations.json")]
    if candidates:
        return sorted(candidates)
    return []


def _coerce_payload_to_rows(raw_payload: object) -> list[object]:
    if isinstance(raw_payload, dict):
        if "conversations" in raw_payload and isinstance(raw_payload["conversations"], list):
            return raw_payload["conversations"]
        return [raw_payload]
    if isinstance(raw_payload, list):
        return raw_payload
    return []


def _parse_conversations(raw_payload: object) -> list[Conversation]:
    if isinstance(raw_payload, dict):
        if "conversations" in raw_payload and isinstance(raw_payload["conversations"], list):
            rows = raw_payload["conversations"]
        else:
            rows = [raw_payload]
    elif isinstance(raw_payload, list):
        rows = raw_payload
    else:
        raise ExportReadError("Unsupported conversations payload type")

    output: list[Conversation] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        conv = _parse_conversation(row)
        if conv is not None:
            output.append(conv)

    if not output:
        raise ExportReadError("No conversations were found in the export archive")
    return output


def _parse_conversation(row: dict) -> Conversation | None:
    conv_id = str(row.get("id") or "").strip()
    if not conv_id:
        return None

    title = str(row.get("title") or "Untitled Chat")
    created_at = parse_timestamp(row.get("create_time") or row.get("created_at"))
    updated_at = parse_timestamp(row.get("update_time") or row.get("updated_at"))

    messages = _extract_messages(row)
    if created_at is None:
        created_at = _min_message_time(messages)
    if updated_at is None:
        updated_at = _max_message_time(messages)
    all_attachments: list[Attachment] = []
    for msg in messages:
        all_attachments.extend(msg.attachments)

    return Conversation(
        id=conv_id,
        title=title,
        created_at=created_at,
        updated_at=updated_at,
        messages=messages,
        attachments=all_attachments,
    )


def _min_message_time(messages: list[Message]):
    times = [msg.timestamp for msg in messages if msg.timestamp is not None]
    return min(times) if times else None


def _max_message_time(messages: list[Message]):
    times = [msg.timestamp for msg in messages if msg.timestamp is not None]
    return max(times) if times else None


def _extract_messages(row: dict) -> list[Message]:
    mapping = row.get("mapping")
    if isinstance(mapping, dict):
        messages = []
        for node_id, node in mapping.items():
            if not isinstance(node, dict):
                continue
            payload = node.get("message")
            if not isinstance(payload, dict):
                continue
            parsed = _parse_message(node_id, payload)
            if parsed is not None:
                messages.append(parsed)

        messages.sort(key=lambda m: (m.timestamp is None, m.timestamp, m.id))
        return messages

    # Fallback for alternate structures with flat messages arrays.
    raw_messages = row.get("messages")
    if isinstance(raw_messages, list):
        parsed_messages = []
        for idx, msg in enumerate(raw_messages):
            if isinstance(msg, dict):
                parsed = _parse_message(str(msg.get("id") or idx), msg)
                if parsed is not None:
                    parsed_messages.append(parsed)
        parsed_messages.sort(key=lambda m: (m.timestamp is None, m.timestamp, m.id))
        return parsed_messages

    return []


def _parse_message(message_id: str, payload: dict) -> Message | None:
    author = payload.get("author")
    role = "unknown"
    if isinstance(author, dict):
        role = str(author.get("role") or "unknown")
    elif isinstance(author, str):
        role = author

    timestamp = parse_timestamp(payload.get("create_time") or payload.get("timestamp"))

    content = payload.get("content") or {}
    text_parts: list[str] = []
    attachments: list[Attachment] = []

    if isinstance(content, dict):
        parts = content.get("parts")
        if isinstance(parts, list):
            for part in parts:
                if isinstance(part, str):
                    text_parts.append(part)
                elif isinstance(part, dict):
                    extracted_text, extracted_attachment = _parse_content_part(part)
                    if extracted_text:
                        text_parts.append(extracted_text)
                    if extracted_attachment:
                        attachments.append(extracted_attachment)

    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        attachments.extend(_extract_attachments_from_metadata(metadata))

    if not text_parts and not attachments:
        return None

    normalized = [normalize_markdown(part) for part in text_parts if normalize_markdown(part)]
    return Message(
        id=message_id,
        role=role,
        timestamp=timestamp,
        text_markdown="\n\n".join(normalized),
        raw_parts=normalized,
        attachments=attachments,
    )


def _parse_content_part(part: dict) -> tuple[str | None, Attachment | None]:
    if "text" in part and isinstance(part["text"], str):
        return part["text"], None

    candidate_path = (
        part.get("path")
        or part.get("file_path")
        or part.get("local_path")
        or part.get("asset_pointer")
    )
    if candidate_path:
        display_name = str(part.get("name") or Path(str(candidate_path)).name or "attachment")
        att = Attachment(
            id=str(part.get("id") or "") or None,
            display_name=display_name,
            source_path=str(candidate_path),
            source_token=str(part.get("asset_pointer") or "") or None,
            mime_type=str(part.get("mime_type") or "") or None,
        )
        return None, att

    return None, None


def _extract_attachments_from_metadata(metadata: dict) -> list[Attachment]:
    raw = metadata.get("attachments")
    if not isinstance(raw, list):
        return []

    out: list[Attachment] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        source_path = item.get("path") or item.get("file_path") or item.get("asset_pointer")
        display_name = str(item.get("name") or Path(str(source_path or "attachment")).name)
        out.append(
            Attachment(
                id=str(item.get("id") or "") or None,
                display_name=display_name,
                source_path=str(source_path) if source_path else None,
                source_token=str(item.get("asset_pointer") or "") or None,
                mime_type=str(item.get("mime_type") or "") or None,
            )
        )
    return out
