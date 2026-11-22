"""Run compare_layouts.py on a private, GPU-backed Linux X display.

Usage: python3 tools/benchmarks/gpu_display.py OUTPUT [compare_layouts options]
Requires Gamescope with its headless backend, Xwayland, xauth, xwd and glxinfo.
"""

import os
import secrets
import select
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def benchmark(runtime, args):
    # The display used for input and pixel sampling must belong to this compositor.
    wayland = os.environ.get("WAYLAND_DISPLAY", "")
    if not wayland.startswith("gamescope-") or not (runtime / wayland).is_socket():
        raise RuntimeError("Gamescope did not expose its private Wayland socket.")
    auth = runtime / "Xauthority"
    auth.touch(mode=0o600)
    cookie = secrets.token_hex(16)

    def authorize(display):
        subprocess.run(
            ["xauth", "-f", auth, "add", display, "MIT-MAGIC-COOKIE-1", cookie],
            check=True,
        )

    # Xwayland needs the cookie before -displayfd returns its dynamic display number.
    authorize(":9999")
    read, write = os.pipe()
    args_x = [
        "Xwayland",
        "-displayfd",
        str(write),
        "-auth",
        str(auth),
        "-geometry",
        "1920x1080",
        "-dpi",
        "96",
        "-noreset",
        "-nolisten",
        "tcp",
    ]
    with subprocess.Popen(args_x, pass_fds=(write,)) as server:
        os.close(write)
        try:
            with os.fdopen(read) as ready:
                if not select.select([ready], [], [], 10)[0]:
                    raise RuntimeError("Rootful Xwayland did not become ready.")
                number = ready.readline().strip()
            if not number.isdigit():
                raise RuntimeError(
                    "Rootful Xwayland closed before it reported a display."
                )
            display = ":" + number
            authorize(display)
            env = dict(
                os.environ, DISPLAY=display, XAUTHORITY=str(auth), GDK_BACKEND="x11"
            )
            env.pop("WAYLAND_DISPLAY", None)
            print("Private rootful Xwayland display", display, flush=True)
            renderer = subprocess.check_output(["glxinfo", "-B"], env=env, text=True)
            print(renderer, flush=True)
            if "direct rendering: Yes" not in renderer or any(
                name in renderer.lower() for name in ("llvmpipe", "softpipe", "swrast")
            ):
                raise RuntimeError(
                    "Private Xwayland did not report a hardware renderer."
                )
            subprocess.run(
                ["xwd", "-root", "-silent", "-out", os.devnull], env=env, check=True
            )
            script = Path(__file__).with_name("compare_layouts.py")
            return subprocess.call([sys.executable, script, *args], env=env)
        finally:
            server.terminate()
            server.wait(timeout=8)


def main(args):
    if args[:1] == ["--inside"]:
        runtime = Path(os.environ["XDG_RUNTIME_DIR"])
        code = benchmark(runtime, args[1:])
        # Gamescope can exit successfully even if its primary child failed.
        (runtime / "benchmark-exit").write_text(str(code))
        return code
    gamescope = (
        shutil.which("gamescope", path=os.defpath + ":/usr/games") or "gamescope"
    )
    with tempfile.TemporaryDirectory(
        prefix="branchline-gpu-", ignore_cleanup_errors=True
    ) as directory:
        runtime = Path(directory)
        env = dict(os.environ, XDG_RUNTIME_DIR=directory)
        for key in (
            "DISPLAY",
            "WAYLAND_DISPLAY",
            "WAYLAND_SOCKET",
            "XAUTHORITY",
            "DBUS_SESSION_BUS_ADDRESS",
        ):
            env.pop(key, None)
        command = [
            "dbus-run-session",
            "--",
            gamescope,
            "--backend",
            "headless",
            "--expose-wayland",
            "-w",
            "1920",
            "-h",
            "1080",
            "-W",
            "1920",
            "-H",
            "1080",
            "-r",
            "60",
            "--",
            sys.executable,
            str(Path(__file__).resolve()),
            "--inside",
            *args,
        ]
        subprocess.run(command, env=env, check=True)
        result = runtime / "benchmark-exit"
        if not result.exists():
            raise RuntimeError("The isolated GPU benchmark did not complete.")
        return int(result.read_text())


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
