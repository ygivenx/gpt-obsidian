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
from gpt_obsidian.insights import InsightError


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
                rc = run(["doctor", "--input", str(bad_zip), "--vault", str(vault)])
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
                        "--tag-provider",
                        "openai",
                    ]
                )
            self.assertEqual(rc, 1)
            self.assertIn("--tag-model is required", err.getvalue())

    def test_openai_fallback_to_heuristic_on_error(self) -> None:
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
                        "--summary-provider",
                        "openai",
                        "--summary-model",
                        "gpt-4o-mini",
                    ]
                )
            self.assertEqual(rc, 0)
            self.assertIn("created=1", out.getvalue())

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


if __name__ == "__main__":
    unittest.main()
