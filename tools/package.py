"""Build a single-file desktop launcher using the Python standard library."""

import shutil
import tempfile
import zipapp
from pathlib import Path

root = Path(__file__).resolve().parents[1]
target = root / "dist" / "branchline.pyz"
target.parent.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory() as directory:
    source = Path(directory)
    shutil.copytree(root / "branchline", source / "branchline", ignore=shutil.ignore_patterns("__pycache__"))
    zipapp.create_archive(
        source, target, main="branchline.__main__:main", interpreter="/usr/bin/env python3", compressed=True
    )
print(target)
