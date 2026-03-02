from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gpt_obsidian.insights import InsightError, _parse_json_object, build_insights, build_heuristic_insights
from gpt_obsidian.models import Conversation, Message


class InsightsTests(unittest.TestCase):
    def test_heuristic_extracts_sections_and_tags(self) -> None:
        conv = Conversation(
            id="c1",
            title="Deploy plan",
            created_at=datetime(2024, 1, 1, tzinfo=UTC),
            updated_at=datetime(2024, 1, 1, 1, tzinfo=UTC),
            messages=[
                Message(
                    id="m1",
                    role="user",
                    timestamp=None,
                    text_markdown=(
                        "We will decide to use Render for deployment. "
                        "Next steps are to implement CI and run tests."
                    ),
                ),
                Message(id="m2", role="assistant", timestamp=None, text_markdown="Should we keep staging?"),
            ],
        )
        insights = build_heuristic_insights(conv, summary_max_bullets=5, topic_tag_limit=8, enable_topic_tags=True)
        self.assertTrue(insights.summary_bullets)
        self.assertTrue(insights.key_decisions)
        self.assertTrue(insights.action_items)
        self.assertTrue(insights.open_questions)
        self.assertTrue(any("/" not in tag for tag in insights.topic_tags))

    def test_openai_without_key_raises(self) -> None:
        conv = Conversation(
            id="c1",
            title="x",
            created_at=None,
            updated_at=None,
            messages=[Message(id="m1", role="user", timestamp=None, text_markdown="hello")],
                )

    def test_tag_cleaning_canonical_kebab_case(self) -> None:
        conv = Conversation(
            id="c2",
            title="x",
            created_at=None,
            updated_at=None,
            messages=[Message(id="m1", role="user", timestamp=None, text_markdown="Python docs and API design")],
        )
        insights = build_heuristic_insights(conv, summary_max_bullets=5, topic_tag_limit=8, enable_topic_tags=True)
        for tag in insights.topic_tags:
            self.assertNotIn("/", tag)
            self.assertNotIn("_", tag)
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(InsightError):
                build_insights(
                    conversation=conv,
                summary_provider="openai",
                summary_model="gpt-4o-mini",
                summary_max_bullets=5,
                tag_provider="heuristic",
                tag_model=None,
                topic_tag_limit=8,
                enable_topic_tags=True,
            )

    def test_parse_json_object_from_fenced_content(self) -> None:
        parsed = _parse_json_object("```json\n{\"topic_tags\": [\"python\"]}\n```")
        self.assertEqual(parsed, {"topic_tags": ["python"]})

    def test_parse_json_object_from_wrapped_content(self) -> None:
        parsed = _parse_json_object("Here is the result: {\"topic_tags\": [\"python\"]}")
        self.assertEqual(parsed, {"topic_tags": ["python"]})

if __name__ == "__main__":
    unittest.main()
