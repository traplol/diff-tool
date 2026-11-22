"""Store review state outside the checkout and export immutable comment anchors."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from contextlib import contextmanager
from itertools import pairwise
from pathlib import Path

from .git import WORKTREE, ref_name, show


def data_directory():
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Branchline"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "branchline"


class ReviewConflict(Exception):
    """The saved comment changed while a review window was open."""


class Store:
    def __init__(self, directory=None):
        directory = directory or data_directory()
        directory.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(directory / "reviews.sqlite3")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS stacks (repo BLOB PRIMARY KEY, refs TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS preferences (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS viewed (repo BLOB, base TEXT, head TEXT, path TEXT,
                                                PRIMARY KEY (repo, base, head, path));
        """)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            columns = {row[1] for row in self.db.execute("PRAGMA table_info(notes)")}
            migrate = bool(columns) and "resolved" not in columns
            if migrate:
                self.db.execute("ALTER TABLE notes RENAME TO notes_before_resolution")
            # A second window can still hold an ID after its note is deleted.
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, repo BLOB NOT NULL,
                    data TEXT NOT NULL, resolved INTEGER NOT NULL DEFAULT 0
                )
            """)
            if migrate:
                self.db.execute(
                    "INSERT INTO notes(id,repo,data) SELECT id,repo,data FROM notes_before_resolution"
                )
                self.db.execute("DROP TABLE notes_before_resolution")

    def sidebar_width(self, default=320):
        row = self.db.execute("SELECT value FROM preferences WHERE name='sidebar_width'").fetchone()
        return row[0] if row else default

    def set_sidebar_width(self, width):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO preferences VALUES ('sidebar_width',?)", (width,))

    def stack(self, repo, fallback=None):
        row = self.db.execute("SELECT refs FROM stacks WHERE repo=?", (os.fsencode(repo.root),)).fetchone()
        if row:
            refs = json.loads(row[0])
            if len(refs) >= 2 and all(ref in repo.refs for ref in refs):
                return refs
        return repo.initial.copy() if fallback is None else fallback

    def set_stack(self, repo, refs):
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO stacks VALUES (?,?)", (os.fsencode(repo.root), json.dumps(refs))
            )

    def notes(self, repo):
        rows = self.db.execute(
            "SELECT id, data, resolved FROM notes WHERE repo=? ORDER BY id", (os.fsencode(repo.root),)
        )
        return [dict(json.loads(data), id=key, resolved=bool(resolved)) for key, data, resolved in rows]

    @contextmanager
    def _edit_note(self, repo, key):
        where = (os.fsencode(repo.root), key)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT data, resolved FROM notes WHERE repo=? AND id=?", where).fetchone()
            if row is None:
                raise ReviewConflict("Another window deleted this comment.")
            current = json.loads(row[0])
            yield current, bool(row[1])
            self.db.execute("UPDATE notes SET data=? WHERE repo=? AND id=?", (json.dumps(current), *where))

    def save(self, repo, note, *, original=None):
        if "id" in note:
            if original is None or original["id"] != note["id"]:
                raise ValueError("Saving an edit requires the original comment.")
            with self._edit_note(repo, note["id"]) as (current, _):
                for field in ("body", "suggestion"):
                    value = note.get(field)
                    if value == original.get(field) or value == current.get(field):
                        continue
                    if field == "suggestion" and current.get("applied_location"):
                        raise ReviewConflict(
                            "Another window applied this suggestion. The replacement is read-only."
                        )
                    if current.get(field) != original.get(field):
                        raise ReviewConflict(
                            "Another window edited the same text. Reopen the comment to see its changes."
                        )
                    current[field] = value
            return note["id"]
        with self.db:
            data = json.dumps({k: v for k, v in note.items() if k != "resolved"})
            inserted = self.db.execute(
                "INSERT INTO notes(repo,data) VALUES (?,?)", (os.fsencode(repo.root), data)
            )
            return inserted.lastrowid

    @contextmanager
    def applying(self, repo, note):
        # Serialize the file change and its receipt with other windows editing this comment.
        with self._edit_note(repo, note["id"]) as (current, resolved):
            if resolved or current.get("applied_location") or current.get("suggestion") != note["suggestion"]:
                raise ReviewConflict("Refresh to review the latest version before applying.")
            yield current

    def set_resolved(self, repo, note_id, resolved):
        with self.db:
            updated = self.db.execute(
                "UPDATE notes SET resolved=? WHERE id=? AND repo=?",
                (bool(resolved), note_id, os.fsencode(repo.root)),
            )
            return updated.rowcount == 1

    def delete(self, repo, key):
        with self.db:
            self.db.execute("DELETE FROM notes WHERE repo=? AND id=?", (os.fsencode(repo.root), key))

    def viewed(self, repo, c):
        rows = self.db.execute(
            "SELECT path FROM viewed WHERE repo=? AND base=? AND head=?",
            (os.fsencode(repo.root), *viewed_scope(c)),
        )
        saved = {row[0] for row in rows}
        if c.right != WORKTREE:
            return {json.loads(path) for path in saved}
        return {file_key(f) for f in c.files if viewed_path(f) in saved}

    def set_viewed(self, repo, c, file, value):
        key = (os.fsencode(repo.root), *viewed_scope(c), viewed_path(file))
        with self.db:
            if value:
                self.db.execute("INSERT OR IGNORE INTO viewed VALUES (?,?,?,?)", key)
            else:
                self.db.execute("DELETE FROM viewed WHERE repo=? AND base=? AND head=? AND path=?", key)


def file_key(file):
    return (file.group, file.path) if file.group else file.path


def file_version(file):
    return [file.old_oid, file.oid, file.old_mode, file.mode]


def viewed_scope(c):
    return (c.left, WORKTREE) if c.right == WORKTREE else (c.base, c.head)


def viewed_path(file):
    if isinstance(file, str):
        return json.dumps(file)
    if file.group:
        return json.dumps([file_key(file), file.old, file_version(file)])
    return json.dumps(file.path)


def comparisons(stack):
    if len(stack) < 2:
        return []
    pairs = [(stack[0], stack[-1])]
    if len(stack) > 2:
        pairs.extend(pairwise(stack))
    return pairs


def line_ranges(lines, side):
    def line_range(numbers):
        values = [n for n in numbers if n is not None]
        return [values[0], values[-1]] if values else []

    return {
        "old": [] if side == "new" else line_range(line.old for line in lines),
        "new": [] if side == "old" else line_range(line.new for line in lines),
    }


def make_note(c, file, lines, side, body, *, diff_lines=()):
    note = {
        "left": c.left,
        "right": c.right,
        "left_tip": c.left_tip,
        "base": c.base,
        "head": c.head,
        "path": file.path,
        "old_path": file.old,
        **line_ranges(lines, side),
        "excerpt": "\n".join(line.kind + line.text for line in lines),
        "body": body,
    }
    if c.right == WORKTREE:
        note.update(group=file.group, file_version=file_version(file))
        if diff_lines and lines:
            neighbors = {}
            for name in ("old", "new"):
                if not note[name]:
                    continue
                start, end = note[name]
                context = {
                    getattr(line, name): line.text
                    for line in diff_lines
                    if line.hunk == lines[0].hunk and getattr(line, name) is not None
                }
                neighbors[name] = {
                    str(number - (start if number < start else end)): context[number]
                    for number in (*range(start - 3, start), *range(end + 1, end + 4))
                    if number in context
                }
            note["neighbors"] = neighbors
    return note


def note_matches_file(c, file, note):
    if (note["left"], note["right"], note["path"]) != (c.left, c.right, file.path):
        return False
    if c.right == WORKTREE:
        return (
            note["group"] == file.group
            and note["old_path"] == file.old
            and note["file_version"] == file_version(file)
        )
    return (note["base"], note["head"]) == (c.base, c.head)


def follow_path(file, note):
    return file.path == note["path"] or (file.status == "R" and file.old == note["path"])


def _follow_range(lines, note, side, same_blob):
    """Find the selected side's consecutive lines in a single visible hunk."""
    sign = "+" if side == "new" else "-"
    expected = [s for s in note["excerpt"].split("\n") if s and s[0] in (" ", sign)]
    if not expected or not note[side]:
        return []
    visible = {getattr(line, side): line for line in lines if getattr(line, side) is not None}
    starts = [note[side][0]] if same_blob else visible
    neighbors = note.get("neighbors", {}).get(side, {})
    matches = []
    for start in starts:
        first = visible.get(start)
        if first is None or first.text != expected[0][1:]:
            continue
        end = start + len(expected) - 1
        found = [visible.get(n) for n in range(start, end + 1)]
        if not all(
            line and line.hunk == first.hunk and line.text == word[1:] for line, word in zip(found, expected)
        ):
            continue
        # A staged addition may also be visible as context in the unstaged diff.
        # Only the comparison that actually includes its change owns the note.
        if any(word[0] == sign for word in expected) and not any(
            line.kind == sign and word[0] == sign for line, word in zip(found, expected)
        ):
            continue
        if same_blob:
            return [start, end]
        score = 0
        for offset, text in neighbors.items():
            step = int(offset)
            line = visible.get((start if step < 0 else end) + step)
            if line and line.hunk == first.hunk and text.strip() and line.text == text:
                score += 1
        matches.append((score, start, end))
    if not matches:
        return []
    matches.sort(reverse=True)
    score, start, end = matches[0]
    if len(matches) > 1 and score == matches[1][0]:
        return []
    # A different occurrence can become unique simply because the reviewed
    # block was deleted. Do not ignore contradictory stored context.
    if not score and (
        any(text.strip() for text in neighbors.values()) or not any(word[1:].strip() for word in expected)
    ):
        return []
    return [start, end]


