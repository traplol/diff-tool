"""Prepare the fixed Linux-kernel workload on the campaign's two VM filesystems.

Run inside Ubuntu WSL, after cloning Linux v6.12 into LINUX_ROOT. This command
only changes the two exact campaign directories below. It does not download a
kernel, reset an existing fixture, or touch the application's checkout.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


BASE = "adc218676eef25575469234709c2d87185ca223a"  # Linux v6.12
LINUX_ROOT = Path("/home/max/benchmarks/branchline-boundary/kernel-wsl")
WINDOWS_ROOT = Path("/mnt/c/Users/max/branchline-bench/kernel-windows")
WINDOWS_GIT = Path("/mnt/c/Program Files/Git/cmd/git.exe")
WINDOWS_NATIVE_ROOT = "C:/Users/max/branchline-bench/kernel-windows"
MANIFEST = LINUX_ROOT.parent / "workload.json"
REFS = ["main", "feature/boundary-first", "feature/boundary-final"]
OWNER = "branchline-boundary-fixture.json"
ENV = dict(
    os.environ,
    GIT_CONFIG_NOSYSTEM="1",
    GIT_CONFIG_GLOBAL=os.devnull,
    GIT_TERMINAL_PROMPT="0",
    GIT_OPTIONAL_LOCKS="0",
    GIT_AUTHOR_NAME="Branchline Benchmark",
    GIT_AUTHOR_EMAIL="benchmark@example.invalid",
    GIT_COMMITTER_NAME="Branchline Benchmark",
    GIT_COMMITTER_EMAIL="benchmark@example.invalid",
)


def git(root, *args, data=None, date=None):
    env = dict(ENV)
    if date:
        env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    executable, directory = "git", str(root)
    if root == WINDOWS_ROOT:
        # The NTFS control must retain a Windows-native index stat cache. Using
        # WSL Git here makes every Windows worktree scan revalidate the kernel.
        executable, directory = str(WINDOWS_GIT), WINDOWS_NATIVE_ROOT
        env["GIT_CONFIG_GLOBAL"] = "NUL"
        shared = set(ENV) - set(os.environ)
        shared.update(k for k in ENV if k.startswith("GIT_"))
        inherited = [k for k in env.get("WSLENV", "").split(":")
                     if k and k.split("/")[0] not in shared]
        env["WSLENV"] = ":".join(inherited + sorted(shared))
    return subprocess.run(
        [executable, "--no-optional-locks", "-C", directory, *args], input=data, capture_output=True,
        check=True, env=env, timeout=900,
    ).stdout


def text(root, *args):
    return git(root, *args).decode().strip()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def portable_exclusions(paths):
    """Keep the same sparse checkout on both platforms, including the full index."""
    invalid = set()
    folded = {}
    reserved = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.I)
    for path in paths:
        parts = path.split("/")
        if any(reserved.match(p) or p.endswith((".", " "))
               or any(c in p for c in '<>:"\\|?*') for p in parts):
            invalid.add(path)
        for i in range(1, len(parts) + 1):
            prefix = "/".join(parts[:i])
            folded.setdefault(prefix.casefold(), set()).add(prefix)
    ambiguous = {p for variants in folded.values() if len(variants) > 1 for p in variants}
    invalid.update(path for path in paths if any(
        "/".join(path.split("/")[:i]) in ambiguous
        for i in range(1, len(path.split("/")) + 1)
    ))
    return sorted(invalid)


def select_files(paths, excluded):
    preferred = {
        "kernel/": "kernel/fork.c", "mm/": "mm/memory.c", "fs/": "fs/open.c",
        "net/": "net/core/dev.c", "drivers/": "drivers/base/core.c",
    }
    selected = []
    for prefix in ["kernel/", "mm/", "fs/", "net/", "drivers/", "arch/",
                   "include/", "lib/", "security/", "block/"]:
        candidates = sorted(
            (p for p in paths if p.startswith(prefix) and p.endswith((".c", ".h"))
             and p not in excluded),
            key=lambda p: hashlib.sha256(p.encode()).digest(),
        )
        chosen = [preferred[prefix]] if prefix in preferred else []
        chosen.extend(p for p in candidates if p not in chosen)
        selected.extend(chosen[:3])
    if len(selected) != 30 or len(set(selected)) != 30:
        raise RuntimeError("Expected thirty distinct kernel review files")
    return selected


def marked(data, marker):
    return data + (b"" if data.endswith(b"\n") else b"\n") + b"\n/* " + marker.encode() + b" */\n"


def append_marker(root, path, marker):
    file = root / path
    data = marked(file.read_bytes(), marker)
    file.write_bytes(data)
    return len(data.splitlines())


def local_changes(root, files):
    staged, unstaged = {}, {}
    for i, path in enumerate(files[:5]):
        marker = f"BRANCHLINE_BOUNDARY_STAGED_{i:02d}"
        staged[path] = {"marker": marker, "line": append_marker(root, path, marker)}
    git(root, "add", "--", *staged)
    for i, path in enumerate(files[3:8]):
        marker = f"BRANCHLINE_BOUNDARY_UNSTAGED_{i:02d}"
        unstaged[path] = {"marker": marker, "line": append_marker(root, path, marker)}
    untracked = {}
    directory = root / "branchline-review-fixture"
    directory.mkdir()
    for i in range(5):
        path = f"branchline-review-fixture/untracked-{i:02d}.txt"
        marker = f"BRANCHLINE_BOUNDARY_UNTRACKED_{i:02d}"
        (root / path).write_text(f"Untracked review fixture {i}\n{marker}\n", encoding="utf-8")
        untracked[path] = {"marker": marker, "line": 2}
    return {"Staged": staged, "Unstaged": unstaged, "Untracked": untracked}


def fingerprint(root):
    digest = hashlib.sha256()
    for args in [
        ["rev-parse", "HEAD"], ["show-ref"], ["ls-files", "--stage", "-z"],
        ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
        ["diff", "--cached", "--binary", "--no-ext-diff"],
        ["diff", "--binary", "--no-ext-diff"],
    ]:
        digest.update(git(root, *args))
    for path in sorted(git(root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0")):
        if path:
            digest.update(path)
            digest.update((root / os.fsdecode(path)).read_bytes())
    return digest.hexdigest()


def verify(manifest):
    actual = {name: fingerprint(root) for name, root in
              [("wsl", LINUX_ROOT), ("windows", WINDOWS_ROOT)]}
    if set(actual.values()) != {manifest["git_state_sha256"]}:
        raise RuntimeError(f"Fixture changed or replica differs: {actual}")
    for root in [LINUX_ROOT, WINDOWS_ROOT]:
        counts = [len(git(root, *args).rstrip(b"\0").split(b"\0")) for args in [
            ["diff", "--cached", "--name-only", "-z"],
            ["diff", "--name-only", "-z"],
            ["ls-files", "--others", "--exclude-standard", "-z"],
        ]]
        if counts != [5, 5, 5]:
            raise RuntimeError(f"Unexpected staged/unstaged/untracked counts in {root}: {counts}")
    return actual


def refresh_index(root, unstaged):
    try:
        git(root, "update-index", "--refresh")
    except subprocess.CalledProcessError as error:
        expected = {f"{path}: needs update".encode() for path in unstaged}
        if error.returncode != 1 or set(error.stdout.splitlines()) != expected or error.stderr:
            raise


def existing_layers(files):
    """Validate a preparation interrupted before adding any local changes."""
    heads = text(LINUX_ROOT, "for-each-ref", "--format=%(refname)", "refs/heads").splitlines()
    if set(heads) != {f"refs/heads/{r}" for r in REFS}:
        raise RuntimeError("Interrupted fixture has unexpected local branches")
    if text(LINUX_ROOT, "rev-parse", REFS[0]) != BASE:
        raise RuntimeError("Interrupted fixture base changed")
    previous = BASE
    layers = []
    contents = {path: git(LINUX_ROOT, "show", f"{BASE}:{path}") for path in files}
    for i, branch in enumerate(REFS[1:], 1):
        sha = text(LINUX_ROOT, "rev-parse", branch)
        if text(LINUX_ROOT, "rev-parse", f"{sha}^") != previous:
            raise RuntimeError("Interrupted fixture commit parents changed")
        changed = git(LINUX_ROOT, "diff", "--name-only", "-z", previous, sha).split(b"\0")
        if {os.fsdecode(p) for p in changed if p} != set(files):
            raise RuntimeError("Interrupted fixture changed-file set differs")
        markers = {}
        for j, path in enumerate(files):
            marker = f"BRANCHLINE_BOUNDARY_LAYER_{i}_{j:02d}"
            contents[path] = marked(contents[path], marker)
            if git(LINUX_ROOT, "show", f"{sha}:{path}") != contents[path]:
                raise RuntimeError(f"Interrupted fixture marker contents changed: {path}")
            markers[path] = {"marker": marker, "line": len(contents[path].splitlines())}
        layers.append({"ref": f"refs/heads/{branch}", "sha": sha, "files": markers})
        previous = sha
    expected_head = f"refs/heads/{REFS[-1]}"
    for root in [LINUX_ROOT, WINDOWS_ROOT]:
        owner = json.loads((root / ".git" / OWNER).read_text())
        if owner != {"status": "preparing", "base": BASE}:
            raise RuntimeError(f"Not an owned interrupted fixture: {root}")
        if text(root, "symbolic-ref", "HEAD") != expected_head:
            raise RuntimeError(f"Interrupted fixture checkout changed: {root}")
        if (root / ".git" / "index.lock").exists():
            raise RuntimeError(f"Fixture still has an index lock: {root}")
    if git(LINUX_ROOT, "status", "--porcelain=v1", "-z", "--untracked-files=all"):
        raise RuntimeError("Interrupted WSL fixture is not clean; local changes must not be replayed")
    if git(WINDOWS_ROOT, "ls-files", "--others", "--exclude-standard", "-z"):
        raise RuntimeError("Interrupted NTFS fixture contains unexpected untracked files")
    for args in [("show-ref",), ("ls-files", "--stage", "-z")]:
        if git(LINUX_ROOT, *args) != git(WINDOWS_ROOT, *args):
            raise RuntimeError("Interrupted fixture replicas differ in refs or index entries")
    return layers


def prepare(resume_owned=False):
    # Fixed absolute destinations make accidental use on a user's checkout fail.
    for root in [LINUX_ROOT, WINDOWS_ROOT]:
        if root.resolve() != root:
            raise RuntimeError(f"Fixture destination resolves elsewhere: {root}")
    if MANIFEST.exists():
        manifest = json.loads(MANIFEST.read_text())
        verify(manifest)
        return manifest
    if not WINDOWS_GIT.is_file():
        raise RuntimeError(f"Windows-native Git is required: {WINDOWS_GIT}")
    if not resume_owned:
        if (LINUX_ROOT / ".git" / OWNER).exists() or WINDOWS_ROOT.exists():
            raise RuntimeError("Partial fixture found; use --resume-owned only after its owned process exits")
        if text(LINUX_ROOT, "rev-parse", "HEAD") != BASE:
            raise RuntimeError("WSL source must be the pinned Linux v6.12 commit")
        if git(LINUX_ROOT, "status", "--porcelain=v1", "-z"):
            raise RuntimeError("WSL source must be a clean kernel clone")
        if text(LINUX_ROOT, "for-each-ref", "--format=%(refname)", "refs/heads"):
            raise RuntimeError("Expected a fresh detached Linux tag clone with no local branches")
    entries = [entry.split(b"\t", 1) for entry in
               git(LINUX_ROOT, "ls-tree", "-r", "-z", BASE).split(b"\0") if entry]
    paths = [os.fsdecode(path) for _, path in entries]
    regular = [os.fsdecode(path) for meta, path in entries if meta.startswith(b"100")]
    excluded = portable_exclusions(paths)
    # Pin these counts so a changed source/workload cannot silently compete.
    if len(paths) != 86680 or len(excluded) != 29:
        raise RuntimeError(f"Unexpected kernel workload: {len(paths)} files, {len(excluded)} exclusions")
    files = select_files(regular, set(excluded))
    if resume_owned:
        layers = existing_layers(files)
        for root in [LINUX_ROOT, WINDOWS_ROOT]:
            git(root, "config", "core.longpaths", "true")
    else:
        write_json(LINUX_ROOT / ".git" / OWNER, {"status": "preparing", "base": BASE})
        for key, value in [("core.autocrlf", "false"), ("core.filemode", "false"),
                           ("core.ignorecase", "false"), ("core.symlinks", "false"),
                           ("core.longpaths", "true"),
                           ("commit.gpgsign", "false")]:
            git(LINUX_ROOT, "config", key, value)
        patterns = "/*\n" + "".join(f"!/{p}\n" for p in excluded)
        git(LINUX_ROOT, "sparse-checkout", "set", "--no-cone", "--stdin", data=patterns.encode())
        git(LINUX_ROOT, "branch", REFS[0], BASE)
        layers = []
        for i, branch in enumerate(REFS[1:], 1):
            git(LINUX_ROOT, "switch", "-qc", branch)
            changed = {}
            for j, path in enumerate(files):
                marker = f"BRANCHLINE_BOUNDARY_LAYER_{i}_{j:02d}"
                changed[path] = {"marker": marker, "line": append_marker(LINUX_ROOT, path, marker)}
            git(LINUX_ROOT, "add", "--", *files)
            git(LINUX_ROOT, "commit", "-qm", f"Boundary benchmark layer {i}",
                date=f"2024-11-18T12:0{i}:00+0000")
            layers.append({"ref": f"refs/heads/{branch}", "sha": text(LINUX_ROOT, "rev-parse", "HEAD"), "files": changed})
        WINDOWS_ROOT.mkdir(parents=True)
        shutil.copytree(LINUX_ROOT / ".git", WINDOWS_ROOT / ".git", symlinks=True)
    # Native checkout both avoids DrvFS materialization and writes Windows stat
    # data (-u). The cross-platform cases intentionally consume this real index.
    git(WINDOWS_ROOT, "-c", "core.longpaths=true", "checkout-index", "--all", "--force", "-u")
    local = local_changes(LINUX_ROOT, files)
    if local_changes(WINDOWS_ROOT, files) != local:
        raise RuntimeError("Replica line positions differ")
    for root in [LINUX_ROOT, WINDOWS_ROOT]:
        refresh_index(root, local["Unstaged"])
    manifest = {
        "schema_version": 1, "kernel_release": "v6.12", "kernel_base": BASE,
        "tracked_files": len(paths), "materialized_tracked_files": len(paths) - len(excluded),
        "sparse_exclusions": excluded,
        "windows_symlinks": "core.symlinks=false; tracked Git entries preserved",
        "index_stat_cache": {"wsl": "Linux Git", "windows": "Git for Windows"},
        "refs": [f"refs/heads/{r}" for r in REFS],
        "head": layers[-1]["sha"], "layers": layers, "local": local,
        "changed_files_per_layer": 30,
        "first_branch_file": min(files), "comment_target_file": files[0],
        "first_worktree_file": min(local["Staged"]),
        "paths": {
            "wsl_linux": str(LINUX_ROOT), "wsl_windows": str(WINDOWS_ROOT),
            "windows_linux": "\\\\wsl.localhost\\Ubuntu-26.04\\home\\max\\benchmarks\\branchline-boundary\\kernel-wsl",
            "windows_windows": "C:\\Users\\max\\branchline-bench\\kernel-windows",
        },
        "git_state_sha256": fingerprint(LINUX_ROOT),
    }
    verify(manifest)
    for root in [LINUX_ROOT, WINDOWS_ROOT]:
        write_json(root / ".git" / OWNER, {"status": "complete", "base": BASE,
                   "git_state_sha256": manifest["git_state_sha256"]})
    write_json(MANIFEST, manifest)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="verify existing fixtures without rebuilding")
    parser.add_argument("--resume-owned", action="store_true", help="resume an owned preparation interrupted before local changes")
    args = parser.parse_args()
    if args.verify and args.resume_owned:
        parser.error("--verify and --resume-owned are mutually exclusive")
    if args.verify:
        result = verify(json.loads(MANIFEST.read_text()))
    else:
        result = prepare(args.resume_owned)
    print(json.dumps(result, indent=2, sort_keys=True))
