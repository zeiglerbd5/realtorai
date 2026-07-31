"""Every captured record field must be able to reach a form.

This is the per-push half of the guard; `python -m realtorai.evals
schema-coverage` is the same logic behind a CLI for the CI job summary.

It exists because eight disclosure facts — personal property, unit count,
basement moisture, lead paint condition among them — were being extracted
correctly and then stranded in the free-text `comments` field, invisible to
every filler. Nothing caught that, because nothing was looking.
"""

import pytest

from realtorai.evals.field_map import destination_map, record_fields
from realtorai.evals.schema_coverage import (
    DELIBERATE_UNMAPPED,
    Disposition,
    audit,
    exempted_but_required,
    problems,
    stale_allowlist_entries,
    uncovered,
)


def test_no_field_is_silently_stranded() -> None:
    assert uncovered() == [], (
        "These record fields reach no destination and have no stated reason:\n  "
        + "\n  ".join(uncovered())
        + "\n\nMap them in a filler, or add them to DELIBERATE_UNMAPPED "
        "in src/realtorai/evals/schema_coverage.py with a reason."
    )


def test_allowlist_has_not_gone_stale() -> None:
    """A wired-up or renamed field must not keep its exemption."""
    assert stale_allowlist_entries() == [], "\n  ".join(stale_allowlist_entries())


def test_mls_required_fields_are_never_exempt() -> None:
    assert exempted_but_required() == []


def test_every_allowlist_entry_states_a_reason() -> None:
    blank = [name for name, reason in DELIBERATE_UNMAPPED.items() if not reason.strip()]
    assert blank == [], f"exempted without saying why: {blank}"


def test_audit_covers_every_field_exactly_once() -> None:
    assert set(audit()) == record_fields()


def test_deadline_only_fields_count_as_mapped() -> None:
    """`emd_due_date` prints on no form but reaches the dashboard deadline board."""
    disposition, detail = audit()["emd_due_date"]
    assert disposition is Disposition.MAPPED
    assert "DEAD" in detail


def test_guard_actually_fires_on_an_unmapped_field(monkeypatch: pytest.MonkeyPatch) -> None:
    """A green guard is worthless if it cannot go red."""
    from realtorai.evals import schema_coverage

    monkeypatch.setattr(
        schema_coverage, "record_fields", lambda: record_fields() | {"invented_field"}
    )
    assert "invented_field" in schema_coverage.uncovered()
    assert any("invented_field" in p for p in schema_coverage.problems())


def test_guard_fires_on_a_stale_allowlist_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    from realtorai.evals import schema_coverage

    # `city` is mapped to ten destinations — exempting it must be reported.
    monkeypatch.setattr(
        schema_coverage, "DELIBERATE_UNMAPPED", {**DELIBERATE_UNMAPPED, "city": "bogus"}
    )
    stale = schema_coverage.stale_allowlist_entries()
    assert any(entry.startswith("city:") for entry in stale)


def test_repo_is_currently_healthy() -> None:
    assert problems() == [], "\n  ".join(problems())


def test_allowlisted_fields_really_have_no_destinations() -> None:
    """Guards against an allowlist that describes an imaginary state."""
    usage = destination_map()
    assert [name for name in DELIBERATE_UNMAPPED if usage.get(name)] == []
