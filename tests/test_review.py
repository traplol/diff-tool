import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from branchline import git
from branchline.review import Store, comparisons, location, make_note, markdown


def command(repo, *args):
    env = dict(
        os.environ,
        GIT_AUTHOR_NAME="Alex Chen",
        GIT_COMMITTER_NAME="Alex Chen",
        GIT_AUTHOR_EMAIL="alex@example.test",
        GIT_COMMITTER_EMAIL="alex@example.test",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
    )
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env).stdout


def write(root, path, text):
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding="utf-8")


def record(root, title):
    command(root, "add", "-A")
    command(root, "commit", "-qm", title)


def fixture(root):
    root.mkdir()
    command(root, "init", "-q", "-b", "main")
    write(
        root,
        "src/cache.py",
        '''"""Cache entries for the current workspace."""

from pathlib import Path

DEFAULT_CAPACITY = 128


class WorkspaceCache:
    def __init__(self, root: Path):
        self.root = root
        self.entries = {}

    def get(self, key: str):
        return self.entries.get(key)

    def put(self, key: str, value):
        self.entries[key] = value
''',
    )
    write(root, "docs/cache.md", "# Workspace cache\n\nCache entries are stored in memory.\n")
    write(root, "config.toml", "[cache]\ncapacity = 128\n")
    record(root, "Add workspace cache")
    command(root, "switch", "-qc", "feature/cache-policy")
    cache = root / "src/cache.py"
    cache.write_text(
        cache.read_text()
        .replace("DEFAULT_CAPACITY = 128", "DEFAULT_CAPACITY = 256")
        .replace("self, root: Path", "self, root: Path, capacity: int = DEFAULT_CAPACITY")
        .replace("        self.entries = {}", "        self.capacity = capacity\n        self.entries = {}")
        .replace(
            "        self.entries[key] = value",
            "        if key not in self.entries and len(self.entries) >= self.capacity:\n"
            "            oldest = next(iter(self.entries))\n            del self.entries[oldest]\n"
            "        self.entries[key] = value",
        )
    )
    write(root, "config.toml", '[cache]\ncapacity = 256\npolicy = "oldest"\n')
    command(root, "mv", "docs/cache.md", "docs/cache-policy.md")
    record(root, "Bound the workspace cache")
    command(root, "switch", "-qc", "feature/cache-metrics")
    write(
        root,
        "src/metrics.py",
        "from dataclasses import dataclass\n\n\n@dataclass\nclass CacheMetrics:\n    hits: int = 0\n    misses: int = 0\n",
    )
    cache.write_text(
        cache.read_text()
        .replace("from pathlib import Path", "from pathlib import Path\n\nfrom .metrics import CacheMetrics")
        .replace(
            "        self.capacity = capacity",
            "        self.metrics = CacheMetrics()\n        self.capacity = capacity",
        )
        .replace(
            "        return self.entries.get(key)",
            "        if key in self.entries:\n            self.metrics.hits += 1\n"
            "            return self.entries[key]\n        self.metrics.misses += 1\n        return None",
        )
    )
    write(
        root,
        "tests/test_metrics.py",
        "from src.metrics import CacheMetrics\n\n\ndef test_empty_cache():\n    metrics = CacheMetrics()\n    assert metrics.hits == metrics.misses == 0\n",
    )
    (root / "logo.bin").write_bytes(b"branchline\0image")
    record(root, "Track cache hits and misses")
    command(root, "switch", "-q", "main")
    write(root, "unrelated.txt", "A change that exists only on main.\n")
    record(root, "Update main after the branch point")
    command(root, "switch", "-q", "feature/cache-metrics")
    return git.open_repo(root)


class ReviewTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "relay"
        self.repo = fixture(self.root)
        self.stack = ["refs/heads/" + x for x in ("main", "feature/cache-policy", "feature/cache-metrics")]
        self.c = git.compare(self.repo, self.stack[0], self.stack[-1])
        self.store = Store(Path(self.temp.name) / "data")
        self.addCleanup(self.store.db.close)

    def test_stack_merge_base_and_layers(self):
        self.assertEqual(self.repo.initial, [self.stack[0], self.stack[-1]])
        self.assertNotEqual(self.c.left_tip, self.c.base)
        self.assertNotIn("unrelated.txt", [f.path for f in self.c.files])
        pairs = comparisons(self.stack)
        self.assertEqual(
            pairs,
            [(self.stack[0], self.stack[2]), (self.stack[0], self.stack[1]), (self.stack[1], self.stack[2])],
        )
        self.assertEqual(len(git.commits(self.repo, self.c)), 2)
        self.assertEqual(len(git.commits(self.repo, git.compare(self.repo, *pairs[-1]))), 1)
        self.store.set_stack(self.repo, self.stack)
        self.assertEqual(self.store.stack(self.repo), self.stack)

    def test_discovery_from_the_middle_and_a_fork(self):
        base, middle, tip = self.stack
        self.assertEqual(git.discover_stack(self.repo, base, middle), (self.stack, []))
        self.assertEqual(git.discover_stack(self.repo, base, tip), (self.stack, []))
        command(self.root, "update-ref", "refs/remotes/origin/cache-policy", self.repo.refs[middle])
        command(self.root, "switch", "-qc", "feature/expiry", middle)
        write(self.root, "expiry.txt", "expire stale entries\n")
        record(self.root, "Add expiry")
        repo = git.open_repo(self.root)
        expiry = "refs/heads/feature/expiry"
        chain, choices = git.discover_stack(repo, base, middle)
        self.assertEqual(chain, [base, middle])
        self.assertEqual(set(choices), {tip, expiry})
        self.assertEqual(git.discover_stack(repo, base, expiry), ([base, middle, expiry], []))
        self.assertEqual(git.discover_stack(repo, base, tip), (self.stack, []))

    def test_advertised_default_branch_includes_the_full_stack(self):
        _, middle, tip = self.stack
        default = "refs/remotes/origin/release/stable"
        command(self.root, "update-ref", default, "main^")
        command(self.root, "symbolic-ref", "refs/remotes/origin/HEAD", default)
        # Neither the common local name nor a stale local namesake is the base.
        command(self.root, "branch", "-f", "main", middle)
        command(self.root, "branch", "release/stable", tip)
        repo = git.open_repo(self.root)
        self.assertEqual(repo.initial, [default, tip])
        self.assertEqual(git.discover_stack(repo, repo.default_branch, tip), ([default, middle, tip], []))
        self.assertEqual(len(git.commits(repo, git.compare(repo, *repo.initial))), 2)

    def test_advertised_default_with_local_branch_at_same_tip(self):
        default = "refs/remotes/upstream/stable"
        command(self.root, "update-ref", default, "main")
        command(self.root, "symbolic-ref", "refs/remotes/upstream/HEAD", default)
        command(self.root, "switch", "-qc", "stable", "main")
        repo = git.open_repo(self.root)
        self.assertEqual(repo.default_branch, "refs/heads/stable")
        self.assertEqual(repo.initial, ["HEAD^", repo.checkout])

    @unittest.skipUnless(shutil.which("ssh-keygen"), "Creating an SSH-signed commit needs ssh-keygen")
    def test_signature_display_does_not_change_commit_rows(self):
        key = Path(self.temp.name) / "signer"
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True, capture_output=True
        )
        allowed = key.with_name("allowed_signers")
        allowed.write_text("reviewer " + key.with_suffix(".pub").read_text(), encoding="utf-8")
        command(self.root, "config", "gpg.format", "ssh")
        command(self.root, "config", "gpg.ssh.allowedSignersFile", str(allowed))
        command(self.root, "config", "user.signingkey", str(key))
        command(self.root, "commit", "-qS", "--allow-empty", "-m", "Signed review change")
        command(self.root, "config", "log.showSignature", "true")
        repo = git.open_repo(self.root)
        comparison = git.compare(repo, "HEAD^", repo.checkout)
        date = command(self.root, "show", "--no-show-signature", "-s", "--format=%as", "HEAD").decode().strip()
        self.assertEqual(
            git.commits(repo, comparison),
            [(repo.refs[repo.checkout], "Alex Chen", date, "Signed review change")],
        )

    def test_renames_binary_and_literal_paths(self):
        rename = next(f for f in self.c.files if f.status == "R")
        self.assertEqual((rename.old, rename.path), ("docs/cache.md", "docs/cache-policy.md"))
        self.assertEqual(git.patch(self.repo, self.c, rename), [])
        self.assertTrue(next(f for f in self.c.files if f.path == "logo.bin").binary)
        odd = "docs/a[1] patch.md"
        write(self.root, odd, "+++ a line\n\n```\n")
        record(self.root, "Add bracketed filename")
        self.repo = git.open_repo(self.root / "src")
        c = git.compare(self.repo, *self.repo.initial)
        lines = git.patch(self.repo, c, next(f for f in c.files if f.path == odd))
        self.assertEqual(
            [(l.text, l.new) for l in lines if l.kind == "+"], [("+++ a line", 1), ("", 2), ("```", 3)]
        )

    def test_comment_survives_branch_move_and_round_trips(self):
        f = next(f for f in self.c.files if f.path == "src/cache.py")
        lines = git.patch(self.repo, self.c, f)
        selected = [l for l in lines if l.kind == "+" and "DEFAULT_CAPACITY = " in l.text]
        note = make_note(self.c, f, selected, "new", "Should this be configurable?")
        self.assertTrue(note["new"])
        self.assertFalse(note["old"])
        self.store.save(self.repo, note)
        self.store.set_viewed(self.repo, self.c, f.path, True)
        self.assertEqual(self.store.viewed(self.repo, self.c), {f.path})
        write(self.root, f.path, "# Replaced\n")
        record(self.root, "Replace cache")
        moved = git.open_repo(self.root)
        fresh = git.compare(moved, *moved.initial)
        self.assertFalse(self.store.viewed(moved, fresh))
        (note,) = self.store.notes(moved)
        self.assertNotEqual(note["head"], fresh.head)
        report = markdown(moved, self.stack, [note])
        for text in (note["head"], note["base"], note["body"], note["excerpt"], location(note)):
            self.assertIn(text, report)
        self.store.save(moved, dict(note, body="Resolved after review"), original=note)
        self.assertEqual(self.store.notes(moved)[0]["body"], "Resolved after review")
        self.store.delete(moved, note["id"])
        self.assertFalse(self.store.notes(moved))

    def test_first_commit_and_unborn_repository(self):
        other = Path(self.temp.name) / "new"
        other.mkdir()
        command(other, "init", "-q", "-b", "main")
        self.assertFalse(git.open_repo(other).initial)
        write(other, "a.txt", "a\n")
        record(other, "Root")
        repo = git.open_repo(other)
        self.assertEqual(repo.initial[0], git.EMPTY)
        c = git.compare(repo, *repo.initial)
        self.assertEqual(c.files[0].added, 1)
        self.assertEqual(len(git.commits(repo, c)), 1)

    def test_split_preserves_old_and_new_lines(self):
        f = next(f for f in self.c.files if f.path == "src/cache.py")
        lines = git.patch(self.repo, self.c, f)
        rows = git.split_rows(lines)
        self.assertEqual([l.old for l, _ in rows if l and l.old], [l.old for l in lines if l.old])
        self.assertEqual([r.new for _, r in rows if r and r.new], [l.new for l in lines if l.new])

    def test_deleted_lines_and_hunk_numbers_across_blank_context(self):
        path = "src/blank.txt"
        original = "first\n\n" + "".join(f"row {i}\n" for i in range(20)) + "last\n"
        write(self.root, path, original)
        record(self.root, "Add blank context")
        command(self.root, "config", "diff.suppressBlankEmpty", "true")
        write(self.root, path, original.replace("row 0", "updated").replace("last", "replacement"))
        record(self.root, "Change a distant line")
        repo = git.open_repo(self.root)
        c = git.compare(repo, "HEAD^", repo.initial[-1])
        (f,) = c.files
        lines = git.patch(repo, c, f)
        self.assertEqual([(l.old, l.hunk) for l in lines if l.kind == "-"], [(3, 1), (23, 2)])
        old = next(line for line in lines if line.kind == "-" and line.hunk == 2)
        self.assertEqual((old.text, old.old, old.new), ("last", 23, None))
        note = make_note(c, f, [old], "old", "Keep this line.")
        self.assertEqual(location(note), "old L23")
        self.assertEqual(note["excerpt"], "-last")

    @unittest.skipIf(os.name == "nt", "Creating symlinks can need elevated permissions on Windows")
    def test_regular_file_to_symlink_keeps_both_sides(self):
        path = self.root / "config.toml"
        path.unlink()
        path.symlink_to("config.local.toml")
        record(self.root, "Link local configuration")
        repo = git.open_repo(self.root)
        c = git.compare(repo, "HEAD^", repo.initial[-1])
        (f,) = c.files
        self.assertEqual(f.status, "T")
        lines = git.patch(repo, c, f)
        self.assertTrue(any(line.kind == "-" and line.old == 1 for line in lines))
        self.assertTrue(
            any(line.kind == "+" and line.new == 1 and line.text == "config.local.toml" for line in lines)
        )

    def test_default_pair_for_branch_at_same_tip(self):
        command(self.root, "switch", "-qc", "fresh", "main")
        repo = git.open_repo(self.root)
        self.assertEqual(repo.initial, ["refs/heads/main", "refs/heads/fresh"])
        self.assertEqual(git.compare(repo, *repo.initial).files, [])


if __name__ == "__main__":
    unittest.main()
