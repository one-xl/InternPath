from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def find_project_python() -> str:
    configured = os.environ.get("INTERNPATH_PYTHON")
    candidates = [
        Path(configured) if configured else None,
        ROOT / ".venv" / "Scripts" / "python.exe",
        ROOT / ".venv" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate and candidate.exists():
            return str(candidate)
    return shutil.which("python") or sys.executable


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python scripts/run_project_python.py <python-args...>", file=sys.stderr)
        return 2
    result = subprocess.run([find_project_python(), *sys.argv[1:]], cwd=str(ROOT), check=False)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
