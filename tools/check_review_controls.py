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


PALETTE = "#search-palette"
QUERY = "#palette-query"
OPTIONS = "#palette-results [role=option]"
ACTIVE = "#diff .bl-diff:not([inert])"


def open_palette(d, scope="all"):
    d.wait("!document.querySelector('#app').hasAttribute('aria-busy')")
    chord(d, "\ue009", "f")
    d.wait("document.querySelector(arguments[0]).open && document.activeElement.id === 'palette-query'", PALETTE)
    d.wait("document.querySelector('#palette-scope').value === 'all'")
    if scope != "all":
        d.click(f"#palette-scope option[value={scope}]")


def search_palette(d, query, scope="all"):
    open_palette(d, scope)
    d.fill(QUERY, query)


def pick_palette(d, text=None, kind="text"):
    if text is None:
        press(d, "\ue007")
    else:
        d.click(f'{OPTIONS}[data-search-kind="{kind}"]', text, False)
    d.wait("!document.querySelector(arguments[0]).open", PALETTE)


def check_navigation(d):
    d.expect_text("#diff", "capacity = three")
    d.click("#tab-commits")
    d.expect_text("#commit-table", "feature/metrics")
    press(d, "\ue014")  # Arrow Right
    d.wait("document.querySelector('#tab-comments').getAttribute('aria-selected') === 'true'")
    press(d, "\ue011")  # Home
    d.wait("!document.querySelector('#changes').hidden")

    d.click("#tab-commits")
    d.click("#local-review")
    d.expect_text("#range", "Working tree")
    d.wait("!document.getElementById('app').hasAttribute('aria-busy')")
    assert d.script("return !document.querySelector('#changes').hidden"), "Working tree opened on Commits"
    d.expect_text("#diff", "capacity = four")
    staged_open = """[...document.querySelectorAll('#file-list summary')]
        .find(node => node.textContent.trim() === 'Staged')?.parentElement.open"""
    d.click("#file-list summary", "Staged")
    d.wait(f"({staged_open}) === false")
    d.fill("#filter", "cache.txt")
    d.wait(staged_open)
    press(d, "\ue00c")
    d.wait(f"({staged_open}) === false")
    d.click("#stack-review")
    d.expect_text("#diff", "capacity = three")
    d.click("#sidebar-toggle")
    d.wait("document.querySelector('#sidebar').hidden")
    set_size(d, 840, 600)
    set_size(d, 1280, 720)
    assert d.script("return document.querySelector('#sidebar').hidden"), "Resize discarded sidebar choice"
    d.click("#sidebar-toggle")
    d.wait("!document.querySelector('#sidebar').hidden")

    d.click("#tab-comments")
    d.click("#search-review")
    d.wait("document.activeElement.id === 'palette-query' && document.querySelector('#palette-scope').value === 'all'")
    press(d, "\ue00c")  # Escape retains the page and restores the actual opener.
    d.wait("document.activeElement.id === 'search-review'")
    d.wait("document.getElementById('tab-comments').getAttribute('aria-selected') === 'true'")
    d.click("#export")
    draft_at_top = """[...document.querySelectorAll('dialog[open] textarea')].some(field =>
        field.value.length > 0 && field.scrollTop === 0 && field.selectionStart === 0 && field.selectionEnd === 0)"""
    d.wait(draft_at_top)
    d.click("dialog input[type=checkbox]")
    d.wait(draft_at_top)
    d.click("dialog [aria-label=Close]")


def check_file_rows(d):
    d.click("#tab-changes")
    cache = "#file-list button[aria-label='cache.txt']"
    history = "#file-list button[aria-label='history.txt']"
    d.script("window.cacheRow = document.querySelector(arguments[0])", cache)
    d.click(history)
    d.expect_text("#diff", "entry 3")
    d.click(cache)
    d.expect_text("#diff", "capacity = three")
    d.click("#viewed")
    d.expect_text("#progress", "1 of 2 files viewed")
    d.fill("#filter", "cache")
    d.wait("!document.querySelector(arguments[0])?.getClientRects().length", history)
    assert d.script("return document.querySelector(arguments[0]) === window.cacheRow", cache), "Filter or selection rebuilt the file row"
    press(d, "\ue00c")  # Clear the filter with Escape.
    d.find(history)
    d.click("#viewed")
    d.expect_text("#progress", "0 of 2 files viewed")


def set_size(d, width, height):
    d.call("POST", "/window/rect", {"x": 0, "y": 0, "width": width, "height": height})
    d.wait("innerWidth === arguments[0] && innerHeight === arguments[1]", width, height)
    d.call("POST", "/execute/async", {
        "script": "const done = arguments[0]; requestAnimationFrame(() => requestAnimationFrame(() => done(true)))",
        "args": [],
    })


