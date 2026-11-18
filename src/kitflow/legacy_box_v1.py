"""Temporary Box 0 → 1 migration. Remove after existing projects have migrated."""

from kitflow import mise
from kitflow.catalog import Artifact
from kitflow.engine import Change, Plan

TRANSLATION_COMPONENTS = {"django-i18n", "babel-i18n", "script-i18n"}
TRANSLATION_KEYS = {
    "i18n_source_language",
    "i18n_languages",
    "i18n_directory",
    "i18n_babel_config",
    "i18n_script",
}


def migrate(result: Plan, text: str):
    registry = {("vars", name) for name in TRANSLATION_KEYS}
    registry.update(("env", name.upper()) for name in TRANSLATION_KEYS)
    existing = registry & mise.setting_keys(mise.parse(text))
    if not existing:
        return
    keys = ", ".join(".".join(key) for key in sorted(existing))
    if TRANSLATION_COMPONENTS.intersection(result.selected):
        state = result.document.setdefault("state", {})
        owned = set(map(tuple, state.get("seeded_mise_keys", [])))
        state["seeded_mise_keys"] = [list(key) for key in sorted(owned | existing)]
        artifact = Artifact("migration.translation", "mise.toml", b"", True, "defaults")
        result.changes.append(
            Change(artifact, None, None, "track-settings", reason=f"Track: {keys}")
        )
    else:
        artifact = Artifact("migration.translation", "mise.toml", b"", True, "defaults")
        result.changes.append(
            Change(
                artifact,
                None,
                None,
                "remove-settings",
                reason=f"Remove obsolete Translation keys: {keys}",
                setting_keys=tuple(sorted(existing)),
            )
        )
