"""Exercise context expansion and scoped search in the packaged desktop app."""

import smoke_native
from check_diff_resize import actions, press
from check_review_controls import OPTIONS, QUERY, chord, pick_palette, search_palette
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
    grouped = repo / "groups.txt"
    grouped.write_text("value = baseline\n", encoding="utf-8")
    reference.write_text("reference heading\n🧭 branch reference\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "Add review documents")
    git(repo, "switch", "-qc", "outside-review")
    (repo / "outside.txt").write_text("outside stack content\n", encoding="utf-8")
    git(repo, "add", "outside.txt")
    git(repo, "commit", "-qm", "Outside stack commit")
    git(repo, "switch", "-q", "main")
    git(repo, "switch", "-qc", "feature/first")
    lines[12] = "intermediate wording\n"
    document.write_text("".join(lines), encoding="utf-8")
    git(repo, "commit", "-qam", "Write the first draft")
    git(repo, "switch", "-qc", "feature/final")
    lines[12] = "revised wording\n"
    lines[164] = "revised conclusion\n"
    document.write_text("".join(lines), encoding="utf-8")
    (repo / "appendix.txt").write_text(
        "searchable appendix\n" + "x" * 170 + " complete-hit-tail with trailing characters\n",
        encoding="utf-8",
    )
    (repo / "occurrences.txt").write_text(
        "😀 document line 010 covered here zz zz\n   spaced literal target   \n", encoding="utf-8"
    )
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "Revise the document")
    reference.write_text("different worktree text\n", encoding="utf-8")
    grouped.write_text("value = working identity staged\n", encoding="utf-8")
    git(repo, "add", "groups.txt")
    grouped.write_text("value = working identity unstaged\n", encoding="utf-8")
    (repo / "draft.txt").write_text(
        "untracked draft\nvalue = working identity untracked\n", encoding="utf-8"
    )


ACTIVE = "#diff .bl-diff:not([inert])"


def resize(d, width, height):
    d.call("POST", "/window/rect", {"x": 0, "y": 0, "width": width, "height": height})
    d.wait("innerWidth === arguments[0] && innerHeight === arguments[1]", width, height)


def after_layout(d):
    d.call("POST", "/execute/async", {
        "script": """
            const done = arguments[0];
            (async () => {
                for (let i = 0; i < 4; i++) await new Promise(requestAnimationFrame);
                done(true);
            })();
        """,
        "args": [],
    })


HIT_POINT = """(() => {
    const target = [...document.querySelectorAll(arguments[0])].find(node =>
        !node.disabled && (arguments[1] == null || node.textContent.trim() === arguments[1]));
    if (!target) return false;
    const r = target.getBoundingClientRect();
    const x = Math.round(r.left + r.width / 2), y = Math.round(r.top + r.height / 2);
    return target.contains(document.elementFromPoint(x, y)) && [x, y];
})()"""


def click_visible(d, selector, text=None, scroll=False):
    if scroll:
        after_layout(d)
        if not d.script("return " + HIT_POINT, selector, text):
            target = d.find(selector, text)
            d.script("""const target = arguments[0], pane = target.closest('.cm-scroller');
                const box = target.getBoundingClientRect(), viewport = pane.getBoundingClientRect();
                pane.scrollTop += box.top + box.height / 2 - viewport.top - viewport.height / 2;
            """, {smoke_native.ELEMENT: target})
            after_layout(d)
    x, y = d.wait(HIT_POINT, selector, text)
    actions(d, "pointer", [
        {"type": "pointerMove", "origin": "viewport", "x": x, "y": y},
        {"type": "pointerDown", "button": 0},
        {"type": "pointerUp", "button": 0},
    ])


def expect_hit(d, text, root=ACTIVE):
    d.wait("""[...document.querySelectorAll(arguments[0] + ' .bl-find-current')].some(mark => {
        const hit = mark.getBoundingClientRect();
        const pane = mark.closest('.cm-scroller').getBoundingClientRect();
        return mark.textContent === arguments[1] && hit.top >= pane.top && hit.bottom <= pane.bottom;
    })""", root, text)


