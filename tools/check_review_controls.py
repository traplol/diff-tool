"""Exercise diff search and saved review settings in the packaged desktop app."""

import json

import smoke_native
from check_diff_resize import actions, press


def chord(driver, modifier, key):
    actions(driver, "key", [
        {"type": "keyDown", "value": modifier},
        {"type": "keyDown", "value": key},
        {"type": "keyUp", "value": key},
        {"type": "keyUp", "value": modifier},
    ])


def check_search(d):
    d.expect_text("#diff", "capacity = three")
    control, shift, enter, escape = "\ue009", "\ue008", "\ue007", "\ue00c"
    current_line = "document.querySelector('.bl-diff:not([inert]) .bl-find-current')?.closest('.cm-line')?.textContent"
    chord(d, control, "f")
    d.wait("document.activeElement.id === 'diff-search'")
    d.fill("#diff-search", "capacity")
    d.expect_text("#find-status", "1 of 2")
    d.wait(current_line + " === 'capacity = one'")
    press(d, enter)
    d.expect_text("#find-status", "2 of 2")
    d.wait(current_line + " === 'capacity = three'")
    press(d, enter)
    d.expect_text("#find-status", "1 of 2")
    chord(d, shift, enter)
    d.expect_text("#find-status", "2 of 2")
    d.click("#split")
    chord(d, control, "f")
    d.fill("#diff-search", "one")
    d.wait(current_line + " === 'capacity = one'")
    d.fill("#diff-search", "THREE")
    d.wait(current_line + " === 'capacity = three'")
    d.fill("#diff-search", "no such text")
    d.expect_text("#find-status", "No matches")
    press(d, escape)
    d.wait("document.activeElement.matches('.bl-diff:not([inert]) .cm-content')")
    chord(d, control, "p")
    d.wait("document.activeElement.id === 'filter'")
    d.fill("#filter", "history")
    d.expect_text("#filename", "history.txt")
    chord(d, control, "f")
    d.fill("#diff-search", "entry 299")
    d.wait(current_line + " === 'entry 299'")
    d.wait("""(() => {
        const hit = document.querySelector('.bl-diff:not([inert]) .bl-find-current');
        if (!hit) return false;
        const row = hit.getBoundingClientRect(), pane = hit.closest('.cm-scroller').getBoundingClientRect();
        return row.top >= pane.top && row.bottom <= pane.bottom;
    })()""")
    assert d.script("return document.querySelector('#filter').value") == "history"
    press(d, escape)


def check_saved_settings(d, repo):
    # Save a distinct base, resize the sidebar, and make the old head disappear.
    d.click("#edit-stack")
    d.click("dialog button", "Remove")
    d.click("dialog button", "Review stack")
    d.wait("!document.querySelector('dialog[open]')")
    d.wait("document.querySelector('#stack li').textContent.includes('feature/policy')")
    original_width = d.script("""
        document.getElementById('divider').focus();
        return document.getElementById('sidebar').offsetWidth;
    """)
    press(d, "\ue014")  # Arrow Right
    width = d.wait("""
        document.getElementById('sidebar').offsetWidth > arguments[0]
        && document.getElementById('sidebar').offsetWidth
    """, original_width)
    smoke_native.git(repo, "branch", "-m", "feature/new-head")
    d.call("POST", "/refresh", {})
    d.expect_text("#range", "feature/new-head")
    d.wait("document.querySelector('#stack li').textContent.includes('feature/policy')")
    d.wait("document.querySelector('#split').getAttribute('aria-pressed') === 'true'")
    d.wait("document.getElementById('sidebar').offsetWidth === arguments[0]", width)
    config = json.loads((repo.parent / "config/branchline/config.json").read_text(encoding="utf-8"))
    assert config["sidebar_width"] == width and config["diff_layout"] == "split"
    assert config["repositories"][str(repo)]["base_branch"] == "refs/heads/feature/policy"


def exercise(d, repo, _screenshot):
    check_search(d)
    check_saved_settings(d, repo)
    print("Diff search, file filter, saved base after head rename, sidebar width and split layout passed.")


if __name__ == "__main__":
    smoke_native.exercise = exercise
    smoke_native.main()
