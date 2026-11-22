"""Run the visible-pane desktop benchmark or score two completed runs."""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from restore_python_reference import ROOT, restore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("radeon", "xvfb", "score"))
    parser.add_argument("options", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    restore(ROOT / "dist/branchline.pyz")
    scratch = ROOT / "build/benchmarks"
    scratch.mkdir(parents=True, exist_ok=True)
    # The frozen runner generates its drivers next to itself. Stage it here so
    # scoring stays reproducible and parallel invocations have separate drivers.
    with tempfile.TemporaryDirectory(prefix="layout-runner-", dir=scratch) as tmp:
        runner = Path(tmp)
        shutil.copytree(
            Path(__file__).with_name("v2"),
            runner,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("generated", "__pycache__"),
        )
        command = (
            [runner / "score.py"]
            if args.action == "score"
            else [runner / "run.py", args.action]
        )
        return subprocess.call([sys.executable, *command, *args.options])


if __name__ == "__main__":
    sys.exit(main())
