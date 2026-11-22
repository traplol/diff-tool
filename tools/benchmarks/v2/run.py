"""Run an independently materialized v2 scorer, display wrapper, or packaged smoke test."""
import subprocess
import sys

from prepare import prepare, verify_generated

entry = {"xvfb": "compare_layouts.py", "radeon": "gpu_display.py", "smoke": "smoke_native.py"}
if len(sys.argv) < 2 or sys.argv[1] not in entry:
    sys.exit("Usage: run.py {radeon|xvfb|smoke} [original options]")
target = prepare()
verify_generated()
sys.exit(subprocess.call([sys.executable, target / entry[sys.argv[1]], *sys.argv[2:]]))
