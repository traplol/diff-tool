"""Exercise context expansion and scoped search in the packaged desktop app."""

import smoke_native
from check_diff_resize import actions
from check_review_controls import chord
from smoke_native import git


def fixture(repo):
    repo.mkdir()
    git(repo, "init", "-qb", "main")
    git(repo, "config", "user.name", "Branchline Smoke")
    git(repo, "config", "user.email", "smoke@example.test")
    git(repo, "config", "commit.gpgsign", "false")
    document = repo / "document.txt"
    lines = [f"document line {n:03d}\n" for n in range(1, 201)]
    document.write_text("".join(lines), encoding="utf-8")
    reference = repo / "reference.txt"
    reference.write_text("reference heading\n🧭 branch reference\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "Add review documents")
    git(repo, "switch", "-qc", "feature/first")
    lines[12] = "intermediate wording\n"
    document.write_text("".join(lines), encoding="utf-8")
    git(repo, "commit", "-qam", "Write the first draft")
    git(repo, "switch", "-qc", "feature/final")
    lines[12] = "revised wording\n"
    lines[164] = "revised conclusion\n"
    document.write_text("".join(lines), encoding="utf-8")
    (repo / "appendix.txt").write_text("searchable appendix\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "Revise the document")
    reference.write_text("different worktree text\n", encoding="utf-8")
    (repo / "draft.txt").write_text("untracked draft\n", encoding="utf-8")


ACTIVE = "#diff .bl-diff:not([inert])"


def expect_hit(d, text, root=ACTIVE):
    d.wait("""[...document.querySelectorAll(arguments[0] + ' .bl-find-current')].some(mark => {
        const hit = mark.getBoundingClientRect();
        const pane = mark.closest('.cm-scroller').getBoundingClientRect();
        return mark.textContent === arguments[1] && hit.top >= pane.top && hit.bottom <= pane.bottom;
    })""", root, text)


def exercise(d, _repo, _screenshot):
    d.expect_text("#stack", "feature/first")
    d.click("#file-list button", "document.txt", False)
    d.expect_text(ACTIVE, "revised wording")
    leading_gap = ACTIVE + " button[data-context-at='0']"
    d.click(leading_gap)
    d.expect_text(ACTIVE, "document line 001")
    d.click("#split")
    d.expect_text(ACTIVE + ".bl-split", "document line 001")

    # Saving from an expanded split view must use logical line 13.
    d.click(ACTIVE + " .cm-line", "revised wording")
    d.click("#comment")
    d.fill("dialog textarea", "Check the final wording")
    d.click("#dialog-actions button", "Save", False)
    d.expect_text(ACTIVE, "Check the final wording")
    d.click("#full-file", "Full file")
    d.click("#full-file", "Changes only")
    d.wait("!document.querySelector(arguments[0]).innerText.includes('document line 001')", ACTIVE)
    d.click("[data-tab=Comments]")
    d.expect_text("#note-table", "new L13")
    d.click("#note-table td", "Check the final wording")
    d.click("#show-diff")
    d.expect_text(ACTIVE, "Check the final wording")
    d.click("#unified")

    chord(d, "\ue009", "f")
    d.fill("#diff-search", "document line 199")
    d.expect_text("#find-status", "No matches")
    d.click("#find-scope option[value=file]")
    expect_hit(d, "document line 199")
    d.find("#collapse-context")
    keys = ["\ue009", "\ue008", "f"]
    actions(d, "key", [
        *({"type": "keyDown", "value": k} for k in keys),
        *({"type": "keyUp", "value": k} for k in reversed(keys)),
    ])
    d.wait("document.querySelector('#find-scope').value === 'comparison'")
    d.fill("#diff-search", "searchable appendix")
    d.click("#find-results button", "appendix.txt", False)
    d.expect_text("#filename", "appendix.txt")
    expect_hit(d, "searchable appendix")

    d.click("#find-scope option[value=branch]")
    d.fill("#diff-search", "branch reference")
    d.click("#find-results button", "reference.txt", False)
    d.expect_text("dialog h2", "reference.txt")
    d.expect_text("#dialog-body", "feature/final")
    expect_hit(d, "branch reference", "dialog")
    d.click("dialog [aria-label=Close]")

    d.click("#find-scope option[value=stack]")
    d.fill("#diff-search", "intermediate wording")
    d.click("#find-results button", "feature/first", False)
    d.expect_text("#range", "feature/first")
    d.expect_text("#filename", "document.txt")
    expect_hit(d, "intermediate wording")
    d.fill("#diff-search", "untracked draft")
    d.click("#find-results button", "draft.txt", False)
    d.expect_text("#range", "Working tree")
    d.expect_text("#filename", "draft.txt")
    expect_hit(d, "untracked draft")
    print("Passed context expansion, comment anchors, and all five search scopes.")


if __name__ == "__main__":
    smoke_native.fixture = fixture
    smoke_native.exercise = exercise
    smoke_native.main()
