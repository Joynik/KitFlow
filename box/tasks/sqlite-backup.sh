if [ "${usage_docker:-false}" = true ]; then DATABASE_TARGET=docker; fi
case "${DATABASE_TARGET:-native}" in
    native) ;;
    docker)
        : "${COMPOSE_FILE:?Select Docker or set COMPOSE_FILE}"
        : "${COMPOSE_ENV_FILE:?Set COMPOSE_ENV_FILE}"
        : "${DATABASE_DOCKER_SERVICE:?Set vars.database_docker_service}"
        ;;
    *) echo "DATABASE_TARGET must be native or docker" >&2; exit 2 ;;
esac
: "${DATABASE_SQLITE_PATH:?Set vars.database_sqlite_path}"
[ "${DATABASE_TARGET:-native}" = docker ] || [ -f "$DATABASE_SQLITE_PATH" ] || { echo "SQLite database does not exist: $DATABASE_SQLITE_PATH" >&2; exit 2; }
output=${usage_file:-${DATABASE_BACKUP_FILE:-backup.sql}}
[ ! -e "$output" ] && [ ! -L "$output" ] || { echo "Backup file already exists: $output" >&2; exit 2; }
temporary=$(mktemp "$(dirname "$output")/.kitflow-backup.XXXXXX")
trap 'rm -f "$temporary"' EXIT HUP INT TERM
if [ "${DATABASE_TARGET:-native}" = docker ]; then
    : "${DATABASE_DOCKER_SQLITE_PATH:?Set vars.database_docker_sqlite_path}"
    docker compose --env-file "$COMPOSE_ENV_FILE" -f "$COMPOSE_FILE" exec -T "$DATABASE_DOCKER_SERVICE" sqlite3 -readonly -bail "$DATABASE_DOCKER_SQLITE_PATH" .dump > "$temporary"
else
    sqlite3 -readonly -bail "$DATABASE_SQLITE_PATH" .dump > "$temporary"
fi
ln "$temporary" "$output"
printf 'Database backup: %s\n' "$output"
