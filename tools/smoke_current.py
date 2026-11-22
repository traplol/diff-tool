"""Run the packaged Linux smoke test against the visible, interactive diff panes."""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    tools = Path(__file__).resolve().parent
    v2 = tools / "benchmarks" / "v2"
    with tempfile.TemporaryDirectory(prefix="branchline-smoke-driver-") as tmp:
        root = Path(tmp)
        generated = root / "generated"
        generated.mkdir()
        script = generated / "smoke_native.py"
        shutil.copyfile(tools / script.name, script)
        shutil.copyfile(v2 / "active_surface.js", root / "active_surface.js")
        # Apply only the desktop workflow from the frozen benchmark extension.
        subprocess.run(
            ["git", "apply", "-p0", "--include=smoke_native.py", str(v2 / "v2.patch")],
            cwd=generated,
            env=dict(os.environ, GIT_CEILING_DIRECTORIES=tmp),
            check=True,
        )
        manifest = (v2 / "generated.sha256").read_text().splitlines()
        checksum = hashlib.sha256(script.read_bytes()).hexdigest()
        if f"{checksum}  {script.name}" not in manifest:
            raise ValueError(
                "The generated smoke test differs from the verified workflow."
            )
        return subprocess.call([sys.executable, script, *sys.argv[1:]])


if __name__ == "__main__":
    sys.exit(main())