def project_file_note(file, lines, note):
    """Find a local anchor's range in a candidate file from a related comparison."""
    side = "new" if note["new"] else "old"
    old_oid, oid = note["file_version"][:2]
    if not note[side]:
        # Whole-file notes only follow the same reviewed content (the removed
        # blob for a deletion). Line comments can survive later edits.
        same = oid == file.oid and (bool(oid.strip("0")) or old_oid == file.old_oid)
        return dict(note) if same else None
    same_blob = (oid == file.oid) if side == "new" else (old_oid == file.old_oid)
    primary = _follow_range(lines, note, side, same_blob)
    if not primary:
        return None
    result = dict(note, old=[], new=[])
    result[side] = primary
    if side == "new" and note["old"]:
        old = _follow_range(lines, note, "old", old_oid == file.old_oid)
        if old:
            selected = [
                line.kind + line.text
                for line in lines
                if (line.old is not None and old[0] <= line.old <= old[1])
                or (line.new is not None and primary[0] <= line.new <= primary[1])
            ]
            if "\n".join(selected) == note["excerpt"]:
                result["old"] = old
    return result


def location(note):
    parts = []
    for side in ("old", "new"):
        if note[side]:
            first, last = note[side]
            parts.append(f"{side} L{first}" + (f"–{last}" if last != first else ""))
    return " · ".join(parts) or "Whole file"