def check_incremental_gap(d):
    # The changed lines at 13 and 165 leave lines 17–161 hidden.
    at = d.wait("""[...document.querySelectorAll(arguments[0] + ' .bl-context [data-context-at]')]
        .find(b => b.closest('.bl-context').textContent.includes('145'))?.dataset.contextAt""", ACTIVE)
    gap = ACTIVE + f" [data-context-at='{at}']"
    block = ACTIVE + f" .bl-context:has([data-context-at='{at}'])"
    top = ACTIVE + f" .cm-gutter [data-context-at='{at}'][data-context-action=top]"
    bottom = ACTIVE + f" .cm-gutter [data-context-at='{at}'][data-context-action=bottom]"
    reveal_rest = gap + "[data-context-action=all]"
    collapse = gap + "[data-context-action=collapse]"
    d.script("window.originalUnified = document.querySelector(arguments[0] + ' .cm-content')", ACTIVE)
    d.click("#split")
    d.wait("document.querySelectorAll(arguments[0] + ' .cm-content').length === 2", ACTIVE)
    d.script("window.originalSplit = [...document.querySelectorAll(arguments[0] + ' .cm-content')]", ACTIVE)

    def expect_step(button, hidden):
        d.expect_text(block, f"{hidden} lines hidden")
        after_layout(d)
        assert d.script("return " + HIT_POINT, button), f"{button} scrolled out of view"
        assert d.script("return document.activeElement.matches(arguments[0])", button), (
            f"{button} lost focus after expanding to {hidden} hidden lines"
        )
        assert d.script("""const panes = [...document.querySelectorAll(arguments[0] + ' .cm-scroller')];
            return Math.abs(panes[0].scrollTop - panes[1].scrollTop) <= 2;
        """, ACTIVE), "Expanding context desynchronized the split panes"

    click_visible(d, top, scroll=True)
    expect_step(top, 125)
    press(d, "\ue007")
    expect_step(top, 105)
    assert d.script("""return [...document.querySelectorAll(arguments[0] + ' .cm-content')]
        .every((pane, i) => pane === window.originalSplit[i]);
    """, ACTIVE), "Expanding context recreated a split pane"

    click_visible(d, bottom)
    expect_step(bottom, 85)
    at_seam = """(() => {
      const panes = [...document.querySelectorAll(arguments[0] + ' .cm-content')];
      return panes.length === 2 && panes.every(pane => {
        const rows = [...pane.querySelectorAll('.cm-line')].map(r => r.textContent);
        const last = rows.indexOf('document line 056');
        return last >= 0 && rows[last + 1] === arguments[1]
            && rows.lastIndexOf('document line 056') === last
            && rows.lastIndexOf(arguments[1]) === last + 1;
      });
    })()"""
    d.wait(at_seam, ACTIVE, "document line 142")
    press(d, "\ue007")
    expect_step(bottom, 65)
    d.wait(at_seam, ACTIVE, "document line 122")

    d.click("#unified")
    d.expect_text(block, "65 lines hidden")
    assert d.script("""return document.querySelector(arguments[0] + ' .cm-content')
        === window.originalUnified;
    """, ACTIVE), "Expanding context discarded the cached unified pane"
    button = d.find(reveal_rest)
    assert "65 lines hidden" in d.call("GET", f"/element/{button}/computedlabel")
    click_visible(d, reveal_rest, scroll=True)
    d.wait("""[...document.querySelectorAll(arguments[0] + ' .cm-line')].some(row => {
        const pane = row.closest('.cm-scroller').getBoundingClientRect();
        const r = row.getBoundingClientRect();
        return row.textContent === 'document line 057' && r.top >= pane.top && r.bottom <= pane.bottom;
    })""", ACTIVE)
    after_layout(d)
    assert d.script("""const focus = document.activeElement;
        if (!focus.matches(arguments[0] + ' .cm-content') &&
            !focus.matches(arguments[0] + ' [data-context-action]')) return false;
        if (focus.matches('.cm-content')) return true;
        const r = focus.getBoundingClientRect();
        const pane = focus.closest('.cm-scroller').getBoundingClientRect();
        return r.top >= pane.top && r.bottom <= pane.bottom;
    """, ACTIVE), "Opening the remaining lines lost focus at the gap"
    scroll = d.script("return document.activeElement.closest('.cm-scroller').scrollTop")
    press(d, "\ue015")  # Down continues from the visible code.
    after_layout(d)
    assert d.script("""const active = document.activeElement;
        const pane = active.closest('.cm-scroller');
        return active.matches('.cm-content') && pane &&
            Math.abs(pane.scrollTop - arguments[0]) < pane.clientHeight / 2;
    """, scroll), "ArrowDown moved away from the expanded gap or lost editor focus"
    d.find("#full-file", "Full file")

    # The collapse control now sits at the top of the 145-line block.
    d.script("document.querySelector(arguments[0] + ' .cm-scroller').scrollTop = 0", ACTIVE)
    d.expect_text(collapse, "Collapse 145 lines")
    click_visible(d, collapse, scroll=True)
    d.expect_text(block, "145 lines hidden")


