#!/bin/sh
# Runs CodeWarrior for ARM (mwccarm) under wine, the way meson/cross.ini
# invokes it. MWCC_VERSION selects the compiler build under tools/mwccarm.
set -e
here=$(cd "$(dirname "$0")" && pwd)
version=${MWCC_VERSION:-2.0/sp2}
export WINEDEBUG=-all
exec wine "$here/mwccarm/$version/mwccarm.exe" "$@"
