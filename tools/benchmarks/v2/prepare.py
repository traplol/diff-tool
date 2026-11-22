"""Build the separate v2 runner from the pinned v1 sources and a small unified diff."""
import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "tools/autoresearch/rust-layout/pins.sha256").is_file())
V1 = ROOT / "tools" / "autoresearch" / "rust-layout"
BENCH = ROOT / "tools" / "benchmarks"
NAMES = ("compare_layouts.py", "gpu_display.py", "native_layout.py", "native_layout_probe.js", "smoke_native.py")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pins():
    for manifest, base in [(V1 / "pins.sha256", ROOT), (HERE / "pins.sha256", HERE)]:
        for line in manifest.read_text().splitlines():
            expected, name = line.split("  ", 1)
            if digest(base / name) != expected:
                raise ValueError(f"Changed scoring input {name}")
    return digest(HERE / "pins.sha256")


def prepare():
    pins()
    target = HERE / "generated"
    target.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target) as tmp:
        directory = Path(tmp)
        for name in NAMES:
            source = ROOT / "tools" / name if name == "smoke_native.py" else BENCH / name
            shutil.copyfile(source, directory / name)
        subprocess.run(["patch", "--batch", "--fuzz=0", "-s", "-p0", "-i", HERE/"v2.patch"],
                       cwd=directory, check=True)
        for name in NAMES:
            (directory / name).replace(target / name)
    return target


if __name__ == "__main__":
    print(prepare())


def verify_generated():
    contract = pins()
    for line in (HERE / "generated.sha256").read_text().splitlines():
        expected, name = line.split("  ", 1)
        if digest(HERE / "generated" / name) != expected:
            raise ValueError(f"Changed generated scoring input {name}")
    return contract
