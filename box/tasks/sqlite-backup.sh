if [ "${usage_docker:-false}" = true ]; then DATABASE_EXECUTION_MODE=docker; fi
case "${DATABASE_EXECUTION_MODE:-native}" in
    native) ;;
    docker)
        : "${COMPOSE_FILE:?Select Docker or set COMPOSE_FILE}"
        : "${COMPOSE_ENV_FILE:?Set COMPOSE_ENV_FILE}"
        : "${DATABASE_DOCKER_SERVICE:?Set vars.database_docker_service}"
        ;;
    *) echo "DATABASE_EXECUTION_MODE must be native or docker" >&2; exit 2 ;;
esac
: "${SQLITE_DATABASE_PATH:?Set vars.sqlite_database_path}"
[ "${DATABASE_EXECUTION_MODE:-native}" = docker ] || [ -f "$SQLITE_DATABASE_PATH" ] || { echo "SQLite database does not exist: $SQLITE_DATABASE_PATH" >&2; exit 2; }
output=${usage_file:-${DATABASE_BACKUP_FILE:-backup.sql}}
[ ! -e "$output" ] && [ ! -L "$output" ] || { echo "Backup file already exists: $output" >&2; exit 2; }
temporary=$(mktemp "$(dirname "$output")/.kitflow-backup.XXXXXX")
trap 'rm -f "$temporary"' EXIT HUP INT TERM
if [ "${DATABASE_EXECUTION_MODE:-native}" = docker ]; then
    : "${SQLITE_CONTAINER_PATH:?Set vars.sqlite_container_path}"
    docker compose --env-file "$COMPOSE_ENV_FILE" -f "$COMPOSE_FILE" exec -T "$DATABASE_DOCKER_SERVICE" sqlite3 -readonly -bail "$SQLITE_CONTAINER_PATH" .dump > "$temporary"
else
    sqlite3 -readonly -bail "$SQLITE_DATABASE_PATH" .dump > "$temporary"
fi
ln "$temporary" "$output"
printf 'Database backup: %s\n' "$output"
