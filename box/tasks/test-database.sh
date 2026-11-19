uv run --project "${PROJECT_ROOT:-$PWD}" python - <<'KITFLOW_TEST_DATABASE'
import os
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit


def fail(message):
    raise SystemExit(message)


def pg_endpoint(value):
    try:
        url = urlsplit(value)
        if (
            url.scheme in {"postgresql", "postgres"}
            and url.hostname
            and url.username
            and url.path.strip("/")
            and not (
                {"host", "hostaddr", "port", "dbname", "user", "service"}
                & parse_qs(url.query, keep_blank_values=True).keys()
            )
        ):
            return unquote(url.path[1:]), unquote(url.username)
    except ValueError:
        pass
    return None


env = os.environ
backend = env.get("TEST_DATABASE_BACKEND")
if backend == "sqlite":
    path = env.get("TEST_SQLITE_DATABASE_PATH", "")
    if not path or path.startswith("file:"):
        fail("Set TEST_SQLITE_DATABASE_PATH to :memory: or a separate filesystem path.")
    if path != ":memory:":
        test = Path(path).resolve()
        primary = env.get("SQLITE_DATABASE_PATH")
        if primary:
            primary_paths = [Path(primary)]
            if not Path(primary).is_absolute():
                primary_paths.extend(
                    Path(env[key]) / primary
                    for key in ("PROJECT_ROOT", "PYTHON_SOURCE")
                    if env.get(key)
                )
            for candidate in primary_paths:
                if (
                    candidate.resolve() == test
                    or (test.exists() and candidate.exists() and test.samefile(candidate))
                ):
                    fail("TEST_SQLITE_DATABASE_PATH points to the application database.")
elif backend == "postgresql":
    endpoint = pg_endpoint(env.get("TEST_DATABASE_URL", ""))
    if endpoint is None:
        fail("Set TEST_DATABASE_URL to a PostgreSQL URL with a dedicated database and user.")
    name, user = endpoint
    application = pg_endpoint(env.get("DATABASE_URL", ""))
    if (
        name == env.get("PGDATABASE")
        or user == env.get("PGUSER")
        or (application and (name == application[0] or user == application[1]))
    ):
        fail("TEST_DATABASE_URL must use a separate PostgreSQL database and user.")
else:
    fail("Select SQLite or PostgreSQL as the test database in KitFlow.")
KITFLOW_TEST_DATABASE
