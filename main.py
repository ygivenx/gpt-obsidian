from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from gpt_obsidian.cli import run

if __name__ == "__main__":
    raise SystemExit(run())
