"""Score real Branchline boundary interactions in an already launched native app.

Start the app on an owned, empty non-repository directory. Run --seed once to
create real review anchors in its isolated profile, close that process, then
restart the same profile before measuring. This program never launches an app,
changes a Git fixture, disables MCP, or replaces a native workspace operation.

Exit zero means a complete, valid run, including a slow baseline. The separate
target_met field reports the 250 ms target. Incomplete/incorrect runs exit two.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from driver import CdpDriver, WebKitDriver


HERE = Path(__file__).resolve().parent
CASES = ("windows_linux", "windows_windows", "wsl_linux", "wsl_windows")
WORKTREE = ":worktree:"
BRANCH_BODY = "Boundary benchmark branch comment"
WORKTREE_BODY = "Boundary benchmark working-tree comment"
TARGET_MS = 250.0
TIMEOUT_MS = 180_000
ACTIONS = ("branch_first", "branch_final", "working_tree", "stack",
           "comment_branch", "comment_worktree")
# Process startup first attempts the owned non-Git welcome directory. Before
# startup_path resolves the page is briefly idle, so !aria-busy alone can race
# that attempt. Its expected error proves startup finished; no selected-repo
# work has begun. The review Open timer still starts on the real button click.
WELCOME_READY = """typeof window.__TAURI_INTERNALS__?.invoke === 'function' &&
    document.querySelector('#welcome-open')?.getClientRects().length &&
    !document.querySelector('#app')?.hasAttribute('aria-busy') &&
    document.querySelector('#status')?.classList.contains('error')"""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def source_identity(source):
    """Identity of actual app source; bench tooling has a separate contract hash."""
    source = Path(source).resolve()
    head = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True,
    ).strip()
    paths = set()
    for directory in ("frontend", "src-tauri/src", "src-tauri/git-worker/src",
                      "src-tauri/git-worker/tests", "src-tauri/capabilities"):
        paths.update(p for p in (source / directory).rglob("*") if p.is_file())
    for name in ("build.sh", "package.json", "package-lock.json", "vite.config.js",
                 "vite.config.ts", "src-tauri/Cargo.toml", "src-tauri/Cargo.lock",
                 "src-tauri/build.rs", "src-tauri/tauri.conf.json",
                 "src-tauri/git-worker/Cargo.toml", "src-tauri/git-worker/Cargo.lock"):
        if (source / name).is_file():
            paths.add(source / name)
    if not (source / "frontend/app.js").is_file() or not paths:
        raise ValueError("--source does not contain Branchline app source")
    files = {p.relative_to(source).as_posix(): digest(p.read_bytes()) for p in sorted(paths)}
    identity = {"git_head": head, "files": files}
    identity["source_hash"] = digest(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode())
    return identity


def contract_identity():
    files = {name: digest((HERE / name).read_bytes()) for name in
             ("charter.md", "probe.js", "driver.py", "launch.py", "launch_linux.py", "workload.py", "score.py")}
    return {"files": files, "sha256": digest(json.dumps(files, sort_keys=True).encode())}


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def load_manifest(path):
    data = path.read_bytes()
    manifest = json.loads(data)
    if manifest.get("schema_version") != 1 or manifest.get("tracked_files") != 86680:
        raise ValueError("Expected the pinned 86,680-file kernel workload")
    if manifest.get("kernel_base") != "adc218676eef25575469234709c2d87185ca223a":
        raise ValueError("Kernel revision differs from the fixed workload")
    if len(manifest.get("refs", [])) != 3 or len(manifest.get("layers", [])) != 2:
        raise ValueError("Expected a two-layer, three-reference review stack")
    if manifest.get("changed_files_per_layer") != 30:
        raise ValueError("Each branch layer must change thirty files")
    for group in ("Staged", "Unstaged", "Untracked"):
        if len(manifest.get("local", {}).get(group, {})) != 5:
            raise ValueError("Expected five files in every local change group")
    if not all(name in manifest.get("paths", {}) for name in CASES):
        raise ValueError("Manifest omits a matrix cell path")
    return manifest, digest(data)


def validate_launch(record, identity, case):
    for key in ("binary_sha256", "source_hash"):
        value = record.get(key)
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError(f"Launch record needs a lowercase SHA256 {key}")
    if record["source_hash"] != identity["source_hash"]:
        raise ValueError("Native executable's recorded source does not match --source")
    if not isinstance(record.get("pid"), int) or record["pid"] <= 0:
        raise ValueError("Launch record lacks an owned native process PID")
    if not record.get("binary") or not record.get("created") or not record.get("profile"):
        raise ValueError("Launch record lacks executable, creation time, or isolated profile")
    if case.startswith("windows_") != record["binary"].lower().endswith(".exe"):
        raise ValueError("Native executable platform does not match the matrix cell")


def percentile(values, fraction):
    values = sorted(values)
    return values[max(0, math.ceil(len(values) * fraction) - 1)]


def validate_samples(samples, repetitions):
    expected_counts = {"open": 1, **{name: repetitions for name in ACTIONS}}
    if Counter(s.get("action") for s in samples) != Counter(expected_counts):
        raise ValueError("Missing, duplicate, or unexpected interaction samples")
    for action in expected_counts:
        indices = sorted(s.get("repetition") for s in samples if s.get("action") == action)
        if indices != list(range(expected_counts[action])):
            raise ValueError(f"Incorrect repetition indices for {action}")
    for sample in samples:
        if sample.get("correct") is not True:
            raise ValueError("Incorrect or incomplete interaction")
        elapsed = sample.get("elapsed_ms")
        if isinstance(elapsed, bool) or not isinstance(elapsed, (float, int)) or not math.isfinite(elapsed):
            raise ValueError("Non-finite or missing interaction timing")
        if not 0 <= elapsed < TIMEOUT_MS:
            raise ValueError("Interaction exceeded its completion deadline")
        expected = sample.get("expected", {})
        if not expected.get("marker"):
            raise ValueError("Missing exact diff-content completion marker")
        for key in ("file", "left", "right", "file_count"):
            if sample.get(key) != expected.get(key):
                raise ValueError(f"Incorrect completed {key} for {sample['action']}")
        ipc = sample.get("ipc")
        if not isinstance(ipc, list) or not any(c.get("command") == "workspace" for c in ipc):
            raise ValueError("No real native workspace work was observed")
        for call in ipc:
            for key in ("start_ms", "elapsed_ms"):
                value = call.get(key)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                    raise ValueError("Incomplete or invalid native IPC timing")
        if sample["action"].startswith("comment_") and not expected.get("note_body"):
            raise ValueError("Comment jump lacks a visible expanded-thread completion gate")


def summarize(samples, repetitions):
    validate_samples(samples, repetitions)
    actions = {}
    for action in ("open", *ACTIONS):
        rows = [s for s in samples if s["action"] == action]
        values = [s["elapsed_ms"] for s in rows]
        actions[action] = {"count": len(values), "p50_ms": percentile(values, .5),
                           "p95_ms": percentile(values, .95), "max_ms": max(values),
                           "first_use_ms": rows[0]["elapsed_ms"]}
    worst = max(actions[action]["p95_ms"] for action in ("open", *ACTIONS))
    return {"actions": actions, "worst_interaction_p95_ms": worst,
            "target_ms": TARGET_MS, "target_met": worst < TARGET_MS}


def self_check():
    # Exercise the actual JS readiness condition across the observed startup
    # race: idle before startup_path, loading, then the finished welcome error.
    readiness_test = """
        import assert from 'node:assert/strict';
        const ready = new Function('window', 'document', 'return (' + CONDITION + ')');
        const window = {__TAURI_INTERNALS__: {invoke() {}}};
        function documentAt(busy, error, visible = true) {
            return {querySelector(selector) {
                if (selector === '#welcome-open') return {getClientRects: () => visible ? [{}] : []};
                if (selector === '#app') return {hasAttribute: () => busy};
                if (selector === '#status') return {classList: {contains: () => error}};
                return null;
            }};
        }
        assert.equal(Boolean(ready(window, documentAt(false, false))), false);
        assert.equal(Boolean(ready(window, documentAt(true, true))), false);
        assert.equal(Boolean(ready(window, documentAt(false, true))), true);
        assert.equal(Boolean(ready(window, documentAt(false, true, false))), false);
    """.replace('CONDITION', json.dumps(WELCOME_READY))
    subprocess.run(['node', '--input-type=module', '-e', readiness_test], check=True)
    with tempfile.TemporaryDirectory(prefix="branchline-source-identity-") as temporary:
        source = Path(temporary)
        subprocess.run(["git", "init", "-q", str(source)], check=True)
        hooks = source / "empty-hooks"
        hooks.mkdir()
        subprocess.run(["git", "-C", str(source), "-c", "user.name=Source test",
                        "-c", "user.email=source@example.invalid", "-c", "commit.gpgsign=false",
                        "-c", f"core.hooksPath={hooks}", "commit", "-q", "--allow-empty",
                        "-m", "Source identity fixture"], check=True)
        app = source / "frontend/app.js"
        app.parent.mkdir()
        app.write_text("source one")
        before = source_identity(source)
        artifact = source / "src-tauri/git-worker/target/debug/worker"
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(b"generated compiler output")
        assert source_identity(source) == before, "Compiler output changed source identity"
        app.write_text("source two")
        assert source_identity(source) != before, "Source edit did not change source identity"
    expected = {"marker": "correct diff", "file": "file.c", "left": "a", "right": "b", "file_count": 30}
    samples = [{"action": action, "repetition": 0, "correct": True,
                "elapsed_ms": 42.0, "expected": dict(expected), **{k: expected[k] for k in ("file", "left", "right", "file_count")},
                "ipc": [{"command": "workspace", "start_ms": 0.0, "elapsed_ms": 1.0}]}
               for action in ("open", *ACTIONS)]
    for sample in samples:
        if sample["action"].startswith("comment_"):
            sample["expected"]["note_body"] = "visible comment"
    assert summarize(samples, 1)["target_met"]
    mutations = {
        "missing_sample": lambda data: data.pop(),
        "wrong_content": lambda data: data[0].update(file="wrong.c"),
        "incorrect": lambda data: data[0].update(correct=False),
        "timeout": lambda data: data[0].update(elapsed_ms=TIMEOUT_MS),
        "non_finite": lambda data: data[0].update(elapsed_ms=float("nan")),
        "missing_native_work": lambda data: data[0].update(ipc=[]),
    }
    for name, mutate in mutations.items():
        altered = json.loads(json.dumps(samples))
        mutate(altered)
        try:
            summarize(altered, 1)
        except (ValueError, TypeError):
            continue
        raise AssertionError(f"Scorer accepted controlled failure: {name}")
    print(json.dumps({"self_check": "passed", "rejected": list(mutations)}))


class Run:
    def __init__(self, args, driver, manifest, output):
        self.args, self.driver, self.manifest, self.output = args, driver, manifest, output
        self.root = manifest["paths"][args.case]
        self.refs = manifest["refs"]
        self.samples = []

    def expected(self, kind, *, note=False):
        m, refs = self.manifest, self.refs
        if kind == "working_tree":
            file = m["first_worktree_file"]
            value = {"root": self.root, "left": refs[2], "right": WORKTREE,
                     "file_count": 15, "file": file, "marker": m["local"]["Staged"][file]["marker"]}
        else:
            layer = 0 if kind == "branch_first" else 1
            file = m["comment_target_file"] if note else m["first_branch_file"]
            left = refs[1] if kind == "branch_final" else refs[0]
            value = {"root": self.root, "left": left, "right": refs[layer + 1],
                     "file_count": 30, "file": file, "marker": m["layers"][layer]["files"][file]["marker"]}
        if note:
            value["note_body"] = WORKTREE_BODY if kind == "working_tree" else BRANCH_BODY
        return value

    def state(self):
        return self.driver.evaluate("return window.boundaryProbe.state();")

    def settle(self, expected):
        self.driver.wait("window.boundaryProbe.check(arguments[0])", expected, timeout=180)
        self.driver.evaluate("await window.boundaryProbe.settle();")
        self.verify_state(expected)

    def verify_state(self, expected):
        state = self.state()
        m, refs = self.manifest, self.refs
        hashes = (m["kernel_base"], m["layers"][0]["sha"], m["layers"][1]["sha"])
        if any(state["repo"]["refs"].get(ref) != sha for ref, sha in zip(refs, hashes)):
            raise ValueError("Native repository references differ from the fixture commits")
        comparison = state["comparison"]
        if comparison["right"] == WORKTREE:
            wanted = {(group, path) for group, files in m["local"].items() for path in files}
            if comparison["base"] != m["head"]:
                raise ValueError("Working tree was compared against the wrong checkout")
        else:
            layer = 0 if comparison["right"] == refs[1] else 1
            wanted = {("", path) for path in m["layers"][layer]["files"]}
            base = hashes[1] if comparison["left"] == refs[1] else hashes[0]
            if comparison["base"] != base or comparison["head"] != hashes[layer + 1]:
                raise ValueError("Branch comparison contains the wrong commit versions")
        actual = [(file["group"], file["path"]) for file in comparison["files"]]
        if len(actual) != len(wanted) or set(actual) != wanted:
            raise ValueError("Native comparison has incorrect file paths or local change groups")
        for key in ("left", "right"):
            if comparison[key] != expected[key]:
                raise ValueError("Native comparison changed after the completion frame")

    def measure(self, action, repetition, selector, expected, *, value=None):
        self.driver.evaluate("return window.boundaryProbe.arm(...arguments);", selector, expected,
                             "change" if value is not None else "click", TIMEOUT_MS)
        if value is None:
            self.driver.click(selector)
        else:
            self.driver.select(selector, str(value))
        result = self.driver.evaluate("return await window.boundaryProbe.finish();")
        self.verify_state(expected)
        sample = {"action": action, "repetition": repetition,
                  "phase": "fresh_process" if action == "open" else "first_use" if repetition == 0 else "repeated",
                  "expected": expected, **result}
        self.samples.append(sample)
        with (self.output / "samples.jsonl").open("a") as stream:
            stream.write(json.dumps(sample, allow_nan=False) + "\n")
            stream.flush()
        print(json.dumps({"action": action, "repetition": repetition, "elapsed_ms": result["elapsed_ms"]}), flush=True)
        self.driver.screenshot(self.output / f"{repetition:03d}-{action}.png")

    def open(self, measured):
        self.driver.evaluate("window.boundaryProbe.chooseRoot(arguments[0]);", self.root)
        if measured:
            self.measure("open", 0, "#welcome-open", self.expected("stack"))
        else:
            self.driver.click("#welcome-open")
            self.settle(self.expected("stack"))
        state = self.state()
        if state["stack"] != self.refs or state["repo"]["checkout"] != self.refs[2]:
            raise ValueError("Opened stack or checked-out reference differs from the fixture")

    def select_pair(self, value, expected):
        self.driver.select("#pair", str(value))
        self.settle(expected)

    def seed_comment(self, file, group, marker, body):
        return self.driver.evaluate("""
            const [file, group, marker, body] = arguments;
            const state = boundaryProbe.state();
            const index = state.comparison.files.findIndex(f => f.path === file && f.group === group);
            if (index < 0) throw Error('Missing seed file/group: ' + file + '/' + group);
            const patch = await boundaryProbe.request({op:'patch',file:index});
            const rows = patch.flatMap((line,index) => line.new && line.text.includes(marker) ? [index] : []);
            if (rows.length !== 1) throw Error('Seed marker does not identify one new-side patch line');
            const saved = await boundaryProbe.request({op:'create',file:index,rows,side:'new',body,suggestion:null});
            const matches = saved.notes.filter(note => note.body === body);
            if (matches.length !== 1) throw Error('Seed did not produce one comment');
            return {id:matches[0].id,path:matches[0].path,body,anchor:matches[0].new};
        """, file, group, marker, body)

    def seed(self):
        self.open(False)
        if any(note.get("body") in (BRANCH_BODY, WORKTREE_BODY) for note in self.state()["notes"]):
            raise ValueError("Benchmark comments already exist; use the existing seed with a fresh measurement process")
        self.select_pair(1, self.expected("branch_first"))
        file = self.manifest["comment_target_file"]
        branch = self.seed_comment(file, "", self.manifest["layers"][0]["files"][file]["marker"], BRANCH_BODY)
        self.driver.click("#local-review")
        self.settle(self.expected("working_tree"))
        file = self.manifest["first_worktree_file"]
        working = self.seed_comment(file, "Staged", self.manifest["local"]["Staged"][file]["marker"], WORKTREE_BODY)
        self.driver.click("#refresh")
        self.settle(self.expected("working_tree"))
        self.notes()
        self.driver.screenshot(self.output / "seeded.png")
        return {"setup_complete": True, "comments": [branch, working],
                "next_action": "Close the seed app and restart the same isolated profile on the non-repository directory before measurement."}

    def notes(self):
        notes = self.state()["notes"]
        result = {}
        for name, body in (("branch", BRANCH_BODY), ("worktree", WORKTREE_BODY)):
            matches = [note for note in notes if note.get("body") == body and note.get("resolved") is False]
            if len(matches) != 1:
                raise ValueError(f"Expected exactly one open seeded {name} comment")
            result[name] = matches[0]
        branch, working = result["branch"], result["worktree"]
        if (branch["left"], branch["right"], branch["path"]) != (self.refs[0], self.refs[1], self.manifest["comment_target_file"]):
            raise ValueError("Branch comment is not anchored in the non-checkout first layer")
        line = self.manifest["layers"][0]["files"][branch["path"]]["line"]
        if branch["new"] != [line, line]:
            raise ValueError("Branch comment is not anchored to its exact marker line")
        if (working["left"], working["right"], working["path"], working["group"]) != (self.refs[2], WORKTREE, self.manifest["first_worktree_file"], "Staged"):
            raise ValueError("Working-tree comment is not anchored in the staged fixture")
        line = self.manifest["local"]["Staged"][working["path"]]["line"]
        if working["new"] != [line, line]:
            raise ValueError("Working-tree comment is not anchored to its exact marker line")
        return result

    def comment(self, name, note, repetition):
        self.driver.click("#tab-comments")
        self.driver.select("#scope", "all")
        selector = f'#note-table tbody tr[data-id="{int(note["id"])}"]'
        self.driver.wait("document.querySelector(arguments[0])?.getClientRects().length", selector)
        self.driver.click(selector)
        kind = "branch_first" if name == "branch" else "working_tree"
        self.measure("comment_" + name, repetition, "#show-diff", self.expected(kind, note=True))

    def score(self):
        self.open(True)
        notes = self.notes()
        for i in range(self.args.repetitions):
            self.measure("branch_first", i, "#pair", self.expected("branch_first"), value=1)
            self.measure("branch_final", i, "#pair", self.expected("branch_final"), value=2)
            self.measure("working_tree", i, "#local-review", self.expected("working_tree"))
            self.measure("stack", i, "#stack-review", self.expected("stack"))
            self.comment("branch", notes["branch"], i)
            self.comment("worktree", notes["worktree"], i)
        return summarize(self.samples, self.args.repetitions)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--label")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--case", choices=CASES)
    parser.add_argument("--launch-record", type=Path)
    engines = parser.add_mutually_exclusive_group()
    engines.add_argument("--cdp")
    engines.add_argument("--webkit-port", type=int)
    parser.add_argument("--session")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--seed", action="store_true")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        self_check()
        return 0
    if not all((args.source, args.run_dir, args.label, args.manifest, args.case, args.launch_record)):
        parser.error("--source, --run-dir, --label, --manifest, --case, and --launch-record are required")
    if not (args.cdp or args.webkit_port) or (args.webkit_port and not args.session):
        parser.error("Use --cdp, or both --webkit-port and --session")
    if args.case.startswith("windows_") != bool(args.cdp):
        parser.error("Windows cells require CDP; WSL cells require WebKit")
    if args.repetitions < 1:
        parser.error("--repetitions must be positive")
    try:
        args.run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        parser.error("--run-dir already exists; stale artifacts cannot become a new score")
    driver = None
    run = None
    verdict = {"schema_version": 1, "mode": "seed" if args.seed else "measure",
               "valid": False, "label": args.label, "case": args.case,
               "started_at_unix": time.time(), "repetitions": args.repetitions,
               "warmup": "none; setup uses a separate process; OS caches are not flushed"}
    try:
        identity = source_identity(args.source)
        manifest, manifest_hash = load_manifest(args.manifest)
        launch = json.loads(args.launch_record.read_text(encoding="utf-8-sig"))
        validate_launch(launch, identity, args.case)
        verdict.update(source_hash=identity["source_hash"], git_head=identity["git_head"],
                       binary_sha256=launch["binary_sha256"], manifest_sha256=manifest_hash,
                       contract=contract_identity(), launch=launch)
        atomic_json(args.run_dir / "source.json", identity)
        atomic_json(args.run_dir / "workload.json", manifest)
        driver = CdpDriver(args.cdp, timeout=190) if args.cdp else WebKitDriver(args.webkit_port, args.session, timeout=190)
        driver.wait(WELCOME_READY, timeout=180)
        before = driver.info()
        if before.get("visible") != "visible":
            raise ValueError("Native webview is hidden; rendering timings would be invalid")
        atomic_json(args.run_dir / "browser-before.json", before)
        driver.screenshot(args.run_dir / "before.png")
        driver.evaluate((HERE / "probe.js").read_text() + "\nreturn true;")
        run = Run(args, driver, manifest, args.run_dir)
        result = run.seed() if args.seed else run.score()
        verdict.update(result, valid=True)
        atomic_json(args.run_dir / "browser-after.json", driver.info())
    except Exception as error:
        verdict["valid"] = False
        verdict["error"] = f"{type(error).__name__}: {error}"
        if run:
            verdict["completed_samples"] = len(run.samples)
        if driver:
            try:
                driver.screenshot(args.run_dir / "failure.png")
                atomic_json(args.run_dir / "browser-failure.json", driver.info())
            except Exception as capture_error:
                verdict["capture_error"] = str(capture_error)
    finally:
        if driver:
            try:
                driver.close()
            except Exception as close_error:
                verdict["valid"] = False
                verdict["close_error"] = str(close_error)
        verdict["finished_at_unix"] = time.time()
        atomic_json(args.run_dir / "verdict.json", verdict)
    print(json.dumps(verdict, indent=2, sort_keys=True, allow_nan=False))
    return 0 if verdict["valid"] else 2


if __name__ == "__main__":
    sys.exit(main())
