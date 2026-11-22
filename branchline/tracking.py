"""Locate saved working-tree comments in the checkout and its committed stack."""

from functools import cache

from . import git
from .review import (
    comparisons,
    file_version,
    follow_path,
    note_matches_file,
    project_file_note,
)


def location_for(c, file, note):
    location = {
        "left": c.left,
        "right": c.right,
        "base": c.base,
        "head": c.head,
        "path": file.path,
        "group": file.group,
        "old": note["old"],
        "new": note["new"],
    }
    if c.right == git.WORKTREE:
        location["blob"] = file.old_oid if (note["old"] and not note["new"]) or file.status == "D" else file.oid
    return location


def locate_notes(repo, stack, primary, notes):
    """Return one location per matching comparison; omit inconclusive lookups."""
    branch_refs = {repo.checkout if ref == "HEAD" else ref for ref in stack}
    relevant = branch_refs | {repo.checkout}
    anchors = [
        (n["id"], anchor, applied)
        for n in notes
        for applied, anchor in ((False, n), (True, n.get("applied_anchor")))
        if anchor and anchor["right"] == git.WORKTREE and anchor["left"] in relevant
    ]
    empty = repo.refs[git.EMPTY]
    patches = {}
    untracked_paths = {anchor["path"] for _, anchor, _ in anchors if anchor["left"] == repo.checkout}

    @cache
    def comparison(left, right):
        if primary and (primary.left, primary.right) == (left, right):
            return primary
        if right == git.WORKTREE:
            return git.working_tree(repo, left, untracked_paths=untracked_paths)
        return git.compare(repo, left, right)

    @cache
    def common(a, b):
        return a if a == b else git.git(repo.root, "merge-base", a, b).decode().strip()

    @cache
    def descends_from(origin, head):
        if origin == empty or origin == head:
            return True
        return head != empty and bool(
            git.git(repo.root, "rev-list", "--ancestry-path", "--max-count=1", origin + ".." + head, "--")
        )

    @cache
    def since_origin(origin, shared):
        if primary and (primary.base, primary.head) == (origin, shared) and primary.right != git.WORKTREE:
            return primary
        return git.compare_trees(repo, origin, shared, origin, origin, shared)

    def match(c, note):
        exact = next((f for f in c.files if note_matches_file(c, f, note)), None)
        if exact:
            return exact, note
        candidates = []
        for file in c.files:
            if not follow_path(file, note):
                continue
            key = (c.base, c.head, file)
            if key not in patches:
                patches[key] = git.patch(repo, c, file)
            projected = project_file_note(file, patches[key], note)
            if projected is not None:
                side = int(bool(note["new"]))
                same_content = note["file_version"][side] == file_version(file)[side]
                candidates.append(((same_content, file.group == note["group"]), file, projected))
        if candidates:
            best = max(rank for rank, _, _ in candidates)
            winners = [(f, n) for rank, f, n in candidates if rank == best]
            if len(winners) == 1:
                return winners[0]
        return None

    def in_stack(note, source, left, right):
        origin = note["left_tip"]
        if not descends_from(origin, source):
            return None
        shared = common(source, repo.refs[right])
        if shared == origin or not descends_from(origin, shared):
            return None
        c = comparison(left, right)
        if c.base != empty and common(c.base, shared) == shared:
            return None  # The source change was already included in the base of this layer.
        introduced = since_origin(origin, shared)
        seen = match(introduced, note)
        if not seen:
            return None
        file, anchor = seen
        if (c.base, c.head) != (origin, shared):
            # The source change must survive in the destination. Use its confirmed
            # blob and coordinates when comparing the same content in another layer.
            origin_anchor = dict(anchor, path=file.path, file_version=file_version(file))
            seen = match(c, origin_anchor)
            if not seen:
                return None
            file, anchor = seen
        return location_for(c, file, anchor)

    locations = {}
    unavailable = set()
    # An independent advance of the left branch can leave the reviewed diff identical.
    pairs = comparisons(stack)
    for note in notes:
        left, right = note["left"], note["right"]
        if (left, right) in pairs and repo.refs[right] == note["head"] and repo.refs[left] != note["left_tip"]:
            try:
                c = comparison(left, right)
                file = next((f for f in c.files if note_matches_file(c, f, note)), None)
                if file:
                    locations[note["id"]] = {(left, right): location_for(c, file, note)}
            except git.GitError:
                unavailable.add(note["id"])
    for key, note, applied in anchors:
        found = locations.setdefault(key, {})
        matches = []
        branch = note["left"]
        if branch == repo.checkout:
            try:
                local = comparison(branch, git.WORKTREE)
                resolved = match(local, note)
                if resolved and (
                    note_matches_file(local, resolved[0], note) or descends_from(note["left_tip"], local.base)
                ):
                    matches.append(location_for(local, *resolved))
            except (git.GitError, OSError):
                unavailable.add(key)
        source = repo.refs.get("HEAD" if branch.startswith("HEAD@") else branch)
        if branch in branch_refs and source and source != note["left_tip"]:
            for left, right in pairs:
                try:
                    committed = in_stack(note, source, left, right)
                    if committed:
                        matches.append(committed)
                except (git.GitError, OSError):
                    unavailable.add(key)
        for location in matches:
            if applied:
                location["applied_text"] = True
            found[location["left"], location["right"]] = location
    return {key: list(found.values()) for key, found in locations.items() if found or key not in unavailable}
