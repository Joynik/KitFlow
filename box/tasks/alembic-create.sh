uv run alembic --config "${ALEMBIC_CONFIG:-alembic.ini}" revision --autogenerate --message "${usage_name:-${MIGRATION_NAME:-update_schema}}"
