#!/usr/bin/env python3
"""Second diagnostic: unchanged UI probe plus an external bounded CPU sampler."""
import argparse
import base64
import importlib.util
import json
from pathlib import Path
import shlex
import subprocess
import time

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("original_ui_runner", HERE / "run.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
RELEASE = "VM UI CPU DIAGNOSTIC RELEASED"
samplers = []


class CpuDiagnosticRun(base.DiagnosticRun):
    def open(self, measured):
        # The only additional browser reads are clocks in the existing install call.
        base.score.Run.open(self, measured)
        info = self.driver.evaluate((HERE / "inject.js").read_text() + """
            return {...window.branchlineUiPhaseProbe.info(), clock:{
                time_origin_ms:performance.timeOrigin,
                performance_ms:performance.now(), wall_ms:Date.now()}};
        """)
        self.installed = True
        base.score.atomic_json(self.output / "probe-installed.json", info)
        launch = json.loads((self.output / "launch.json").read_text())
        root = {key: launch["app_process"][key] for key in ("pid", "start_ticks", "binary")}
        payload = base64.b64encode(json.dumps(root).encode()).decode()
        command = "MSYS_NO_PATHCONV=1 " + shlex.join([
            "wsl.exe", "-d", "Ubuntu-26.04", "-u", "max", "--exec", "/usr/bin/python3", "-u", "-", payload])
        path = self.output / "cpu-sampler.jsonl"
        with path.open("w") as log:
            process = subprocess.Popen([*base.SSH, "windows-vm", command], stdin=subprocess.PIPE,
                                       stdout=log, stderr=subprocess.STDOUT, text=True)
        samplers.append((process, path))
        process.stdin.write((HERE / "cpu-sampler.py").read_text())
        process.stdin.close()
        deadline = time.monotonic() + 15
        while True:
            with path.open() as stream: first = stream.readline()
            if first:
                header = json.loads(first)
                if header.get("kind") != "ready" or header.get("root") != root:
                    raise RuntimeError("CPU observer did not verify the exact GUI identity")
                base.score.atomic_json(self.output / "cpu-observer.json", {
                    "host_controller_pid": process.pid, "ready": header})
                break
            if process.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError("CPU observer startup expired; inspect the same controller and log")
            time.sleep(.05)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", choices=[RELEASE])
    args = parser.parse_args()
    plan = base.prepare()
    plan.update(execution_gate=RELEASE, status="prepared-host-only-awaiting-cpu-diagnostic-release",
                original_run=str(HERE / "run-20261125T213031571855Z"),
                cpu_sampler={"target_period_ms": 20, "max_seconds": 60, "max_processes": 64,
                             "scope": "Exact recorded GUI and recursively discovered children only",
                             "fields": "Process CPU ticks/state and WebKit main-thread CPU ticks/state",
                             "clock_alignment": "Guest wall_ns to browser timeOrigin+performance.now; clock pair retained",
                             "limitations": "No outside-tree GPU/compositor coverage; short-lived children can be missed; observer overhead retained"})
    for path in [Path(__file__), HERE / "cpu-sampler.py"]:
        plan["files_sha256"][str(path.relative_to(base.ROOT))] = base.sha(path)
    if not args.release:
        base.score.atomic_json(HERE / "prepared-cpu.json", plan)
        print(json.dumps(plan, indent=2))
        return
    base.DiagnosticRun = CpuDiagnosticRun
    try:
        base.execute(plan)
    finally:
        for process, path in samplers:
            result = {"host_controller_pid": process.pid}
            try:
                result["exit_code"] = process.wait(timeout=10)
                last = None
                with path.open() as stream:
                    for line in stream:
                        if line.strip(): last = line
                result["finished"] = json.loads(last) if last else None
                base.score.atomic_json(path.parent / "cpu-sampler-finished.json", result)
                assert result["exit_code"] == 0 and result["finished"]["reason"] == "root_gone", result
            except BaseException as error:
                result["error"] = str(error)
                base.score.atomic_json(path.parent / "cpu-sampler-finished.json", result)
                raise


if __name__ == "__main__":
    main()
