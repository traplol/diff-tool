"""Serial, backend-only sparse-index experiment. Run inside the fixture WSL distro."""

import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import selectors
import statistics
import subprocess
import time


def sha(data):
    return hashlib.sha256(data).hexdigest()


class Worker:
    def __init__(self, binary, label, output, records, cwd=None, env=None):
        self.label, self.records, self.sequence, self.pending = label, records, 0, b""
        self.stderr = (output / (label + ".stderr")).open("wb")
        self.started = time.perf_counter_ns()
        self.process = subprocess.Popen([str(binary), "--stdio"], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=self.stderr, cwd=cwd, env=env)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)

    def call(self, phase, op, iteration=0, **arguments):
        self.sequence += 1
        request = dict(id=self.sequence, op=op, **arguments)
        encoded = json.dumps(request, separators=(",", ":")).encode() + b"\n"
        start = time.perf_counter_ns()
        self.process.stdin.write(encoded)
        self.process.stdin.flush()
        deadline = time.monotonic() + 120
        while b"\n" not in self.pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self.selector.select(remaining):
                raise TimeoutError(f"{self.label}: {phase} exceeded 120 seconds")
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError(f"{self.label}: worker exited during {phase}")
            self.pending += chunk
        line, self.pending = self.pending.split(b"\n", 1)
        end = time.perf_counter_ns()
        response = json.loads(line)
        if response.get("id") != self.sequence or "error" in response:
            raise RuntimeError(f"{self.label}: invalid response {response}")
        self.records.append(dict(variant=self.label, phase=phase, op=op, iteration=iteration,
                                 start_ns=start, end_ns=end, elapsed_ns=end - start,
                                 request_bytes=len(encoded), response_bytes=len(line) + 1,
                                 response_sha256=sha(line)))
        return response["result"]

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.selector.close()
        self.stderr.close()


def header(comparison):
    return {key: value for key, value in comparison.items() if key != "files"}


def identity(file):
    return file.get("group", ""), file["path"]


