#!/bin/sh
# Install a wheel, never an editable checkout. Re-run to upgrade.
set -eu
python=${PAPERSMITH_PYTHON:-python3}
prefix=${PAPERSMITH_PREFIX:-$HOME/.local/share/papersmith}
bindir=${PAPERSMITH_BIN_DIR:-$HOME/.local/bin}
"$python" -c 'import sys; assert sys.version_info >= (3,12), "Python >=3.12 is required"'
source=${PAPERSMITH_SOURCE:-}
selection=explicit-source
if [ "${PAPERSMITH_SOURCE+x}" = x ]; then
    [ -n "$source" ] || { printf '%s\n' 'PAPERSMITH_SOURCE cannot be empty.' >&2; exit 2; }
elif [ "${PAPERSMITH_REF+x}" = x ]; then
    case "$PAPERSMITH_REF" in *[!0-9a-f]*|'') printf '%s\n' 'PAPERSMITH_REF must be a full lowercase commit SHA.' >&2; exit 2 ;; esac
    [ "${#PAPERSMITH_REF}" -eq 40 ] || { printf '%s\n' 'PAPERSMITH_REF must contain 40 characters.' >&2; exit 2; }
    source="https://github.com/a-green-hand-jack/paperbench-harbor/archive/$PAPERSMITH_REF.tar.gz"
    selection="pinned-remote:$PAPERSMITH_REF"
elif [ -f ./pyproject.toml ] && [ -d ./src/paperbench_harbor ]; then
    source=$(pwd -P)
    selection=local-checkout
else
    printf '%s\n' 'Set PAPERSMITH_SOURCE or PAPERSMITH_REF, or run from a checkout.' >&2
    exit 2
fi
printf 'Selected installation source: %s\n' "$selection"
"$python" - "$source" <<'PY'
import sys
from urllib.parse import urlsplit
source = sys.argv[1]
url = urlsplit(source)
if source.startswith('-') or url.username or url.password or url.query or url.fragment:
    raise SystemExit('Use a local path or credential-free source URL without query or fragment.')
PY
command -v flock >/dev/null || { printf '%s\n' 'flock is required for environment lifecycle locking.' >&2; exit 2; }
mkdir -p "$prefix" "$bindir"
prefix=$(CDPATH= cd -- "$prefix" && pwd -P)
for launcher in papersmith paperbench-harbor paperbench-distribute; do
    target="$bindir/$launcher"
    if [ -e "$target" ] || [ -L "$target" ]; then
        [ -L "$target" ] && [ "$(readlink "$target")" = "$prefix/venv/bin/$launcher" ] || {
            printf 'Refusing to replace existing launcher %s; explicitly move it or select PAPERSMITH_BIN_DIR.\n' "$target" >&2
            exit 2
        }
    fi
done
# Keep the inode stable: neither installers nor workers may unlink this lock.
exec 9>"$prefix/.papersmith-environment.lock"
flock -n 9 || { printf '%s\n' 'PaperSmith environment is in use; no installation was changed.' >&2; exit 2; }
if [ ! -x "$prefix/venv/bin/python" ]; then
    [ ! -e "$prefix/venv" ] || { printf '%s\n' 'Existing environment is incomplete; refusing to replace it.' >&2; exit 2; }
    "$python" -m venv "$prefix/venv"
fi
"$prefix/venv/bin/python" -c 'import sys; assert sys.version_info >= (3,12), "Existing environment requires Python >=3.12"; assert sys.prefix != sys.base_prefix, "A virtual environment is required"'
"$prefix/venv/bin/python" -m pip check
wheelhouse=$(mktemp -d)
trap 'rm -r -- "$wheelhouse"' EXIT HUP INT TERM
"$prefix/venv/bin/python" -m pip wheel --no-deps --wheel-dir "$wheelhouse" "$source"
"$prefix/venv/bin/python" -m pip install --upgrade "$wheelhouse"/*.whl
# Repackage same-version source edits without reinstalling all compatible dependencies.
"$prefix/venv/bin/python" -m pip install --no-deps --force-reinstall "$wheelhouse"/*.whl
"$prefix/venv/bin/python" -m pip check
"$prefix/venv/bin/python" - "$wheelhouse" <<'PY'
import hashlib, importlib.metadata as metadata, pathlib, sys
wheels = list(pathlib.Path(sys.argv[1]).glob('*.whl'))
assert len(wheels) == 1, 'Expected exactly one product wheel'
print('Installed wheel SHA256:', hashlib.sha256(wheels[0].read_bytes()).hexdigest())
identity = '\n'.join(sorted(f'{d.metadata["Name"]}=={d.version}' for d in metadata.distributions()))
print('Installed dependency identity SHA256:', hashlib.sha256(identity.encode()).hexdigest())
PY
ln -sf "$prefix/venv/bin/papersmith" "$bindir/papersmith"
ln -sf "$prefix/venv/bin/paperbench-harbor" "$bindir/paperbench-harbor"
ln -sf "$prefix/venv/bin/paperbench-distribute" "$bindir/paperbench-distribute"
"$bindir/papersmith" --version
printf 'Installed wheel into %s. Add %s to PATH. Run papersmith doctor. Re-run this installer to upgrade.\n' "$prefix" "$bindir"
