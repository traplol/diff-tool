"""Verify v2 run receipts, then apply the hash-pinned v1 sample, environment and output gates."""
import argparse
import json
import runpy
import sys
from pathlib import Path

from prepare import V1, digest, pins


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("radeon", type=Path)
    p.add_argument("xvfb", type=Path)
    p.add_argument("--binary", required=True, type=Path)
    args = p.parse_args()
    try:
        contract = pins()
        paths = (args.radeon, args.xvfb)
        for folder in paths:
            receipt = json.loads((folder / "series.json").read_text())
            if receipt != {"contract":contract,"samples_sha256":digest(folder / "samples.jsonl")}:
                raise ValueError(f"{folder} has an invalid v2 measurement receipt")
        report = runpy.run_path(str(V1 / "score.py"))["score"](paths, args.binary)
        report["v1_contract"] = report["contract"]
        report["contract"] = contract
        print(json.dumps(report, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError, AssertionError) as exc:
        print(json.dumps({"valid_measurement":False, "error":str(exc)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
