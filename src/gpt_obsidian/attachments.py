from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from .models import Attachment, AttachmentExtractionResult


def extract_attachments_for_conversation(
    source_path: Path,
    source_kind: str,
    members: set[str],
    conversation_id: str,
    attachments: list[Attachment],
    vault_path: Path,
    assets_dir: str,
) -> AttachmentExtractionResult:
    """Extract conversation attachments and return map[display_name] -> relative vault path."""
    if not attachments:
        return AttachmentExtractionResult()

    out_dir = vault_path / assets_dir / conversation_id
    out_dir.mkdir(parents=True, exist_ok=True)

    used_names: set[str] = set()
    output: dict[str, str] = {}
    missing: list[str] = []

    if source_kind == "zip":
        with zipfile.ZipFile(source_path, "r") as zf:
            for att in attachments:
                source_member = resolve_member_path(att, members)
                if not source_member:
                    missing.append(att.display_name)
                    continue
                target_name = _pick_target_name(att, source_member, used_names)
                target_path = out_dir / target_name
                with zf.open(source_member, "r") as src, target_path.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                output[att.display_name] = str(
                    (Path(assets_dir) / conversation_id / target_name).as_posix()
                )
        return AttachmentExtractionResult(paths_by_display_name=output, missing_display_names=missing)

    if source_kind == "dir":
        for att in attachments:
            source_member = resolve_member_path(att, members)
            if not source_member:
                missing.append(att.display_name)
                continue
            source_file = source_path / source_member
            if not source_file.exists():
                missing.append(att.display_name)
                continue
            target_name = _pick_target_name(att, source_member, used_names)
            target_path = out_dir / target_name
            shutil.copyfile(source_file, target_path)
            output[att.display_name] = str((Path(assets_dir) / conversation_id / target_name).as_posix())
        return AttachmentExtractionResult(paths_by_display_name=output, missing_display_names=missing)

    raise ValueError(f"Unsupported source kind: {source_kind}")


def resolve_member_path(attachment: Attachment, zip_members: set[str]) -> str | None:
    candidates: list[str] = []
    if attachment.source_path:
        raw = attachment.source_path.strip()
        if raw.startswith("file-service://"):
            raw = raw.split("file-service://", 1)[1]
        candidates.extend([raw, raw.lstrip("/"), Path(raw).name])
    if attachment.source_token:
        token = attachment.source_token.replace("file-service://", "").strip("/")
        candidates.extend([token, Path(token).name])
    if attachment.display_name:
        candidates.append(attachment.display_name)

    for candidate in candidates:
        if not candidate:
            continue
        if candidate in zip_members:
            return candidate

    basename_map: dict[str, list[str]] = {}
    for member in zip_members:
        basename_map.setdefault(Path(member).name, []).append(member)

    for candidate in candidates:
        base = Path(candidate).name
        if base in basename_map and len(basename_map[base]) == 1:
            return basename_map[base][0]

    # Many ChatGPT exports reference attachments by token without extension,
    # while actual files include an extension (e.g. token -> .jpeg file).
    stem_map: dict[str, list[str]] = {}
    for member in zip_members:
        stem_map.setdefault(Path(member).stem, []).append(member)

    for candidate in candidates:
        stem = Path(candidate).stem
        if stem in stem_map and len(stem_map[stem]) == 1:
            return stem_map[stem][0]

    # Fallback prefix matching when token is truncated but still unique.
    for candidate in candidates:
        token = Path(candidate).name
        if not token:
            continue
        matches = [member for member in zip_members if Path(member).name.startswith(token)]
        if len(matches) == 1:
            return matches[0]

    return None


def _dedupe_name(name: str, used_names: set[str]) -> str:
    candidate = Path(name).name or "attachment"
    stem = Path(candidate).stem
    suffix = Path(candidate).suffix
    index = 1
    while candidate in used_names:
        candidate = f"{stem}-{index}{suffix}"
        index += 1
    used_names.add(candidate)
    return candidate


def _pick_target_name(attachment: Attachment, source_member: str, used_names: set[str]) -> str:
    display = Path(attachment.display_name)
    source_base = Path(source_member).name
    if display.suffix:
        return _dedupe_name(display.name, used_names)
    if Path(source_base).suffix:
        return _dedupe_name(source_base, used_names)
    return _dedupe_name(display.name, used_names)
