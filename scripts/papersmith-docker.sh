#!/bin/sh
# Run the current checkout without granting construction agents host write access.
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
    run|shell|exec) ;;
    help|--help|-h)
        printf '%s\n' \
            'Usage: sh scripts/papersmith-docker.sh build [docker build options]' \
            '       sh scripts/papersmith-docker.sh run <PaperSmith runner arguments>' \
            '       sh scripts/papersmith-docker.sh shell' \
            '       sh scripts/papersmith-docker.sh exec <command> [arguments...]' \
            'Use /runs/<name> for run roots. Source is mounted read-only at its host path.' \
            'Optional: PAPERSMITH_IMAGE, PAPERSMITH_VOLUME_PREFIX.' \
            'PAPERSMITH_NETWORK: bridge (default, network ALLOWED) or none (opt out).' \
            'PAPERSMITH_HOST_CONFIG=1 mounts host OpenCode and Codex config/dependencies read-only.' \
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
docker run --rm --network none --read-only --cap-drop ALL --cap-add CHOWN \
    --security-opt no-new-privileges \
    --mount "type=volume,src=$prefix-runs,dst=/runs" \
    --mount "type=volume,src=$prefix-state,dst=/state" \
    --mount "type=volume,src=$prefix-cache,dst=/cache" \
    "$image" sh -ec 'mkdir -p /state/home; chown "$1:$2" /runs /cache /state/home' sh "$uid" "$gid"
docker run --rm --network none --read-only --cap-drop ALL --user "$uid:$gid" \
    --security-opt no-new-privileges --mount "type=volume,src=$prefix-state,dst=/state" \
    "$image" sh -ec 'umask 077; mkdir -p "$HOME/.local/share/opencode" "$HOME/.config/opencode" "$HOME/.codex"; chmod 700 "$HOME"'

case "$action" in
    run) set -- python "$repo/scripts/run_paperrecon_domain.py" "$@" ;;
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
case "${PAPERSMITH_HOST_CONFIG:-0}" in
    0) ;;
    1)
        [ -z "${PAPERSMITH_OPENCODE_CONFIG:-}${PAPERSMITH_OPENCODE_AUTH:-}" ] || {
            printf '%s\n' 'Host config and individual OpenCode overrides are mutually exclusive.' >&2; exit 2;
        }
        config="$HOME/.config/opencode"
        codex_home=${PAPERSMITH_CODEX_HOME:-${CODEX_HOME:-$HOME/.codex}}
        [ -f "$config/opencode.jsonc" ] && [ -f "$codex_home/config.toml" ] && [ -f "$codex_home/auth.json" ] || {
            printf '%s\n' 'Missing host OpenCode config or Codex config/auth.' >&2; exit 2;
        }
        # Keep absolute provider imports and relative plugin dependencies intact.
        # Do not mount backups, histories, databases, or entire account directories.
        for path in "$config/opencode.jsonc" "$config/package.json" "$config/package-lock.json" \
            "$config/node_modules" "$config"/lck-provider/*.mjs "$config"/plugins/*.ts "$config"/plugins/*.js; do
            [ -e "$path" ] || continue
            case "$path" in /*) ;; *) exit 2 ;; esac
            case "$path" in *,*) exit 2 ;; esac
            set -- --mount "type=bind,src=$path,dst=$path,readonly" "$@"
        done
        set -- --env "OPENCODE_CONFIG=$config/opencode.jsonc" \
            --env "HOME=$HOME" \
            --mount "type=volume,src=$prefix-state,dst=$HOME,volume-subpath=home" \
            --mount "type=bind,src=$config/node_modules,dst=/state/home/.config/opencode/node_modules,readonly" \
            --mount "type=bind,src=$config/plugins,dst=/state/home/.config/opencode/plugins,readonly" \
            --mount "type=bind,src=$codex_home/config.toml,dst=/state/home/.codex/config.toml,readonly" \
            --mount "type=bind,src=$codex_home/auth.json,dst=/state/home/.codex/auth.json,readonly" \
            --mount "type=bind,src=$codex_home/config.toml,dst=$HOME/.codex/config.toml,readonly" "$@"
        # An explicit same-path auth mount may already be in READONLY_PATHS.
        case "
${PAPERSMITH_READONLY_PATHS:-}
" in
            *"
$HOME/.codex/auth.json
"*) ;;
            *) set -- --mount "type=bind,src=$codex_home/auth.json,dst=$HOME/.codex/auth.json,readonly" "$@" ;;
        esac
        ;;
    *) printf '%s\n' 'PAPERSMITH_HOST_CONFIG must be 0 or 1.' >&2; exit 2 ;;
esac
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
if [ -t 0 ] && [ -t 1 ]; then
    set -- -it "$@"
else
    set -- -i "$@"
fi
exec docker run --rm --init --read-only --user "$uid:$gid" \
    --cap-drop ALL --security-opt no-new-privileges --pids-limit 512 \
    --network "$network" \
    --tmpfs /tmp:rw,nosuid,nodev,mode=1777 \
    --mount "type=bind,src=$repo,dst=$repo,readonly" \
    --mount "type=volume,src=$prefix-runs,dst=/runs" \
    --mount "type=volume,src=$prefix-state,dst=/state" \
    --mount "type=volume,src=$prefix-cache,dst=/cache" \
    --workdir "$repo" --env "PYTHONPATH=$repo/src:$repo" --env RUFF_CACHE_DIR=/cache/ruff \
    --env "GIT_CONFIG_COUNT=1" --env "GIT_CONFIG_KEY_0=safe.directory" \
    --env "GIT_CONFIG_VALUE_0=$repo" "$@"