def check_split_file_search(d):
    d.click("#split")
    for line in (158, 199, 2, 120, 167, 59, 200, 158):
        query = f"document line {line:03d}"
        search_palette(d, query, "file")
        pick_palette(d, query)
        expect_hit(d, query)
        d.wait("""(() => {
            const panes = [...document.querySelectorAll(arguments[0] + ' .cm-scroller')];
            return panes.length === 2 && Math.abs(panes[0].scrollTop - panes[1].scrollTop) <= 2;
        })()""", ACTIVE)
    d.click("#unified")


def check_horizontal_search(d):
    target = "complete-hit-tail"
    fully_visible = """[...document.querySelectorAll(arguments[0] + ' .bl-find-current')]
        .some(mark => {
            if (mark.textContent !== arguments[1]) return false;
            const box = mark.getBoundingClientRect();
            const y = (box.top + box.bottom) / 2;
            return mark.contains(document.elementFromPoint(box.left + 1, y)) &&
                mark.contains(document.elementFromPoint(box.right - 1, y));
        })"""
    d.click("#file-list button", "appendix.txt", False)
    for layout in ("unified", "split"):
        d.click("#" + layout)
        search_palette(d, "searchable appendix", "patch")
        pick_palette(d, "searchable appendix")
        expect_hit(d, "searchable appendix")
        for scope in ("patch", "comparison"):
            search_palette(d, target, scope)
            pick_palette(d, target)
            d.wait(fully_visible, ACTIVE, target)


def check_scoped_search(d):
    search_palette(d, "document line 199", "patch")
    d.expect_text("#palette-status", "No matches")
    d.click("#palette-scope option[value=file]")
    pick_palette(d, "document line 199")
    expect_hit(d, "document line 199")
    d.find("#collapse-context")

    search_palette(d, "searchable appendix", "comparison")
    pick_palette(d, "searchable appendix")
    d.expect_text("#filename", "appendix.txt")
    expect_hit(d, "searchable appendix")

    search_palette(d, "branch reference", "branch")
    pick_palette(d, "reference.txt")
    d.expect_text("#dialog[open] h2", "reference.txt")
    d.expect_text("#dialog-body", "feature/final")
    expect_hit(d, "branch reference", "#dialog")
    d.click("#dialog [aria-label=Close]")

    search_palette(d, "intermediate wording", "stack")
    pick_palette(d, "intermediate wording")
    d.expect_text("#range", "feature/first")
    d.expect_text("#filename", "document.txt")
    expect_hit(d, "intermediate wording")

    search_palette(d, "untracked draft", "stack")
    pick_palette(d, "untracked draft")
    d.expect_text("#range", "Working tree")
    d.expect_text("#filename", "draft.txt")
    expect_hit(d, "untracked draft")
    search_palette(d, "different worktree text", "comparison")
    pick_palette(d, "different worktree text")
    d.expect_text("#filename", "reference.txt")
    expect_hit(d, "different worktree text")


def check_global_search(d):
    d.click("#stack-review")
    d.expect_text("#range", "feature/final")
    search_palette(d, "appendix")
    d.wait("""[...document.querySelectorAll(arguments[0])].some(option =>
        option.dataset.searchKind === 'text' &&
        option.querySelector('.palette-preview mark')?.textContent === 'appendix')""", OPTIONS)
    assert d.script("return document.querySelector(arguments[0]).dataset.searchKind", OPTIONS) == "path"
    pick_palette(d)
    d.expect_text("#filename", "appendix.txt")

    search_palette(d, "Check the final wording")
    pick_palette(d, "Check the final wording", "comment")
    d.expect_text(ACTIVE + " [data-note]", "Check the final wording")

    search_palette(d, "Revise the document")
    pick_palette(d, "Revise the document", "commit")
    d.expect_text("#dialog[open] h2", "Commit details")
    d.expect_text("#dialog-body", "Revise the document")
    d.click("#dialog [aria-label=Close]")

    search_palette(d, "feature/first")
    pick_palette(d, "feature/first", "branch")
    d.expect_text("#range", "feature/first")
    d.wait("document.activeElement.id === 'pair'")


