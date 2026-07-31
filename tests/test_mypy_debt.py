"""The mypy debt list must describe modules that actually exist.

CI gates on `mypy src/realtorai`, which passes only because 55 modules are
listed under an `ignore_errors` override in pyproject.toml. That list is the
type-debt counter — it should shrink and never grow.

The failure mode it guards against is quiet: rename `workflows/listing.py` and
its old dotted path stays in the list forever, exempting nothing while the
renamed module silently becomes strict (or, if the rename is partial, stays
exempt under a name nobody recognises). Either way the list stops meaning what
it claims.
"""

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"
SRC = Path(__file__).resolve().parent.parent / "src"


def debt_modules() -> list[str]:
    config = tomllib.loads(PYPROJECT.read_text())
    for override in config["tool"]["mypy"]["overrides"]:
        if override.get("ignore_errors"):
            modules: list[str] = override["module"]
            return modules
    return []


def module_exists(dotted: str) -> bool:
    relative = Path(*dotted.split("."))
    return (SRC / relative).with_suffix(".py").exists() or (
        SRC / relative / "__init__.py"
    ).exists()


def test_the_debt_list_is_not_empty_by_accident() -> None:
    """If this ever legitimately empties, delete the override and this test."""
    assert debt_modules(), "no ignore_errors override found — did the table move?"


def test_every_exempted_module_still_exists() -> None:
    missing = [m for m in debt_modules() if not module_exists(m)]
    assert missing == [], (
        "These modules are exempted from mypy but no longer exist — they were "
        f"renamed or deleted. Remove them from pyproject.toml:\n  {missing}"
    )


def test_no_duplicate_entries() -> None:
    modules = debt_modules()
    duplicates = sorted({m for m in modules if modules.count(m) > 1})
    assert duplicates == [], f"listed twice: {duplicates}"


def test_the_list_stays_sorted() -> None:
    """Sorted order keeps the diff readable when an entry is removed."""
    modules = debt_modules()
    assert modules == sorted(modules), "keep the debt list alphabetical"


def test_new_eval_code_is_not_exempt() -> None:
    """The harness was written strict from birth; it must stay that way."""
    exempt = [m for m in debt_modules() if m.startswith("realtorai.evals")]
    assert exempt == [], f"evals must remain strict-typed, but found: {exempt}"