def check_search(d):
    d.expect_text("#diff", "capacity = three")
    control, shift, down, up, escape = "\ue009", "\ue008", "\ue015", "\ue013", "\ue00c"
    d.click("#find")
    d.wait("document.activeElement.id === 'palette-query' && document.querySelector('#palette-scope').value === 'all'")
    press(d, escape)
    d.wait("document.activeElement.id === 'find'")
    current_line = "document.querySelector('.bl-diff:not([inert]) .bl-find-current')?.closest('.cm-line')?.textContent"
    selected = OPTIONS + '[aria-selected="true"]'
    geometry = """['#file-list', '#diff', '.diff-actions'].map(selector => {
        const box = document.querySelector(selector).getBoundingClientRect();
        return [box.x, box.y, box.width, box.height];
    })"""
    before = d.script("return " + geometry)
    d.script("document.querySelector(arguments[0] + ' .cm-content').focus()", ACTIVE)
    search_palette(d, "capacity", "patch")
    d.wait("document.querySelectorAll(arguments[0]).length === 2", OPTIONS)
    d.expect_text(selected, "capacity = one")
    press(d, down)
    d.expect_text(selected, "capacity = three")
    press(d, down)
    d.expect_text(selected, "capacity = one")
    press(d, up)
    d.expect_text(selected, "capacity = three")
    assert d.script("return " + geometry) == before, "Previewing results moved the review layout"
    assert not d.script("return " + current_line), "Previewing results jumped the diff"
    pick_palette(d)
    d.wait(current_line + " === 'capacity = three'")
    d.wait("document.activeElement.matches(arguments[0] + ' .cm-content')", ACTIVE)

    d.click("#split")
    search_palette(d, "one", "patch")
    pick_palette(d, "capacity = one")
    d.wait(current_line + " === 'capacity = one'")
    search_palette(d, "THREE", "patch")
    pick_palette(d, "capacity = three")
    d.wait(current_line + " === 'capacity = three'")
    search_palette(d, "no such text", "patch")
    d.expect_text("#palette-status", "No matches")
    press(d, escape)
    d.wait("document.activeElement.matches(arguments[0] + ' .cm-content')", ACTIVE)

    chord(d, control, "p")
    d.wait("document.activeElement.id === 'palette-query' && document.querySelector('#palette-scope').value === 'all'")
    d.fill(QUERY, "history")
    d.wait("document.querySelector(arguments[0])?.dataset.searchKind === 'path'", OPTIONS)
    pick_palette(d, "history.txt", "path")
    d.expect_text("#filename", "history.txt")
    d.fill("#filter", "history")
    actions(d, "key", [
        {"type": "keyDown", "value": control},
        {"type": "keyDown", "value": shift},
        {"type": "keyDown", "value": "f"},
        {"type": "keyUp", "value": "f"},
        {"type": "keyUp", "value": shift},
        {"type": "keyUp", "value": control},
    ])
    d.wait("document.activeElement.id === 'palette-query' && document.querySelector('#palette-scope').value === 'all'")
    d.click("#palette-scope option[value=patch]")
    d.fill(QUERY, "entry 299")
    pick_palette(d, "entry 299")
    d.wait(current_line + " === 'entry 299'")
    d.wait("""(() => {
        const hit = document.querySelector('.bl-diff:not([inert]) .bl-find-current');
        if (!hit) return false;
        const row = hit.getBoundingClientRect(), pane = hit.closest('.cm-scroller').getBoundingClientRect();
        return row.top >= pane.top && row.bottom <= pane.bottom;
    })()""")
    assert d.script("return document.querySelector('#filter').value") == "history"


def check_keyboard_recovery(d):
    alt, shift = "\ue00a", "\ue008"
    down, f10, escape = "\ue015", "\ue03a", "\ue00c"
    d.click("#tab-commits")
    d.expect_text("#commit-table", "feature/metrics")
    d.script("document.querySelector('#commit-table tbody tr[tabindex]').focus()")
    chord(d, shift, f10)
    d.expect_text("[role=menu]", "Copy full SHA")
    press(d, escape)
    d.wait("document.activeElement.matches('#commit-table tbody tr')")
    d.click("#tab-changes")
    d.fill("#filter", "cache.txt")
    d.expect_text("#filename", "cache.txt")
    d.script("document.querySelector('#pair').focus()")
    chord(d, alt, down)
    press(d, escape)
    d.expect_text("#filename", "cache.txt")
    assert d.script("return document.activeElement.id === 'pair'")
    d.click("#stack-review")
    d.expect_text("#diff", "capacity = three")
    d.fill("#filter", "no-file-matches-this")
    d.expect_text("#diff", "No changed files match the filter.")
    open_palette(d, "patch")
    chord(d, "\ue009", "a")
    press(d, "\ue003")  # Backspace clears the search input.
    d.expect_text("#palette-status", "Search files")
    d.script("""const status = document.getElementById('palette-status');
        window.searchStatuses = [];
        const observer = new MutationObserver(() => window.searchStatuses.push(status.textContent));
        observer.observe(status, {childList: true, characterData: true, subtree: true});
        window.stopSearchStatusObserver = () => observer.disconnect();
    """)
    d.fill(QUERY, "capacity")
    d.expect_text("#palette-status", "Choose a text file")
    assert d.script("""window.stopSearchStatusObserver();
        return window.searchStatuses.some(text => text.includes('Searching'));
    """), "The palette skipped the loading state"
    press(d, escape)
    d.wait("document.activeElement.id === 'filter'")
    press(d, escape)
    d.expect_text("#diff", "capacity = three")


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
    set_size(d, 1280, 720)
    check_navigation(d)
    check_file_rows(d)
    check_search(d)
    check_keyboard_recovery(d)
    check_saved_settings(d, repo)
    print("Diff search, file filter, saved base after head rename, sidebar width and split layout passed.")


if __name__ == "__main__":
    smoke_native.exercise = exercise
    smoke_native.main()
