"""Read only the recorded GUI and its descendants. Run over foreground SSH."""
import base64
import json
import os
from pathlib import Path
import resource
import sys
import time

expected = json.loads(base64.b64decode(sys.argv[1]))
period = .020
limit = 60
max_processes = 64
ticks = os.sysconf("SC_CLK_TCK")


def stat(path):
    text = path.read_text()
    end = text.rfind(") ")
    fields = text[end + 2:].split()
    return {"pid": int(text.split(" ", 1)[0]), "comm": text[text.find("(") + 1:end],
            "state": fields[0], "ppid": int(fields[1]), "utime": int(fields[11]),
            "stime": int(fields[12]), "start_ticks": fields[19]}


def read_process(pid):
    directory = Path("/proc") / str(pid)
    first = stat(directory / "stat")
    try:
        binary = os.readlink(directory / "exe")
        exe_error = None
    except OSError as error:
        binary, exe_error = None, type(error).__name__
    current = stat(directory / "stat")
    if current["start_ticks"] != first["start_ticks"]:
        raise ProcessLookupError("PID identity changed during observation")
    current.update(binary=binary)
    if exe_error: current["exe_error"] = exe_error
    return current


def matches_root(process):
    return all(process.get(key) == expected[key] for key in ("pid", "start_ticks", "binary"))


def emit(value):
    print(json.dumps(value, separators=(",", ":")), flush=True)


def sample(root):
    queue = [(root, None)]
    result, errors, seen = [], [], set()
    while queue:
        process, parent = queue.pop()
        pid = process["pid"]
        if pid in seen: continue
        seen.add(pid)
        if len(seen) > max_processes: raise RuntimeError("Descendant limit exceeded")
        if parent is not None and process["ppid"] != parent: continue
        directory = Path("/proc") / str(pid)
        if "WebKit" in (process["binary"] or "") or process["comm"].startswith("WebKit"):
            try:
                main = stat(directory / "task" / str(pid) / "stat")
                if main["start_ticks"] != process["start_ticks"]:
                    raise ProcessLookupError("Main-thread identity changed")
                process["main_thread"] = main
            except OSError as error:
                process["main_thread_error"] = type(error).__name__
        result.append(process)
        try:
            children = (directory / "task" / str(pid) / "children").read_text().split()
            # Revalidate the parent before using its descendant list.
            if stat(directory / "stat")["start_ticks"] != process["start_ticks"]:
                continue
            for child in children:
                if len(seen) + len(queue) >= max_processes:
                    raise RuntimeError("Descendant limit exceeded")
                try: queue.append((read_process(int(child)), pid))
                except OSError as error: errors.append({"pid": int(child), "error": type(error).__name__})
        except OSError as error:
            errors.append({"pid": pid, "children_error": type(error).__name__})
    return result, errors


started = time.monotonic()
count, reason, error = 0, "deadline", None
webkit = {}
try:
    root = read_process(expected["pid"])
    if not matches_root(root): raise RuntimeError("Recorded GUI identity does not match")
    emit({"kind": "ready", "diagnostic_only": True, "root": expected,
          "observer": read_process(os.getpid()), "ticks_per_second": ticks,
          "target_period_ms": 20, "max_seconds": limit, "max_processes": max_processes})
    next_sample = started
    while time.monotonic() - started < limit and count < 3000:
        begin = time.monotonic_ns()
        wall = time.time_ns()
        try: root = read_process(expected["pid"])
        except OSError:
            reason = "root_gone"
            break
        if not matches_root(root):
            reason = "root_identity_changed"
            break
        processes, errors = sample(root)
        for process in processes:
            if "main_thread" in process:
                webkit[(process["pid"], process["start_ticks"])] = {
                    key: process[key] for key in ("pid", "start_ticks", "binary", "comm")}
        emit({"kind": "sample", "index": count, "monotonic_ns": begin,
              "wall_ns": wall, "read_duration_ns": time.monotonic_ns() - begin,
              "processes": processes, "read_errors": errors})
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
          "duration_s": time.monotonic() - started, "webkit_seen": list(webkit.values()),
          "observer_cpu_s": usage.ru_utime + usage.ru_stime})
if reason not in ("root_gone", "root_identity_changed"): raise SystemExit(1)
