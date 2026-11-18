"""Plan project migrations before applying a new standard Box."""

from collections.abc import Callable
from copy import deepcopy
from pathlib import Path

from kitflow.catalog import KitFlowError
from kitflow.engine import CONFIG, Plan, preview_files, read_file

# Revision 1 is the baseline after retiring the initial migration.
BASELINE = 1
MIGRATIONS: dict[int, Callable[[Plan, str], None]] = {}


def require_supported_migration(required: int):
    if required > max(MIGRATIONS, default=BASELINE):
        raise KitFlowError(f"Box requires migration {required}; upgrade KitFlow first")


def plan_migrations(
    root: Path, document: dict, snapshot: bytes | None, required: int
) -> Plan | None:
    require_supported_migration(required)
    migrated = max(BASELINE, document.get("migrated_box_version", 0))
    pending = [revision for revision in sorted(MIGRATIONS) if migrated < revision <= required]
    if not pending:
        return None
    result = Plan(root, deepcopy(document), list(document["selection"].get("components", [])))
    result.snapshots[CONFIG] = snapshot
    content = read_file(root / "mise.toml")
    result.snapshots["mise.toml"] = content
    text = (content or b"").decode()
    for revision in pending:
        MIGRATIONS[revision](result, text)
        if updated := preview_files(result).get("mise.toml"):
            assert isinstance(updated[1], bytes)
            text = updated[1].decode()
    result.document["migrated_box_version"] = pending[-1]
    return result
