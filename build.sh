#!/bin/sh
set -eu

CDPATH= cd -- "$(dirname -- "$0")"

if [ "${1:-}" = --windows ]; then
    shift
    target=x86_64-pc-windows-msvc
    case "$(uname -s)" in
        MINGW*|MSYS*|CYGWIN*) ;;
        *)
            export XWIN_ARCH="${XWIN_ARCH:-x86_64}"
            export XWIN_CACHE_DIR="${XWIN_CACHE_DIR:-$PWD/build/xwin}"
            # Reuse the local prebuilt SDK if one was prepared for this checkout.
            sdk="$PWD/build/prebuilt-msvc/windows-msvc-sysroot"
            if [ -z "${XWIN_MSVC_SYSROOT:-}" ] && [ -d "$sdk/include" ]; then
                export XWIN_MSVC_SYSROOT="$sdk"
            fi
            if [ -n "${XWIN_MSVC_SYSROOT:-}" ]; then
                export XWIN_CROSS_COMPILER="${XWIN_CROSS_COMPILER:-clang}"
            fi
            set -- --runner cargo-xwin "$@"
            ;;
    esac
    # Keep the Visual C++ runtime inside the executable.
    export RUSTFLAGS="${RUSTFLAGS:+$RUSTFLAGS }-C target-feature=+crt-static"
    npm ci --no-audit --no-fund
    exec npm run tauri -- build --target "$target" --no-bundle "$@"
fi

# This checkout can supply the Linux SDK when the system lacks the dev packages.
sdk="$PWD/build/linux-dev/root/usr/lib/x86_64-linux-gnu"
if [ "$(uname -s)" = Linux ] && [ -d "$sdk/pkgconfig" ] && ! pkg-config --exists gtk+-3.0 webkit2gtk-4.1; then
    export PKG_CONFIG_PATH="${PKG_CONFIG_PATH:+$PKG_CONFIG_PATH:}$sdk/pkgconfig"
    export LIBRARY_PATH="${LIBRARY_PATH:+$LIBRARY_PATH:}$sdk"
fi

npm ci --no-audit --no-fund
exec npm run tauri -- build "$@"
