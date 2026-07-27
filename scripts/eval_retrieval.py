"""Eval: knowledge-base retrieval quality on TC-shaped questions.

Ten questions a Maine TC actually asks, each with the source document the
answer lives in. A case passes when the expected source appears in the top
results from `search_knowledge` (the same function the copilot's
search_knowledge_base tool and the email drafter's planned retrieval use).

Runs fully locally (sentence-transformers embeddings) — no API key needed:

    python scripts/eval_retrieval.py

Exit code 0 when every case passes, 1 otherwise.
"""

import sys

# (question, kind filter or None, expected source substring)
CASES: list[tuple[str, str | None, str]] = [
    (
        "What is required before a brokerage can act as a disclosed dual agent?",
        "legal",
        "maine_re_commission_rules",
    ),
    (
        "What must a written brokerage agreement contain?",
        "legal",
        "maine_title32",
    ),
    (
        "definition of an appointed agent under Maine license law",
        "legal",
        "maine_title32",
    ),
    (
        "fiduciary duties owed to a client under the REALTOR code",
        "legal",
        "nar_code_of_ethics",
    ),
    (
        "email to send a buyer about scheduling building inspections",
        "templates",
        "email_templates",
    ),
    (
        "closing procedure email — what should the client bring?",
        "templates",
        "email_templates",
    ),
    (
        "what does the office do when earnest money is received",
        "policies",
        "policies_and_procedures",
    ),
    (
        "who reviews the settlement statement before closing",
        "policies",
        "policies_and_procedures",
    ),
    (
        "fuel proration at closing — whose day is closing day?",
        None,
        "policies_and_procedures",
    ),
    (
        "final walkthrough timing before closing",
        None,
        "email_templates",
    ),
]


def main() -> int:
    from realtorai.rag.retrieval import search_knowledge

    failures = 0
    print(f"{'result':7s} {'kind':10s} {'expected in top hits':28s} question")
    for question, kind, expected in CASES:
        hits = search_knowledge(question, kind=kind, n_results=4)
        ok = expected in hits
        failures += 0 if ok else 1
        mark = "PASS" if ok else "FAIL"
        print(f"{mark:7s} {kind or 'any':10s} {expected:28s} {question[:44]}")

    print(f"\n{len(CASES) - failures}/{len(CASES)} retrievals found the right source")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
