from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gpt_obsidian.cli import run
from gpt_obsidian.insights import InsightError, build_heuristic_insights


class CliIntegrationTests(unittest.TestCase):
    def test_import_incremental_upsert_and_attachments(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            zip_path = base / "export.zip"
            vault = base / "vault"

            self._write_export(
                zip_path,
                message_text="Original answer",
                update_time=1704153600,
            )

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = run([
                    "import",
                    "--input",
                    str(zip_path),
                    "--vault",
                    str(vault),
                    "--input-format",
                    "chatgpt",
                ])
            self.assertEqual(rc, 0)
            self.assertIn("created=1", out.getvalue())

            note_path = vault / "Chats/2024/01/chat-title--conv-1.md"
            self.assertTrue(note_path.exists())
            self.assertIn("Original answer", note_path.read_text(encoding="utf-8"))
            self.assertTrue((vault / "Assets/ChatGPT/conv-1/image.png").exists())
            reports = sorted((vault / "Reports/ChatGPT Imports").glob("*.md"))
            self.assertTrue(reports)
            self.assertTrue((vault / "Indexes/ChatGPT/2024-01.md").exists())
            self.assertTrue((vault / "Bases/Chat Conversations.base").exists())
            self.assertTrue((vault / "Bases/Topics.base").exists())
            self.assertTrue(any((vault / "Topics").rglob("*.md")))

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = run([
                    "import",
                    "--input",
                    str(zip_path),
                    "--vault",
                    str(vault),
                    "--input-format",
                    "chatgpt",
                ])
            self.assertEqual(rc, 0)
            self.assertIn("skipped=1", out.getvalue())

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = run([
                    "import",
                    "--input",
                    str(zip_path),
                    "--vault",
                    str(vault),
                    "--input-format",
                    "chatgpt",
                    "--force",
                ])
            self.assertEqual(rc, 0)
            self.assertIn("updated=1", out.getvalue())

            self._write_export(
                zip_path,
                message_text="Updated answer",
                update_time=1704240000,
            )
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = run([
                    "import",
                    "--input",
                    str(zip_path),
                    "--vault",
                    str(vault),
                    "--input-format",
                    "chatgpt",
                ])
            self.assertEqual(rc, 0)
            self.assertIn("updated=1", out.getvalue())
            self.assertIn("Updated answer", note_path.read_text(encoding="utf-8"))

    def test_doctor_reports_invalid_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            bad_zip = base / "bad.zip"
            bad_zip.write_text("not-a-zip", encoding="utf-8")
            vault = base / "vault"

            out = io.StringIO()
            err = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = run(
                    [
                        "doctor",
                        "--input",
                        str(bad_zip),
                        "--vault",
                        str(vault),
                        "--input-format",
                        "chatgpt",
                    ]
                )
            self.assertEqual(rc, 1)
            self.assertIn("Export validation failed", err.getvalue())

    def test_import_from_extracted_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            export_dir = base / "export"
            vault = base / "vault"
            self._write_export_dir(
                export_dir,
                message_text="Answer from directory export",
                update_time=1704240000,
            )

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = run(
                    [
                        "import",
                        "--input",
                        str(export_dir),
                        "--vault",
                        str(vault),
                        "--input-format",
                        "chatgpt",
                    ]
                )
            self.assertEqual(rc, 0)
            self.assertIn("created=1", out.getvalue())
            note_path = vault / "Chats/2024/01/chat-title--conv-1.md"
            self.assertTrue(note_path.exists())
            self.assertIn("Answer from directory export", note_path.read_text(encoding="utf-8"))
            self.assertTrue((vault / "Assets/ChatGPT/conv-1/image.png").exists())

    def test_openai_mode_requires_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            zip_path = base / "export.zip"
            vault = base / "vault"
            self._write_export(zip_path, message_text="x", update_time=1704240000)
            err = io.StringIO()
            with contextlib.redirect_stderr(err), mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test"}):
                rc = run(
                    [
                        "import",
                        "--input",
                        str(zip_path),
                        "--vault",
                        str(vault),
                        "--input-format",
                        "chatgpt",
                        "--summary-provider",
                        "openai",
                    ]
                )
            self.assertEqual(rc, 1)
            self.assertIn("--summary-model is required", err.getvalue())

    def test_openai_tag_mode_requires_tag_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            zip_path = base / "export.zip"
            vault = base / "vault"
            self._write_export(zip_path, message_text="x", update_time=1704240000)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = run(
                    [
                        "import",
                        "--input",
                        str(zip_path),
                        "--vault",
                        str(vault),
                        "--input-format",
                        "chatgpt",
                        "--tag-provider",
                        "openai",
                    ]
                )
            self.assertEqual(rc, 1)
            self.assertIn("--tag-model is required", err.getvalue())

    def test_vllm_mode_does_not_require_openai_key_or_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            zip_path = base / "export.zip"
            vault = base / "vault"
            self._write_export(zip_path, message_text="x", update_time=1704240000)
            out = io.StringIO()
            with (
                contextlib.redirect_stdout(out),
                mock.patch.dict("os.environ", {}, clear=True),
                mock.patch(
                    "gpt_obsidian.cli.build_insights",
                    side_effect=lambda **kwargs: build_heuristic_insights(
                        conversation=kwargs["conversation"],
                        summary_max_bullets=kwargs["summary_max_bullets"],
                        topic_tag_limit=kwargs["topic_tag_limit"],
                        enable_topic_tags=kwargs["enable_topic_tags"],
                    ),
                ),
            ):
                rc = run(
                    [
                        "import",
                        "--input",
                        str(zip_path),
                        "--vault",
                        str(vault),
                        "--input-format",
                        "chatgpt",
                        "--summary-provider",
                        "vllm",
                        "--tag-provider",
                        "vllm",
                    ]
                )
            self.assertEqual(rc, 0)
            self.assertIn("created=1", out.getvalue())

    def test_openai_error_is_not_silent_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            zip_path = base / "export.zip"
            vault = base / "vault"
            self._write_export(zip_path, message_text="x", update_time=1704240000)
            out = io.StringIO()
            err = io.StringIO()
            with (
                contextlib.redirect_stdout(out),
                contextlib.redirect_stderr(err),
                mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test"}),
                mock.patch("gpt_obsidian.cli.build_insights", side_effect=InsightError("boom")),
            ):
                rc = run(
                    [
                        "import",
                        "--input",
                        str(zip_path),
                        "--vault",
                        str(vault),
                        "--input-format",
                        "chatgpt",
                        "--summary-provider",
                        "openai",
                        "--summary-model",
                        "gpt-4o-mini",
                    ]
                )
            self.assertEqual(rc, 1)
            self.assertIn("errors=1", out.getvalue())
            self.assertIn("openai_error", err.getvalue())

    def test_openai_fallback_can_be_explicitly_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            zip_path = base / "export.zip"
            vault = base / "vault"
            self._write_export(zip_path, message_text="x", update_time=1704240000)
            out = io.StringIO()
            with (
                contextlib.redirect_stdout(out),
                mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test"}),
                mock.patch("gpt_obsidian.cli.build_insights", side_effect=InsightError("boom")),
            ):
                rc = run(
                    [
                        "import",
                        "--input",
                        str(zip_path),
                        "--vault",
                        str(vault),
                        "--input-format",
                        "chatgpt",
                        "--summary-provider",
                        "openai",
                        "--summary-model",
                        "gpt-4o-mini",
                        "--allow-openai-fallback",
                    ]
                )
            self.assertEqual(rc, 0)
            self.assertIn("created=1", out.getvalue())

    def test_import_requires_input_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            zip_path = base / "export.zip"
            vault = base / "vault"
            self._write_export(zip_path, message_text="x", update_time=1704240000)
            with self.assertRaises(SystemExit) as ctx:
                run(
                    [
                        "import",
                        "--input",
                        str(zip_path),
                        "--vault",
                        str(vault),
                    ]
                )
            self.assertEqual(ctx.exception.code, 2)

    def test_import_claude_zip_sets_source_and_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            zip_path = base / "claude.zip"
            vault = base / "vault"
            self._write_claude_export(zip_path)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = run(
                    [
                        "import",
                        "--input",
                        str(zip_path),
                        "--vault",
                        str(vault),
                        "--input-format",
                        "claude",
                    ]
                )
            self.assertEqual(rc, 0)
            note_path = vault / "Chats/2026/02/claude-example--claude-1.md"
            note_text = note_path.read_text(encoding="utf-8")
            self.assertIn("source: claude", note_text)
            self.assertIn("tags:\n  - claude", note_text)
            self.assertIn("**Tool use:** web_search", note_text)

    def test_cost_estimate_prints_for_heuristic(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            zip_path = base / "export.zip"
            vault = base / "vault"
            self._write_export(zip_path, message_text="x", update_time=1704240000)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = run(
                    [
                        "import",
                        "--input",
                        str(zip_path),
                        "--vault",
                        str(vault),
                        "--input-format",
                        "chatgpt",
                        "--cost-estimate",
                    ]
                )
            self.assertEqual(rc, 0)
            self.assertIn("Estimated OpenAI cost: $0.0000", out.getvalue())

    def test_cost_estimate_openai_without_key_still_prints_estimate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            zip_path = base / "export.zip"
            vault = base / "vault"
            self._write_export(zip_path, message_text="x", update_time=1704240000)
            out = io.StringIO()
            err = io.StringIO()
            cwd = Path.cwd()
            os.chdir(base)
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch.dict("os.environ", {}, clear=True):
                rc = run(
                    [
                        "import",
                        "--input",
                        str(zip_path),
                        "--vault",
                        str(vault),
                        "--input-format",
                        "chatgpt",
                        "--summary-provider",
                        "openai",
                        "--summary-model",
                        "gpt-4o-mini",
                        "--cost-estimate",
                    ]
                )
            os.chdir(cwd)
            self.assertEqual(rc, 1)
            self.assertIn("Estimated OpenAI cost:", out.getvalue())
            self.assertIn("OPENAI_API_KEY is required", err.getvalue())

    def test_batch_size_parallel_mode_imports_successfully(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            zip_path = base / "export.zip"
            vault = base / "vault"
            self._write_export(zip_path, message_text="x", update_time=1704240000)

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = run(
                    [
                        "import",
                        "--input",
                        str(zip_path),
                        "--vault",
                        str(vault),
                        "--input-format",
                        "chatgpt",
                        "--batch-size",
                        "2",
                    ]
                )
            self.assertEqual(rc, 0)
            self.assertIn("created=1", out.getvalue())

    def test_batch_size_must_be_positive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            zip_path = base / "export.zip"
            vault = base / "vault"
            self._write_export(zip_path, message_text="x", update_time=1704240000)

            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = run(
                    [
                        "import",
                        "--input",
                        str(zip_path),
                        "--vault",
                        str(vault),
                        "--input-format",
                        "chatgpt",
                        "--batch-size",
                        "0",
                    ]
                )
            self.assertEqual(rc, 1)
            self.assertIn("--batch-size must be >= 1", err.getvalue())

    def _write_export(self, path: Path, message_text: str, update_time: int) -> None:
        payload = [
            {
                "id": "conv-1",
                "title": "Chat Title",
                "create_time": 1704067200,
                "update_time": update_time,
                "mapping": {
                    "m1": {
                        "message": {
                            "id": "m1",
                            "author": {"role": "user"},
                            "create_time": 1704067201,
                            "content": {"parts": ["Question"]},
                        }
                    },
                    "m2": {
                        "message": {
                            "id": "m2",
                            "author": {"role": "assistant"},
                            "create_time": 1704067202,
                            "content": {
                                "parts": [
                                    message_text,
                                    {"name": "image.png", "path": "attachments/image.png"},
                                ]
                            },
                        }
                    },
                },
            }
        ]
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("conversations.json", json.dumps(payload))
            zf.writestr("attachments/image.png", b"test-image")

    def _write_export_dir(self, path: Path, message_text: str, update_time: int) -> None:
        payload = [
            {
                "id": "conv-1",
                "title": "Chat Title",
                "create_time": 1704067200,
                "update_time": update_time,
                "mapping": {
                    "m1": {
                        "message": {
                            "id": "m1",
                            "author": {"role": "user"},
                            "create_time": 1704067201,
                            "content": {"parts": ["Question"]},
                        }
                    },
                    "m2": {
                        "message": {
                            "id": "m2",
                            "author": {"role": "assistant"},
                            "create_time": 1704067202,
                            "content": {
                                "parts": [
                                    message_text,
                                    {"name": "image.png", "path": "attachments/image.png"},
                                ]
                            },
                        }
                    },
                },
            }
        ]
        (path / "attachments").mkdir(parents=True, exist_ok=True)
        (path / "conversations.json").write_text(json.dumps(payload), encoding="utf-8")
        (path / "attachments" / "image.png").write_bytes(b"test-image")

    def _write_claude_export(self, path: Path) -> None:
        payload = [
            {
                "uuid": "claude-1",
                "name": "Claude Example",
                "created_at": "2026-02-15T10:00:00Z",
                "updated_at": "2026-02-15T10:05:00Z",
                "chat_messages": [
                    {
                        "uuid": "cm1",
                        "sender": "human",
                        "text": "Find planning apps",
                        "content": [{"type": "text", "text": "Find planning apps"}],
                        "files": [],
                    },
                    {
                        "uuid": "cm2",
                        "sender": "assistant",
                        "content": [
                            {"type": "thinking", "thinking": "Searching for planning apps."},
                            {
                                "type": "tool_use",
                                "name": "web_search",
                                "message": "Looking up itineraries",
                                "input": {"query": "travel planning websites"},
                            },
                            {
                                "type": "tool_result",
                                "name": "web_search",
                                "content": [
                                    {
                                        "type": "knowledge",
                                        "title": "Trip Planner",
                                        "url": "https://example.com",
                                        "text": "Trip planner example snippet.",
                                    }
                                ],
                            },
                        ],
                        "files": [],
                    },
                ],
            }
        ]
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("conversations.json", json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
