"""Deed review: flag restrictions, rights of way, and anything out of the ordinary.

Runs on the REVIEW tier (Opus) — a missed easement or restrictive covenant is
exactly the kind of error that surfaces at title-commitment time and blows up
a closing. Findings land in the master info document and as a room-uploadable
artifact.
"""

from typing import Literal

import structlog
from pydantic import BaseModel, Field

from realtorai.inference.claude_engine import get_claude_engine
from realtorai.inference.model_router import LLMTask

logger = structlog.get_logger()


class DeedFinding(BaseModel):
    """One notable item found in the deed."""

    kind: Literal[
        "restriction",
        "right_of_way",
        "easement",
        "exception",
        "encumbrance",
        "chain_of_title",
        "other",
    ]
    severity: Literal["info", "warning", "critical"]
    excerpt: str = Field(description="The deed language that triggered the finding, quoted")
    explanation: str = Field(description="Plain-English impact for the seller/buyer")


class DeedReviewReport(BaseModel):
    """Full deed review result."""

    findings: list[DeedFinding] = Field(default_factory=list)
    summary: str
    out_of_ordinary: bool = Field(
        description="True if anything beyond boilerplate conveyance language was found"
    )


DEED_REVIEW_SYSTEM = """You are reviewing a recorded Maine deed for a real-estate \
brokerage before listing the property. Identify anything a transaction \
coordinator must flag to the agent and title company:

- Restrictions and restrictive covenants
- Rights of way and easements (granted or reserved, including railroad, \
utility, and shared-driveway language)
- Exceptions and reservations from the conveyance ("excepting", "reserving", \
"subject to")
- Encumbrances, life estates, mineral/timber rights
- Chain-of-title oddities (quitclaim where warranty expected, estate/heir \
conveyances, gaps)

Quote the operative deed language in each finding. Ordinary boilerplate \
(habendum clause, standard warranty covenants) is NOT a finding. Report every \
genuine item, including uncertain ones — a human reviews this list."""


async def review_deed(
    deed_text: str | None = None,
    property_label: str = "",
    *,
    deed_pdf: bytes | None = None,
) -> DeedReviewReport:
    """Analyze a deed for restrictions/ROWs (REVIEW tier).

    Accepts plain text OR a scanned PDF (registry pulls) — Claude reads the
    scan directly, watermark overlay and all.
    """
    if deed_text is None and deed_pdf is None:
        raise ValueError("review_deed needs deed_text or deed_pdf")
    engine = get_claude_engine()
    header = f"Property: {property_label}\n\n" if property_label else ""
    if deed_pdf is not None:
        prompt = header + (
            "The attached PDF is the recorded deed as pulled from the county "
            "registry (free-view copy — ignore the NOT AN OFFICIAL COPY "
            "watermark overlay). Review it."
        )
    else:
        prompt = header + "Deed text:\n\n" + (deed_text or "")
    report = await engine.generate_structured(
        prompt,
        DeedReviewReport,
        task=LLMTask.DEED_REVIEW,
        system_prompt=DEED_REVIEW_SYSTEM,
        pdf=deed_pdf,
    )
    logger.info(
        "deed_reviewed",
        findings=len(report.findings),
        out_of_ordinary=report.out_of_ordinary,
    )
    return report


def render_deed_review_markdown(report: DeedReviewReport, property_label: str = "") -> str:
    """Render the report as a room-uploadable markdown artifact."""
    title = f"Deed Review — {property_label}" if property_label else "Deed Review"
    out = [f"# {title}", "", report.summary, ""]
    if not report.findings:
        out.append("No restrictions, rights of way, or unusual provisions identified.")
    for finding in report.findings:
        kind = finding.kind.replace("_", " ").title()
        out.append(f"## [{finding.severity.upper()}] {kind}")
        out.append("")
        out.append(f"> {finding.excerpt}")
        out.append("")
        out.append(finding.explanation)
        out.append("")
    return "\n".join(out).rstrip() + "\n"
