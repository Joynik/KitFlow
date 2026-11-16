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
input=${usage_file:-${DATABASE_RESTORE_FILE:-}}
[ -n "$input" ] && [ -f "$input" ] || { echo "Specify an existing SQL restore file" >&2; exit 2; }
if [ "${DATABASE_TARGET:-native}" = docker ]; then
    : "${DATABASE_DOCKER_SQLITE_PATH:?Set vars.database_docker_sqlite_path}"
    docker compose --env-file "$COMPOSE_ENV_FILE" -f "$COMPOSE_FILE" exec -T "$DATABASE_DOCKER_SERVICE" sh -eu -c '
DATABASE_SQLITE_PATH=$1
[ ! -e "$DATABASE_SQLITE_PATH" ] || [ -f "$DATABASE_SQLITE_PATH" ] || { echo "SQLite target is not a regular file" >&2; exit 2; }
[ ! -L "$DATABASE_SQLITE_PATH" ] || { echo "Refusing to replace a SQLite symbolic link" >&2; exit 2; }
[ ! -e "$DATABASE_SQLITE_PATH-wal" ] && [ ! -e "$DATABASE_SQLITE_PATH-shm" ] || { echo "Stop the SQLite application and checkpoint its WAL before restoring" >&2; exit 2; }
temporary=$(mktemp "$(dirname "$DATABASE_SQLITE_PATH")/.kitflow-restore.XXXXXX")
trap '\''rm -f "$temporary" "$temporary-wal" "$temporary-shm"'\'' EXIT HUP INT TERM
sqlite3 -bail "$temporary"
[ "$(sqlite3 -readonly "$temporary" '\''PRAGMA integrity_check;'\'')" = ok ] || { echo "Restored SQLite database failed integrity checking" >&2; exit 1; }
if [ -f "$DATABASE_SQLITE_PATH" ]; then
    case "$(uname -s)" in
        Darwin) chmod "$(stat -f '\''%Lp'\'' "$DATABASE_SQLITE_PATH")" "$temporary" ;;
        *) chmod --reference="$DATABASE_SQLITE_PATH" "$temporary" ;;
    esac
fi
mv -f "$temporary" "$DATABASE_SQLITE_PATH"
printf '\''Database restored: %s\n'\'' "$DATABASE_SQLITE_PATH"

' sh "$DATABASE_DOCKER_SQLITE_PATH" < "$input"
else
[ ! -e "$DATABASE_SQLITE_PATH" ] || [ -f "$DATABASE_SQLITE_PATH" ] || { echo "SQLite target is not a regular file" >&2; exit 2; }
[ ! -L "$DATABASE_SQLITE_PATH" ] || { echo "Refusing to replace a SQLite symbolic link" >&2; exit 2; }
[ ! -e "$DATABASE_SQLITE_PATH-wal" ] && [ ! -e "$DATABASE_SQLITE_PATH-shm" ] || { echo "Stop the SQLite application and checkpoint its WAL before restoring" >&2; exit 2; }
temporary=$(mktemp "$(dirname "$DATABASE_SQLITE_PATH")/.kitflow-restore.XXXXXX")
trap 'rm -f "$temporary" "$temporary-wal" "$temporary-shm"' EXIT HUP INT TERM
sqlite3 -bail "$temporary" < "$input"
[ "$(sqlite3 -readonly "$temporary" 'PRAGMA integrity_check;')" = ok ] || { echo "Restored SQLite database failed integrity checking" >&2; exit 1; }
if [ -f "$DATABASE_SQLITE_PATH" ]; then
    case "$(uname -s)" in
        Darwin) chmod "$(stat -f '%Lp' "$DATABASE_SQLITE_PATH")" "$temporary" ;;
        *) chmod --reference="$DATABASE_SQLITE_PATH" "$temporary" ;;
    esac
fi
mv -f "$temporary" "$DATABASE_SQLITE_PATH"
printf 'Database restored: %s\n' "$DATABASE_SQLITE_PATH"
fi
