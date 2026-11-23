"""Check busy search and review actions at the minimum desktop window size."""

import base64

import smoke_native
from check_diff_resize import actions, press
from check_review_context import after_layout, fixture as stack_fixture
from check_review_controls import OPTIONS, pick_palette, search_palette

ACTIVE = "#diff .bl-diff:not([inert])"
LONG_PATH = (
    "src/a/b/c/d/e/f/g/h/"
    "enterprise-payment-retry-scheduling-and-settlement-reconciliation.js"
)


def fixture(repo):
    stack_fixture(repo)
    folder = repo / "busy"
    folder.mkdir()
    for index in range(160):
        heading = f"File {index}"
        if index == 159:
            heading += " with a deliberately long code line that extends beyond the pane"
        (folder / f"{index:03d}-notes.md").write_text(
            f"{heading}\nneedle {index}\n", encoding="utf-8"
        )
    long_file = repo / LONG_PATH
    long_file.parent.mkdir(parents=True)
    long_file.write_text("export const settlementRetryWindow = 20;\n")
    smoke_native.git(repo, "add", "busy", LONG_PATH)
    smoke_native.git(repo, "commit", "-qm", "Add files for review search")


def visible_center(driver, selector, text=None):
    return driver.wait("""(() => {
        const node = [...document.querySelectorAll(arguments[0])].find(el =>
            arguments[1] == null || el.textContent === arguments[1]);
        if (!node) return false;
        const rect = node.getBoundingClientRect();
        const x = Math.floor(rect.x + rect.width / 2);
        const y = Math.floor(rect.y + rect.height / 2);
        return node.contains(document.elementFromPoint(x, y)) && [x, y];
    })()""", selector, text)


def expect_hit(driver, index):
    driver.expect_text("#filename", f"{index:03d}-notes.md")
    driver.wait("""(() => {
        const hit = document.querySelector(arguments[0] + ' .bl-find-current');
        if (!hit || hit.textContent !== 'needle') return false;
        const mark = hit.getBoundingClientRect();
        const pane = hit.closest('.cm-scroller').getBoundingClientRect();
        const gutter = hit.closest('.cm-editor').querySelector('.cm-gutters')
            .getBoundingClientRect();
        const y = (mark.top + mark.bottom) / 2;
        return mark.left >= gutter.right && mark.right <= pane.right &&
            mark.top >= pane.top && mark.bottom <= pane.bottom &&
            [mark.left + 1, mark.right - 1].every(x =>
                hit.closest('.cm-line').contains(document.elementFromPoint(x, y)));
    })()""", ACTIVE)


def check_footer(driver):
    driver.wait("""(() => {
        const footer = document.querySelector('.diff-actions').getBoundingClientRect();
        const status = document.querySelector('footer').getBoundingClientRect();
        return ['#comment', '#suggest'].every(selector => {
            const button = document.querySelector(selector).getBoundingClientRect();
            return button.left >= footer.left && button.right <= footer.right &&
                button.top >= footer.top && button.bottom <= footer.bottom &&
                button.bottom <= status.top;
        });
    })()""")
    visible_center(driver, "#comment")
    visible_center(driver, "#suggest")


def check_inline_suggestion(driver):
    driver.click("#suggest")
    driver.expect_text("dialog[open] h2", "New suggestion")
    driver.fill("dialog textarea.replacement", "needle 159 revised")
    driver.script("""document.querySelector('dialog textarea:not(.replacement)')
        .scrollIntoView({block: 'center'});""")
    driver.fill(
        "dialog textarea:not(.replacement)",
        "Please retain the original ordering so a later retry cannot be recorded "
        "before the first settlement completes.",
    )
    driver.click("#dialog-actions button", "Save suggestion")
    card = ACTIVE + " [data-note]"
    driver.expect_text(card + " .bl-after", "needle 159 revised")
    driver.wait("""(() => {
        const card = document.querySelector(arguments[0]);
        const body = card?.querySelector('.bl-body');
        return body?.offsetWidth >= 140 && body.offsetHeight < 300 &&
            [...card.querySelectorAll('button')].every(button => {
                const box = button.getBoundingClientRect();
                const panel = card.getBoundingClientRect();
                return box.left >= panel.left && box.right <= panel.right;
            });
    })()""", card)
    driver.script("""document.querySelector(arguments[0])
        .closest('.cm-scroller').scrollLeft = 70;""", card)
    driver.wait("""(() => {
        const thread = document.querySelector(arguments[0]);
        const pane = thread?.closest('.cm-scroller');
        if (!pane || pane.scrollLeft < 50) return false;
        const box = thread.getBoundingClientRect();
        const viewport = pane.getBoundingClientRect();
        return box.left >= viewport.left && box.right <= viewport.left + pane.clientWidth;
    })()""", card)
    for name in ("Edit", "Resolve", "Apply to working file"):
        driver.script("""[...document.querySelectorAll(arguments[0] + ' button')]
            .find(button => button.textContent === arguments[1])
            .scrollIntoView({block: 'center', inline: 'nearest'});""", card, name)
        visible_center(driver, card + " .bl-card-actions button", name)


