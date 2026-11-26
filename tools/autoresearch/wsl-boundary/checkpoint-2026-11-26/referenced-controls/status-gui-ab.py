#!/usr/bin/env python3
"""Prepare locally by default. Run only after the coordinator releases the UI."""
import argparse
from collections import defaultdict
import datetime as dt
import hashlib
import json
from pathlib import Path
import shlex
import statistics
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "build/autoresearch/wsl-boundary"
TOOLS = ROOT / "tools/autoresearch/wsl-boundary"
sys.path.insert(0, str(TOOLS))
import score

CONTRACT = "3db306b466166cb39b8c5a9dc27a9739b16df52fa9f83d32bd6656f226026b04"
HEAD = "b2de070becf3fcba2d47557efd375221c586f273"
PROFILE = "/home/max/benchmarks/branchline-boundary/profiles/candidate-worker-v1-wsl-windows"
CASE = "wsl_windows"
SSH = ["ssh", "-F", str(Path.home() / ".ssh/config"), "-o", "BatchMode=yes",
       "-o", "ConnectTimeout=10", "windows-vm"]
LAUNCHER = TOOLS / "launch_linux.py"


def write_json(path, value):
    score.atomic_json(path, value)


def variants():
    result = {}
    for key, label, stem, expected in [
        ("A", "checkpoint-b2de070", "checkpoint-b2de070",
         "56a8fe492b376ef76bca7c6e17ac1327e0b6c5a805277916aec8fcb4306c7272"),
        ("B", "stateless-status-b2de070", "candidate-stateless-status-b2de070",
         "d5b05d3585f7f04dea63f4f8786c67e253c9337c24793c71c57f707ee36c9bbb"),
    ]:
        build_path = BASE / (stem + "-build.json")
        build = json.loads(build_path.read_text())
        source = BASE / (stem + "-source")
        identity = score.source_identity(source)
        assert identity == build["source"], (key, "source identity differs from build")
        assert identity["source_hash"] == expected and identity["git_head"] == HEAD
        result[key] = {"label": label, "source": str(source), "source_hash": expected,
                       "binary": build["linux_gui"]["path"],
                       "binary_sha256": build["linux_gui"]["sha256"],
                       "build_record": str(build_path),
                       "build_record_sha256": hashlib.sha256(build_path.read_bytes()).hexdigest()}
    assert score.contract_identity()["sha256"] == CONTRACT, "Scoring contract changed"
    score.load_manifest(BASE / "workload.json")
    return result


def plan(versions):
    return {"status": "prepared-only-no-VM-or-port-access", "case": CASE,
            "contract_sha256": CONTRACT, "variants": versions, "profile": PROFILE,
            "existing_profile": "Reuse its two seeded notes; never seed or delete data.",
            "ports": {"driver": 29225, "mcp": 28867, "existing_host_tunnel": 19225},
            "tunnel": "Coordinator retains the existing loopback 19225 -> Windows localhost:29225 SSH forward.",
            "order": ["A1:3", "B1:3", "A2:3", "B2:3", "pilot gate", "A3:20", "B3:20"],
            "pilot_gate": {"all_four_runs_valid": True,
                           "working_tree_pooled_median_candidate_max_ratio": 0.9,
                           "worst_pooled_p95_candidate_max_ratio": 1.1,
                           "failure_action": "Stop for review; no automatic discard or promotion."},
            "measurement": "Canonical scorer, fresh process on completed non-Git welcome error; no warmup or OS cache flushing.",
            "report": "Open and all six actions, first-use/max/p50/p95, raw IPC and background IPC, exact source/binary/process identities.",
            "execution_gate": "Do not pass --ui-released until root sends UI RELEASED."}


def samples_for(run):
    return [json.loads(line) for line in Path(run["samples"]).read_text().splitlines()]


def action_summary(samples):
    result = {}
    for action in ("open", *score.ACTIONS):
        rows = [row for row in samples if row["action"] == action]
        values = [row["elapsed_ms"] for row in rows]
        calls = defaultdict(list)
        background = defaultdict(list)
        for row in rows:
            for field, target in [("ipc", calls), ("background_ipc", background)]:
                for call in row.get(field, []):
                    target[call["command"] + "/" + call.get("op", "")].append(call["elapsed_ms"])
        def stats(vals):
            measured = [value for value in vals if value is not None]
            return {"count": len(vals), "pending_count": len(vals) - len(measured),
                    "median_ms": statistics.median(measured) if measured else None,
                    "p95_ms": score.percentile(measured, .95) if measured else None,
                    "max_ms": max(measured) if measured else None}
        result[action] = {**stats(values), "first_use_ms": [row["elapsed_ms"] for row in rows
                            if row["phase"] in ("fresh_process", "first_use")],
                          "ipc_by_command_and_op": {key: stats(value) for key, value in calls.items()},
                          "background_ipc_by_command_and_op": {key: stats(value) for key, value in background.items()}}
    return result


