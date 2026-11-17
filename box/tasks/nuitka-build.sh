uv run --no-sync python -m nuitka --mode=standalone \
    --output-dir="${PYTHON_BUILD_DIRECTORY:-dist}" \
    "${PYTHON_ENTRYPOINT:?Set PYTHON_ENTRYPOINT in mise.toml or .env}"
