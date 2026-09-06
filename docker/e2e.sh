#!/bin/sh
# Run the installed wheel without mounting the checkout.
set -eu

repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
image=${PAPERSMITH_IMAGE:-paperbench-papersmith:dev}
uid=$(id -u)
gid=$(id -g)
key=$(printf '%s' "$repo" | cksum | cut -d ' ' -f 1)
prefix=${PAPERSMITH_VOLUME_PREFIX:-papersmith-$key-$uid}
case "$prefix" in
    ''|[!A-Za-z0-9]*|*[!A-Za-z0-9_.-]*)
        printf '%s\n' 'PAPERSMITH_VOLUME_PREFIX must be a Docker volume-name token.' >&2; exit 2 ;;
esac
network=${PAPERSMITH_NETWORK-bridge}
case "$network" in
    none|bridge) ;;
    *) printf '%s\n' 'PAPERSMITH_NETWORK must be bridge (default) or none (opt out).' >&2; exit 2 ;;
esac
action=${1:-help}
[ "$#" -eq 0 ] || shift

case "$action" in
    build)
        exec docker build -f "$repo/docker/papersmith/Dockerfile" -t "$image" \
            --build-arg "PAPERSMITH_UID=$uid" --build-arg "PAPERSMITH_GID=$gid" \
            --build-arg "PAPERSMITH_HOME=$HOME" "$@" "$repo"
        ;;
    run|shell|exec|status|resume|validate|doctor) ;;
    help|--help|-h)
        printf '%s\n' \
            'Usage: sh docker/e2e.sh build [docker build options]' \
            '       sh docker/e2e.sh run <papersmith create arguments>' \
            '       sh docker/e2e.sh status|resume|validate <workspace> [flags]' \
            '       sh docker/e2e.sh doctor [flags]' \
            '       sh docker/e2e.sh exec <command> [arguments...]' \
            'Use /runs/<name>. Installed package only; no source mount.' \
            'Optional: PAPERSMITH_IMAGE, PAPERSMITH_VOLUME_PREFIX.' \
            'PAPERSMITH_DETACH=1 runs detached and retains the container for status inspection.' \
            'PAPERSMITH_CONTAINER_NAME: optional Docker container name.' \
            'PAPERSMITH_NETWORK: bridge (default, network ALLOWED) or none (opt out).' \
            'PAPERSMITH_READONLY_PATHS: newline-separated additional absolute file/dependency paths.' \
            'PAPERSMITH_INPUT: optional read-only input directory, mounted at /input.' \
            'Opt-in: PAPERSMITH_OPENCODE_CONFIG (secret-free JSON), PAPERSMITH_OPENCODE_AUTH (single auth file).' \
            'No credentials, host home, or Docker socket are mounted by default.'
        exit 0
        ;;
    *) printf 'Unknown action: %s\n' "$action" >&2; exit 2 ;;
esac

[ "$uid" -ne 0 ] || { printf '%s\n' 'Run as an ordinary user, not root/sudo.' >&2; exit 2; }
for path in "$repo" "${PAPERSMITH_OPENCODE_CONFIG:-}" "${PAPERSMITH_OPENCODE_AUTH:-}"; do
    case "$path" in *,*) printf '%s\n' 'Docker mount paths cannot contain commas.' >&2; exit 2 ;; esac
done
docker image inspect "$image" >/dev/null 2>&1 || {
    printf '%s\n' 'Image missing; run the build command first.' >&2
    exit 2
}

# Only these dedicated volume directories are initialized as root; payloads run
# as the caller, with no capabilities and no writable image filesystem.
docker run --rm --network none --read-only --user 0:0 --cap-drop ALL --cap-add CHOWN --cap-add DAC_OVERRIDE \
    --security-opt no-new-privileges \
    --mount "type=volume,src=$prefix-runs,dst=/runs" \
    --mount "type=volume,src=$prefix-state,dst=/state" \
    --mount "type=volume,src=$prefix-cache,dst=/cache" \
    "$image" sh -ec 'mkdir -p /state/home; chown "$1:$2" /runs /cache /state /state/home' sh "$uid" "$gid"
docker run --rm --network none --read-only --cap-drop ALL --user "$uid:$gid" \
    --security-opt no-new-privileges --mount "type=volume,src=$prefix-state,dst=/state" \
    "$image" sh -ec 'umask 077; mkdir -p "$HOME/.local/share/opencode" "$HOME/.config/opencode" "$HOME/.codex"; chmod 700 "$HOME"'

case "$action" in
    run) set -- papersmith create "$@" ;;
    status|resume|validate|doctor) set -- papersmith "$action" "$@" ;;
    shell) [ "$#" -eq 0 ] || { printf '%s\n' 'shell takes no arguments' >&2; exit 2; }; set -- bash ;;
    exec) [ "$#" -gt 0 ] || { printf '%s\n' 'exec requires a command' >&2; exit 2; } ;;
