"""Compare the two packaged Branchline desktop implementations on the same display."""

import argparse
import hashlib
import json
import math
import os
import platform
import shutil
import statistics
import subprocess
import sys
import zipfile
from pathlib import Path

from native_layout import sample as native_sample
from python_layout import prepare
from python_layout import sample as python_sample

ROOT = Path(__file__).resolve().parents[2]
PHASES = ("open_ms", "to_split_ms", "to_unified_ms", "repeat_split_ms")


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def provenance(binary, driver):
    # The Tk driver uses the live widget tree. Verify that the code it imports
    # matches the legacy package shipped alongside the native executable.
    archive = ROOT / "dist" / "branchline.pyz"
    with zipfile.ZipFile(archive) as package:
        for module in sorted((ROOT / "branchline").glob("*.py")):
            if package.read("branchline/" + module.name) != module.read_bytes():
                raise RuntimeError(f"The packaged Python module differs from {module}")
    import tkinter

    tk = tkinter.Tk()
    tk_version = tk.tk.call("package", "present", "Tk")
    tk.destroy()
    return {
        "native_binary_sha256": digest(binary),
        "python_package_sha256": digest(archive),
        "webdriver_sha256": digest(driver),
        "python": sys.version.split()[0],
        "tk": tk_version,
        "kernel": platform.release(),
        "cpu": next(
            (
                line.split(":", 1)[1].strip()
                for line in Path("/proc/cpuinfo").read_text().splitlines()
                if line.startswith("model name")
            ),
            "",
        ),
        "git": subprocess.check_output(["git", "--version"], text=True).strip(),
        "display": subprocess.check_output(["xdpyinfo"], text=True)
        .split("dimensions:", 1)[1]
        .splitlines()[0]
        .strip(),
    }


def summarize(rows):
    stats = {}
    measured = [
        dict(r, sequence_ms=sum(r[k] for k in PHASES)) for r in rows if not r["warmup"]
    ]
    for fixture in sorted({r["fixture"] for r in measured}):
        group = {}
        for build in ("python", "rust"):
            group[build] = {
                r["pair"]: r
                for r in measured
                if r["build"] == build and r["fixture"] == fixture
            }
        assert group["python"].keys() == group["rust"].keys()
        result = {"rust": {}, "python": {}, "paired": {}}
        for phase in (*PHASES, "sequence_ms"):
            for build, samples in group.items():
                values = [r[phase] for r in samples.values()]
                result[build][phase] = {
                    "median_ms": round(statistics.median(values), 2),
                    "min_ms": round(min(values), 2),
                    "max_ms": round(max(values), 2),
                }
            differences = [
                group["rust"][i][phase] - group["python"][i][phase]
                for i in group["python"]
            ]
            result["paired"][phase] = {
                "median_rust_minus_python_ms": round(statistics.median(differences), 2),
                "rust_faster_pairs": sum(d < 0 for d in differences),
                "pairs": len(differences),
            }
        stats[fixture] = result
    return stats


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "output",
        type=Path,
        help="New directory for disposable repositories, sample data and the summary",
    )
    p.add_argument("--binary", type=Path, default=ROOT / "dist/linux/branchline")
    p.add_argument(
        "--driver",
        type=Path,
        default=shutil.which("WebKitWebDriver")
        or ROOT / "build/linux-dev/root/usr/bin/WebKitWebDriver",
    )
    p.add_argument(
        "--iterations",
        type=int,
        default=9,
        help="Measured pairs per fixture, after one warmup pair",
    )
    args = p.parse_args()
    if args.iterations < 1:
        p.error("--iterations must be positive")
    output, binary, driver = (
        args.output.resolve(),
        args.binary.resolve(),
        args.driver.resolve(),
    )
    output.mkdir(parents=True, exist_ok=False)
    os.environ.update(
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_COUNT="0",
        GDK_BACKEND="x11",
        GDK_SCALE="1",
        LC_ALL="C.UTF-8",
    )
    environment = provenance(binary, driver)
    if shutil.which("dpkg-query"):
        version = subprocess.run(
            ["dpkg-query", "-W", "-f=${Version}", "libwebkit2gtk-4.1-0"],
            capture_output=True,
            text=True,
            check=False,
        )
        if version.returncode == 0:
            environment["webkit_runtime_package"] = version.stdout
    print(json.dumps(environment), flush=True)
    (output / "environment.json").write_text(json.dumps(environment, indent=2) + "\n")
    fixtures = {
        name: prepare(output / name, large)
        for name, large in [("4k-annotated", False), ("40k-mixed", True)]
    }
    rows = []
    with (output / "samples.jsonl").open("x") as stream:
        for iteration in range(args.iterations + 1):
            for i, (name, (repo, data_home)) in enumerate(fixtures.items()):
                large = name == "40k-mixed"
                order = (
                    ["python", "rust"]
                    if (iteration + i) % 2 == 0
                    else ["rust", "python"]
                )
                for build in order:
                    print(f"Pair {iteration:02} {name} {build}", flush=True)
                    row = (
                        python_sample(repo, data_home, large)
                        if build == "python"
                        else native_sample(driver, binary, repo, data_home, large)
                    )
                    if not all(
                        v > 0 and math.isfinite(v)
                        for k in PHASES
                        for v in (row[k], row["gap_ms"][k])
                    ):
                        raise RuntimeError(f"Invalid timing sample {row}")
                    row.update(
                        fixture=name, build=build, pair=iteration, warmup=iteration == 0
                    )
                    rows.append(row)
                    print(json.dumps(row), file=stream, flush=True)
    summary = summarize(rows)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
