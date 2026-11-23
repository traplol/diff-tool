"""Run the historical visible-pane benchmark from its pinned source revision."""

import io
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_REVISION = "333f870b3691d41420ec82eb2421b406895af4dc"


def main():
    try:
        source = subprocess.check_output(
            ["git", "archive", "--format=zip", BENCHMARK_REVISION],
            cwd=ROOT,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as error:
        sys.exit(
            f"Cannot archive benchmark revision {BENCHMARK_REVISION}. "
            "Use a Git checkout containing that revision.\n"
            + error.stderr.decode(errors="replace").strip()
        )

    # The frozen scorer verifies the original tests, Python package, and drivers.
    # Materialize them together so changes to the live app cannot alter its contract.
    with tempfile.TemporaryDirectory(prefix="branchline-layout-reference-") as tmp:
        root = Path(tmp)
        with zipfile.ZipFile(io.BytesIO(source)) as archive:
            archive.extractall(root)
        # The historical CLI finds local binaries relative to its source tree.
        for name in ("dist/linux/branchline", "build/linux-dev/root/usr/bin/WebKitWebDriver"):
            local_default = root / name
            local_default.parent.mkdir(parents=True, exist_ok=True)
            local_default.symlink_to(ROOT / name)
        runner = root / "tools" / "benchmarks" / "current.py"
        return subprocess.call([sys.executable, runner, *sys.argv[1:]])


if __name__ == "__main__":
    sys.exit(main())
