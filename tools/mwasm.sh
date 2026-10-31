#!/bin/sh
# Runs the CodeWarrior ARM assembler under wine.
set -e
here=$(cd "$(dirname "$0")" && pwd)
version=${MWCC_VERSION:-2.0/sp2}
export WINEDEBUG=-all
exec wine "$here/mwccarm/$version/mwasmarm.exe" "$@"
