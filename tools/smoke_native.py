"""Exercise the packaged Linux desktop app against a disposable checkout and review database.

Run under a graphical session, or with xvfb-run. Requires WebKitWebDriver for
the installed WebKitGTK runtime. The executable must contain its built assets.
"""

import argparse
import base64
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib import error, request

ELEMENT = "element-6066-11e4-a52e-4f735466cecf"
ACTIVE = "#diff .bl-diff:not([inert], [hidden], [inert] *, [hidden] *)"
PANES = f"{ACTIVE} .cm-content"
NOTES = f"{ACTIVE} [data-note]"


def git(repo, *args):
    subprocess.run(
        ["git", "-C", repo, *args],
        check=True,
        capture_output=True,
        env=dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull),
    )


def fixture(repo):
    repo.mkdir()
    git(repo, "init", "-qb", "main")
    git(repo, "config", "user.name", "Branchline Smoke")
    git(repo, "config", "user.email", "smoke@example.test")
    git(repo, "config", "commit.gpgsign", "false")
    path = repo / "cache.txt"
    for branch, value in [
        (None, "one"),
        ("feature/policy", "two"),
        ("feature/metrics", "three"),
    ]:
        if branch:
            git(repo, "switch", "-qc", branch)
        path.write_text(f"capacity = {value}\n", encoding="utf-8")
        git(repo, "add", "cache.txt")
        if branch == "feature/metrics":
            (repo / "history.txt").write_text(
                "".join(f"entry {i}\n" for i in range(300)), encoding="utf-8"
            )
            git(repo, "add", "history.txt")
        git(repo, "commit", "-qm", branch or "Initial capacity")
    path.write_text("capacity = four\n", encoding="utf-8")
    git(repo, "add", "cache.txt")
    path.write_text("capacity = five\n", encoding="utf-8")
    (repo / "new.txt").write_text("review this line\n", encoding="utf-8")