esac

set -- sh -ec 'umask 077; mkdir -p "$HOME/.local/share/opencode" "$HOME/.config/opencode" "$HOME/.codex"; chmod 700 "$HOME"; exec "$@"' sh "$@"

if [ -n "${PAPERSMITH_OPENCODE_CONFIG:-}" ]; then
    case "$PAPERSMITH_OPENCODE_CONFIG" in /*) ;; *) printf '%s\n' 'Config path must be absolute.' >&2; exit 2 ;; esac
    [ -f "$PAPERSMITH_OPENCODE_CONFIG" ] || exit 2
    set -- --mount "type=bind,src=$PAPERSMITH_OPENCODE_CONFIG,dst=/opt/opencode.json,readonly" \
        --env OPENCODE_CONFIG=/opt/opencode.json "$image" "$@"
else
    set -- "$image" "$@"
fi
if [ -n "${PAPERSMITH_OPENCODE_AUTH:-}" ]; then
    case "$PAPERSMITH_OPENCODE_AUTH" in /*) ;; *) printf '%s\n' 'Auth path must be absolute.' >&2; exit 2 ;; esac
    [ -f "$PAPERSMITH_OPENCODE_AUTH" ] || exit 2
    set -- --mount "type=bind,src=$PAPERSMITH_OPENCODE_AUTH,dst=/state/home/.local/share/opencode/auth.json,readonly" "$@"
fi
[ "${PAPERSMITH_HOST_CONFIG:-0}" = 0 ] || {
    printf '%s\n' 'Broad host-config mode is retired; supply explicit narrow config/auth/module mounts.' >&2
    exit 2
}
# Explicit additions supply only the selected providers' credentials and any
# config-referenced external modules/catalogs. Never inspect their contents.
old_ifs=$IFS
IFS='
'
set -f
for path in ${PAPERSMITH_READONLY_PATHS:-}; do
    case "$path" in /*) ;; *) printf '%s\n' 'Additional mount paths must be absolute.' >&2; exit 2 ;; esac
    destination=$path
    path=$(realpath -e -- "$path") || exit 2
    case "$path" in *,*|*/../*|*/..|/|/home|"$HOME"|"$HOME/"|"$HOME/.config"|"$HOME/.codex"|"$HOME/.config/opencode"|/var/run|/run|/var/run/docker.sock|/run/docker.sock)
        printf '%s\n' 'Refusing broad, ambiguous, or Docker socket mount.' >&2; exit 2 ;;
    esac
    [ -f "$path" ] || [ -d "$path" ] || { printf '%s\n' 'Additional mount must be a file or dependency directory.' >&2; exit 2; }
    case "$destination" in *,*|*/../*|*/..) exit 2 ;; esac
    set -- --mount "type=bind,src=$path,dst=$destination,readonly" "$@"
done
set +f
IFS=$old_ifs
if [ -n "${PAPERSMITH_INPUT:-}" ]; then
    case "$PAPERSMITH_INPUT" in /*) ;; *) exit 2 ;; esac
    PAPERSMITH_INPUT=$(realpath -e -- "$PAPERSMITH_INPUT") || exit 2
    case "$PAPERSMITH_INPUT" in *,*|/|"$HOME"|"$HOME/"|/home|/run|/var/run) exit 2 ;; esac
    [ -d "$PAPERSMITH_INPUT" ] || exit 2
    set -- --mount "type=bind,src=$PAPERSMITH_INPUT,dst=/input,readonly" "$@"
fi
if [ -n "${PAPERSMITH_CONTAINER_NAME:-}" ]; then
    set -- --name "$PAPERSMITH_CONTAINER_NAME" "$@"
fi
case "${PAPERSMITH_DETACH:-0}" in
    1) set -- --detach "$@" ;;
    0)
        if [ -t 0 ] && [ -t 1 ]; then
            set -- --rm -it "$@"
        else
            set -- --rm -i "$@"
        fi
        ;;
    *) printf '%s\n' 'PAPERSMITH_DETACH must be 0 or 1.' >&2; exit 2 ;;
esac
exec docker run --init --read-only --user "$uid:$gid" \
    --cap-drop ALL --security-opt no-new-privileges --pids-limit 512 \
    --network "$network" \
    --tmpfs /tmp:rw,nosuid,nodev,mode=1777 \
    --mount "type=volume,src=$prefix-runs,dst=/runs" \
    --mount "type=volume,src=$prefix-state,dst=/state" \
    --mount "type=volume,src=$prefix-cache,dst=/cache" \
    --workdir /runs --env RUFF_CACHE_DIR=/cache/ruff "$@"
