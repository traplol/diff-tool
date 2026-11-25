#!/bin/sh
set -eu

CDPATH= cd -- "$(dirname -- "$0")"

need() {
    command -v "$1" >/dev/null 2>&1 || {
        printf '%s\n' "Missing build prerequisite: $1. See README.md, Build from source." >&2
        exit 1
    }
}

configure_xwin() {
    need cargo-xwin
    export XWIN_ARCH="${XWIN_ARCH:-x86_64}"
    export XWIN_CACHE_DIR="${XWIN_CACHE_DIR:-$PWD/build/xwin}"
    sdk="$PWD/build/prebuilt-msvc/windows-msvc-sysroot"
    if [ -z "${XWIN_MSVC_SYSROOT:-}" ] && [ -d "$sdk/include" ]; then
        export XWIN_MSVC_SYSROOT="$sdk"
    fi
    if [ -n "${XWIN_MSVC_SYSROOT:-}" ]; then
        export XWIN_CROSS_COMPILER="${XWIN_CROSS_COMPILER:-clang}"
    fi
}

case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) native_windows=true ;;
    *) native_windows=false ;;
esac
windows_gui=$native_windows
portable=false
if [ "${1:-}" = --windows ]; then
    shift
    windows_gui=true
    portable=true
fi

# Each GUI includes a standalone worker for the other OS. Git then reads a WSL
# or Windows checkout on its own filesystem without a runtime build toolchain.
if [ -z "${BRANCHLINE_GIT_WORKER_PATH:-}" ]; then
    worker_manifest="$PWD/src-tauri/git-worker/Cargo.toml"
    worker_target="$PWD/src-tauri/target/git-worker"
    if [ "$windows_gui" = false ]; then
        configure_xwin
        rustup target add x86_64-pc-windows-msvc
        CARGO_TARGET_DIR="$worker_target" \
            RUSTFLAGS="${RUSTFLAGS:+$RUSTFLAGS }-C target-feature=+crt-static" \
            cargo xwin build --locked --release --manifest-path "$worker_manifest" \
            --target x86_64-pc-windows-msvc
        BRANCHLINE_GIT_WORKER_PATH="$worker_target/x86_64-pc-windows-msvc/release/branchline-git-worker.exe"
    else
        if [ "$native_windows" = true ]; then
            need wsl.exe
            linux_project=$(MSYS_NO_PATHCONV=1 wsl.exe --exec wslpath -u "$(cygpath -am "$PWD")" | tr -d '\r')
            MSYS_NO_PATHCONV=1 wsl.exe --exec sh -lc '
                set -eu
                cd "$1"
                export PATH="${CARGO_HOME:-$HOME/.cargo}/bin:$PATH"
                command -v gcc >/dev/null && command -v cmake >/dev/null || { printf "%s\n" "Install build-essential and cmake in the build WSL distribution." >&2; exit 1; }
                rustup target add x86_64-unknown-linux-gnu
                CARGO_TARGET_DIR="$PWD/src-tauri/target/git-worker" LIBZ_SYS_STATIC=1 \
                    RUSTFLAGS="${RUSTFLAGS:+$RUSTFLAGS }-C target-feature=+crt-static" \
                    cargo build --locked --release --manifest-path src-tauri/git-worker/Cargo.toml \
                    --target x86_64-unknown-linux-gnu
            ' sh "$linux_project"
        else
            need gcc
            need cmake
            rustup target add x86_64-unknown-linux-gnu
            CARGO_TARGET_DIR="$worker_target" LIBZ_SYS_STATIC=1 \
                RUSTFLAGS="${RUSTFLAGS:+$RUSTFLAGS }-C target-feature=+crt-static" \
                cargo build --locked --release --manifest-path "$worker_manifest" \
                --target x86_64-unknown-linux-gnu
        fi
        BRANCHLINE_GIT_WORKER_PATH="$worker_target/x86_64-unknown-linux-gnu/release/branchline-git-worker"
    fi
fi
if [ "$native_windows" = true ]; then
    BRANCHLINE_GIT_WORKER_PATH=$(cygpath -am "$BRANCHLINE_GIT_WORKER_PATH")
fi
if [ ! -s "$BRANCHLINE_GIT_WORKER_PATH" ]; then
    printf '%s\n' "Git worker not found: $BRANCHLINE_GIT_WORKER_PATH" >&2
    exit 1
fi
export BRANCHLINE_GIT_WORKER_PATH

if [ "$windows_gui" = true ]; then
    if [ "$native_windows" = false ]; then
        configure_xwin
        set -- --runner cargo-xwin "$@"
    fi
    # Keep the Visual C++ runtime inside both portable executables.
    export RUSTFLAGS="${RUSTFLAGS:+$RUSTFLAGS }-C target-feature=+crt-static"
    if [ "$portable" = true ]; then
        rustup target add x86_64-pc-windows-msvc
        set -- --target x86_64-pc-windows-msvc --no-bundle "$@"
    fi
else
    # This checkout can supply the Linux SDK when system dev packages are absent.
    sdk="$PWD/build/linux-dev/root/usr/lib/x86_64-linux-gnu"
    if [ "$(uname -s)" = Linux ] && [ -d "$sdk/pkgconfig" ] && ! pkg-config --exists gtk+-3.0 webkit2gtk-4.1; then
        export PKG_CONFIG_PATH="${PKG_CONFIG_PATH:+$PKG_CONFIG_PATH:}$sdk/pkgconfig"
        export LIBRARY_PATH="${LIBRARY_PATH:+$LIBRARY_PATH:}$sdk"
    fi
fi

npm ci --no-audit --no-fund
exec npm run tauri -- build "$@"
