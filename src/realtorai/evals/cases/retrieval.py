"""Retrieval cases: ten questions a Maine TC actually asks.

A case passes when the expected source appears in the top-k. Scoring is on
`metadata["source"]`, matched exactly — the old version substring-matched
against the rendered citation block, which also matched chunk *body* text and
passed whenever a document happened to mention another document's filename.

Six of these expect the office's internal manual or email templates. Those two
files are deliberately gitignored (`.gitignore` — "Agency-internal documents,
kept locally for RAG, never published"), so they cannot exist in CI. Rather
than delete the cases and lose half the local signal, each declares what it
`requires`: locally all ten run, in CI the four legal cases run and the rest
report `skip` with a reason. `--min-cases` stops an all-skipped run from
reading as green.
"""

from realtorai.evals.harness import Case

#: Publicly obtainable — CI fetches these by URL (see evals/corpus.py).
LEGAL_SOURCES: tuple[str, ...] = (
    "maine_title32_ch114.pdf",
    "maine_re_commission_rules_2025-10.pdf",
    "nar_code_of_ethics_2026.pdf",
)

#: Agency-internal, gitignored. Cases needing these skip outside a dev machine.
PRIVATE_SOURCES: tuple[str, ...] = (
    "email_templates.md",
    "policies_and_procedures.md",
)


def _case(
    case_id: str, question: str, kind: str | None, expected: str, *, tags: tuple[str, ...] = ()
) -> Case:
    return Case(
        id=case_id,
        inputs={"question": question, "kind": kind},
        expected=expected,
        tags=tags + (("private",) if expected in PRIVATE_SOURCES else ("public",)),
        requires=(expected,),
    )


RETRIEVAL_CASES: tuple[Case, ...] = (
    _case(
        "dual-agency-prerequisites",
        "What is required before a brokerage can act as a disclosed dual agent?",
        "legal",
        "maine_re_commission_rules_2025-10.pdf",
    ),
    _case(
        "brokerage-agreement-contents",
        "What must a written brokerage agreement contain?",
        "legal",
        "maine_title32_ch114.pdf",
    ),
    _case(
        "appointed-agent-definition",
        "definition of an appointed agent under Maine license law",
        "legal",
        "maine_title32_ch114.pdf",
    ),
    _case(
        "realtor-fiduciary-duties",
        "fiduciary duties owed to a client under the REALTOR code",
        "legal",
        "nar_code_of_ethics_2026.pdf",
    ),
    _case(
        "inspection-scheduling-email",
        "email to send a buyer about scheduling building inspections",
        "templates",
        "email_templates.md",
    ),
    _case(
        "closing-procedure-email",
        "closing procedure email — what should the client bring?",
        "templates",
        "email_templates.md",
    ),
    _case(
        "emd-office-handling",
        "what does the office do when earnest money is received",
        "policies",
        "policies_and_procedures.md",
    ),
    _case(
        "settlement-statement-review",
        "who reviews the settlement statement before closing",
        "policies",
        "policies_and_procedures.md",
    ),
    _case(
        "fuel-proration-unfiltered",
        "fuel proration at closing — whose day is closing day?",
        None,
        "policies_and_procedures.md",
        tags=("unfiltered",),
    ),
    _case(
        "walkthrough-timing-unfiltered",
        "final walkthrough timing before closing",
        None,
        "email_templates.md",
        tags=("unfiltered",),
    ),
)
