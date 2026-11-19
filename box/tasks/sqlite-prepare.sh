case "${SQLITE_MODE:-local}" in
    local) ;;
    remote) echo "This task requires a local SQLite file; use the remote service's database tools." >&2; exit 2 ;;
    *) echo "SQLITE_MODE must be local or remote." >&2; exit 2 ;;
esac
[ "${DATABASE_EXECUTION_MODE:-native}" = native ] || { echo "Prepare SQLite in the container explicitly" >&2; exit 2; }
: "${SQLITE_DATABASE_PATH:?Set vars.sqlite_database_path}"
[ ! -e "$SQLITE_DATABASE_PATH" ] && [ ! -L "$SQLITE_DATABASE_PATH" ] || { echo "SQLite database already exists" >&2; exit 2; }
mkdir -p "$(dirname "$SQLITE_DATABASE_PATH")"
temporary=$(mktemp "$(dirname "$SQLITE_DATABASE_PATH")/.kitflow-prepare.XXXXXX")
trap 'rm -f "$temporary" "$temporary-wal" "$temporary-shm"' EXIT HUP INT TERM
if [ -n "${SQLITE_INIT_SQL:-}" ]; then
    [ -f "$SQLITE_INIT_SQL" ] || { echo "Initialization SQL does not exist: $SQLITE_INIT_SQL" >&2; exit 2; }
    sqlite3 -bail "$temporary" < "$SQLITE_INIT_SQL"
else
    sqlite3 -bail "$temporary" 'PRAGMA user_version=0;'
fi
ln "$temporary" "$SQLITE_DATABASE_PATH"
