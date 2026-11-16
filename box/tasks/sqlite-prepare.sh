[ "${DATABASE_TARGET:-native}" = native ] || { echo "Prepare SQLite in the container explicitly" >&2; exit 2; }
: "${DATABASE_SQLITE_PATH:?Set vars.database_sqlite_path}"
[ ! -e "$DATABASE_SQLITE_PATH" ] && [ ! -L "$DATABASE_SQLITE_PATH" ] || { echo "SQLite database already exists" >&2; exit 2; }
temporary=$(mktemp "$(dirname "$DATABASE_SQLITE_PATH")/.kitflow-prepare.XXXXXX")
trap 'rm -f "$temporary" "$temporary-wal" "$temporary-shm"' EXIT HUP INT TERM
if [ -n "${DATABASE_INIT_SQL:-}" ]; then
    [ -f "$DATABASE_INIT_SQL" ] || { echo "Initialization SQL does not exist: $DATABASE_INIT_SQL" >&2; exit 2; }
    sqlite3 -bail "$temporary" < "$DATABASE_INIT_SQL"
else
    sqlite3 -bail "$temporary" 'PRAGMA user_version=0;'
fi
ln "$temporary" "$DATABASE_SQLITE_PATH"
