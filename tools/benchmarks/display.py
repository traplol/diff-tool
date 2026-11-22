"""Time a real X11 click until sampled code pixels reach their final state.

The independent process owns a fresh X connection, even when its caller has Tk
or WebKit running. Start and finish use the same host monotonic clock. The
caller confirms the target view/selection before signaling completion. The
extra settling interval identifies the final pixels and is outside the timer.
"""

import ctypes as c
import json
import select
import subprocess
import sys
import time
import zlib
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Capture:
    elapsed_ms: float = 0
    gap_ms: float = 0


@contextmanager
def capture_click(x, y, box):
    """Click screen pixel (x,y) and watch the code area (x,y,width,height)."""
    args = [
        sys.executable,
        "-I",
        str(Path(__file__).resolve()),
        *map(str, map(round, (x, y, *box))),
    ]
    process = subprocess.Popen(
        args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
    )
    try:
        if not select.select([process.stdout], [], [], 8)[0]:
            raise TimeoutError("X11 observer failed to dispatch the click")
        line = process.stdout.readline()
        if line.strip() != "CLICK":
            raise RuntimeError(
                f"X11 observer failed to dispatch the click: {line.strip()}"
            )
        result = Capture()
        yield result
        output, _ = process.communicate("done\n", timeout=12)
        if process.returncode:
            raise RuntimeError(f"X11 sampling failed: {output.strip()}")
        stats = json.loads(output)
        result.elapsed_ms = stats["elapsed_ms"]
        result.gap_ms = stats["gap_ms"]
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdin.close()
        process.stdout.close()


class XImage(c.Structure):
    # Only XImage's public prefix through bytes_per_line is needed.
    _fields_ = [
        ("width", c.c_int),
        ("height", c.c_int),
        ("xoffset", c.c_int),
        ("format", c.c_int),
        ("data", c.c_void_p),
        ("byte_order", c.c_int),
        ("bitmap_unit", c.c_int),
        ("bitmap_bit_order", c.c_int),
        ("bitmap_pad", c.c_int),
        ("depth", c.c_int),
        ("bytes_per_line", c.c_int),
    ]


def observe(x, y, left, top, width, height):
    x11 = c.CDLL("libX11.so.6")
    xtest = c.CDLL("libXtst.so.6")

    def bind(lib, name, result, *args):
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = args, result
        return fn

    ptr, integer, uint, ulong = c.c_void_p, c.c_int, c.c_uint, c.c_ulong
    display = bind(x11, "XOpenDisplay", ptr, c.c_char_p)(None)
    if not display:
        raise RuntimeError("Could not connect to X11; run on an Xvfb display")
    close = bind(x11, "XCloseDisplay", integer, ptr)
    try:
        root = bind(x11, "XDefaultRootWindow", ulong, ptr)(display)
        screen = bind(x11, "XDefaultScreen", integer, ptr)(display)
        sw = bind(x11, "XDisplayWidth", integer, ptr, integer)(display, screen)
        sh = bind(x11, "XDisplayHeight", integer, ptr, integer)(display, screen)
        if not (
            0 <= x < sw
            and 0 <= y < sh
            and width > 0
            and height >= 8
            and 0 <= left <= sw - width
            and 0 <= top <= sh - height
        ):
            raise ValueError(
                f"Invalid click or sample rectangle {(x, y, left, top, width, height)} on {sw}x{sh}"
            )

        image_ptr = c.POINTER(XImage)
        get = bind(
            x11,
            "XGetImage",
            image_ptr,
            ptr,
            ulong,
            integer,
            integer,
            uint,
            uint,
            ulong,
            integer,
        )
        destroy = bind(x11, "XDestroyImage", integer, image_ptr)
        motion = bind(
            xtest,
            "XTestFakeMotionEvent",
            integer,
            ptr,
            integer,
            integer,
            integer,
            ulong,
        )
        button = bind(xtest, "XTestFakeButtonEvent", integer, ptr, uint, integer, ulong)
        flush = bind(x11, "XFlush", integer, ptr)
        sync = bind(x11, "XSync", integer, ptr, integer)

        # Four bands sample both text and background without transferring a full frame.
        offsets = tuple(round((height - 6) * f) for f in (0.05, 0.31, 0.62, 0.91))

        def pixels():
            value = 0
            for offset in offsets:
                image = get(display, root, left, top + offset, width, 6, ulong(-1), 2)
                if not image:
                    raise RuntimeError("XGetImage failed to read the diff")
                try:
                    frame = image.contents
                    value = zlib.crc32(
                        c.string_at(frame.data, frame.height * frame.bytes_per_line),
                        value,
                    )
                finally:
                    destroy(image)
            return value

        motion(display, screen, x, y, 0)
        sync(display, False)
        before = pixels()
        start = time.monotonic_ns()
        if not button(display, 1, True, 0) or not button(display, 1, False, 0):
            raise RuntimeError("XTEST button event failed")
        flush(display)
        print("CLICK", flush=True)
        last, last_sample_start = before, start
        first_final_end = previous_start = start
        done_at = None
        while True:
            sample_start = time.monotonic_ns()
            current = pixels()
            sample_end = time.monotonic_ns()
            if current != last:
                first_final_end, previous_start = sample_end, last_sample_start
                last = current
            last_sample_start = sample_start
            if done_at is None and select.select([sys.stdin], [], [], 0)[0]:
                if sys.stdin.readline() != "done\n":
                    raise RuntimeError(
                        "Benchmark caller exited before confirming the destination"
                    )
                done_at = sample_end
            # Require 120 ms of quiet after semantic readiness and the last pixel transition.
            if done_at and sample_end - max(done_at, first_final_end) >= 120_000_000:
                break
            if done_at and sample_end - done_at > 3_000_000_000:
                raise RuntimeError(
                    "The diff pixels did not settle; exclude animated widgets from the sample"
                )
            if sample_end - start > 90_000_000_000:
                raise TimeoutError("Timed out waiting for a confirmed view")
            time.sleep(0.001)
        if last == before:
            raise ValueError(
                "Final code pixels match the starting view; choose a discriminating sample rectangle"
            )
        return {
            "elapsed_ms": (first_final_end - start) / 1e6,
            "gap_ms": (first_final_end - previous_start) / 1e6,
        }
    finally:
        close(display)


if __name__ == "__main__":
    try:
        print(json.dumps(observe(*map(int, sys.argv[1:]))))
    except (OSError, RuntimeError, ValueError) as exc:
        print(str(exc), flush=True)
        sys.exit(1)
