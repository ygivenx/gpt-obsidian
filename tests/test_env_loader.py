from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gpt_obsidian.cli import _load_env_file


class EnvLoaderTests(unittest.TestCase):
    def test_loads_openai_key_from_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text('OPENAI_API_KEY="abc123"\n', encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=True):
                _load_env_file(env_file)
                self.assertEqual(os.getenv("OPENAI_API_KEY"), "abc123")

    def test_does_not_override_existing_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text("OPENAI_API_KEY=from_file\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "from_env"}, clear=True):
                _load_env_file(env_file)
                self.assertEqual(os.getenv("OPENAI_API_KEY"), "from_env")


if __name__ == "__main__":
    unittest.main()
