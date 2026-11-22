"""Benchmark the CPU work of decoding a diff and building its first unified and split rows."""

import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from time import perf_counter_ns

from python_layout import ROOT, git, prepare

FIXTURES = {
    "4k-annotated": "5ee43492b09841da2068458edbb7a8a0bf3f72c8ca515a12aa1131e25fa5802f",
    "40k-mixed": "49e3e567ff523a338795cc0a9cfee3474141a6ce2c35e0c344f39467e8ff0ca6",
}


def digest(value):
    data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def measure(operation, warmups, iterations):
    samples = []
    for index in range(warmups + iterations):
        start = perf_counter_ns()
        rows = operation()
        elapsed = (perf_counter_ns() - start) / 1_000_000
        if not rows:
            raise ValueError("Expected a nonempty fixture")
        del rows
        if index >= warmups:
            samples.append(elapsed)
    return samples


def run_fixture(work, name, worker, warmups, iterations):
    checkout, _ = prepare(work / name, name == "40k-mixed")
    repo = git.open_repo(checkout)
    comparison = git.compare(repo, "refs/heads/main", repo.checkout)
    patch = git.diff_patch(repo, comparison.base, comparison.head, "--", "policy.py")
    # Both production parsers receive a frozen file section with its Git prefix removed.
    if not patch.startswith(b"diff --git "):
        raise ValueError(f"{name} is missing the Git section header")
    section = patch.removeprefix(b"diff --git ")
    checksum = hashlib.sha256(section).hexdigest()
    if checksum != FIXTURES[name]:
        raise ValueError(f"{name} input changed: expected {FIXTURES[name]}, got {checksum}")
    output = subprocess.check_output([worker, str(warmups), str(iterations)], input=section)
    durations, starts, text = output.split(b"\n", 2)
    payload = [text.decode("utf-8"), json.loads(starts)]

    # The working-tree parser accepts an already resident Git section.
    change = next(f for f in comparison.files if f.path == "policy.py")
    resident = replace(change, group="Staged", local_sections=(section,))

    def parse():
        return git.patch(repo, comparison, resident)

    samples = {
        "rust_encode": [ns / 1_000_000 for ns in json.loads(durations)],
        "python_parse": measure(parse, warmups, iterations),
    }
    lines = parse()

    # DiffView.__init__ wraps each line in a singleton tuple for its unified view.
    def unified():
        return [(line,) for line in lines]

    samples["python_unified_rows"] = measure(unified, warmups, iterations)
    samples["python_split_rows"] = measure(lambda: git.split_rows(lines), warmups, iterations)
    js = json.loads(subprocess.check_output(
        ["node", Path(__file__).with_suffix(".js")],
        input=json.dumps({"payload": payload, "warmups": warmups, "iterations": iterations}).encode(),
    ))
    samples.update(js["timings"])

    # Normalize references and empty split cells to the port's source-row indices.
    indices = {id(line): i for i, line in enumerate(lines)}
    split = git.split_rows(lines)
    hashes = {
        "lines": digest([[line.kind, line.text, line.old, line.new, line.hunk] for line in lines]),
        "unified_rows": digest([[indices[id(line)]] for (line,) in unified()]),
        "split_rows": digest([
            [indices[id(line)] if line is not None else -1 for line in row]
            for row in split
        ]),
    }
    if hashes != js["hashes"]:
        raise ValueError(f"{name} source lines or layout cells disagree: Python={hashes}, port={js['hashes']}")
    return {
        "input_bytes": len(section),
        "input_sha256": checksum,
        "unified_rows": len(lines),
        "split_rows": len(split),
        "verified_sha256": hashes,
        "phases": {
            phase: {
                "median_ms": round(statistics.median(values), 6),
                "samples_ms": [round(v, 6) for v in values],
            }
            for phase, values in samples.items()
        },
    }, {"node": js["node"], "v8": js["v8"]}


def cpu_model():
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        for line in cpuinfo.read_text().splitlines():
            if line.startswith("model name"):
                return line.partition(":")[2].strip()
    return platform.processor() or platform.machine()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--warmups", type=int, default=5, help="Discarded calls per phase")
    parser.add_argument("--iterations", type=int, default=31, help="Measured calls per phase")
    parser.add_argument("--output", type=Path, help="Write the JSON report to this file (default: stdout)")
    args = parser.parse_args()
    if args.warmups < 0 or args.iterations < 1:
        parser.error("Use at least zero warmups and one measured iteration.")

    os.environ.update(
        GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_COUNT="0", GIT_ATTR_NOSYSTEM="1",
    )
    environment = {
        "platform": platform.platform(), "cpu": cpu_model(), "python": sys.version.split()[0],
        "rustc": subprocess.check_output(["rustc", "--version"], text=True).strip(),
        "git": subprocess.check_output(["git", "--version"], text=True).strip(),
    }
    sources = (
        "src-tauri/src/git/patch_data.rs", "frontend/review-ui.js", "frontend/editor.js",
        "branchline/git.py", "branchline/diffview.py", "tools/benchmarks/cpu_layout.py",
        "tools/benchmarks/cpu_layout.js", "tools/benchmarks/cpu_patch.rs",
    )
    fixtures = {}
    with tempfile.TemporaryDirectory(prefix="branchline-cpu-") as tmp:
        work = Path(tmp)
        worker = work / ("cpu_patch.exe" if os.name == "nt" else "cpu_patch")
        subprocess.run(
            ["rustc", "--edition=2021", "-O", Path(__file__).with_name("cpu_patch.rs"), "-o", worker],
            check=True,
        )
        for name in FIXTURES:
            fixtures[name], versions = run_fixture(work, name, worker, args.warmups, args.iterations)
            environment.update(versions)
    result = {
        "method": (
            "Sequential monotonic elapsed milliseconds per in-memory operation. "
            "Git, IPC, fixture setup, validation, and graphics are outside the timings. "
            "JavaScript uses Node/V8."
        ),
        "warmups_per_phase": args.warmups, "samples_per_phase": args.iterations,
        "environment": environment, "fixtures": fixtures,
        "source_sha256": {
            path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in sources
        },
    }
    output = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)


if __name__ == "__main__":
    main()
