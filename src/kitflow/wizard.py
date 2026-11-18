"""Declarative wizard steps and selection changes, independent of the terminal UI."""

from contextlib import suppress
from dataclasses import dataclass

from kitflow.catalog import Catalog, KitFlowError


@dataclass(frozen=True)
class Step:
    id: str
    label: str
    categories: tuple[str, ...]
    description: str = ""


def validate_wizard(catalog: Catalog):
    categories = set()
    for row in catalog.data.get("steps", []):
        if row["id"] in {"review", "ownership"}:
            raise KitFlowError("Wizard step IDs review and ownership are reserved")
        if set(row) - {"id", "label", "categories", "description", "order", "when", "when_any"}:
            raise KitFlowError("Unknown wizard step field")
        if not isinstance(row.get("label"), str) or not row["label"].strip():
            raise KitFlowError("Wizard steps require a nonempty label")
        names = row.get("categories")
        if (
            not isinstance(names, list)
            or not names
            or any(not isinstance(x, str) or not x.strip() for x in names)
        ):
            raise KitFlowError("Step categories must be a nonempty array of names")
        if len(set(names)) != len(names) or categories.intersection(names):
            raise KitFlowError("A category may belong to only one wizard step")
        categories.update(names)
        if type(row.get("order", 0)) is not int:
            raise KitFlowError("Step order must be an integer")
        if not isinstance(row.get("description", ""), str):
            raise KitFlowError("Step description must be a string")
        catalog.enabled(row, set(catalog.components))
    for row in catalog.data["components"]:
        if type(row.get("recommended", False)) is not bool:
            raise KitFlowError("Component recommended must be a boolean")
        catalog.enabled(row, set(catalog.components))


class Wizard:
    def __init__(
        self, catalog: Catalog, selected: list[str], excluded: list[str], *, existing=False
    ):
        self.catalog = catalog
        self.chosen = set(catalog.resolve(selected))
        self.excluded = set(excluded)
        self.rows = {row["id"]: row for row in catalog.data["components"]}
        self.seen = (
            {identity for identity in self.rows if self.eligible(identity)} if existing else set()
        )
        self.step_rows = sorted(catalog.data.get("steps", []), key=lambda row: row.get("order", 0))
        assigned = {name for row in self.step_rows for name in row["categories"]}
        # Legacy catalogs and new user categories work without extra wizard definitions.
        for category in dict.fromkeys(c.category for c in catalog.components.values()):
            if category not in assigned:
                self.step_rows.append(
                    {"id": f"category:{category}", "label": category, "categories": [category]}
                )

    def eligible(self, identity: str) -> bool:
        row = self.rows[identity]
        if not self.catalog.enabled(row, self.chosen):
            return False
        return bool("when" in row or "when_any" in row) or set(row.get("requires", [])).issubset(
            self.chosen
        )

    def choices(self, step: Step) -> list[str]:
        return [
            identity
            for identity, component in self.catalog.components.items()
            if component.category in step.categories
            and (identity in self.chosen or self.eligible(identity))
        ]

    def steps(self) -> list[Step]:
        result = []
        for row in self.step_rows:
            step = Step(
                row["id"], row["label"], tuple(row["categories"]), row.get("description", "")
            )
            if self.catalog.enabled(row, self.chosen) and self.choices(step):
                result.append(step)
        if self.excluded:
            result.append(
                Step(
                    "ownership",
                    "User-owned files and blocks",
                    (),
                    "Select an entry to return it to KitFlow management.",
                )
            )
        result.append(Step("review", "Review plan", ()))
        return result

    def enter(self, step: Step):
        for identity in self.choices(step):
            if identity not in self.seen and self.rows[identity].get("recommended", False):
                # A recommendation never overrides a user's conflicting selection.
                with suppress(KitFlowError):
                    self.chosen = set(self.catalog.resolve(sorted(self.chosen | {identity})))
            self.seen.add(identity)

    def remove(self, identities: set[str]) -> set[str]:
        removed = set(identities)
        while True:
            dependent = {
                identity
                for identity in self.chosen
                if removed.intersection(self.catalog.components[identity].requires)
            }
            if dependent.issubset(removed):
                break
            removed.update(dependent)
        self.chosen -= removed
        return removed

    def toggle(self, identity: str) -> tuple[set[str], set[str]]:
        before = self.chosen.copy()
        previously_available = {
            x for x in self.chosen if self.catalog.enabled(self.rows[x], self.chosen)
        }
        if identity in self.chosen:
            self.remove({identity})
        else:
            # Selecting an alternative replaces its conflicting components and their dependents.
            conflicts = {
                other
                for other in self.chosen
                if other in self.catalog.components[identity].conflicts
                or identity in self.catalog.components[other].conflicts
            }
            self.remove(conflicts)
            try:
                self.chosen = set(self.catalog.resolve(sorted(self.chosen | {identity})))
            except KitFlowError:
                self.chosen = before
                raise
        while True:
            invalid = {
                x
                for x in self.chosen & previously_available
                if not self.catalog.enabled(self.rows[x], self.chosen)
            }
            if not invalid:
                break
            self.remove(invalid)
        self.seen.add(identity)
        return self.chosen - before, before - self.chosen
