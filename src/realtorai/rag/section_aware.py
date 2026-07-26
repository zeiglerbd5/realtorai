"""Section-aware text splitting for legal/regulatory documents.

Standard chunkers split text into fixed-size windows, which often separates a
section header (e.g. "§13271. Definitions.") from the subsection content
underneath it (e.g. "7. Disclosed dual agent."). The LLM then sees the
content without knowing which section it belongs to and either hallucinates
or attaches the content to the wrong section number.

This module detects section markers in legal documents and exposes
`split_by_sections()` which returns (header, body) tuples. Downstream chunking
operates *within* each section's body and prepends the section header to each
chunk — so every chunk that the model sees is self-identifying.

Supported styles:
- maine_mrsa: Maine Revised Statutes (e.g., Title 32 Ch. 114) — `§NNNNN.  Name`
- commission_rules: Maine Real Estate Commission rules — `SECTION N. Name`
"""

import re
from typing import Literal

SectionStyle = Literal["maine_mrsa", "commission_rules"]


# Maine MRSA: e.g. "§13271. Definitions" or "§13271.  Real estate brokerage..."
# Section numbers are 4-5 digits. We capture the section and a short name
# (up to the next newline, capped at 80 chars).
_MAINE_MRSA_PATTERN = re.compile(
    r"(?:^|\n)\s*§(\d{4,5})\.\s*([^\n]{1,80})",
    re.MULTILINE,
)

# Commission Rules: e.g. "SECTION 8. Appointed Agent Procedures and Disclosure"
_COMMISSION_RULES_PATTERN = re.compile(
    r"(?:^|\n)\s*SECTION\s+(\d+)\.\s*([^\n]{1,120})",
    re.MULTILINE,
)


def detect_section_style(text: str) -> SectionStyle | None:
    """Detect which (if any) legal-doc section style this text uses.

    Looks at the first 20 KB; needs at least 2 distinct section markers to
    declare a style (avoids false positives from incidental text).
    """
    head = text[:20_000]

    mrsa_hits = len(set(_MAINE_MRSA_PATTERN.findall(head)))
    rules_hits = len(set(_COMMISSION_RULES_PATTERN.findall(head)))

    if mrsa_hits >= 2 and mrsa_hits >= rules_hits:
        return "maine_mrsa"
    if rules_hits >= 2:
        return "commission_rules"
    return None


def _format_header(style: SectionStyle, num: str, name: str) -> str:
    """Render a section header in the canonical form we prepend to chunks."""
    name = name.strip().rstrip(".").strip()
    # Strip noise that sometimes follows the header on the same line
    # (e.g. cross-reference notes in brackets)
    name = re.sub(r"\s*\[.*$", "", name).strip()
    # Limit name length defensively
    if len(name) > 80:
        name = name[:80].rstrip() + "..."
    if style == "maine_mrsa":
        return f"§{num}. {name}" if name else f"§{num}"
    if style == "commission_rules":
        return f"SECTION {num}. {name}" if name else f"SECTION {num}"
    return f"{num}. {name}"


def split_by_sections(text: str, style: SectionStyle) -> list[tuple[str, str]]:
    """Split `text` into (section_header, body) tuples.

    Body excludes the header line itself; the header is the canonical form
    (e.g. "§13271. Definitions") suitable for prepending to chunks.

    If a span of text appears before the first section header (e.g. preamble,
    table of contents), it's returned with header="" so the caller can still
    ingest it as preamble context.
    """
    pattern = _MAINE_MRSA_PATTERN if style == "maine_mrsa" else _COMMISSION_RULES_PATTERN
    matches = list(pattern.finditer(text))

    if not matches:
        return [("", text)]

    out: list[tuple[str, str]] = []

    # Preamble (anything before the first match)
    first = matches[0]
    if first.start() > 0:
        preamble = text[: first.start()].strip()
        if preamble:
            out.append(("", preamble))

    # Each section runs from end-of-header-line to start of next match
    for i, m in enumerate(matches):
        num, raw_name = m.group(1), m.group(2)
        header = _format_header(style, num, raw_name)
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        if body:
            out.append((header, body))

    return out
