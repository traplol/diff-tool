"""Time file-tree selection and layout clicks in a fresh packaged Linux Tauri app."""

import os
import runpy
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.error import URLError

from display import capture_click

TOOLS = Path(__file__).resolve().parent.parent
Driver = runpy.run_path(str(TOOLS / "smoke_native.py"))["Driver"]
PROBE = Path(__file__).with_name("native_layout_probe.js").read_text(encoding="utf-8")


def evaluate(driver, script, *args):
    result = driver.call(
        "POST",
        "/execute/async",
        {
            "script": "const done = arguments[arguments.length-1]; "
            + "Promise.resolve().then(() => ("
            + script
            + ")).then("
            + "result => done({result: result ?? null}), err => done({error: String(err)}));",
            "args": list(args),
        },
    )
    if "error" in result:
        raise AssertionError(result["error"])
    return result["result"]


def select(driver, text, label, *, extend=False):
    # Normal WebDriver mouse input selects the first line. Shift+Down extends it.
    driver.click("#diff .bl-pane:last-child .cm-line", text, False)
    if extend:
        driver.script("""
            document.activeElement.dispatchEvent(new KeyboardEvent("keydown", {
                key: "ArrowDown", shiftKey: true, bubbles: true, cancelable: true,
            }));
        """)
    driver.wait(
        "document.querySelector('#selection').textContent === arguments[0]", label
    )


def measure(driver, large):
    driver.call("POST", "/window/rect", {"x": 0, "y": 0, "width": 1380, "height": 840})
    driver.wait("""document.querySelector('#filename')?.textContent === 'small.py' &&
        document.querySelector('#diff .cm-content') && !document.querySelector('#app').hasAttribute('aria-busy')""")
    assert driver.script("return [innerWidth,innerHeight]") == [1380, 840]
    # Use a real WebDriver mouse click to get GTK's client-to-X11 offset.
    driver.script("""window.addEventListener("click", e => { window.layoutScreenOffset = [
        e.screenX - e.clientX, e.screenY - e.clientY]; }, {capture:true,once:true});""")
    driver.click("#file-list button[aria-label='small.py']")
    offset = driver.script("return window.layoutScreenOffset")
    driver.script(PROBE)
    evaluate(driver, "window.layoutProbe.settle()")
    out = {
        "ready_ms": {},
        "frame_ms": {},
        "gap_ms": {},
        "checks": {},
        "frame_control_ms": evaluate(driver, "window.layoutProbe.frameControl()"),
    }

    def click(key, selector, panes, label="", top=""):
        expected = {
            "panes": panes,
            "marker": "rule_16:" if large else "enabled_10:",
            "selection": label,
            "top": top,
            "card": "" if large else "Review rules at 10.",
        }
        point = driver.script(
            "return window.layoutProbe.arm(...arguments)", selector, expected, offset
        )
        with capture_click(*point["xy"], point["box"]) as capture:
            result = evaluate(driver, "window.layoutProbe.finish()")
        out[key] = capture.elapsed_ms
        out["gap_ms"][key] = capture.gap_ms
        out["ready_ms"][key] = result["ready_ms"]
        out["frame_ms"][key] = result["frame_ms"]
        out["checks"][key] = result["state"]

    click("open_ms", "#file-list button[aria-label='policy.py']", 1)
    stats = driver.script("return document.querySelector('#file-stats').textContent")
    assert stats == ("+10000  −10000" if large else "+4000  −0"), stats
    if large:
        label, top = "new L16", "@@"
        select(driver, 'return "after 16"', label)
    else:
        label, top = "new L10–11", "enabled_3:"
        select(driver, "enabled_10:", label, extend=True)
        evaluate(driver, "window.layoutProbe.setTop(arguments[0])", top)
    click("to_split_ms", "#split", 2, label, top)
    if not large:
        label, top = "new L13–14", "enabled_5:"
        select(driver, "enabled_13:", label, extend=True)
        evaluate(driver, "window.layoutProbe.setTop(arguments[0])", top)
    click("to_unified_ms", "#unified", 1, label, top)
    click("repeat_split_ms", "#split", 2, label, top)
    return out


def sample(
    driver_bin: Path, binary: Path, repo: Path, data_home: Path, large: bool
) -> dict:
    with tempfile.TemporaryDirectory(
        prefix="branchline-layout-", ignore_cleanup_errors=True
    ) as tmp:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = dict(
            os.environ,
            XDG_DATA_HOME=str(data_home.resolve()),
            XDG_CONFIG_HOME=tmp + "/config",
            XDG_CACHE_HOME=tmp + "/cache",
            TAURI_WEBVIEW_AUTOMATION="true",
            GDK_BACKEND="x11",
            GDK_SCALE="1",
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
        )
        driver = Driver(port)
        with subprocess.Popen(
            [str(driver_bin.resolve()), f"--port={port}"], env=env
        ) as process:
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError("WebKitWebDriver exited on startup")
                    try:
                        driver.call("GET", "/status")
                        break
                    except URLError:
                        time.sleep(0.05)
                caps = {
                    "webkitgtk:browserOptions": {
                        "binary": str(binary.resolve()),
                        "args": [str(repo.resolve())],
                    }
                }
                info = driver.call(
                    "POST", "/session", {"capabilities": {"alwaysMatch": caps}}
                )
                driver.session = "/session/" + info["sessionId"]
                return measure(driver, large)
            finally:
                try:
                    if driver.session:
                        driver.call("DELETE", "")
                finally:
                    process.terminate()
