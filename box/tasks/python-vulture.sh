source_dir="${PYTHON_SOURCE:-.}"
tests_dir="${PYTHON_TESTS:-tests}"
set -- "$source_dir"
if [ "$source_dir" != "." ] && [ "$source_dir" != "$PWD" ] && [ -d "$tests_dir" ]; then
  set -- "$@" "$tests_dir"
fi
uv run --no-sync vulture "$@" --config pyproject.toml
