: "${PYTHON_APP:?Set vars.python_app or PYTHON_APP in .env}"
uv run flask --app "$PYTHON_APP" routes
