#!/bin/sh
# Install a wheel, never an editable checkout. Re-run to upgrade.
set -eu
python=${PAPERSMITH_PYTHON:-python3}
prefix=${PAPERSMITH_PREFIX:-$HOME/.local/share/papersmith}
bindir=${PAPERSMITH_BIN_DIR:-$HOME/.local/bin}
"$python" -c 'import sys; assert sys.version_info >= (3,12), "Python >=3.12 is required"'
source=${PAPERSMITH_SOURCE:-}
if [ -z "$source" ] && [ -f ./pyproject.toml ] && [ -d ./src/paperbench_harbor ]; then
    source=$(pwd -P)
fi
if [ -z "$source" ]; then
    : "${PAPERSMITH_REF:?Set PAPERSMITH_REF to a trusted full 40-character commit for remote installation}"
    case "$PAPERSMITH_REF" in *[!0-9a-f]*|'') exit 2 ;; esac
    [ "${#PAPERSMITH_REF}" -eq 40 ] || exit 2
    source="https://github.com/a-green-hand-jack/paperbench-harbor/archive/$PAPERSMITH_REF.tar.gz"
fi
mkdir -p "$prefix" "$bindir"
if [ ! -x "$prefix/venv/bin/python" ]; then
    "$python" -m venv "$prefix/venv"
fi
wheelhouse=$(mktemp -d)
trap 'rm -r -- "$wheelhouse"' EXIT HUP INT TERM
"$prefix/venv/bin/python" -m pip wheel --no-deps --wheel-dir "$wheelhouse" "$source"
"$prefix/venv/bin/python" -m pip install --upgrade "$wheelhouse"/*.whl
# Repackage same-version source edits without reinstalling all compatible dependencies.
"$prefix/venv/bin/python" -m pip install --no-deps --force-reinstall "$wheelhouse"/*.whl
ln -sf "$prefix/venv/bin/papersmith" "$bindir/papersmith"
ln -sf "$prefix/venv/bin/paperbench-harbor" "$bindir/paperbench-harbor"
ln -sf "$prefix/venv/bin/paperbench-distribute" "$bindir/paperbench-distribute"
"$bindir/papersmith" --version
printf 'Installed wheel into %s. Add %s to PATH. Run papersmith doctor. Re-run this installer to upgrade.\n' "$prefix" "$bindir"