def fenced(text, language=""):
    ticks = "`" * max(3, 1 + max((len(m[0]) for m in re.finditer(r"`+", text)), default=0))
    return f"{ticks}{language}\n{text}\n{ticks}"


def suggestion_source(note):
    return "\n".join(line[1:] for line in note["excerpt"].split("\n") if line.startswith(("+", " ")))


def receipt_location(receipt):
    first, last = receipt["new"]
    span = f"L{first}" if first == last else f"L{first}–{last}"
    branch = f" on {show(ref_name(receipt['branch']))}" if receipt.get("branch") else ""
    return f"{show(receipt['path'])} · {span}{branch} (before replacement)"


def markdown(repo, stack, notes, *, locations=None, open_only=False):
    if stack is None:
        scope = "Scope: entire repository"
    elif stack:
        scope = "Branch stack: " + " → ".join(show(ref_name(ref)) for ref in stack)
    else:
        scope = "Scope: working tree"
    open_count = sum(not note.get("resolved", False) for note in notes)
    summary = f"{open_count} open"
    instructions = "Address the open comments."
    if open_only:
        notes = [note for note in notes if not note.get("resolved")]
    else:
        summary += f" · {len(notes) - open_count} resolved"
        instructions += " Use resolved comments as review history."
    out = [
        "# Code review · Open comments only" if open_only else "# Code review",
        "",
        f"Repository: {show(repo.root.name)}",
        scope,
        "",
        f"**{summary}**",
        "",
        instructions if open_count else "No open comments need work in this scope.",
        "",
    ]
    if any("suggestion" in n and not n.get("resolved") for n in notes):
        out.extend(
            [
                "Check open suggestions against the current code. An application receipt records a working-file edit. Use the current locations to see whether the change reached the index or a commit.",
                "",
            ]
        )
    for index, note in enumerate(sorted(notes, key=lambda n: bool(n.get("resolved"))), 1):
        if index == 1 and open_count:
            out.extend(["## Open comments", ""])
        if index == open_count + 1:
            out.extend(["## Resolved comments", ""])
        status = "Resolved" if note.get("resolved") else "Open"
        out.extend([f"### {index}. {show(note['path'])}", "", f"- Review status: {status}"])
        if note["right"] == WORKTREE:
            out.extend(
                [
                    f"- Working tree: {show(ref_name(note['left']))} · {note['group']}",
                    f"- Checkout base: {note['left_tip']}",
                    f"- Working tree snapshot: {note['head']}",
                ]
            )
        else:
            out.extend(
                [
                    f"- Comparison: {show(ref_name(note['left']))} → {show(ref_name(note['right']))}",
                    f"- Base tip: {note['left_tip']}",
                    f"- Diff base: {note['base']}",
                    f"- Head: {note['head']}",
                ]
            )
        if note["old_path"] != note["path"]:
            out.append("- Previous path: " + show(note["old_path"]))
        tracked = note["right"] == WORKTREE or "applied_anchor" in note
        label = "Original lines" if tracked and locations is not None else "Lines"
        out.extend([f"- {label}: {location(note)}", ""])
        if tracked and locations is not None:
            matches = locations.get(note.get("id"))
            if matches is None:
                out.extend(
                    [
                        "Current location unverified in the selected stack and checkout. Use the saved excerpt as historical context.",
                        "",
                    ]
                )
            elif not matches:
                out.extend(
                    [
                        "The reviewed lines have no unambiguous match in the current working-tree or stack diffs. The excerpt below is historical.",
                        "",
                    ]
                )
            else:
                for dest in matches:
                    if dest["right"] == WORKTREE:
                        version = (
                            f"{dest['group']} on {show(ref_name(dest['left']))} (file blob {dest['blob']})"
                        )
                    else:
                        version = f"Committed in {show(ref_name(dest['left']))} → {show(ref_name(dest['right']))} (head {dest['head']})"
                    content = "reviewed code"
                    if dest.get("applied_text"):
                        content = "replacement" if note["suggestion"] else "applied deletion"
                    out.append(
                        f"- Current location of {content}: {version} · {show(dest['path'])} · {location(dest)}"
                    )
                out.append("")
        if "suggestion" in note:
            status = "applied to working file" if note.get("applied_location") else "proposed"
            out.extend([f"- Suggestion status: {status}", ""])
            if receipt := note.get("applied_location"):
                out.extend([f"- Applied at: {receipt_location(receipt)}", ""])
            out.extend(["**Original selected code**", "", fenced(suggestion_source(note)), ""])
            if note["suggestion"]:
                out.extend(["**Replacement**", "", fenced(note["suggestion"], "suggestion"), ""])
            else:
                out.extend(["**Replacement**", "", "Delete the selected lines.", ""])
            if earlier := note.get("earlier_application"):
                out.extend(
                    [
                        "**Earlier replacement applied to working file**",
                        "",
                        f"- Applied at: {receipt_location(earlier['applied_location'])}",
                        "",
                        fenced(earlier["suggestion"])
                        if earlier["suggestion"]
                        else "Deleted the selected lines.",
                        "",
                    ]
                )
        elif note["excerpt"]:
            if tracked and locations is not None:
                out.extend(["**Original excerpt**", ""])
            out.extend([fenced(note["excerpt"], "diff"), ""])
        if note["body"]:
            out.extend(["**Reviewer comment**", "", note["body"], ""])
    return "\n".join(out) + "\n"
