"""Guard: every captured record field can actually reach a form.

One extraction pass populates all downstream paperwork, so a field with no
destination is data the pipeline extracted and then stranded. That is not
hypothetical — personal property, unit count, basement moisture, and lead
paint condition all used to arrive as free text inside `comments`, where the
MIS filler, the TW filler, and the MLS feeder could not read them. They were
extracted correctly and reached nothing.

Three rules, all enforced:

1. Every field is mapped to a destination, or listed in `DELIBERATE_UNMAPPED`
   with a stated reason.
2. Every allowlist entry still exists on the record *and* still has zero
   destinations. Without this, the allowlist rots into a permanent mute
   button: a field gets wired up, nobody removes the exemption, and the next
   genuinely stranded field hides behind a stale entry.
3. No MLS-required field is exempt. A required field with no destination is
   unambiguously a bug, so rule 1's escape hatch does not apply.

Note that a deadline *is* a destination — `emd_due_date` reaches the operator
through the dashboard board even though it prints on no form. That is the
`DEAD` tag in `field_map`, not an exemption here.
"""

from __future__ import annotations

from enum import StrEnum

from realtorai.evals.field_map import destination_map, mls_required_fields, record_fields


class Disposition(StrEnum):
    MAPPED = "mapped"
    DELIBERATE = "deliberate"
    UNCOVERED = "uncovered"


#: Fields captured on purpose that no form consumes yet. Each entry needs a
#: reason someone can act on later — "why is this here" is the whole point.
#:
#: These eight are disclosure facts recovered from the `comments` blob. They
#: are structured now so a P&S, a disclosure, or a buyer question can reach
#: them; wiring them to fillers is separate work.
DELIBERATE_UNMAPPED: dict[str, str] = {
    "unit_count": "MLS-required on Multi-Family, but no filler consumes it yet",
    "personal_property_included": "SPD/P&S fact — recovered from the `comments` blob",
    "system_updates": "SPD fact (replacements + service history) — recovered from `comments`",
    "known_defects": "SPD fact — recovered from the `comments` blob",
    "basement_moisture": "SPD fact (water intrusion) — recovered from `comments`",
    "sump_pump": "SPD fact — recovered from the `comments` blob",
    "lead_paint_status": "LEAD disclosure fact; distinct from whether the form was signed",
    "lead_paint_condition": "LEAD disclosure fact (observed paint condition)",
}


def audit() -> dict[str, tuple[Disposition, str]]:
    """Every record field -> (disposition, explanation)."""
    usage = destination_map()
    out: dict[str, tuple[Disposition, str]] = {}
    for name in sorted(record_fields()):
        destinations = usage.get(name) or []
        if destinations:
            out[name] = (Disposition.MAPPED, ", ".join(destinations))
        elif name in DELIBERATE_UNMAPPED:
            out[name] = (Disposition.DELIBERATE, DELIBERATE_UNMAPPED[name])
        else:
            out[name] = (Disposition.UNCOVERED, "no destination and no stated reason")
    return out


def uncovered() -> list[str]:
    """Rule 1: fields that reach nothing and have no stated reason."""
    return [n for n, (d, _) in audit().items() if d is Disposition.UNCOVERED]


def stale_allowlist_entries() -> list[str]:
    """Rule 2: allowlist entries that are renamed away or now actually mapped."""
    usage = destination_map()
    fields = record_fields()
    stale = []
    for name in sorted(DELIBERATE_UNMAPPED):
        if name not in fields:
            stale.append(f"{name}: no longer a field on TransactionRecord (renamed or removed)")
        elif usage.get(name):
            stale.append(
                f"{name}: now reaches {', '.join(usage[name])} — remove the exemption"
            )
    return stale


def exempted_but_required() -> list[str]:
    """Rule 3: MLS-required fields must never be exempt."""
    return sorted(mls_required_fields() & set(DELIBERATE_UNMAPPED))


def problems() -> list[str]:
    """All rule violations, as operator-readable lines. Empty means healthy."""
    messages = []
    for name in uncovered():
        messages.append(
            f"`{name}` has no destination. Either map it in a filler, or add it to "
            "DELIBERATE_UNMAPPED in evals/schema_coverage.py with a reason."
        )
    messages += [f"stale allowlist entry — {line}" for line in stale_allowlist_entries()]
    messages += [
        f"`{name}` is MLS-required and must not be exempt — wire it to a destination."
        for name in exempted_but_required()
    ]
    return messages


def summary() -> str:
    counts: dict[str, int] = {}
    for disposition, _ in audit().values():
        counts[disposition] = counts.get(disposition, 0) + 1
    return (
        f"{counts.get(Disposition.MAPPED, 0)} mapped · "
        f"{counts.get(Disposition.DELIBERATE, 0)} captured-but-unmapped (allowlisted) · "
        f"{counts.get(Disposition.UNCOVERED, 0)} uncovered"
    )
