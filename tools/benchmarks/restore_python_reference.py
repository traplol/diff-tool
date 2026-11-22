"""Reproduce the original Python benchmark archive from its sources and ZIP metadata."""

import argparse
import hashlib
import io
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = "e7545f67c6460a923cb5cc716095f814afaad90b433422ceb6b272836fec4193"
# Record the entry order and timestamps from the shipped zipapp. Git checkouts
# assign fresh mtimes to files, which change the bytes of a normal zipapp build.
ENTRIES = [
    ("branchline/", 12, 22, 44),
    ("branchline/__init__.py", 10, 12, 18),
    ("branchline/__main__.py", 10, 22, 6),
    ("branchline/app.py", 14, 10, 2),
    ("branchline/diffview.py", 14, 9, 56),
    ("branchline/git.py", 13, 41, 40),
    ("branchline/review.py", 13, 41, 40),
    ("branchline/suggestions.py", 13, 42, 24),
    ("branchline/tracking.py", 13, 41, 40),
    ("branchline/ui.py", 14, 9, 56),
    ("__main__.py", 14, 10, 48),
]


def restore(target):
    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest() != EXPECTED:
            raise ValueError(
                f"Existing {target} differs from the archived Python release."
            )
        return
    data = io.BytesIO()
    data.write(b"#!/usr/bin/env python3\n")
    with zipfile.ZipFile(data, "w") as archive:
        for name, hour, minute, second in ENTRIES:
            info = zipfile.ZipInfo(name, (2026, 11, 21, hour, minute, second))
            info.create_system = 3  # Unix permissions from the reference host
            info.compress_type = zipfile.ZIP_DEFLATED
            if name.endswith("/"):
                info.compress_type = zipfile.ZIP_STORED
                info.external_attr = 0x41FD0010
                content = b""
            elif name == "__main__.py":
                info.external_attr = 0o600 << 16
                content = b"# -*- coding: utf-8 -*-\nimport branchline.__main__\nbranchline.__main__.main()\n"
            else:
                info.external_attr = 0o100664 << 16
                content = (ROOT / name).read_bytes()
            archive.writestr(info, content)
    payload = data.getvalue()
    if hashlib.sha256(payload).hexdigest() != EXPECTED:
        raise ValueError(
            "These Python sources or ZIP encoder produced a different archive."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as out:
        out.write(payload)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output", nargs="?", type=Path, default=ROOT / "dist/branchline.pyz"
    )
    args = parser.parse_args()
    restore(args.output)
    print(f"Verified {args.output} ({EXPECTED})")
