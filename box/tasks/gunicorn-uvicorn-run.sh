: "${PYTHON_APP:?Set vars.python_app or PYTHON_APP in .env}"
if [ "${BUILD_BEFORE_RUN:-false}" = true ]; then
    mise run --quiet build
fi
uv run gunicorn "$PYTHON_APP" --bind "${SERVER_HOST:-127.0.0.1}:${SERVER_PORT:-8000}" --worker-class uvicorn_worker.UvicornWorker --workers "${SERVER_WORKERS:-1}"
