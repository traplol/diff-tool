"""Read committed and local changes with Git's diff semantics."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field, replace
from functools import cache
from itertools import zip_longest
from pathlib import Path

EMPTY = ":empty:"
WORKTREE = ":worktree:"


class GitError(Exception):
    pass


def windows_git(directory):
    # Windows can search the launching directory before PATH for an unqualified
    # executable. The launcher and the directory selected in the UI may both
    # be inside checkouts, including when opened from a subdirectory.
    directories = {Path.cwd().resolve(), Path(directory).resolve()}
    markers = (parent / ".git" for path in directories for parent in (path, *path.parents))
    checkouts = {marker.parent for marker in markers if marker.is_file() or (marker / "HEAD").is_file()}
    for entry in os.get_exec_path():
        folder = Path(entry.strip('"'))
        if not folder.is_absolute():
            continue
        candidate = folder / "git.exe"
        if candidate.is_file():
            candidate = candidate.resolve()
            if candidate.parent not in directories and not any(
                candidate.is_relative_to(root) for root in checkouts
            ):
                return str(candidate)
    raise FileNotFoundError("git.exe")


def git(directory, *args, diff_exit=False):
    try:
        executable = windows_git(directory) if sys.platform == "win32" else "git"
        cmd = [executable, "--no-pager", "--literal-pathspecs", "-C", str(directory), *args]
        p = subprocess.run(
            cmd,
            check=False,
            input=b"",
            env={**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"},
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError as error:
        raise GitError("Install Git and add it to PATH, then reopen Branchline.") from error
    if p.returncode and not (diff_exit and p.returncode == 1 and p.stdout):
        raise GitError(p.stderr.decode(errors="replace").strip() or "Git could not read this revision.")
    return p.stdout


def show(value):
    """Keep non-UTF-8 filenames and control characters legible in single-line labels."""
    return (
        value.encode("utf-8", "backslashreplace")
        .decode()
        .replace("\n", r"\n")
        .replace("\r", r"\r")
        .replace("\t", r"\t")
    )


def ref_name(ref):
    if ref == EMPTY:
        return "Empty tree"
    if ref == WORKTREE:
        return "Working tree"
    if ref.startswith("HEAD@"):
        return "Detached HEAD " + ref[5:13]
    if ref.startswith("refs/remotes/"):
        return ref.removeprefix("refs/remotes/") + " (remote)"
    return ref.removeprefix("refs/heads/")


@dataclass
class Repository:
    root: Path
    refs: dict[str, str]
    initial: list[str]
    default_branch: str | None = None
    checkout: str = "HEAD"


def checkout_state(root):
    try:
        head = git(root, "rev-parse", "--verify", "HEAD").decode().strip()
    except GitError:
        head = None
    try:
        branch = os.fsdecode(git(root, "symbolic-ref", "--quiet", "HEAD").rstrip(b"\n"))
    except GitError:
        branch = "HEAD@" + head if head else "HEAD"
    return branch, head


def open_repo(path):
    root = Path(os.fsdecode(git(path, "rev-parse", "--show-toplevel").removesuffix(b"\n"))).resolve()
    refs = {}
    advertised = {}
    lines = git(
        root, "for-each-ref", "--format=%(refname)%00%(objectname)%00%(symref)", "refs/heads", "refs/remotes"
    ).splitlines()
    for line in lines:
        name, oid, symbolic = line.split(b"\0")
        name = os.fsdecode(name)
        if not symbolic:
            refs[name] = oid.decode()
        elif name.startswith("refs/remotes/") and name.endswith("/HEAD"):
            remote = name.removesuffix("HEAD")
            target = os.fsdecode(symbolic)
            if target.startswith(remote):
                advertised[remote] = target
    checkout, head = checkout_state(root)
    branch = "HEAD" if checkout.startswith("HEAD@") else checkout
    refs[EMPTY] = git(root, "hash-object", "-t", "tree", "--stdin").decode().strip()
    if head:
        refs[branch] = head
    elif len(refs) > 1:
        branch = next(iter(refs))
    else:
        return Repository(root, refs, [], checkout=checkout)
    candidates = []
    for remote in sorted(advertised, key=lambda ref: (ref != "refs/remotes/origin/", ref)):
        target = advertised[remote]
        if target in refs:
            local = "refs/heads/" + target.removeprefix(remote)
            candidates.append(local if refs.get(local) == refs[target] else target)
    candidates += ["refs/heads/" + n for n in ("main", "master", "trunk", "develop")]
    candidates += ["refs/remotes/origin/" + n for n in ("main", "master", "trunk")]
    base = next((r for r in candidates if r in refs), None)
    if head:
        try:
            refs["HEAD^"] = git(root, "rev-parse", "--verify", head + "^").decode().strip()
        except GitError:
            pass  # The root commit has no parent.
    default_branch = base
    if base is None or base == branch:
        base = "HEAD^" if "HEAD^" in refs and head == refs[branch] else EMPTY
    return Repository(root, refs, [base, branch], default_branch, checkout)


def discover_stack(repo, base, branch):
    """Follow unambiguous ancestry between named branch tips, stopping at forks."""
    if branch == EMPTY:
        return [base], []
    names = {}
    for ref, oid in sorted(repo.refs.items()):
        if ref.startswith(("refs/heads/", "refs/remotes/")):
            names.setdefault(oid, ref)
    start = repo.refs[branch]
    names[start] = branch

    @cache
    def tips(filter_arg):
        data = git(
            repo.root, "for-each-ref", filter_arg, "--format=%(objectname)", "refs/heads", "refs/remotes"
        )
        return set(data.decode().splitlines()) & names.keys()

    def merged(tip):
        return tips("--merged=" + tip)

    excluded = merged(repo.refs[base]) if base.startswith("refs/") else set()
    if start in excluded and repo.refs[base] != start:
        return [base, branch], []
    parents = merged(start) - excluded - {start}
    descendants = tips("--contains=" + start) - {start}
    before, after, forks = [], [], []
    while parents:
        nearest = parents - set().union(*(merged(tip) - {tip} for tip in parents))
        if len(nearest) != 1:
            forks.extend(sorted(names[tip] for tip in nearest))
            break
        tip = nearest.pop()
        before.append(names[tip])
        parents = (merged(tip) & parents) - {tip}
    while descendants:
        children = [tip for tip in descendants if not ((merged(tip) - {tip}) & descendants)]
        if len(children) != 1:
            forks.extend(sorted(names[tip] for tip in children))
            break
        tip = children[0]
        after.append(names[tip])
        descendants = {other for other in descendants if other != tip and tip in merged(other)}
    stack = [base, *reversed(before)]
    if branch != base:
        stack.append(branch)
    if not base.startswith("refs/") and (before or after):
        stack = [*reversed(before), branch]
    return [*stack, *after], forks


@dataclass(frozen=True)
class Change:
    status: str
    old: str
    path: str
    added: int | None
    removed: int | None
    old_mode: str
    mode: str
    old_oid: str
    oid: str
    group: str = ""
    local_sections: tuple[bytes, ...] = field(default=(), repr=False, compare=False)

    @property
    def binary(self):
        return self.added is None


@dataclass
class Comparison:
    left: str
    right: str
    left_tip: str
    base: str
    head: str
    files: list[Change]


def compare(repo, left, right):
    if right == WORKTREE:
        return working_tree(repo, left)
    tip, head = repo.refs[left], repo.refs[right]
    if left == EMPTY:
        base = tip
    else:
        try:
            base = git(repo.root, "merge-base", tip, head).decode().strip()
        except GitError as error:
            raise GitError(
                "These branches have no common ancestor. Choose another base or use Empty tree."
            ) from error
    return compare_trees(repo, left, right, tip, base, head)


def compare_trees(repo, left, right, tip, base, head):
    """Read a diff between the given trees after its ancestry has been determined."""
    raw = git(
        repo.root,
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--find-renames",
        "--ignore-submodules=none",
        "--raw",
        "--no-abbrev",
        "--numstat",
        "-z",
        base,
        head,
        "--",
    )
    return Comparison(left, right, tip, base, head, parse_changes(raw))


def parse_changes(raw):
    parts = iter(raw.split(b"\0"))
    records = []
    part = next(parts)
    while part.startswith(b":"):
        old_mode, mode, old_oid, oid, status = part[1:].decode().split()
        old = os.fsdecode(next(parts))
        path = os.fsdecode(next(parts)) if status[0] in "RC" else old
        records.append((status[0], old, path, old_mode, mode, old_oid, oid))
        part = next(parts)
    counts = {}
    while part:
        plus, minus, name = part.split(b"\t", 2)
        if not name:
            next(parts)
            name = next(parts)
        counts[os.fsdecode(name)] = (None, None) if plus == b"-" else (int(plus), int(minus))
        part = next(parts)
    return [
        Change(status, old, path, *counts[path], om, mode, oo, oid)
        for status, old, path, om, mode, oo, oid in records
    ]


@dataclass(frozen=True)
class Line:
    kind: str
    text: str
    old: int | None
    new: int | None
    hunk: int


HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def diff_patch(repo, *args, diff_exit=False):
    return git(
        repo.root,
        "-c",
        "core.quotePath=true",
        "-c",
        "diff.suppressBlankEmpty=false",
        "diff",
        "--patch",
        "--full-index",
        "--no-color",
        "--no-ext-diff",
        "--no-textconv",
        "--find-renames",
        "--unified=3",
        "--ignore-submodules=none",
        "--submodule=short",
        "--no-relative",
        "--output-indicator-new=+",
        "--output-indicator-old=-",
        "--output-indicator-context= ",
        *args,
        diff_exit=diff_exit,
    )


def local_changes(repo, group, *args, diff_exit=False):
    # A single diff pairs the summary with the exact bytes the reviewer will see.
    data = diff_patch(repo, "--raw", "--numstat", "--no-abbrev", "-z", *args, diff_exit=diff_exit)
    raw, _, patch_data = data.partition(b"\0\0")
    sections = iter(re.split(rb"(?m)^diff --git ", patch_data)[1:])
    changes = []
    for change in parse_changes(raw + b"\0"):
        # Git emits a delete and an add for a type change.
        chunks = [next(sections, None) for _ in range(2 if change.status == "T" else 1)]
        if None in chunks:
            raise GitError("Git returned an incomplete working tree diff. Refresh to try again.")
        # Raw worktree records use all zeroes for the new object ID. The full-index
        # patch carries the content hash, including for binary files.
        index = re.search(rb"(?m)^index [0-9a-f]+\.\.([0-9a-f]+)", chunks[-1])
        oid = change.oid if change.oid.strip("0") else change.old_oid
        if index:
            oid = index[1].decode()
        changes.append(replace(change, group=group, oid=oid, local_sections=tuple(chunks)))
    if next(sections, None) is not None:
        raise GitError("Git returned inconsistent working tree changes. Refresh to try again.")
    return changes


def working_tree(repo, checkout, *, untracked_paths=None):
    if checkout != repo.checkout:
        raise GitError("The checked-out branch changed. Refresh the working tree.")
    head = repo.refs.get("HEAD" if checkout.startswith("HEAD@") else checkout)
    base = head or repo.refs[EMPTY]
    index_path = repo.root / os.fsdecode(git(repo.root, "rev-parse", "--git-path", "index").rstrip(b"\n"))

    def index_state():
        try:
            stat = index_path.stat()
            return stat.st_ino, stat.st_size, stat.st_mtime_ns
        except FileNotFoundError:
            return None

    initial_index = index_state()
    files = local_changes(repo, "Staged", "--cached", "--diff-filter=u", base, "--")
    unstaged = local_changes(repo, "Unstaged", "--ours", "--diff-filter=u", "--")

    # An unmerged index has up to three entries for a path and no single staged
    # version. Show its on-disk resolution against our side in Unstaged.
    conflicts = {}
    for entry in git(repo.root, "ls-files", "--unmerged", "-z").split(b"\0"):
        if entry:
            metadata, raw_path = entry.split(b"\t", 1)
            mode, oid, stage = metadata.decode().split()
            path = os.fsdecode(raw_path)
            conflicts.setdefault(path, ("000000", "0" * len(base)))
            if stage == "2":
                conflicts[path] = (mode, oid)
    for change in unstaged:
        if change.path in conflicts:
            files.append(replace(change, status="U"))
            del conflicts[change.path]
        else:
            files.append(change)
    for path, (mode, oid) in conflicts.items():
        remaining = local_changes(repo, "Unstaged", base, "--", path)
        if remaining:
            files.extend(replace(change, status="U") for change in remaining)
        else:
            files.append(Change("U", path, path, 0, 0, mode, mode, oid, oid, "Unstaged"))

    untracked = b""
    if untracked_paths is None or untracked_paths:
        untracked = git(repo.root, "ls-files", "--others", "--exclude-standard", "-z")
    for raw_path in untracked.split(b"\0"):
        if not raw_path:
            continue
        path = os.fsdecode(raw_path)
        if untracked_paths is not None and path.rstrip("/") not in untracked_paths:
            continue
        source = repo.root / path
        if source.is_symlink():
            # diff --no-index follows a link to a directory or FIFO when passed
            # on the command line. Compare the link text, as Git's index does.
            with tempfile.TemporaryDirectory() as directory:
                link = Path(directory) / "link"
                link.write_bytes(os.fsencode(os.readlink(source)))
                (change,) = local_changes(
                    repo, "Untracked", "--no-index", "--", "/dev/null", str(link), diff_exit=True
                )
            files.append(replace(change, old=path, path=path, mode="120000"))
        elif source.is_file():
            # A bare "-" asks diff --no-index to read standard input.
            added = local_changes(
                repo, "Untracked", "--no-index", "--", "/dev/null", "./" + path, diff_exit=True
            )
            files.extend(replace(f, old=path, path=path) for f in added)
        elif source.is_dir() and (source / ".git").exists():
            # Git reports an embedded repository as a single untracked directory.
            # Do not descend into the nested checkout.
            path = path.rstrip("/")
            try:
                oid = git(source, "rev-parse", "--verify", "HEAD").decode().strip()
            except GitError:
                oid = "0" * len(base)
            files.append(Change("A", path, path, 0, 0, "000000", "160000", "0" * len(oid), oid, "Untracked"))
    if checkout_state(repo.root) != (checkout, head) or initial_index != index_state():
        raise GitError("The checkout or index changed. Refresh to review its current changes.")
    digest = hashlib.sha256()
    for f in files:
        for value in (f.group, f.status, f.old, f.path, f.old_mode, f.mode, f.old_oid, f.oid):
            digest.update(os.fsencode(value) + b"\0")
    return Comparison(checkout, WORKTREE, base, base, digest.hexdigest(), files)


def patch(repo, comparison, change):
    if change.group:
        sections = change.local_sections
    else:
        paths = [change.path] if change.old == change.path else [change.old, change.path]
        data = diff_patch(repo, comparison.base, comparison.head, "--", *paths)
        sections = re.split(rb"(?m)^diff --git ", data)[1:]
        if len(sections) > 1 and change.status != "T":
            index = ("index " + change.old_oid + ".." + change.oid).encode()
            sections = [
                section
                for section in sections
                if re.search(b"^" + re.escape(index) + rb"(?: |$)", section, re.MULTILINE)
            ]
    result = []
    hunk = 0
    for section in sections:
        in_hunk = False
        for line in section.decode("utf-8", "replace").split("\n"):
            match = HUNK.match(line)
            if match:
                old, new = map(int, match.groups())
                hunk += 1
                in_hunk = True
                result.append(Line("@", line, None, None, hunk))
            elif in_hunk and line and line[0] in " +-":
                kind = line[0]
                result.append(
                    Line(
                        kind,
                        line[1:].removesuffix("\r"),
                        old if kind != "+" else None,
                        new if kind != "-" else None,
                        hunk,
                    )
                )
                old += kind != "+"
                new += kind != "-"
            elif in_hunk and line.startswith("\\"):
                result.append(Line("\\", line, None, None, hunk))
    return result


def split_rows(lines):
    rows, deleted, added = [], [], []
    for line in lines:
        if line.kind == "-":
            deleted.append(line)
        elif line.kind == "+":
            added.append(line)
        else:
            rows.extend(zip_longest(deleted, added))
            deleted.clear()
            added.clear()
            rows.append((line, line))
    rows.extend(zip_longest(deleted, added))
    return rows


def commits(repo, comparison):
    if comparison.right == WORKTREE:
        return []
    revisions = [comparison.head]
    if comparison.left != EMPTY:
        revisions.append("^" + comparison.base)
    data = git(
        repo.root, "log", "--no-show-signature", "-z", "--format=%H%x00%an%x00%as%x00%s", *revisions, "--"
    )
    fields = data.decode(errors="replace").split("\0")
    return list(zip(fields[0::4], fields[1::4], fields[2::4], fields[3::4]))
