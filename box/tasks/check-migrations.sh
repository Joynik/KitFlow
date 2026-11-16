if [ "${kitflow_checked_migrations:-0}" != 1 ]; then
    mise run --quiet db:check
    kitflow_checked_migrations=1
fi
