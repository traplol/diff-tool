"""Bounded thread ticks for one exact WebKit process descended from the owned GUI."""
import base64
import json
import os
from pathlib import Path
import resource
import sys
import time

root = json.loads(base64.b64decode(sys.argv[1]))
webkit_binary = "/usr/lib/x86_64-linux-gnu/webkit2gtk-4.1/WebKitWebProcess"
max_threads, period, max_seconds = 256, .020, 60


def stat(path):
    text = path.read_text()
    end = text.rfind(") ")
    fields = text[end + 2:].split()
    return {"pid": int(text.split(" ", 1)[0]), "comm": text[text.find("(") + 1:end],
            "state": fields[0], "ppid": int(fields[1]), "utime": int(fields[11]),
            "stime": int(fields[12]), "start_ticks": fields[19]}


def process(pid):
    directory = Path("/proc") / str(pid)
    before = stat(directory / "stat")
    binary = os.readlink(directory / "exe")
    after = stat(directory / "stat")
    if before["start_ticks"] != after["start_ticks"]: raise ProcessLookupError("PID changed")
    return {**after, "binary": binary}


def same(current, expected):
    return all(current[key] == expected[key] for key in ("pid", "start_ticks", "binary"))


def emit(value):
    print(json.dumps(value, separators=(",", ":")), flush=True)


started = time.monotonic()
count, reason, error, webkit = 0, "deadline", None, None
try:
    actual = process(root["pid"])
    if not same(actual, root): raise RuntimeError("Recorded GUI identity does not match")
    queue, seen, found = [actual], set(), []
    while queue:
        parent = queue.pop()
        if parent["pid"] in seen: continue
        seen.add(parent["pid"])
        if len(seen) > 64: raise RuntimeError("Descendant limit exceeded")
        if parent["binary"] == webkit_binary: found.append(parent)
        directory = Path("/proc") / str(parent["pid"])
        try:
            children = (directory / "task" / str(parent["pid"]) / "children").read_text().split()
            if not same(process(parent["pid"]), parent): continue
            for child in children:
                if len(seen) + len(queue) >= 64: raise RuntimeError("Descendant limit exceeded")
                try: item = process(int(child))
                except OSError: continue
                if item["ppid"] == parent["pid"]: queue.append(item)
        except OSError: continue
    if len(found) != 1: raise RuntimeError(f"Expected one exact WebKitWebProcess, found {len(found)}")
    webkit = found[0]
    directory = Path("/proc") / str(webkit["pid"])
    # Once-only paths, never environments. A loaded library does not prove active use.
    prefixes = ("libEGL", "libGL", "libGLES", "libvulkan", "libgbm", "libdrm", "libgallium",
                "libLLVM", "libepoxy", "libcairo", "libpixman", "libwebkit", "libjavascriptcore", "libgtk")
    libraries = set()
    with (directory / "maps").open() as maps:
        for line in maps:
            parts = line.split(maxsplit=5)
            if len(parts) != 6: continue
            path = parts[5].strip()
            if path.startswith("/") and (Path(path).name.startswith(prefixes) or "_dri.so" in path): libraries.add(path)
    if not same(process(webkit["pid"]), webkit): raise RuntimeError("WebKit identity changed during maps read")
    emit({"kind": "ready", "diagnostic_only": True, "root": root, "webkit": webkit,
          "observer": process(os.getpid()), "ticks_per_second": os.sysconf("SC_CLK_TCK"),
          "target_period_ms": 20, "max_seconds": max_seconds, "max_threads": max_threads,
          "loaded_graphics_library_paths": sorted(libraries), "library_scope": "Presence only; active renderer is unproven"})
    next_sample = time.monotonic()
    while time.monotonic() - started < max_seconds and count < 3000:
        begin, wall = time.monotonic_ns(), time.time_ns()
        try: actual = process(root["pid"])
        except OSError:
            reason = "root_gone"
            break
        if not same(actual, root):
            reason = "root_identity_changed"
            break
        try: current = process(webkit["pid"])
        except OSError:
            reason = "webkit_gone"
            break
        if not same(current, webkit):
            reason = "webkit_identity_changed"
            break
        tids = list((directory / "task").iterdir())
        if len(tids) > max_threads: raise RuntimeError("Thread limit exceeded")
        threads, errors = [], []
        for tid in tids:
            try: threads.append(stat(tid / "stat"))
            except OSError as caught: errors.append({"tid": int(tid.name), "error": type(caught).__name__})
        emit({"kind": "sample", "index": count, "wall_ns": wall, "monotonic_ns": begin,
              "read_duration_ns": time.monotonic_ns() - begin, "process": current,
              "threads": threads, "read_errors": errors})
        count += 1
        next_sample += period
        delay = next_sample - time.monotonic()
        if delay > 0: time.sleep(delay)
        else: next_sample = time.monotonic()
except BaseException as caught:
    reason, error = "error", f"{type(caught).__name__}: {caught}"
finally:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    emit({"kind": "finished", "reason": reason, "error": error, "samples": count,
          "duration_s": time.monotonic() - started, "observer_cpu_s": usage.ru_utime + usage.ru_stime})
if reason in ("deadline", "error"): raise SystemExit(1)
