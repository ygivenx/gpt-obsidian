from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gpt_obsidian.attachments import extract_attachments_for_conversation, resolve_member_path
from gpt_obsidian.models import Attachment


class AttachmentsTests(unittest.TestCase):
    def test_resolve_member_when_token_missing_extension(self) -> None:
        att = Attachment(
            id=None,
            display_name="file-U3queNzGHtwHMKpTMGYGBN",
            source_path=None,
            source_token="file-U3queNzGHtwHMKpTMGYGBN",
            mime_type=None,
        )
        members = {
            "conversations-000.json",
            "file-U3queNzGHtwHMKpTMGYGBN.jpeg",
        }
        resolved = resolve_member_path(att, members)
        self.assertEqual(resolved, "file-U3queNzGHtwHMKpTMGYGBN.jpeg")

    def test_extract_preserves_extension_when_display_name_has_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            zip_path = base / "export.zip"
            vault = base / "vault"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("file-U3queNzGHtwHMKpTMGYGBN-IMG_ABC.jpeg", b"jpeg")

            att = Attachment(
                id=None,
                display_name="file-U3queNzGHtwHMKpTMGYGBN",
                source_path=None,
                source_token="file-U3queNzGHtwHMKpTMGYGBN",
                mime_type=None,
            )
            result = extract_attachments_for_conversation(
                source_path=zip_path,
                source_kind="zip",
                members={"file-U3queNzGHtwHMKpTMGYGBN-IMG_ABC.jpeg"},
                conversation_id="c1",
                attachments=[att],
                vault_path=vault,
                assets_dir="Assets/ChatGPT",
            )
            self.assertIn("file-U3queNzGHtwHMKpTMGYGBN", result.paths_by_display_name)
            out_rel = result.paths_by_display_name["file-U3queNzGHtwHMKpTMGYGBN"]
            self.assertTrue(out_rel.endswith(".jpeg"))
            self.assertTrue((vault / out_rel).exists())


if __name__ == "__main__":
    unittest.main()
