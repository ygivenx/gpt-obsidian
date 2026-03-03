from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gpt_obsidian.markdown_renderer import render_conversation_markdown
from gpt_obsidian.models import Attachment, Conversation, ConversationInsights, Message


class MarkdownRendererTests(unittest.TestCase):
    def test_renders_new_sections_and_frontmatter(self) -> None:
        conv = Conversation(
            id="c1",
            title="Title",
            created_at=datetime(2024, 1, 1, tzinfo=UTC),
            updated_at=datetime(2024, 1, 1, 1, tzinfo=UTC),
            messages=[
                Message(
                    id="m1",
                    role="user",
                    timestamp=datetime(2024, 1, 1, tzinfo=UTC),
                    text_markdown="Hello world",
                    attachments=[Attachment(id=None, display_name="image.png")],
                )
            ],
            attachments=[Attachment(id=None, display_name="image.png")],
        )
        insights = ConversationInsights(
            summary_bullets=["Summary bullet"],
            key_decisions=["Decision"],
            action_items=["Action"],
            open_questions=["Question?"],
            topic_tags=["python"],
            contains_code=False,
            contains_images=True,
            message_count=1,
        )

        md = render_conversation_markdown(
            conversation=conv,
            note_rel_path=Path("Chats/2024/01/title--c1.md"),
            attachment_rel_paths={"image.png": "Assets/ChatGPT/c1/image.png"},
            insights=insights,
            imported_at_iso="2026-01-01T00:00:00+00:00",
            summary_provider="heuristic",
            tag_provider="openai",
            topic_link_map={"python": "Topics/python.md"},
        )
        self.assertIn("message_count: 1", md)
        self.assertIn("note_type: conversation", md)
        self.assertIn("content_domain: research", md)
        self.assertIn("source: chatgpt", md)
        self.assertIn("summary_provider: heuristic", md)
        self.assertIn("tag_provider: openai", md)
        self.assertIn("## At a Glance", md)
        self.assertIn("## Key Decisions", md)
        self.assertIn("## Action Items", md)
        self.assertIn("## Open Questions", md)
        self.assertIn("## Topic Tags", md)
        self.assertIn("![[Assets/ChatGPT/c1/image.png]]", md)
        self.assertIn("tags:\n  - chatgpt", md)
        self.assertIn("topic_tags:\n  - python", md)
        self.assertIn("[[Topics/python.md|python]]", md)

    def test_renders_custom_source_and_tags(self) -> None:
        conv = Conversation(
            id="c2",
            title="Claude Note",
            created_at=datetime(2024, 2, 2, tzinfo=UTC),
            updated_at=datetime(2024, 2, 2, 1, tzinfo=UTC),
            source="claude",
            tags=["claude", "ai"],
            messages=[
                Message(
                    id="m1",
                    role="assistant",
                    timestamp=datetime(2024, 2, 2, tzinfo=UTC),
                    text_markdown="Claude response",
                )
            ],
        )
        insights = ConversationInsights(
            summary_bullets=[],
            key_decisions=[],
            action_items=[],
            open_questions=[],
            topic_tags=["routing"],
            contains_code=False,
            contains_images=False,
            message_count=1,
        )
        md = render_conversation_markdown(
            conversation=conv,
            note_rel_path=Path("Chats/2024/02/claude-note--c2.md"),
            attachment_rel_paths={},
            insights=insights,
            imported_at_iso="2026-01-01T00:00:00+00:00",
            summary_provider="heuristic",
            tag_provider="heuristic",
            topic_link_map={},
        )
        self.assertIn("source: claude", md)
        self.assertIn("tags:\n  - claude\n  - ai", md)


if __name__ == "__main__":
    unittest.main()