def pilot_gate(runs):
    summaries = {key: action_summary([sample for run in runs if run["variant"] == key
                                    for sample in samples_for(run)]) for key in ("A", "B")}
    a, b = summaries["A"], summaries["B"]
    wt_ratio = b["working_tree"]["median_ms"] / a["working_tree"]["median_ms"]
    worst_ratio = max(row["p95_ms"] for row in b.values()) / max(row["p95_ms"] for row in a.values())
    return {"pass": wt_ratio <= .9 and worst_ratio <= 1.1,
            "working_tree_median_ratio": wt_ratio, "worst_p95_ratio": worst_ratio,
            "pooled_pilot_actions": summaries,
            "interpretation": "Pilot continuation gate only; final source acceptance still needs the charter gates and matrix."}


def stop_exact(launch, log):
    # Use the frozen canonical cleanup functions with the exact saved identities.
    # Refuse cleanup if another session has replaced this profile's ownership record.
    script = "import json\nnamespace={'__name__':'frozen_campaign_launcher'}\n"
    script += "exec(" + repr(LAUNCHER.read_text()) + ", namespace)\n"
    script += "expected=" + repr(launch) + "\n"
    script += "actual=json.loads((namespace['Path'](expected['profile'])/'app.json').read_text())\n"
    script += "keys=('binary','binary_sha256','source_hash','profile','port','mcp_port','session','app_process','driver_process','supervisor_pid')\n"
    script += "assert all(actual.get(key)==expected.get(key) for key in keys), 'Profile ownership changed; refusing cleanup'\n"
    script += "print(json.dumps({'exact_launch_cleanup':namespace['stop_record'](expected)}),flush=True)\n"
    remote = "MSYS_NO_PATHCONV=1 " + shlex.join([
        "wsl.exe", "-d", "Ubuntu-26.04", "-u", "max", "--exec", "/usr/bin/python3", "-"])
    with log.open("w") as stream:
        subprocess.run([*SSH, remote], input=script, text=True, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=45)


