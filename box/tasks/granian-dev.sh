: "${PYTHON_APP:?Set vars.python_app or PYTHON_APP in .env}"
if [ "${BUILD_BEFORE_RUN:-false}" = true ]; then
    mise run --quiet build
fi
uv run granian "$PYTHON_APP" --interface "${SERVER_INTERFACE:-asgi}" --host "${SERVER_HOST:-127.0.0.1}" --port "${SERVER_PORT:-8000}" --reload
