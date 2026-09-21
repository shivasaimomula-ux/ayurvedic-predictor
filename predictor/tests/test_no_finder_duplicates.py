"""Finding #22: reject Finder-style 'foo 2.py' duplicates next to real modules."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_no_tracked_finder_duplicate_filenames():
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "check_no_finder_duplicates.sh")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_working_tree_has_no_module_space_2_py():
    """Catch untracked leftovers beside predictor modules (not venv / caches)."""
    bad: list[Path] = []
    for path in ROOT.rglob("* 2.py"):
        parts = set(path.parts)
        if parts & {".venv", ".venv312", "venv", "env", ".git", "__pycache__", "node_modules"}:
            continue
        bad.append(path)
    assert not bad, f"delete Finder duplicates: {bad}"
