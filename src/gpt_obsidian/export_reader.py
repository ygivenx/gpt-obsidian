from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

from .models import Attachment, Conversation, ExportBundle, Message
from .utils import normalize_markdown, parse_timestamp


class ExportReadError(RuntimeError):
    pass


def load_export(input_path: Path, input_format: str) -> ExportBundle:
    if not input_path.exists():
        raise ExportReadError(f"Input path not found: {input_path}")

    if input_format == "chatgpt":
        return _load_chatgpt_export(input_path)
    if input_format == "claude":
        return _load_claude_export(input_path)
    raise ExportReadError(f"Unsupported input format: {input_format}")


def _load_chatgpt_export(path: Path) -> ExportBundle:
    if path.is_dir():
        return _load_chatgpt_dir(path)
    if zipfile.is_zipfile(path):
        return _load_chatgpt_zip(path)
    raise ExportReadError(f"Input must be a ZIP archive or extracted export directory: {path}")


def _load_claude_export(path: Path) -> ExportBundle:
    if path.is_dir():
        return _load_claude_dir(path)
    if zipfile.is_zipfile(path):
        return _load_claude_zip(path)
    raise ExportReadError(f"Input must be a ZIP archive or extracted export directory: {path}")


def _load_chatgpt_zip(zip_path: Path) -> ExportBundle:
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


def _load_chatgpt_dir(input_dir: Path) -> ExportBundle:
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


def _load_claude_zip(zip_path: Path) -> ExportBundle:
    with zipfile.ZipFile(zip_path, "r") as zf:
        members = {name for name in zf.namelist() if not name.endswith("/")}
        if "conversations.json" not in members:
            raise ExportReadError("Claude export ZIP missing conversations.json")
        try:
            payload = json.loads(zf.read("conversations.json"))
        except json.JSONDecodeError as exc:
            raise ExportReadError(f"Invalid JSON in conversations.json: {exc}") from exc

    conversations = _parse_claude_conversations(payload, members)
    return ExportBundle(
        source_path=zip_path,
        source_kind="zip",
        conversations=conversations,
        members=members,
    )


def _load_claude_dir(input_dir: Path) -> ExportBundle:
    members = {
        str(path.relative_to(input_dir).as_posix())
        for path in input_dir.rglob("*")
        if path.is_file()
    }
    conversation_file = input_dir / "conversations.json"
    if not conversation_file.exists():
        raise ExportReadError("Claude export directory missing conversations.json")
    try:
        payload = json.loads(conversation_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ExportReadError(f"Invalid JSON in conversations.json: {exc}") from exc

    conversations = _parse_claude_conversations(payload, members)
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
        source="chatgpt",
        messages=messages,
        attachments=all_attachments,
    )


def _parse_claude_conversations(raw_payload: object, members: set[str]) -> list[Conversation]:
    if not isinstance(raw_payload, list):
        raise ExportReadError("Claude conversations.json must contain a list of conversations")

    output: list[Conversation] = []
    for row in raw_payload:
        if not isinstance(row, dict):
            continue
        conv_id = str(row.get("uuid") or "").strip()
        if not conv_id:
            continue
        title = str(row.get("name") or "Untitled Claude Chat")
        created_at = parse_timestamp(row.get("created_at"))
        updated_at = parse_timestamp(row.get("updated_at"))

        messages: list[Message] = []
        raw_messages = row.get("chat_messages") or []
        if isinstance(raw_messages, list):
            for payload in raw_messages:
                if not isinstance(payload, dict):
                    continue
                parsed = _parse_claude_message(payload, members)
                if parsed is not None:
                    messages.append(parsed)

        if created_at is None:
            created_at = _min_message_time(messages)
        if updated_at is None:
            updated_at = _max_message_time(messages)

        all_attachments: list[Attachment] = []
        for msg in messages:
            all_attachments.extend(msg.attachments)

        output.append(
            Conversation(
                id=conv_id,
                title=title,
                created_at=created_at,
                updated_at=updated_at,
                source="claude",
                messages=messages,
                attachments=all_attachments,
                tags=["claude"],
            )
        )

    if not output:
        raise ExportReadError("No conversations were found in the export archive")
    return output


