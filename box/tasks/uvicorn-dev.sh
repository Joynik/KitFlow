: "${PYTHON_APP:?Set vars.python_app or PYTHON_APP in .env}"
if [ "${BUILD_BEFORE_RUN:-false}" = true ]; then
    mise run --quiet build
fi
set -- uv run uvicorn "$PYTHON_APP" --host "${SERVER_HOST:-127.0.0.1}" --port "${SERVER_PORT:-8000}" --reload
# Split on newlines and preserve spaces and pattern characters.
(
    IFS='
'
    set -f
    for directory in ${SERVER_RELOAD_IGNORE_DIRS:-}; do
        case "$directory" in
            /*) ;;
            *) directory="./$directory" ;;
        esac
        if [ ! -d "$directory" ]; then
            printf 'Reload exclusion directory does not exist: %s\n' "$directory" >&2
            exit 1
        fi
        absolute_directory=$(CDPATH='' cd -P "$directory" && pwd -P)
        set -- "$@" --reload-exclude="$absolute_directory"
    done
    for pattern in ${SERVER_RELOAD_IGNORE_PATTERNS:-}; do
        set -- "$@" --reload-exclude="$pattern"
    done
    exec "$@"
)