def check_repeated_search(d):
    d.click("#stack-review")
    d.expect_text("#range", "feature/final")
    search_palette(d, "0 covered", "comparison")
    d.find(OPTIONS, "occurrences.txt", False)
    d.fill(QUERY, "missing stale query")
    d.fill(QUERY, "zz")
    marks = OPTIONS + " .palette-preview mark[data-hit]"
    new_results = """(() => {
        const options = document.querySelectorAll(arguments[0]);
        if (options.length !== 1 || options[0].dataset.searchKind !== 'text') return false;
        const row = options[0];
        const marks = [...row.querySelectorAll('.palette-preview mark[data-hit]')];
        return row.querySelector('.palette-title').textContent.includes('occurrences.txt') &&
            marks.length === 2 && marks.every(mark => mark.textContent === 'zz');
    })()"""
    d.wait(new_results, OPTIONS)
    after_layout(d)
    assert d.script("return " + new_results, OPTIONS), "An older query replaced the palette results"

    def active_match():
        return d.script("return document.querySelector(arguments[0] + '.palette-current')?.dataset.hit", marks)

    first = active_match()
    assert first is not None
    press(d, "\ue013")  # Up wraps to the second occurrence on the same line.
    assert active_match() not in (None, first)
    press(d, "\ue015")  # Down wraps back to the first occurrence.
    assert active_match() == first
    press(d, "\ue015")
    pick_palette(d)
    second_occurrence = """const hit = document.querySelector(arguments[0] + ' .bl-find-current');
        const prefix = document.createRange();
        prefix.selectNodeContents(hit.closest('.cm-line'));
        prefix.setEndBefore(hit);
        return prefix.toString() === '😀 document line 010 covered here zz ';
    """
    expect_hit(d, "zz")
    assert d.script(second_occurrence, ACTIVE), "The second occurrence after a surrogate pair jumped to an incorrect offset"
    search_palette(d, "zz", "comparison")
    d.wait(new_results, OPTIONS)
    d.click(marks + ":last-of-type")
    d.wait("!document.getElementById('search-palette').open")
    expect_hit(d, "zz")
    assert d.script(second_occurrence, ACTIVE), "Clicking a later preview mark chose the first occurrence"


def check_literal_search(d):
    d.click("#file-list button", "occurrences.txt", False)
    d.expect_text(ACTIVE, "spaced literal target")
    for scope in ("patch", "file"):
        query = "   spaced literal target   "
        search_palette(d, query, scope)
        pick_palette(d, "spaced literal target")
        expect_hit(d, query)
        search_palette(d, "   ", scope)
        d.expect_text("#palette-status", "2 results")
        pick_palette(d, "spaced literal target")
        expect_hit(d, "   ")
    print("Passed literal surrounding-space and whitespace-only palette queries.")


def hold_search_response(d, preview):
    # Hold delivery after native Git answers, leaving other IPC callbacks live.
    d.script("""const callbacks = window.__TAURI_INTERNALS__.callbacks;
        const original = callbacks.set, preview = arguments[0];
        window.restorePaletteDelivery = () => {
            delete callbacks.set;
            window.releasePaletteResponse?.();
        };
        window.releasePaletteResponse = null;
        callbacks.set = function(id, callback) {
            return original.call(this, id, result => {
                if (!window.releasePaletteResponse &&
                    result?.hits?.some(hit => hit.text.includes(preview))) {
                    window.releasePaletteResponse = () => callback(result);
                    return;
                }
                callback(result);
            });
        };
    """, preview)