def _parse_claude_message(payload: dict, members: set[str]) -> Message | None:
    msg_id = str(payload.get("uuid") or "").strip()
    if not msg_id:
        return None

    sender = str(payload.get("sender") or "unknown").lower()
    if sender == "human":
        role = "user"
    elif sender == "assistant":
        role = "assistant"
    else:
        role = sender or "unknown"

    timestamp = parse_timestamp(payload.get("created_at") or payload.get("updated_at"))

    text_blocks: list[str] = []
    raw_text = payload.get("text")
    if isinstance(raw_text, str) and raw_text.strip():
        text_blocks.append(raw_text)

    contents = payload.get("content")
    if isinstance(contents, list):
        for segment in contents:
            formatted = _format_claude_segment(segment)
            if formatted:
                text_blocks.append(formatted)

    attachments = _claude_attachments(payload.get("files"), members)

    normalized = [normalize_markdown(block) for block in text_blocks if normalize_markdown(block)]
    if not normalized and not attachments:
        return None

    return Message(
        id=msg_id,
        role=role,
        timestamp=timestamp,
        text_markdown="\n\n".join(normalized),
        raw_parts=normalized,
        attachments=attachments,
    )


def _format_claude_segment(segment: object) -> str | None:
    if not isinstance(segment, dict):
        return None
    seg_type = segment.get("type")
    if seg_type == "text":
        text = segment.get("text")
        return text if isinstance(text, str) and text.strip() else None
    if seg_type == "thinking":
        text = segment.get("thinking")
        return _format_claude_thinking(text) if isinstance(text, str) and text.strip() else None
    if seg_type == "tool_use":
        return _format_claude_tool_use(segment)
    if seg_type == "tool_result":
        return _format_claude_tool_result(segment)
    return None


def _format_claude_thinking(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    lines = stripped.splitlines()
    if not lines:
        return ""
    formatted = [f"> [Claude thinking] {lines[0]}"]
    for line in lines[1:]:
        formatted.append(f"> {line}")
    return "\n".join(formatted)


def _format_claude_tool_use(segment: dict) -> str | None:
    name = segment.get("name") or "tool"
    message = segment.get("message")
    input_payload = segment.get("input")
    parts = [f"**Tool use:** {name}"]
    if isinstance(message, str) and message.strip():
        parts.append(message.strip())
    if input_payload is not None:
        try:
            pretty = json.dumps(input_payload, indent=2, sort_keys=True)
        except TypeError:
            pretty = str(input_payload)
        parts.append("```json")
        parts.append(pretty)
        parts.append("```")
    return "\n".join(parts)


def _format_claude_tool_result(segment: dict) -> str | None:
    content = segment.get("content")
    if not isinstance(content, list):
        return None
    lines: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "knowledge":
            title = item.get("title") or "Knowledge Result"
            url = item.get("url")
            snippet = _truncate_snippet(item.get("text", ""))
            bullet = f"- **{title}**"
            if url:
                bullet += f" ({url})"
            if snippet:
                bullet += f": {snippet}"
            lines.append(bullet)
        elif item_type == "text":
            snippet = _truncate_snippet(item.get("text", ""))
            if snippet:
                lines.append(snippet)
    if not lines:
        return None
    header = segment.get("name")
    parts = []
    if header:
        parts.append(f"**Tool result:** {header}")
    parts.extend(lines)
    return "\n".join(parts)


def _claude_attachments(entries: object, members: set[str]) -> list[Attachment]:
    if not isinstance(entries, list):
        return []
    output: list[Attachment] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        file_name = str(entry.get("file_name") or "").strip()
        if not file_name:
            continue
        member = _resolve_claude_file_member(file_name, members)
        if not member:
            continue
        output.append(
            Attachment(
                id=str(entry.get("uuid") or "") or None,
                display_name=Path(file_name).name or file_name,
                source_path=member,
                source_token=None,
                mime_type=str(entry.get("mime_type") or "") or None,
            )
        )
    return output


def _resolve_claude_file_member(file_name: str, members: set[str]) -> str | None:
    candidates = []
    cleaned = file_name.lstrip("/")
    candidates.append(cleaned)
    base = Path(cleaned).name
    if base != cleaned:
        candidates.append(base)
    candidates.extend(
        [
            f"files/{base}",
            f"attachments/{base}",
        ]
    )
    for candidate in candidates:
        if candidate in members:
            return candidate
    return None


def _truncate_snippet(value: object, limit: int = 600) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


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
