"""Evaluate a candidate against the frozen large-diff layout workload."""

import argparse
import json
import math
import os
import platform
import runpy
import statistics
import subprocess
import sys
from pathlib import Path

CONTROL = Path(__file__).resolve().parent
PREVIOUS = CONTROL.parent / "review-latency"
shared = runpy.run_path(str(PREVIOUS / "score.py"))
PHASES = ("open_ms", "to_split_ms", "to_unified_ms", "repeat_split_ms", "small_ms")


def measurements(path, expected):
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if [row["warmup"] for row in rows] != [True] + [False] * 7:
        raise ValueError("Expected a warmup and seven complete file-open and switch sequences")
    for row in rows:
        if row["fingerprint"] != expected:
            raise ValueError("Rendered text, tags, selection, or inline cards differ from baseline")
        if not all(math.isfinite(row[name]) and row[name] > 0 for name in PHASES):
            raise ValueError("Expected finite positive timings")
    rows = rows[1:]
    totals = [sum(row[name] for name in PHASES[:-1]) for row in rows]
    median = statistics.median(totals)
    return {
        "median_ms": median,
        "mad_ms": statistics.median(abs(t - median) for t in totals),
        "phase_medians_ms": {name: statistics.median(row[name] for row in rows) for name in PHASES},
        "samples_ms": totals,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("run", type=Path)
    parser.add_argument("label")
    args = parser.parse_args()
    source, run = args.source.resolve(), args.run.resolve()
    run.mkdir(parents=True, exist_ok=False)
    verdict = {"label": args.label, "source": str(source), "valid": False}
    package = source / "branchline"
    oracle, workload = CONTROL / "expected.sha256", CONTROL / "workload.py"
    tests = shared["TESTS"]
    env = dict(os.environ, LC_ALL="C.UTF-8", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    try:
        if not (package / "app.py").is_file():
            raise ValueError(f"Missing Branchline source in {source}")
        manifest = shared["manifest"]
        verdict["source_id"] = manifest(package.glob("*.py"))
        verdict["contract_id"] = manifest(
            [
                Path(__file__),
                workload,
                oracle,
                PREVIOUS / "workload.py",
                PREVIOUS / "score.py",
                *tests.glob("*.py"),
            ]
        )
        verdict["environment"] = {
            "python": sys.version,
            "os": platform.platform(),
            "git": subprocess.check_output(["git", "--version"], text=True, env=env).strip(),
            "display": os.environ.get("DISPLAY"),
        }
        with (run / "run.log").open("w") as log:
            for command, timeout in (
                (["-m", "compileall", "-q", str(package)], 20),
                (["-c", shared["TEST_RUNNER"], str(source), str(tests)], 120),
                ([str(workload), str(source), str(run)], 120),
            ):
                subprocess.run(
                    [sys.executable, "-I", *command],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=timeout,
                    check=True,
                    cwd=run,
                    env=env,
                )
        metrics = measurements(run / "samples.jsonl", oracle.read_text().strip())
        if verdict["source_id"] != manifest(package.glob("*.py")):
            raise ValueError("Source changed during evaluation")
        verdict.update(valid=True, metrics=metrics)
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        verdict["error"] = str(exc)
    tmp = run / "verdict.tmp"
    tmp.write_text(json.dumps(verdict, indent=2) + "\n")
    tmp.replace(run / "verdict.json")
    print(json.dumps(verdict))
    return 0 if verdict["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