def stable(value):
    return sha(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def comparison_metadata(comparison):
    return dict(header(comparison), files=sorted(
        [{key: value for key, value in file.items() if key != "local_sections"}
         for file in comparison["files"]], key=identity))


def run(parameters):
    output = Path(parameters["output"])
    manifest = json.loads(Path(parameters["manifest"]).read_text())
    root = Path(manifest["paths"]["wsl_linux"])
    if str(root) != "/home/max/benchmarks/branchline-boundary/kernel-wsl":
        raise RuntimeError("This experiment only supports the owned kernel WSL fixture")
    repetitions = parameters.get("repetitions", 10)
    if repetitions < 10:
        raise ValueError("At least ten repetitions are required")
    expected = {(group, path): info for group, files in manifest["local"].items()
                for path, info in files.items()}
    if len(expected) != 15:
        raise RuntimeError("Expected the canonical fifteen working-tree entries")
    spec = importlib.util.spec_from_file_location("workload", output / "workload.py")
    workload = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(workload)
    workload.ENV.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="diff.autoRefreshIndex",
                        GIT_CONFIG_VALUE_0="false")
    index = root / ".git/index"

    def index_state():
        stat = index.stat()
        return dict(sha256=sha(index.read_bytes()), bytes=stat.st_size,
                    mtime_ns=stat.st_mtime_ns, inode=stat.st_ino)

    before = index_state()
    fingerprint = workload.fingerprint(root)
    if fingerprint != manifest["git_state_sha256"]:
        raise RuntimeError("Kernel fixture does not match its frozen workload manifest")
    records, variants = [], {}
    results = dict(schema_version=1, scope="backend IPC only; no GUI latency verdict",
                   clock="WSL perf_counter_ns; encoded request write through complete response line",
                   repetitions=repetitions, fixture=str(root), index_before=before,
                   fixture_fingerprint=fingerprint, variants=variants, raw=records)
    try:
        for label, binary in parameters["workers"]:
            worker = Worker(Path(binary), label, output, records)
            try:
                hello = worker.call("cold_hello", "hello")
                if hello.get("protocol") != 1 or hello.get("os") != "linux":
                    raise RuntimeError(f"Unexpected worker Hello: {hello}")
                end = records[-1]["end_ns"]
                records.append(dict(variant=label, phase="launch_plus_hello", iteration=0,
                                    start_ns=worker.started, end_ns=end, elapsed_ns=end - worker.started))
                initial = worker.call("cold_open", "open", path=str(root))
                view = initial["repo"]
                arguments = dict(view=view, left=manifest["refs"][0], right=manifest["refs"][-1])
                branch = worker.call("cold_compare", "compare", **arguments)
                if len(branch["files"]) != 30:
                    raise RuntimeError("Branch comparison did not return thirty files")
                branch_hash = stable(branch)
                tree_hash = None
                patch_hashes, contents_hashes, patch_rows = {}, {}, {}
                for iteration in range(repetitions):
                    tree = worker.call("working_tree", "working_tree", iteration,
                                       view=view, checkout=manifest["refs"][-1], untracked_paths=None)
                    files = {identity(file): file for file in tree["files"]}
                    if set(files) != set(expected) or len(tree["files"]) != 15:
                        raise RuntimeError(f"Incorrect working-tree entries: {sorted(files)}")
                    current_hash = stable(tree)
                    if tree_hash is not None and tree_hash != current_hash:
                        raise RuntimeError("Working-tree snapshots changed between repetitions")
                    tree_hash = current_hash
                    if iteration == 0:
                        for key, info in expected.items():
                            file = files[key]
                            patch = worker.call("validate_patch", "patch", comparison=header(tree), file=file)
                            if not any(info["marker"] in row["text"] and row.get("new") == info["line"]
                                       for row in patch):
                                raise RuntimeError(f"Missing new-side marker for {key}")
                            patch_hashes["/".join(key)] = stable(patch)
                            patch_rows["/".join(key)] = patch
                            contents = worker.call("validate_contents", "file_contents", file=file)
                            if info["marker"] not in contents[info["line"] - 1]:
                                raise RuntimeError(f"Missing full-file marker for {key}")
                            contents_hashes["/".join(key)] = stable(contents)
                for iteration in range(repetitions):
                    comparison = worker.call("warm_compare", "compare", iteration, **arguments)
                    if stable(comparison) != branch_hash:
                        raise RuntimeError("Warm branch comparison changed")
                for iteration in range(repetitions):
                    first_record = len(records)
                    opened = worker.call("refresh_open", "open", iteration, path=str(root))
                    refreshed = dict(arguments, view=opened["repo"])
                    comparison = worker.call("after_refresh_compare", "compare", iteration, **refreshed)
                    if stable(comparison) != branch_hash:
                        raise RuntimeError("Branch comparison changed after Open refresh")
                    start, end = records[first_record]["start_ns"], records[-1]["end_ns"]
                    records.append(dict(variant=label, phase="refresh_open_plus_compare", iteration=iteration,
                                        start_ns=start, end_ns=end, elapsed_ns=end - start))
                variants[label] = dict(binary=str(binary), binary_sha256=sha(Path(binary).read_bytes()),
                                       hello=hello, branch_sha256=branch_hash, working_tree_sha256=tree_hash,
                                       working_tree_metadata_sha256=stable(comparison_metadata(tree)),
                                       patch_hashes=patch_hashes, contents_hashes=contents_hashes,
                                       patch_rows=patch_rows,
                                       correct_working_tree_entries=15, marker_and_contents_checks=30)
            finally:
                worker.close()
        if len({v["branch_sha256"] for v in variants.values()}) != 1:
            raise RuntimeError("Variants disagree on branch comparison")
        for key in ["working_tree_metadata_sha256", "patch_hashes", "contents_hashes"]:
            if len({stable(v[key]) for v in variants.values()}) != 1:
                raise RuntimeError(f"Variants disagree on {key}")
        results["wire_payloads_byte_identical"] = len({v["working_tree_sha256"] for v in variants.values()}) == 1
        results["valid"] = True
    except Exception as error:
        results.update(valid=False, error=str(error), index_after=index_state())
    # Preserve read-only proof even when an inter-variant equivalence gate fails.
    results["fixture_fingerprint_after"] = workload.fingerprint(root)
    results["index_after"] = index_state()
    if results["fixture_fingerprint_after"] != fingerprint or results["index_after"] != before:
        results.update(valid=False, error="Read-only benchmark changed fixture or index bytes/stat")
    results["metrics_ms"] = {}
    for label, _ in parameters["workers"]:
        results["metrics_ms"][label] = {}
        for phase in sorted({r["phase"] for r in records if r["variant"] == label}):
            values = sorted(r["elapsed_ns"] / 1_000_000 for r in records
                            if r["variant"] == label and r["phase"] == phase)
            results["metrics_ms"][label][phase] = dict(count=len(values), p50=statistics.median(values),
                                                       p95=values[math.ceil(len(values) * .95) - 1], max=max(values))
    (output / "raw.jsonl").write_text("".join(json.dumps(row) + "\n" for row in records))
    (output / "summary.json").write_text(json.dumps(results, indent=2) + "\n")
    return results
