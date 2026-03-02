from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gpt_obsidian.models import Conversation, ConversationInsights, Message
from gpt_obsidian.transform import conversation_content_hash, note_relative_path


class TransformTests(unittest.TestCase):
    def test_hash_is_stable_for_same_content(self) -> None:
        conv1 = Conversation(
            id="c1",
            title="My Chat",
            created_at=datetime(2024, 1, 1, tzinfo=UTC),
            updated_at=datetime(2024, 1, 1, 1, tzinfo=UTC),
            messages=[Message(id="m1", role="user", timestamp=None, text_markdown="hello")],
        )
        conv2 = Conversation(
            id="c1",
            title="My Chat",
            created_at=datetime(2024, 1, 1, tzinfo=UTC),
            updated_at=datetime(2024, 1, 1, 1, tzinfo=UTC),
            messages=[Message(id="m1", role="user", timestamp=None, text_markdown="hello")],
        )

        insights = ConversationInsights(message_count=1)
        self.assertEqual(
            conversation_content_hash(conv1, insights, "heuristic", None, "heuristic", None),
            conversation_content_hash(conv2, insights, "heuristic", None, "heuristic", None),
        )

    def test_hash_changes_with_summary_model(self) -> None:
        conv = Conversation(
            id="c1",
            title="My Chat",
            created_at=datetime(2024, 1, 1, tzinfo=UTC),
            updated_at=datetime(2024, 1, 1, 1, tzinfo=UTC),
            messages=[Message(id="m1", role="user", timestamp=None, text_markdown="hello")],
        )
        insights = ConversationInsights(summary_bullets=["a"], message_count=1)
        hash_a = conversation_content_hash(conv, insights, "openai", "gpt-4o-mini", "openai", "gpt-4o")
        hash_b = conversation_content_hash(conv, insights, "openai", "gpt-4.1-mini", "openai", "gpt-4o")
        self.assertNotEqual(hash_a, hash_b)

    def test_note_path_uses_year_month_and_slug(self) -> None:
        conv = Conversation(
            id="abc123",
            title="Hello World!",
            created_at=datetime(2024, 2, 20, tzinfo=UTC),
            updated_at=None,
            messages=[],
        )
        path = note_relative_path(conv, "Chats")
        self.assertEqual(path.as_posix(), "Chats/2024/02/hello-world--abc123.md")


if __name__ == "__main__":
    unittest.main()
