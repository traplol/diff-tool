"""Validate and score the two completed large-diff benchmark runs."""

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BENCH = ROOT / "tools" / "benchmarks"
FIXTURES = ("4k-annotated", "40k-mixed")
BUILDS = ("rust", "python")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def score(paths, binary):
    pins = HERE / "pins.sha256"
    for line in pins.read_text().splitlines():
        expected, name = line.split("  ", 1)
        if digest(ROOT / name) != expected:
            raise ValueError(f"Changed scoring input {name}")
    sys.path.insert(0, str(BENCH))
    from compare_layouts import PHASES, summarize

    oracle = {}
    for row in read_rows(BENCH / "results" / "pane-reuse-radeon.jsonl"):
        field = "checks" if row["build"] == "rust" else "fingerprint"
        oracle[row["fixture"], row["build"]] = row[field]
    environment = json.loads((HERE / "environment.json").read_text())
    environment["native_binary_sha256"] = digest(binary)
    expected = {(f, b, i) for f in FIXTURES for b in BUILDS for i in range(10)}
    metrics = {}
    seen_files = set()
    for display, path in zip(("radeon", "xvfb"), paths, strict=True):
        if json.loads((path / "environment.json").read_text()) != environment:
            raise ValueError(f"{display}: unexpected binary, control or environment")
        sample_path = path / "samples.jsonl"
        sample_hash = digest(sample_path)
        if sample_hash in seen_files:
            raise ValueError("Both displays supplied the same samples")
        seen_files.add(sample_hash)
        rows = read_rows(sample_path)
        keys = {(r["fixture"], r["build"], r["pair"]) for r in rows}
        if keys != expected or len(rows) != len(expected):
            raise ValueError(f"{display}: missing, duplicate or unexpected samples")
        for r in rows:
            if r["warmup"] is not (r["pair"] == 0):
                raise ValueError(f"{display}: wrong warmup")
            field = "checks" if r["build"] == "rust" else "fingerprint"
            if r[field] != oracle[r["fixture"], r["build"]]:
                raise ValueError(f"{display}: incorrect {r['fixture']} {field}")
            for phase in PHASES:
                for value in (r[phase], r["gap_ms"][phase]):
                    if not math.isfinite(value) or value <= 0:
                        raise ValueError(f"{display}: invalid {phase}")
        summary = summarize(rows)
        if json.loads((path / "summary.json").read_text()) != summary:
            raise ValueError(f"{display}: summary does not match samples")
        for fixture, result in summary.items():
            for phase in (*PHASES, "sequence_ms"):
                name = f"{display}/{fixture}/{phase}"
                metrics[name] = {
                    "rust_ms": result["rust"][phase]["median_ms"],
                    "python_ms": result["python"][phase]["median_ms"],
                    "faster_pairs": result["paired"][phase]["rust_faster_pairs"],
                }
    ratios = [v["rust_ms"] / v["python_ms"] for v in metrics.values()]
    wins = sum(ratio < 1 for ratio in ratios)
    return {
        "valid_measurement": True,
        "contract": digest(pins),
        "binary_sha256": environment["native_binary_sha256"],
        "wins": wins,
        "total": len(ratios),
        "all_faster": wins == len(ratios),
        "worst_ratio": round(max(ratios), 4),
        "metrics": metrics,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("radeon", type=Path)
    parser.add_argument("xvfb", type=Path)
    parser.add_argument("--binary", required=True, type=Path)
    args = parser.parse_args()
    try:
        verdict = score((args.radeon, args.xvfb), args.binary)
    except (OSError, ValueError, KeyError, TypeError, AssertionError) as exc:
        print(json.dumps({"valid_measurement": False, "error": str(exc)}))
        sys.exit(1)
    print(json.dumps(verdict, indent=2))
