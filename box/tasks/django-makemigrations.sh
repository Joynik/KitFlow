if [ -n "${usage_name:-}" ]; then
    uv run python manage.py makemigrations --name "$usage_name" --verbosity 1
else
    uv run python manage.py makemigrations --verbosity 1
fi