class Driver:
    def __init__(self, port):
        self.url = f"http://127.0.0.1:{port}"
        self.session = ""

    def start_session(self, options):
        info = self.call("POST", "/session", {"capabilities": {"alwaysMatch": options}})
        self.session = "/session/" + info["sessionId"]
        self.options = options

    def close_session(self):
        if self.session:
            self.call("DELETE", "")
            self.session = ""

    def restart_session(self):
        self.close_session()
        self.start_session(self.options)

    def call(self, method, path, data=None):
        body = json.dumps(data).encode() if data is not None else None
        req = request.Request(
            self.url + self.session + path,
            method=method,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with request.urlopen(req, timeout=35) as response:
                return json.load(response)["value"]
        except error.HTTPError as exc:
            raise RuntimeError(f"{method} {path}: {exc.read().decode()}") from exc

    def script(self, script, *args):
        return self.call("POST", "/execute/sync", {"script": script, "args": args})

    def wait(self, condition, *args):
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            value = self.script("return (" + condition + ")", *args)
            if value:
                return value
            time.sleep(0.06)
        status = self.script("return document.body?.innerText")
        raise AssertionError(f"Timed out waiting for {condition} {args!r}\n{status}")

    def find(self, selector, text=None, exact=True):
        found = self.wait(
            """
            [...document.querySelectorAll(arguments[0])].find(el => (el.getClientRects().length || el.tagName === 'OPTION')
              && !el.disabled && (arguments[1] == null ||
              (arguments[2] ? el.textContent.trim() === arguments[1] : el.textContent.includes(arguments[1]))))
        """,
            selector,
            text,
            exact,
        )
        if ELEMENT not in found:
            raise RuntimeError(f"Bad webdriver element: {str(found)[:350]}")
        return found[ELEMENT]

    def click(self, selector, text=None, exact=True):
        el = self.find(selector, text, exact)
        self.call("POST", f"/element/{el}/click", {})

    def double_click(self, selector, text):
        el = self.find(selector, text, False)
        point = self.script("""
            const el = arguments[0].querySelector('td') || arguments[0];
            el.scrollIntoView({block:'nearest',inline:'nearest'});
            const r = el.getBoundingClientRect();
            return [Math.round(r.left+r.width/2),Math.round(r.top+r.height/2)];
        """, {ELEMENT: el})
        actions = [
            {
                "type": "pointerMove",
                "duration": 0,
                "origin": "viewport",
                "x": point[0],
                "y": point[1],
            }
        ]
        for _ in range(2):
            actions.extend(
                [
                    {"type": "pointerDown", "button": 0},
                    {"type": "pointerUp", "button": 0},
                ]
            )
        self.call(
            "POST",
            "/actions",
            {
                "actions": [
                    {
                        "type": "pointer",
                        "id": "mouse",
                        "parameters": {"pointerType": "mouse"},
                        "actions": actions,
                    }
                ]
            },
        )

    def fill(self, selector, text):
        el = self.find(selector)
        self.call("POST", f"/element/{el}/clear", {})
        self.call("POST", f"/element/{el}/value", {"text": text})

    def expect_text(self, selector, text):
        self.wait(
            "document.querySelector(arguments[0])?.innerText.includes(arguments[1])",
            selector,
            text,
        )

    def preview(self, includes=(), excludes=()):
        self.wait(
            """
            [...document.querySelectorAll('dialog[open] textarea')].some(t =>
              arguments[0].every(v => t.value.includes(v)) && arguments[1].every(v => !t.value.includes(v)))
        """,
            includes,
            excludes,
        )


def check_layouts(d):
    for width, height in [(1280, 720), (1920, 1080), (2560, 1440), (3840, 2160)]:
        d.call(
            "POST", "/window/rect", {"x": 0, "y": 0, "width": width, "height": height}
        )
        size = d.wait(
            """
            window.innerWidth >= arguments[0] - 32 && window.innerHeight >= arguments[1] - 80
                && [window.innerWidth,window.innerHeight]
        """,
            width,
            height,
        )
        assert d.script("""
            return ['#choose','#nav','#file-list','#diff','.diff-actions','#export','footer']
                .every(sel => {
                    const box = document.querySelector(sel).getBoundingClientRect();
                    return box.width > 0 && box.height > 0 && box.left >= -1 && box.top >= -1
                        && box.right <= innerWidth + 1 && box.bottom <= innerHeight + 1;
                })
        """), f"An essential control was clipped at {size}"
        print(
            f"Layout passed at {width} × {height} (client {size[0]} × {size[1]})",
            flush=True,
        )
    d.call("POST", "/window/rect", {"x": 0, "y": 0, "width": 1440, "height": 900})


def check_rapid_switch_scroll(d):
    d.click("#file-list button", "history.txt", False)
    d.expect_text(ACTIVE, "entry 0")
    d.click("#split")
    d.click("#unified")
    before, after = d.call(
        "POST",
        "/execute/async",
        {
            "script": """
                const [active, done] = arguments;
                const frame = () => new Promise(requestAnimationFrame);
                const scroller = () => document.querySelector(active + " .cm-scroller");
                (async () => {
                    await frame();
                    await frame();
                    scroller().scrollTop = 3200;
                    await frame();
                    await frame();
                    const before = scroller().scrollTop;
                    document.querySelector('#split').click();
                    document.querySelector('#unified').click();
                    await frame();
                    await frame();
                    done([before, scroller().scrollTop]);
                })();
            """,
            "args": [ACTIVE],
        },
    )
    assert before >= 3199 and abs(before - after) <= 2, (
        f"Rapid layout switch moved from {before} to {after}"
    )


def exercise(d, repo, screenshot):
    d.expect_text("#repo-name", "relay")
    surface = Path(__file__).with_name("benchmarks") / "v2" / "active_surface.js"
    d.script(surface.read_text(encoding="utf-8"))
    d.expect_text("#stack", "feature/policy")
    d.expect_text("#stack", "feature/metrics")
    d.click("[data-tab=Changes]")
    d.expect_text(ACTIVE, "capacity = three")
    check_layouts(d)
    d.script("window.originalUnified = document.querySelector(arguments[0])", PANES)
    d.click("#split")
    d.wait("document.querySelectorAll(arguments[0]).length === 2", PANES)
    d.script("window.reviewSurface(2)")
    d.script(
        "window.originalSplit = [...document.querySelectorAll(arguments[0])]", PANES
    )
    d.click(f"{ACTIVE} .cm-line", "capacity = three", False)
    d.wait("document.querySelector('#suggest').disabled === false")
    d.click("#unified")
    d.wait("document.querySelectorAll(arguments[0]).length === 1", PANES)
    d.script("window.reviewSurface(1)")
    assert d.script(
        "return document.querySelector(arguments[0]) === window.originalUnified", PANES
    ), "Returning to unified recreated its editor"
    d.expect_text(f"{ACTIVE} .bl-row-picked", "capacity = three")
    d.wait("document.querySelector('#suggest').disabled === false")
    d.click("#viewed")
    d.wait("document.querySelector('#viewed').checked")
    d.click("#comment")
    d.fill("dialog textarea", "Confirm the metrics capacity")
    d.click("#dialog-actions button", "Save", False)
    d.expect_text(ACTIVE, "Confirm the metrics capacity")
    if screenshot:
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        screenshot.write_bytes(base64.b64decode(d.call("GET", "/screenshot")))
    d.click(f"{ACTIVE} .bl-row-del")
    d.click("#split")
    assert d.script("""
        const panes = document.querySelectorAll(arguments[0]);
        return panes.length === 2 && window.originalSplit.every((pane, i) => pane === panes[i]);
    """, PANES), "Returning to split recreated an editor"
    d.find(f"{ACTIVE} .bl-row-del.bl-row-picked")
    d.wait("!document.querySelector(arguments[0])", f"{ACTIVE} .bl-row-add.bl-row-picked")
    d.expect_text(f"{NOTES} .bl-body", "Confirm the metrics capacity")
    d.click(f"{NOTES} .bl-disclosure")
    d.click("#unified")
    d.wait(
        "document.querySelector(arguments[0])?.getAttribute('aria-expanded') === 'false'",
        f"{NOTES} .bl-disclosure",
    )
    check_rapid_switch_scroll(d)
    d.click("[data-tab='Comments']")
    d.expect_text("#note-table", "Confirm the metrics capacity")
    d.double_click("#note-table tbody tr", "Confirm the metrics capacity")
    d.wait(
        "document.querySelector('dialog[open] textarea')?.value.includes('Confirm the metrics capacity')"
    )
    d.fill("dialog textarea", "Use the documented metrics capacity")
    d.click("#dialog-actions button", "Save", False)
    d.expect_text("#note-table", "Use the documented metrics capacity")
    d.click("#note-table tbody td", "Use the documented metrics capacity", False)
    d.click("#show-diff")
    d.expect_text(ACTIVE, "Use the documented metrics capacity")
    d.click(f"{NOTES} button", "Resolve")
    d.wait(
        "document.querySelector(arguments[0])?.getAttribute('aria-expanded') === 'false'",
        f"{NOTES} .bl-disclosure",
    )
    d.click("[data-tab='Comments']")
    d.wait(
        "!document.querySelector('#note-table').innerText.includes('Use the documented metrics capacity')"
    )
    d.click("#filters button", "Resolved")
    d.expect_text("#note-table", "Use the documented metrics capacity")
    d.click("#export")
    d.preview(includes=["Use the documented metrics capacity"])
    d.click("dialog input[type=checkbox]")
    d.preview(excludes=["Use the documented metrics capacity"])
    d.click("dialog input[type=checkbox]")
    d.preview(includes=["Use the documented metrics capacity"])
    d.click("dialog [aria-label=Close]")
    d.click("[data-tab='Commits']")
    d.expect_text("#commit-table", "feature/policy")
    d.expect_text("#commit-table", "feature/metrics")
    d.click("#fit")
    d.double_click("#commit-table tbody tr", "feature/metrics")
    d.expect_text("#dialog-body", "Branchline Smoke")
    d.click("dialog [aria-label=Close]")
    d.click("[data-tab='Changes']")
    d.click("#pair option", "Working tree", False)
    for group in ("Staged", "Unstaged", "Untracked"):
        d.expect_text("#file-list", group)
    d.click("#file-list button", "new.txt", False)
    d.expect_text(ACTIVE, "review this line")
    d.click(f"{ACTIVE} .cm-line", "review this line", False)
    d.click("#suggest")
    d.wait("document.querySelectorAll('dialog[open] textarea').length === 2")
    d.fill("#dialog-body label:first-of-type textarea", "revised suggestion")
    d.fill("#dialog-body label:last-of-type textarea", "A suggestion to follow")
    d.click("#dialog-actions button", "Save suggestion")
    d.expect_text(ACTIVE, "revised suggestion")
    d.click(f"{NOTES} button", "Apply to working file")
    d.expect_text(ACTIVE, "Applied to working file")
    assert (repo / "new.txt").read_text(encoding="utf-8") == "revised suggestion\n"
    git(repo, "add", "new.txt")
    d.click("#refresh")
    d.wait("!document.querySelector('#file-list').innerText.includes('Untracked')")
    d.click("#file-list button", "new.txt", False)
    d.expect_text(ACTIVE, "Applied to working file")
    git(repo, "commit", "-qm", "Apply reviewed suggestion")
    d.click("#refresh")
    d.wait("!document.querySelector('#file-list').innerText.includes('new.txt')")
    d.click("#pair option", "Full stack", False)
    d.click("#file-list button", "new.txt", False)
    d.expect_text(ACTIVE, "A suggestion to follow")
    d.click("#export")
    d.preview(includes=["A suggestion to follow", "Committed in", "revised suggestion"])
    d.click("dialog input[type=checkbox]")
    d.preview(
        includes=["A suggestion to follow"],
        excludes=["Use the documented metrics capacity"],
    )
    print(
        "Passed stack, diff, line selection, comment editing and resolution, Markdown filters, "
        "commits, working tree, suggestion apply, and staging/commit tracking."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--binary", type=Path, required=True, help="Packaged Branchline binary"
    )
    parser.add_argument("--driver", type=Path, default=shutil.which("WebKitWebDriver"))
    parser.add_argument(
        "--screenshot", type=Path, help="Save the annotated diff as a PNG"
    )
    args = parser.parse_args()
    if not args.driver or not args.binary.is_file():
        parser.error("Pass an existing Branchline executable and WebKitWebDriver.")
    with tempfile.TemporaryDirectory(
        prefix="branchline-native-smoke-", ignore_cleanup_errors=True
    ) as tmp:
        root = Path(tmp)
        repo = root / "relay"
        fixture(repo)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = dict(
            os.environ,
            XDG_DATA_HOME=str(root / "data"),
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_CACHE_HOME=str(root / "cache"),
            TAURI_WEBVIEW_AUTOMATION="true",
            GDK_BACKEND="x11",
            GDK_SCALE="1",
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
        )
        with subprocess.Popen(
            [str(args.driver.resolve()), f"--port={port}"], env=env
        ) as process:
            d = Driver(port)
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError("WebKitWebDriver exited on startup.")
                    try:
                        d.call("GET", "/status")
                        break
                    except error.URLError:
                        time.sleep(0.05)
                options = {
                    "webkitgtk:browserOptions": {
                        "binary": str(args.binary.resolve()),
                        "args": [str(repo)],
                    }
                }
                d.start_session(options)
                exercise(d, repo, args.screenshot)
            finally:
                try:
                    d.close_session()
                finally:
                    process.terminate()


if __name__ == "__main__":
    main()