def run_one(key, number, reps, versions, stamp, state, state_path):
    version = versions[key]
    label = f"{version['label']}-wsl-windows-{stamp}-{number:02}"
    run_dir = BASE / label
    record = BASE / ("launch-" + label + ".json")
    log = BASE / ("launch-" + label + ".log")
    assert not record.exists() and not run_dir.exists(), "Refusing stale run artifacts"
    assert score.contract_identity()["sha256"] == CONTRACT, "Contract changed"
    assert score.source_identity(version["source"])["source_hash"] == version["source_hash"]
    start = [sys.executable, str(LAUNCHER), "start", "--binary", version["binary"],
             "--profile", PROFILE, "--port", "29225", "--mcp-port", "28867",
             "--source-hash", version["source_hash"], "--record", str(record)]
    launch = None
    item = {"variant": key, "number": number, "repetitions": reps, "label": label,
            "record": str(record), "run_dir": str(run_dir), "start_command": start,
            "launch_log": str(log), "status": "launching", "started_unix": time.time()}
    state["runs"].append(item)
    with log.open("w") as stream:
        supervisor = subprocess.Popen(start, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
    item["host_supervisor_pid"] = supervisor.pid
    write_json(state_path, state)
    try:
        deadline = time.monotonic() + 45
        while launch is None:
            if record.exists():
                try:
                    launch = json.loads(record.read_text())
                except json.JSONDecodeError:
                    pass
            if launch is not None:
                break
            if supervisor.poll() is not None:
                raise RuntimeError(f"Launcher exited {supervisor.returncode}; inspect {log}")
            if time.monotonic() >= deadline:
                item["status"] = "launch-observation-expired-supervisor-retained"
                raise TimeoutError(f"Inspect existing supervisor {supervisor.pid} and {record}; do not restart")
            time.sleep(.1)
        assert launch["binary"] == version["binary"]
        assert launch["binary_sha256"] == version["binary_sha256"], "Packaged executable changed"
        assert launch["source_hash"] == version["source_hash"] and launch["profile"] == PROFILE
        assert launch["app_process"]["binary"] == version["binary"]
        assert launch["app_process"]["args"] == [version["binary"], PROFILE + "/welcome"]
        launch["created"] = str(launch["app_process"]["start_ticks"])
        write_json(record, launch)
        item.update(status="scoring", launch=launch)
        score_log = BASE / (label + ".stdout.log")
        command = [sys.executable, str(TOOLS / "score.py"), "--source", version["source"],
                   "--run-dir", str(run_dir), "--label", version["label"], "--manifest",
                   str(BASE / "workload.json"), "--case", CASE, "--launch-record", str(record),
                   "--webkit-port", "19225", "--session", launch["session"], "--repetitions", str(reps)]
        item.update(score_command=command, score_log=str(score_log))
        write_json(state_path, state)
        print(json.dumps({"started": label, "host_supervisor": supervisor.pid,
                          "app": launch["app_process"], "driver": launch["driver_process"]}), flush=True)
        with score_log.open("w") as stream:
            result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        verdict_path = run_dir / "verdict.json"
        verdict = json.loads(verdict_path.read_text()) if verdict_path.exists() else {}
        item.update(score_exit=result.returncode, verdict=str(verdict_path),
                    samples=str(run_dir / "samples.jsonl"), actions=verdict.get("actions"))
        assert result.returncode == 0 and verdict.get("valid") is True, (label, verdict.get("error"))
        assert verdict["contract"]["sha256"] == CONTRACT
        assert verdict["source_hash"] == version["source_hash"]
        assert verdict["binary_sha256"] == version["binary_sha256"]
        assert verdict["repetitions"] == reps and verdict["case"] == CASE
        score.validate_samples(samples_for(item), reps)
        item.update(status="valid-awaiting-cleanup", action_and_ipc_summary=action_summary(samples_for(item)))
    finally:
        write_json(state_path, state)
        if launch is not None:
            cleanup = BASE / (label + ".cleanup.log")
            item["cleanup_log"] = str(cleanup)
            stop_exact(launch, cleanup)
            try:
                code = supervisor.wait(timeout=20)
            except subprocess.TimeoutExpired:
                item["status"] = "stop-observation-expired-inspect-same-supervisor"
                write_json(state_path, state)
                raise TimeoutError(f"Inspect supervisor {supervisor.pid}; do not relaunch")
            item["supervisor_exit"] = code
            assert code == 0, ("Supervisor exit", code, log)
            item["cleanup_complete"] = True
        else:
            item["cleanup_complete"] = False
            item["pending_supervisor_pid"] = supervisor.pid
        write_json(state_path, state)
    item.update(status="complete-valid-stopped", finished_unix=time.time())
    write_json(state_path, state)
    print(json.dumps({"completed": label, "actions": item["actions"]}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ui-released", action="store_true",
                        help="Use only after root explicitly sends UI RELEASED")
    args = parser.parse_args()
    versions = variants()
    prepared = plan(versions)
    if not args.ui_released:
        print(json.dumps(prepared, indent=2))
        return 0
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    state_path = BASE / ("status-gui-ab-" + stamp + ".json")
    state = {**prepared, "status": "running", "started_unix": time.time(), "runs": []}
    write_json(state_path, state)
    print(json.dumps({"state": str(state_path), "orchestrator_pid": __import__('os').getpid()}), flush=True)
    try:
        for key, number, reps in [("A", 1, 3), ("B", 1, 3), ("A", 2, 3), ("B", 2, 3)]:
            run_one(key, number, reps, versions, stamp, state, state_path)
        state["pilot_result"] = pilot_gate(state["runs"])
        write_json(state_path, state)
        print(json.dumps({"pilot": state["pilot_result"]}), flush=True)
        if not state["pilot_result"]["pass"]:
            state["status"] = "pilot-inconclusive-review-before-20-repetitions"
            write_json(state_path, state)
            return 3
        for key in ("A", "B"):
            run_one(key, 3, 20, versions, stamp, state, state_path)
        state["final_20_repetition_actions"] = {run["variant"]: run["action_and_ipc_summary"]
                                               for run in state["runs"] if run["number"] == 3}
        state["fresh_process_open_ms"] = {key: [run["actions"]["open"]["first_use_ms"]
                                               for run in state["runs"] if run["variant"] == key]
                                          for key in ("A", "B")}
        state.update(status="complete-valid-awaiting-charter-review", finished_unix=time.time())
        write_json(state_path, state)
        return 0
    except BaseException as error:
        state.update(status="stopped-on-error-no-restart", error=str(error), traceback=traceback.format_exc())
        write_json(state_path, state)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
