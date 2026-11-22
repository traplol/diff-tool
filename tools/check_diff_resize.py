"""Check diff scroll position, focus and inline editing after resizing the sidebar."""

from pathlib import Path

import smoke_native


def actions(driver, kind, events):
    driver.call("POST", "/actions", {"actions": [{"type": kind, "id": kind, "actions": events}]})


def press(driver, key):
    actions(driver, "key", [
        {"type": "keyDown", "value": key},
        {"type": "keyUp", "value": key},
    ])


def click_active(driver, expression):
    element = driver.wait(expression)[smoke_native.ELEMENT]
    driver.call("POST", f"/element/{element}/click", {})


def check_anchor(driver, panes, stage):
    result = driver.call("POST", "/execute/async", {
        "script": """
            const [count, done] = arguments;
            (async () => {
                for (let i = 0; i < 4; i++) await new Promise(requestAnimationFrame);
                const panes = reviewSurface(count);
                const right = panes.at(-1);
                const rect = historyRow(8)?.getBoundingClientRect();
                return {
                    offset: rect && rect.top - right.getBoundingClientRect().top,
                    line: rect?.height,
                    sync: panes[0].scrollTop - right.scrollTop,
                    selection: document.querySelector('#selection').textContent,
                };
            })().then(done, error => done({error: String(error)}));
        """,
        "args": [panes],
    })
    assert result.get("offset") is not None, (stage, result)
    assert abs(result["offset"] - 3) <= result["line"], (stage, result)
    assert abs(result["sync"]) <= 2, (stage, result)
    assert result["selection"] == "new L12", (stage, result)
    print(f"{stage}: entry 8 is {result['offset']:.1f} CSS px from the top", flush=True)


def exercise(driver, _repo, _screenshot):
    driver.call("POST", "/window/rect", {"x": 0, "y": 0, "width": 1380, "height": 840})
    driver.click("#file-list button", "history.txt", False)
    driver.expect_text("#filename", "history.txt")
    driver.wait("[...document.querySelectorAll('#diff .cm-line')].some(el => el.textContent === 'entry 2')")
    surface = Path(__file__).parent / "benchmarks" / "v2" / "active_surface.js"
    driver.script(surface.read_text(encoding="utf-8"))
    driver.script("""
        window.rightPane = () => reviewSurface().at(-1);
        window.historyRow = n => [...rightPane().querySelectorAll('.cm-line')]
            .find(el => el.textContent === 'entry ' + n);
        window.noteBody = () => rightPane().querySelector('[data-note] .bl-body');
    """)

    click_active(driver, "historyRow(2)")
    driver.click("#comment")
    message = ("Please explain how the reviewer can reproduce this change. " * 8).strip()
    driver.fill("dialog textarea", message)
    driver.click("#dialog-actions button", "Save", False)
    saved_body = "!document.querySelector('dialog[open]') && noteBody()?.textContent === arguments[0]"
    driver.wait(saved_body, message)
    driver.click("#split")
    driver.wait("reviewSurface().length === 2 && noteBody()?.textContent === arguments[0]", message)
    old_height = driver.script("return noteBody().getBoundingClientRect().height")

    click_active(driver, "historyRow(11)")
    driver.wait("document.querySelector('#selection').textContent === 'new L12'")
    driver.script("""
        const pane = rightPane();
        pane.scrollTop += historyRow(8).getBoundingClientRect().top - pane.getBoundingClientRect().top - 3;
    """)
    check_anchor(driver, 2, "Initial Split")
    driver.click("#unified")
    check_anchor(driver, 1, "Unified before resize")

    x, y = driver.script("""
        const r = document.querySelector('#divider').getBoundingClientRect();
        return [Math.round(r.left + r.width / 2), Math.round(r.top + r.height / 2)];
    """)
    actions(driver, "pointer", [
        {"type": "pointerMove", "x": x, "y": y},
        {"type": "pointerDown", "button": 0},
        {"type": "pointerMove", "duration": 125, "x": x + 220, "y": y},
        {"type": "pointerUp", "button": 0},
    ])
    driver.wait("document.querySelector('#sidebar').offsetWidth >= arguments[0] + 175", x)
    check_anchor(driver, 1, "Unified after resize")
    driver.script("for (const id of ['split', 'unified', 'split']) document.getElementById(id).click()")
    check_anchor(driver, 2, "Split after rapid switches")

    driver.click("#filter")
    press(driver, "\ue007")  # Enter returns focus to the active editor.
    driver.wait("rightPane().querySelector('.cm-content') === document.activeElement")
    press(driver, "\ue015")  # Arrow Down selects the next new-side line.
    driver.wait("document.querySelector('#selection').textContent === 'new L13'")

    driver.script("rightPane().scrollTop = 0")
    height = driver.wait("noteBody()?.getBoundingClientRect().height")
    assert height > old_height + 8, f"Comment did not reflow ({old_height} → {height}px)"
    click_active(driver, "[...rightPane().querySelectorAll('[data-note] button')].find(b => b.textContent === 'Edit')")
    driver.wait("document.querySelector('dialog textarea')?.value === arguments[0]", message)
    revised = "Reviewed after resizing the sidebar."
    driver.fill("dialog textarea", revised)
    driver.click("#dialog-actions button", "Save", False)
    driver.wait(saved_body, revised)
    driver.click("#unified")
    driver.wait("reviewSurface().length === 1 && noteBody()?.textContent === arguments[0]", revised)
    print(f"Comment reflowed from {old_height:.1f} to {height:.1f}px. Keyboard input and editing passed.")


if __name__ == "__main__":
    # Reuse the smoke runner's disposable Git repository and WebDriver session.
    smoke_native.exercise = exercise
    smoke_native.main()
