#!/usr/bin/env python3
"""One repeated branch-final action; exact WebKit thread attribution, no renderer change."""
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
RELEASE = "VM UI THREAD DIAGNOSTIC RELEASED"
samplers = []


class ThreadRun(base.DiagnosticRun):
    def open(self, measured):
        base.score.Run.open(self, measured)
        info = self.driver.evaluate((HERE / "inject.js").read_text() + """
            return {...window.branchlineUiPhaseProbe.info(), clock:{
                time_origin_ms:performance.timeOrigin,
                performance_ms:performance.now(), wall_ms:Date.now()}};
        """)
        self.installed = True
        base.score.atomic_json(self.output / "probe-installed.json", info)

    def score(self):
        self.open(True)
        self.notes()  # Validate the existing fixture comments without native reads.
        # Establish the first visit, then return to branch-first before the one repeat.
        self.select_pair(1, self.expected("branch_first"))
        self.select_pair(2, self.expected("branch_final"))
        self.select_pair(1, self.expected("branch_first"))
        launch = json.loads((self.output / "launch.json").read_text())
        root = {key: launch["app_process"][key] for key in ("pid", "start_ticks", "binary")}
        payload = base64.b64encode(json.dumps(root).encode()).decode()
        command = "MSYS_NO_PATHCONV=1 " + shlex.join([
            "wsl.exe", "-d", "Ubuntu-26.04", "-u", "max", "--exec", "/usr/bin/python3", "-u", "-", payload])
        path = self.output / "thread-sampler.jsonl"
        with path.open("w") as log:
            process = subprocess.Popen([*base.SSH, "windows-vm", command], stdin=subprocess.PIPE,
                                       stdout=log, stderr=subprocess.STDOUT, text=True)
        samplers.append((process, path))
        process.stdin.write((HERE / "thread-sampler.py").read_text())
        process.stdin.close()
        deadline = time.monotonic() + 15
        while True:
            with path.open() as stream: first = stream.readline()
            if first:
                header = json.loads(first)
                if header.get("kind") != "ready" or header.get("root") != root:
                    raise RuntimeError("Thread observer did not verify exact identities")
                base.score.atomic_json(self.output / "thread-observer.json", {
                    "host_controller_pid": process.pid, "ready": header})
                break
            if process.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError("Thread observer startup expired; inspect the same controller and log")
            time.sleep(.05)
        self.measure("branch_final", 1, "#pair", self.expected("branch_final"), value=2)
        return {"diagnostic_only": True, "measured_repeated_branch_final_actions": 1,
                "canonical_completions": self.samples, "no_comparative_score": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", choices=[RELEASE])
    args = parser.parse_args()
    plan = base.prepare()
    plan.update(execution_gate=RELEASE, status="prepared-host-only-awaiting-thread-diagnostic-release",
                repetitions=1, actions_per_repetition=["branch_final"],
                setup="Canonical Open, first branch-first/final visits, return to branch-first; these setup transitions are not profiled",
                sampler={"scope": "One exact WebKitWebProcess discovered once under the exact GUI",
                         "target_period_ms": 20, "max_seconds": 60, "max_threads": 256,
                         "fields": "Only this process's per-thread names/start_ticks/CPU ticks/state",
                         "libraries": "Once-only graphics library paths from this exact process; presence does not prove use"})
    for path in [Path(__file__), HERE / "thread-sampler.py"]:
        plan["files_sha256"][str(path.relative_to(base.ROOT))] = base.sha(path)
    if not args.release:
        base.score.atomic_json(HERE / "prepared-thread.json", plan)
        print(json.dumps(plan, indent=2))
        return
    base.DiagnosticRun = ThreadRun
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
                base.score.atomic_json(path.parent / "thread-sampler-finished.json", result)
                assert result["exit_code"] == 0 and result["finished"]["reason"] in (
                    "root_gone", "root_identity_changed", "webkit_gone", "webkit_identity_changed"), result
            except BaseException as error:
                result["error"] = str(error)
                base.score.atomic_json(path.parent / "thread-sampler-finished.json", result)
                raise


if __name__ == "__main__":
    main()