def check_stale_search_response(d):
    d.click("#stack-review")
    d.expect_text("#range", "feature/final")
    presented = """const list = document.getElementById('palette-results');
        return [list.innerHTML, document.getElementById('palette-status').textContent,
                document.getElementById('palette-query').getAttribute('aria-activedescendant')];
    """
    for dismiss in (None, "close", "refresh"):
        hold_search_response(d, "zz zz")
        try:
            search_palette(d, "zz", "comparison")
            d.wait("typeof window.releasePaletteResponse === 'function'")
            if dismiss:
                press(d, "\ue00c")
                d.wait("!document.getElementById('search-palette').open")
                if dismiss == "refresh":
                    d.click("#refresh")
                search_palette(d, "searchable appendix", "comparison")
            else:
                d.fill(QUERY, "searchable appendix")
            d.expect_text(OPTIONS, "searchable appendix")
            d.expect_text("#palette-status", "1 result")
            current = d.script(presented)
            d.script("window.restorePaletteDelivery()")
            after_layout(d)
            assert d.script(presented) == current, "A late native reply changed the palette after replacement"
            press(d, "\ue00c")
            d.wait("!document.getElementById('search-palette').open")
        finally:
            d.script("""if (Object.hasOwn(window.__TAURI_INTERNALS__.callbacks, 'set'))
                window.restorePaletteDelivery();
            """)
    print("Passed delayed native response invalidation on input replacement, close/reopen, and refresh.")


def check_worktree_group_search(d, scope="comparison", marker="working identity"):
    d.click("#local-review")
    d.expect_text("#range", "Working tree")
    for (width, height), layout in [((1280, 720), "unified"), ((720, 460), "split")]:
        resize(d, width, height)
        d.click("#" + layout)
        for group, path in (
            ("Staged", "groups.txt"),
            ("Unstaged", "groups.txt"),
            ("Untracked", "draft.txt"),
        ):
            line = f"value = {marker} {group.lower()}"
            search_palette(d, marker, scope)
            option = d.wait("""[...document.querySelectorAll(arguments[0])].find(option =>
                option.dataset.searchKind === 'text' &&
                option.querySelector('.palette-meta')?.textContent.startsWith(arguments[1] + ' ·') &&
                option.querySelector('.palette-title')?.textContent.includes(arguments[2]) &&
                option.querySelector('.palette-preview')?.textContent === arguments[3]
            )?.id""", OPTIONS, group, path, line)
            d.click("#" + option)
            d.wait("!document.getElementById('search-palette').open")
            d.expect_text("#filename", path)
            d.wait("""(() => {
                const selected = document.querySelector('#file-list button[aria-pressed=true]');
                return selected?.getAttribute('aria-label') === arguments[0] &&
                    selected.closest('details')?.querySelector('summary').textContent.trim() === arguments[1];
            })()""", path, group)
            expect_hit(d, marker)
            d.wait("""document.querySelector(arguments[0] + ' .bl-find-current')
                ?.closest('.cm-line')?.textContent === arguments[1]""", ACTIVE, line)
        print(f"Passed staged, same-path unstaged, and untracked palette jumps at {width}×{height}.")


