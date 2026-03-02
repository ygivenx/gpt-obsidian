from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gpt_obsidian.export_reader import ExportReadError, load_export


class ExportReaderTests(unittest.TestCase):
    def test_load_export_parses_mapping_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = Path(tmpdir) / "export.zip"
            payload = [
                {
                    "id": "conv-1",
                    "title": "Test Chat",
                    "create_time": 1704067200,
                    "update_time": 1704153600,
                    "mapping": {
                        "node-1": {
                            "message": {
                                "id": "m1",
                                "author": {"role": "user"},
                                "create_time": 1704067201,
                                "content": {"parts": ["Hello"]},
                            }
                        },
                        "node-2": {
                            "message": {
                                "id": "m2",
                                "author": {"role": "assistant"},
                                "create_time": 1704067202,
                                "content": {
                                    "parts": [
                                        "Hi",
                                        {
                                            "name": "image.png",
                                            "path": "attachments/image.png",
                                            "mime_type": "image/png",
                                        },
                                    ]
                                },
                            }
                        },
                    },
                }
            ]

            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("conversations.json", json.dumps(payload))
                zf.writestr("attachments/image.png", b"png")

            bundle = load_export(zip_path)
            self.assertEqual(len(bundle.conversations), 1)
            conv = bundle.conversations[0]
            self.assertEqual(conv.id, "conv-1")
            self.assertEqual(len(conv.messages), 2)
            self.assertEqual(conv.messages[0].role, "user")
            self.assertEqual(conv.messages[1].attachments[0].display_name, "image.png")

    def test_load_export_fails_without_conversations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = Path(tmpdir) / "bad.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("foo.json", "{}")

            with self.assertRaises(ExportReadError):
                load_export(zip_path)

    def test_derives_conversation_dates_from_messages_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = Path(tmpdir) / "export.zip"
            payload = [
                {
                    "id": "conv-2",
                    "title": "No top-level dates",
                    "create_time": None,
                    "update_time": None,
                    "mapping": {
                        "node-1": {
                            "message": {
                                "id": "m1",
                                "author": {"role": "user"},
                                "create_time": 1704067201,
                                "content": {"parts": ["Hi"]},
                            }
                        },
                        "node-2": {
                            "message": {
                                "id": "m2",
                                "author": {"role": "assistant"},
                                "create_time": 1704153602,
                                "content": {"parts": ["Hello"]},
                            }
                        },
                    },
                }
            ]
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("conversations.json", json.dumps(payload))

            bundle = load_export(zip_path)
            conv = bundle.conversations[0]
            self.assertIsNotNone(conv.created_at)
            self.assertIsNotNone(conv.updated_at)
            self.assertEqual(conv.created_at.timestamp(), 1704067201)
            self.assertEqual(conv.updated_at.timestamp(), 1704153602)

    def test_load_export_from_sharded_conversation_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            export_dir = Path(tmpdir) / "export"
            export_dir.mkdir(parents=True, exist_ok=True)
            shard_a = [
                {
                    "id": "conv-a",
                    "title": "A",
                    "mapping": {
                        "n1": {
                            "message": {
                                "id": "m1",
                                "author": {"role": "user"},
                                "create_time": 1704067200,
                                "content": {"parts": ["A"]},
                            }
                        }
                    },
                }
            ]
            shard_b = [
                {
                    "id": "conv-b",
                    "title": "B",
                    "mapping": {
                        "n2": {
                            "message": {
                                "id": "m2",
                                "author": {"role": "user"},
                                "create_time": 1704067201,
                                "content": {"parts": ["B"]},
                            }
                        }
                    },
                }
            ]
            (export_dir / "conversations-000.json").write_text(json.dumps(shard_a), encoding="utf-8")
            (export_dir / "conversations-001.json").write_text(json.dumps(shard_b), encoding="utf-8")

            bundle = load_export(export_dir)
            self.assertEqual(len(bundle.conversations), 2)
            ids = sorted(c.id for c in bundle.conversations)
            self.assertEqual(ids, ["conv-a", "conv-b"])


if __name__ == "__main__":
    unittest.main()