def check_comments_table(driver):
    driver.fill("#filter", "enterprise-payment")
    driver.expect_text("#filename", LONG_PATH)
    visible_center(driver, f'#file-list button[aria-label="{LONG_PATH}"]')
    driver.click("#comment")
    driver.fill("dialog textarea", "Document which API owns this retry timeout.")
    driver.click("#dialog-actions button", "Save comment")
    driver.wait("!document.querySelector('#dialog').open")
    driver.click("#tab-comments")
    driver.click("#scope option[value=all]")
    driver.wait("""(() => {
        const path = [...document.querySelectorAll('#note-table .comment-path')]
            .find(cell => cell.textContent === arguments[0]);
        const table = path?.closest('.table-wrap');
        return table?.clientHeight >= 120 && table.scrollWidth <= table.clientWidth &&
            path.clientWidth >= 120 && path.offsetHeight < 160;
    })()""", LONG_PATH)


def exercise(driver, _repo, screenshot):
    driver.call("POST", "/window/rect", {"x": 0, "y": 0, "width": 720, "height": 460})
    driver.wait("innerWidth === 720 && innerHeight === 460 && document.querySelector('#sidebar').hidden")
    driver.click("#split")
    search_palette(driver, "needle", "comparison")
    driver.expect_text("#palette-status", "160 results")
    pick_palette(driver, "000-notes.md")
    expect_hit(driver, 0)
    search_palette(driver, "e", "comparison")
    driver.expect_text("#palette-status", "Refine your search")
    driver.wait("document.querySelector(arguments[0])?.dataset.searchKind === 'path'", OPTIONS)
    press(driver, "\ue00c")
    driver.expect_text("#filename", "000-notes.md")

    driver.click("#sidebar-toggle")
    x, y = visible_center(driver, "#divider")
    actions(driver, "pointer", [
        {"type": "pointerMove", "x": x, "y": y},
        {"type": "pointerDown", "button": 0},
        {"type": "pointerMove", "duration": 125, "x": 700, "y": y},
        {"type": "pointerUp", "button": 0},
    ])
    driver.wait("""(() => {
        const bar = document.querySelector('#sidebar').getBoundingClientRect();
        const app = document.querySelector('#app').getBoundingClientRect();
        return Math.abs(bar.width - app.width * 0.24) < 1;
    })()""")
    diff_geometry = """const box = document.querySelector('#diff').getBoundingClientRect();
        return [box.x, box.y, box.width, box.height];"""
    before = driver.script(diff_geometry)
    search_palette(driver, "needle", "comparison")
    driver.expect_text("#palette-status", "160 results")
    assert driver.script(diff_geometry) == before, "Palette results changed the compact diff geometry"
    selected = OPTIONS + '[aria-selected="true"]'
    press(driver, "\ue013")  # Wrap from the first file to the last.
    driver.expect_text(selected, "159-notes.md")
    for width, height in ((1280, 720), (720, 460)):
        driver.call("POST", "/window/rect", {"width": width, "height": height})
        driver.wait("innerWidth === arguments[0] && innerHeight === arguments[1]", width, height)
        after_layout(driver)
        driver.expect_text(selected, "159-notes.md")
        visible_center(driver, selected + " .palette-preview mark", "needle")
    pick_palette(driver)
    expect_hit(driver, 159)
    check_footer(driver)
    if screenshot:
        after_layout(driver)
        screenshot.write_bytes(base64.b64decode(driver.call("GET", "/screenshot")))

    driver.click("#filter")
    driver.wait("document.activeElement.id === 'filter'")
    visible_center(driver, "#filter")
    row = ACTIVE + " .cm-line"
    driver.click(row, "needle 159")
    check_footer(driver)
    check_inline_suggestion(driver)
    check_comments_table(driver)
    print("Passed compact Split search, inline suggestion, and Comments layouts.")


if __name__ == "__main__":
    smoke_native.fixture = fixture
    smoke_native.exercise = exercise
    smoke_native.main()
