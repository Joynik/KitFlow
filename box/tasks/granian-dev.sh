: "${PYTHON_APP:?Set vars.python_app or PYTHON_APP in .env}"
if [ "${BUILD_BEFORE_RUN:-false}" = true ]; then
    mise run --quiet build
fi
set -- uv run granian "$PYTHON_APP" --interface "${SERVER_INTERFACE:-asgi}" --host "${SERVER_HOST:-127.0.0.1}" --port "${SERVER_PORT:-8000}" --reload
# Split on newlines and preserve spaces and pattern characters.
(
    IFS='
'
    set -f
    for directory in ${SERVER_RELOAD_IGNORE_DIRS:-}; do
        set -- "$@" --reload-ignore-dirs="$directory"
    done
    for pattern in ${SERVER_RELOAD_IGNORE_PATTERNS:-}; do
        set -- "$@" --reload-ignore-patterns="$pattern"
    done
    exec "$@"
)
