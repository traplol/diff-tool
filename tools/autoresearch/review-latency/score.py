"""Score an isolated Branchline source tree on a Linux virtual desktop."""

import argparse
import hashlib
import json
import math
import os
import platform
import statistics
import subprocess
import sys
from pathlib import Path

CONTROL = Path(__file__).resolve().parent
TESTS = CONTROL.parents[2] / "tests"
PHASES = ("tracking_ms", "render_ms", "edit_ms", "small_ms")


def manifest(files):
    digest = hashlib.sha256()
    for path in sorted(files):
        data = path.read_bytes()
        digest.update(path.name.encode() + b"\0" + hashlib.sha256(data).digest())
    return digest.hexdigest()


def measurements(path, expected):
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if [row["warmup"] for row in rows] != [True] + [False] * 7:
        raise ValueError("Expected one warmup and seven completed measurements")
    for row in rows:
        if row["fingerprint"] != expected:
            raise ValueError("Review output differs from the baseline")
        if not all(math.isfinite(row[name]) and row[name] > 0 for name in PHASES):
            raise ValueError("Expected finite positive timings")
    times = [sum(row[name] for name in PHASES[:3]) for row in rows[1:]]
    median = statistics.median(times)
    return {
        "median_ms": median,
        "mad_ms": statistics.median(abs(t - median) for t in times),
        "phase_medians_ms": {name: statistics.median(row[name] for row in rows[1:]) for name in PHASES},
        "samples_ms": times,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("run", type=Path)
    parser.add_argument("label")
    args = parser.parse_args()
    source, run = args.source.resolve(), args.run.resolve()
    run.mkdir(parents=True, exist_ok=False)
    verdict = {"label": args.label, "valid": False, "source": str(source)}
    env = dict(os.environ, LC_ALL="C.UTF-8", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    try:
        package = source / "branchline"
        if not (package / "app.py").is_file():
            raise ValueError(f"Missing Branchline source in {source}")
        verdict["source_id"] = manifest(package.glob("*.py"))
        oracle = CONTROL / "expected.sha256"
        workload = CONTROL / "workload.py"
        verdict["contract_id"] = manifest([Path(__file__), workload, oracle, *TESTS.glob("*.py")])
        verdict["environment"] = {
            "python": sys.version,
            "os": platform.platform(),
            "git": subprocess.check_output(["git", "--version"], text=True, env=env).strip(),
            "display": os.environ.get("DISPLAY"),
        }
        with (run / "run.log").open("w", buffering=1) as log:
            for command, timeout in (
                (["-m", "compileall", "-q", str(package)], 20),
                (["-c", TEST_RUNNER, str(source), str(TESTS)], 120),
                ([str(workload), str(source), str(run)], 120),
            ):
                subprocess.run(
                    [sys.executable, "-I", *command],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=timeout,
                    check=True,
                    env=env,
                    cwd=run,
                )
        metrics = measurements(run / "samples.jsonl", oracle.read_text().strip())
        if manifest(package.glob("*.py")) != verdict["source_id"]:
            raise ValueError("Source changed during evaluation")
        verdict.update(valid=True, metrics=metrics)
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as error:
        verdict["error"] = str(error)
    result = run / "verdict.tmp"
    result.write_text(json.dumps(verdict, indent=2) + "\n")
    result.replace(run / "verdict.json")
    print(json.dumps(verdict))
    return 0 if verdict["valid"] else 1


TEST_RUNNER = """
import sys, unittest
from pathlib import Path
source, tests = sys.argv[1:]
sys.path.insert(0, source)
import branchline
assert Path(branchline.__file__).resolve().parent == Path(source) / 'branchline'
suite = unittest.defaultTestLoader.discover(tests)
result = unittest.TextTestRunner(verbosity=1).run(suite)
assert result.wasSuccessful() and result.testsRun == 78
assert len(result.skipped) == 1 and 'NTFS' in result.skipped[0][1], result.skipped
"""


if __name__ == "__main__":
    sys.exit(main())
