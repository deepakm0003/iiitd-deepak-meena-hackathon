"""Run the same checks as CI, locally: README health command, lint, tests, and the guard over tracked files.

Usage (from the repository root, with the project venv's python):
    python scripts/check.py
Exit code 0 only if every step passes.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(title: str, args: list[str]) -> bool:
    print(f"\n=== {title}: {' '.join(args)}", flush=True)
    ok = subprocess.run(args, cwd=ROOT).returncode == 0
    print(f"--- {title}: {'OK' if ok else 'FAILED'}", flush=True)
    return ok


def main() -> int:
    py = sys.executable
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    results = [
        run("health (README Quickstart)", [py, "-m", "tripwire", "health"]),
        run("lint", [py, "-m", "ruff", "check", "."]),
        run("tests", [py, "-m", "pytest", "-q"]),
        run("guard (tracked files)", [py, "scripts/guard_commit.py", *tracked]),
    ]
    print("\nALL CHECKS PASSED" if all(results) else "\nSOME CHECKS FAILED")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
