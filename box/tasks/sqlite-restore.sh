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
input=${usage_file:-${DATABASE_RESTORE_FILE:-}}
[ -n "$input" ] && [ -f "$input" ] || { echo "Specify an existing SQL restore file" >&2; exit 2; }
if [ "${DATABASE_EXECUTION_MODE:-native}" = docker ]; then
    : "${SQLITE_CONTAINER_PATH:?Set vars.sqlite_container_path}"
    docker compose --env-file "$COMPOSE_ENV_FILE" -f "$COMPOSE_FILE" exec -T "$DATABASE_DOCKER_SERVICE" sh -eu -c '
SQLITE_DATABASE_PATH=$1
[ ! -e "$SQLITE_DATABASE_PATH" ] || [ -f "$SQLITE_DATABASE_PATH" ] || { echo "SQLite target is not a regular file" >&2; exit 2; }
[ ! -L "$SQLITE_DATABASE_PATH" ] || { echo "Refusing to replace a SQLite symbolic link" >&2; exit 2; }
[ ! -e "$SQLITE_DATABASE_PATH-wal" ] && [ ! -e "$SQLITE_DATABASE_PATH-shm" ] || { echo "Stop the SQLite application and checkpoint its WAL before restoring" >&2; exit 2; }
temporary=$(mktemp "$(dirname "$SQLITE_DATABASE_PATH")/.kitflow-restore.XXXXXX")
trap '\''rm -f "$temporary" "$temporary-wal" "$temporary-shm"'\'' EXIT HUP INT TERM
sqlite3 -bail "$temporary"
[ "$(sqlite3 -readonly "$temporary" '\''PRAGMA integrity_check;'\'')" = ok ] || { echo "Restored SQLite database failed integrity checking" >&2; exit 1; }
if [ -f "$SQLITE_DATABASE_PATH" ]; then
    case "$(uname -s)" in
        Darwin) chmod "$(stat -f '\''%Lp'\'' "$SQLITE_DATABASE_PATH")" "$temporary" ;;
        *) chmod --reference="$SQLITE_DATABASE_PATH" "$temporary" ;;
    esac
fi
mv -f "$temporary" "$SQLITE_DATABASE_PATH"
printf '\''Database restored: %s\n'\'' "$SQLITE_DATABASE_PATH"

' sh "$SQLITE_CONTAINER_PATH" < "$input"
else
[ ! -e "$SQLITE_DATABASE_PATH" ] || [ -f "$SQLITE_DATABASE_PATH" ] || { echo "SQLite target is not a regular file" >&2; exit 2; }
[ ! -L "$SQLITE_DATABASE_PATH" ] || { echo "Refusing to replace a SQLite symbolic link" >&2; exit 2; }
[ ! -e "$SQLITE_DATABASE_PATH-wal" ] && [ ! -e "$SQLITE_DATABASE_PATH-shm" ] || { echo "Stop the SQLite application and checkpoint its WAL before restoring" >&2; exit 2; }
temporary=$(mktemp "$(dirname "$SQLITE_DATABASE_PATH")/.kitflow-restore.XXXXXX")
trap 'rm -f "$temporary" "$temporary-wal" "$temporary-shm"' EXIT HUP INT TERM
sqlite3 -bail "$temporary" < "$input"
[ "$(sqlite3 -readonly "$temporary" 'PRAGMA integrity_check;')" = ok ] || { echo "Restored SQLite database failed integrity checking" >&2; exit 1; }
if [ -f "$SQLITE_DATABASE_PATH" ]; then
    case "$(uname -s)" in
        Darwin) chmod "$(stat -f '%Lp' "$SQLITE_DATABASE_PATH")" "$temporary" ;;
        *) chmod --reference="$SQLITE_DATABASE_PATH" "$temporary" ;;
    esac
fi
mv -f "$temporary" "$SQLITE_DATABASE_PATH"
printf 'Database restored: %s\n' "$SQLITE_DATABASE_PATH"
fi