def check_current_review_scope(d, repo):
    def no_matches(query):
        search_palette(d, query)
        assert d.script("return document.querySelector('#palette-scope').selectedOptions[0].textContent") == "Current review"
        d.expect_text("#palette-status", "No matches")
        assert d.script("return document.querySelectorAll(arguments[0]).length", OPTIONS) == 0
        press(d, "\ue00c")
        d.wait("!document.getElementById('search-palette').open")

    def save_comment(path, line, body):
        d.click("#file-list button", path, False)
        d.expect_text(ACTIVE, line)
        click_visible(d, ACTIVE + " .cm-line", line, scroll=True)
        d.click("#comment")
        d.fill("#dialog textarea", body)
        d.click("#dialog-actions button", "Save", False)
        d.expect_text(ACTIVE, body)

    def select_stack(branch):
        d.click("#edit-stack")
        d.fill("[aria-label='Filter available refs']", branch)
        d.click("#dialog-body button", "Find stack", False)
        d.expect_text("#dialog-body", "Found the branch order")
        d.click("#dialog-actions button", "Review stack", False)
        d.wait("!document.getElementById('dialog').open")
        d.expect_text("#range", branch)

    # Make a genuine comment in another stack and restore the saved review.
    resize(d, 1280, 720)
    d.click("#unified")
    select_stack("outside-review")
    save_comment("outside.txt", "outside stack content", "Scope note from a different stack")
    select_stack("feature/final")

    # The working changes carry over because these files are identical at both HEADs.
    git(repo, "switch", "-q", "outside-review")
    d.click("#refresh")
    d.wait("!document.getElementById('app').hasAttribute('aria-busy')")
    d.click("#local-review")
    d.expect_text("#range", "outside-review")
    save_comment("draft.txt", "untracked draft", "Scope note from unrelated checkout")

    # Current review while viewing an off-stack checkout stays local.
    for query in (
        "appendix.txt", "searchable appendix", "Revise the document", "feature/first",
        "Check the final wording", "Scope note from a different stack",
    ):
        no_matches(query)
    search_palette(d, "Scope note from unrelated checkout")
    pick_palette(d, "Scope note from unrelated checkout", "comment")
    d.expect_text(ACTIVE, "Scope note from unrelated checkout")
    check_worktree_group_search(d, "all")

    # The saved review scope excludes the unrelated checkout and unchanged files.
    resize(d, 1280, 720)
    d.click("#stack-review")
    d.expect_text("#range", "feature/final")
    for query in (
        "working identity", "groups.txt", "draft.txt", "reference.txt", "outside-review",
        "Scope note from unrelated checkout", "Scope note from a different stack",
    ):
        no_matches(query)
    search_palette(d, "Check the final wording")
    pick_palette(d, "Check the final wording", "comment")
    d.expect_text(ACTIVE, "Check the final wording")
    search_palette(d, "reference.txt", "branch")
    pick_palette(d, "reference.txt", "path")
    d.expect_text("#dialog[open] h2", "reference.txt")
    d.click("#dialog [aria-label=Close]")
    print("Passed Current review isolation, explicit Branch files, and related comment jumps.")


def check_search_worktree_snapshot(d, repo):
    old_marker, fresh_marker = "working identity", "refreshed identity"

    def refresh():
        d.click("#refresh")
        d.wait("!document.getElementById('app').hasAttribute('aria-busy')")
        d.expect_text("#range", "feature/final")

    def expect_groups(marker):
        for group in ("Staged", "Unstaged", "Untracked"):
            d.wait("""[...document.querySelectorAll(arguments[0])].some(option =>
                option.dataset.searchKind === 'text' &&
                option.querySelector('.palette-meta')?.textContent.startsWith(arguments[1] + ' ·') &&
                option.querySelector('.palette-preview')?.textContent === arguments[2]
            )""", OPTIONS, group, f"value = {marker} {group.lower()}")

    def close_palette():
        press(d, "\ue00c")
        d.wait("!document.getElementById('search-palette').open")

    def expect_absent(marker):
        search_palette(d, marker)
        d.expect_text("#palette-status", "No matches")
        close_palette()

    # Keep the committed comparison open so the first search prepares a
    # noncurrent working-tree snapshot only after the query is entered.
    git(repo, "switch", "-q", "feature/final")
    refresh()
    hold_search_response(d, f"value = {old_marker} untracked")
    try:
        search_palette(d, old_marker)
        d.wait("typeof window.releasePaletteResponse === 'function'")
        d.expect_text("#palette-status", "Searching")
        d.fill(QUERY, "searchable appendix")
        d.expect_text(OPTIONS, "searchable appendix")
    finally:
        d.script("window.restorePaletteDelivery()")
    after_layout(d)
    assert d.script("""return [...document.querySelectorAll(arguments[0])].every(option =>
        !option.textContent.includes(arguments[1]))""", OPTIONS, old_marker)
    d.expect_text(OPTIONS, "searchable appendix")
    close_palette()

    search_palette(d, old_marker)
    expect_groups(old_marker)
    close_palette()
    grouped = repo / "groups.txt"
    grouped.write_text(f"value = {fresh_marker} staged\n", encoding="utf-8")
    git(repo, "add", "groups.txt")
    grouped.write_text(f"value = {fresh_marker} unstaged\n", encoding="utf-8")
    (repo / "draft.txt").write_text(
        f"untracked draft\nvalue = {fresh_marker} untracked\n", encoding="utf-8"
    )

    search_palette(d, old_marker)
    expect_groups(old_marker)
    close_palette()
    expect_absent(fresh_marker)
    refresh()
    expect_absent(old_marker)
    search_palette(d, fresh_marker)
    expect_groups(fresh_marker)
    close_palette()
    check_worktree_group_search(d, "all", fresh_marker)
    print("Passed cold query replacement and frozen working-tree search until Refresh.")


