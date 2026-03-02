from __future__ import annotations

from pathlib import Path

from .utils import ensure_parent


def write_default_bases(vault_path: Path) -> list[str]:
    base_dir = vault_path / "Bases"
    chats = base_dir / "Chat Conversations.base"
    topics = base_dir / "Topics.base"

    ensure_parent(chats)
    chats.write_text(
        "filters:\n"
        "  and:\n"
        "    - file.inFolder(\"Chats\")\n"
        "views:\n"
        "  - type: table\n"
        "    name: Conversations\n"
        "    order:\n"
        "      - updated\n"
        "      - title\n"
        "      - message_count\n"
        "      - tags\n"
        "      - summary_provider\n"
        "      - tag_provider\n"
        "  - type: table\n"
        "    name: Writing Queue\n"
        "    order:\n"
        "      - title\n"
        "      - topic_tags\n"
        "      - has_code\n"
        "      - has_images\n"
        "      - updated\n"
        "      - file.name\n",
        encoding="utf-8",
    )

    ensure_parent(topics)
    topics.write_text(
        "filters:\n"
        "  and:\n"
        "    - file.inFolder(\"Topics\")\n"
        "views:\n"
        "  - type: table\n"
        "    name: Topics\n"
        "    order:\n"
        "      - file.name\n",
        encoding="utf-8",
    )

    return [
        chats.relative_to(vault_path).as_posix(),
        topics.relative_to(vault_path).as_posix(),
    ]
