#!/bin/sh
set -eu

CDPATH= cd -- "$(dirname -- "$0")"

# This checkout can supply the Linux SDK when the system lacks the dev packages.
sdk="$PWD/build/linux-dev/root/usr/lib/x86_64-linux-gnu"
if [ "$(uname -s)" = Linux ] && [ -d "$sdk/pkgconfig" ] && ! pkg-config --exists gtk+-3.0 webkit2gtk-4.1; then
    export PKG_CONFIG_PATH="${PKG_CONFIG_PATH:+$PKG_CONFIG_PATH:}$sdk/pkgconfig"
    export LIBRARY_PATH="${LIBRARY_PATH:+$LIBRARY_PATH:}$sdk"
fi

npm ci --no-audit --no-fund
exec npm run tauri -- build "$@"