def check_keyboard_comment_controls(d):
    click_visible(d, ACTIVE + " .cm-line", "revised wording", scroll=True)
    for _ in range(10):
        chord(d, "\ue008", "\ue015")  # Shift+Down crosses into the second hunk.
    d.wait("document.querySelector('#comment').disabled")
    chord(d, "\ue008", "\ue03a")  # Shift+F10
    disabled = d.script("""return [...document.querySelectorAll('.bl-diff-menu button')]
        .find(button => button.textContent === 'Add comment')?.disabled;""")
    assert disabled is True, "The diff menu offered a cross-hunk line comment"
    press(d, "\ue00c")  # Escape returns to the diff.
    d.wait("document.activeElement.matches(arguments[0] + ' .cm-content')", ACTIVE)
    click_visible(d, ACTIVE + " .cm-line", "revised wording", scroll=True)
    d.wait("!document.querySelector('#comment').disabled")


def check_inline_comment_focus(d):
    card = ACTIVE + " [data-note]"
    d.script("""[...document.querySelectorAll(arguments[0] + ' button')]
        .find(button => button.textContent === 'Resolve').focus();""", card)
    press(d, "\ue007")  # Enter resolves the comment.
    d.wait("document.activeElement.matches(arguments[0] + '.bl-resolved .bl-disclosure')", card)
    press(d, "\ue007")  # Expand the resolved comment.
    d.wait("document.activeElement.getAttribute('aria-expanded') === 'true'")
    press(d, "\ue004")  # Edit
    press(d, "\ue004")  # Reopen
    assert d.script("return document.activeElement.textContent === 'Reopen'")
    press(d, "\ue007")
    d.wait("""document.activeElement.matches(arguments[0] + ':not(.bl-resolved) .bl-disclosure')""", card)


def exercise(d, _repo, _screenshot):
    d.expect_text("#stack", "feature/first")
    for width, height in [(1280, 720), (720, 460)]:
        resize(d, width, height)
        d.click("#file-list button", "appendix.txt", False)
        d.expect_text(ACTIVE, "searchable appendix")
        d.click("#file-list button", "document.txt", False)
        d.expect_text(ACTIVE, "revised wording")
        check_incremental_gap(d)
        check_split_file_search(d)
        print(f"Context expansion and Split file search passed at {width}×{height}.", flush=True)
    resize(d, 720, 460)
    check_horizontal_search(d)
    resize(d, 1280, 720)
    d.click("#unified")
    d.click("#file-list button", "appendix.txt", False)
    d.expect_text(ACTIVE, "searchable appendix")
    d.click("#file-list button", "document.txt", False)
    d.expect_text(ACTIVE, "revised wording")
    check_keyboard_comment_controls(d)
    leading_gap = ACTIVE + " button[data-context-at='0']"
    d.click(leading_gap)
    d.expect_text(ACTIVE, "document line 001")
    d.click("#split")
    d.expect_text(ACTIVE + ".bl-split", "document line 001")

    # Saving from an expanded split view must use logical line 13.
    click_visible(d, ACTIVE + " .cm-line", "revised wording", scroll=True)
    d.click("#comment")
    d.fill("dialog textarea", "Check the final wording")
    d.click("#dialog-actions button", "Save", False)
    d.expect_text(ACTIVE, "Check the final wording")
    check_inline_comment_focus(d)
    d.click("#full-file", "Full file")
    d.click("#full-file", "Changes only")
    d.wait("!document.querySelector(arguments[0]).innerText.includes('document line 001')", ACTIVE)
    d.click("[data-tab=Comments]")
    d.expect_text("#note-table", "new L13")
    d.click("#note-table td", "Check the final wording")
    d.click("#show-diff")
    d.expect_text(ACTIVE, "Check the final wording")
    d.click("#unified")

    check_scoped_search(d)
    check_global_search(d)
    check_repeated_search(d)
    check_literal_search(d)
    check_stale_search_response(d)
    check_worktree_group_search(d)
    check_current_review_scope(d, _repo)
    check_search_worktree_snapshot(d, _repo)
    print("Passed context expansion, comment anchors, scoped palette jumps, and occurrence offsets.")


if __name__ == "__main__":
    smoke_native.fixture = fixture
    smoke_native.exercise = exercise
    smoke_native.main()
