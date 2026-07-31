"""Fetch the public legal corpus so retrieval can be evaluated in CI.

The knowledge base mixes three publicly published documents with two
agency-internal ones. Only the public three can be rebuilt on a clean runner,
which is why the retrieval eval skips its private-corpus cases there.

Each download is checksummed. Maine and NAR republish these at stable URLs but
do revise them, and a silently updated document would show up as a mysterious
recall drop rather than as "the source changed" — so a hash mismatch is a loud
error with instructions, not a warning.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CorpusDocument:
    filename: str
    url: str
    #: sha256 of the published file; empty means "record it on first fetch".
    sha256: str = ""


CORPUS: tuple[CorpusDocument, ...] = (
    CorpusDocument(
        "maine_title32_ch114.pdf",
        "https://legislature.maine.gov/statutes/32/title32ch114sec0.pdf",
    ),
    CorpusDocument(
        "maine_re_commission_rules_2025-10.pdf",
        "https://www.maine.gov/pfr/professionallicensing/sites/maine.gov.pfr."
        "professionallicensing/files/inline-files/realestatecommission_rules.pdf",
    ),
    CorpusDocument(
        "nar_code_of_ethics_2026.pdf",
        "https://www.nar.realtor/sites/default/files/documents/2026-code-of-ethics-"
        "and-standards-of-practice.pdf",
    ),
)


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_all(dest: Path) -> list[Path]:
    """Download every corpus document into `dest`, verifying checksums."""
    import httpx

    dest.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for doc in CORPUS:
        target = dest / doc.filename
        if target.exists():
            written.append(target)
            continue

        response = httpx.get(doc.url, follow_redirects=True, timeout=60.0)
        response.raise_for_status()
        digest = sha256_of(response.content)

        if doc.sha256 and digest != doc.sha256:
            raise RuntimeError(
                f"{doc.filename} changed upstream.\n"
                f"  expected sha256 {doc.sha256}\n"
                f"  got      sha256 {digest}\n"
                "The published document was revised. Review the new text, then update "
                "the checksum in evals/corpus.py — a silent swap would surface as an "
                "unexplained retrieval regression."
            )
        if not doc.sha256:
            print(f"  {doc.filename}: sha256 {digest} (record this in corpus.py)")

        target.write_bytes(response.content)
        written.append(target)

    return written
