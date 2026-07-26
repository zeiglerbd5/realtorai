"""Intake: client paperwork -> canonical TransactionRecord.

The realtor signs a new client and emails the paperwork to the bot. This
module turns those documents (Exclusive Right to Sell / Exclusive Buyer
Representation Agreement, Brokerage Relationship Form, disclosures, deed,
tax card) into the master TransactionRecord, then runs a second-model
verification pass over the extraction.

Model routing (inference/model_router.py):
  - classification + extraction -> STANDARD tier (Sonnet)
  - verification                -> REVIEW tier (Opus)
"""

from pathlib import Path
from typing import Literal

import structlog
from pydantic import BaseModel, Field

from realtorai.inference.claude_engine import get_claude_engine
from realtorai.inference.model_router import LLMTask
from realtorai.schemas.transaction import TransactionRecord

logger = structlog.get_logger()


class PaperworkDocument(BaseModel):
    """One intake document, reduced to text."""

    name: str
    text: str


def load_paperwork(paths: list[Path]) -> list[PaperworkDocument]:
    """Load PDFs / text files into PaperworkDocuments."""
    documents: list[PaperworkDocument] = []
    for path in paths:
        if not path.exists():
            logger.warning("paperwork_missing", path=str(path))
            continue
        documents.append(paperwork_from_bytes(path.name, path.read_bytes()))
    return documents


def paperwork_from_bytes(name: str, content: bytes) -> PaperworkDocument:
    """Build a PaperworkDocument from raw bytes (email attachments).

    A corrupt or scan-only PDF yields empty text rather than an exception —
    the document still gets filed to the room, and extraction works from
    whatever text the other documents provide.
    """
    if name.lower().endswith(".pdf"):
        import io

        from pypdf import PdfReader

        try:
            reader = PdfReader(io.BytesIO(content))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as e:
            logger.warning("paperwork_pdf_unreadable", name=name, error=str(e))
            text = ""
    else:
        text = content.decode("utf-8", errors="replace")
    return PaperworkDocument(name=name, text=text)


def _documents_block(documents: list[PaperworkDocument]) -> str:
    parts = []
    for doc in documents:
        parts.append(f'<document name="{doc.name}">\n{doc.text}\n</document>')
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Intake classification — "here's the new client's paperwork"
# ---------------------------------------------------------------------------


class IntakeClassification(BaseModel):
    """What kind of new-client intake an email represents."""

    intent: Literal["new_listing_client", "new_buyer_client", "other"]
    client_name: str | None = Field(default=None, description="Client name if identifiable")
    property_address: str | None = Field(default=None, description="Listing address if present")
    confidence: Literal["high", "medium", "low"]
    reasoning: str


CLASSIFY_SYSTEM = """You triage inbound email for a Maine real-estate transaction \
coordinator. Decide whether the email is a realtor handing off a NEW CLIENT, and \
which side. The handoff takes two forms: the client's signed paperwork (e.g. a \
completed DocuSign envelope with an ERTS or buyer agreement attached), or a prose \
handoff from an agent naming the new client and their property — possibly with no \
attachments, and rooms/documents may already exist. "new_listing_client" = seller \
side (Exclusive Right to Sell). "new_buyer_client" = buyer side (Exclusive Buyer \
Representation Agreement). Anything else — activity on deals already in progress \
(offers, counters, earnest money, disclosures, showings), office broadcasts, \
vendor mail, marketing — is "other". If one email hands off multiple new clients, \
put the first in client_name/property_address and list the rest in reasoning."""


async def classify_intake_email(
    subject: str, body: str, attachment_names: list[str]
) -> IntakeClassification:
    engine = get_claude_engine()
    prompt = (
        f"Subject: {subject}\n\nBody:\n{body}\n\n"
        f"Attachments: {', '.join(attachment_names) or '(none)'}"
    )
    return await engine.generate_structured(
        prompt,
        IntakeClassification,
        task=LLMTask.CLASSIFY,
        system_prompt=CLASSIFY_SYSTEM,
        max_tokens=2000,
    )


# ---------------------------------------------------------------------------
# Extraction — paperwork -> TransactionRecord
# ---------------------------------------------------------------------------

EXTRACT_SYSTEM = """You are a meticulous Maine real-estate transaction coordinator \
extracting data from a new client's signed paperwork into a canonical transaction \
record.

Rules:
- Only extract what the documents actually state. Leave unknown fields null — \
never guess or invent values.
- Preserve parcel IDs and Map/Lot references VERBATIM in the source's format; \
Maine towns each use their own convention.
- `state` uses DocuSign's US-XX format (e.g. "US-ME").
- `effective_date` is the date of last party signature (mutual acceptance); on a \
new listing it is the listing term start date.
- Deed references: capture book and page separately.
- If the tax card and another document disagree (e.g. year built), prefer the tax \
card and note the discrepancy in `comments`.
- Put material facts that don't fit a field (included personal property, known \
defects, heat systems, lead paint status) into `comments`."""


async def extract_transaction_record(
    documents: list[PaperworkDocument],
    side_hint: Literal["Listing", "Buyer"] | None = None,
    operator_notes: str | None = None,
) -> TransactionRecord:
    """Extract the canonical record from intake paperwork (STANDARD tier)."""
    engine = get_claude_engine()
    hint = f"\n\nRepresentation side hint from intake email: {side_hint}" if side_hint else ""
    notes = (
        f"\n\nOperator notes (from the human TC — authoritative):\n{operator_notes}"
        if operator_notes
        else ""
    )
    prompt = (
        "Extract the transaction record from these documents." + hint + notes + "\n\n"
        + _documents_block(documents)
    )
    record = await engine.generate_structured(
        prompt,
        TransactionRecord,
        task=LLMTask.EXTRACT,
        system_prompt=EXTRACT_SYSTEM,
    )
    logger.info(
        "intake_record_extracted",
        address=record.street_address,
        side=record.representation_side,
    )
    return record


# ---------------------------------------------------------------------------
# Verification — second-model pass (REVIEW tier)
# ---------------------------------------------------------------------------


class VerificationIssue(BaseModel):
    """One problem found when checking the extraction against sources."""

    field: str = Field(description="Canonical field name, e.g. 'effective_date'")
    issue: str = Field(description="What is wrong or suspicious")
    severity: Literal["info", "warning", "critical"]
    evidence: str | None = Field(default=None, description="Quote from the source document")


class VerificationReport(BaseModel):
    """Result of the verification pass."""

    issues: list[VerificationIssue] = Field(default_factory=list)
    summary: str
    safe_to_proceed: bool = Field(
        description="False if any critical issue should stop the workflow for human review"
    )


VERIFY_SYSTEM = """You are the reviewing broker's second set of eyes. You are given \
a transaction record extracted from a new client's paperwork, plus the source \
documents. Audit the extraction:

- Flag any value that does not appear in, or contradicts, the source documents \
(hallucination or transcription error).
- Flag missing values that ARE present in the documents (missed extraction).
- Flag compliance triggers: missing signatures/dates mentioned as blank, \
pre-1978 build year without lead paint acknowledgement, missing deed reference.
- Do not nitpick formatting. Severity: critical = wrong money/date/party/legal \
data; warning = missing extractable data; info = observations.
Report every issue you find, including ones you are uncertain about — a human \
reviews this list."""


async def verify_transaction_record(
    record: TransactionRecord,
    documents: list[PaperworkDocument],
) -> VerificationReport:
    """Cross-check the extracted record against sources (REVIEW tier)."""
    engine = get_claude_engine()
    prompt = (
        "Extracted transaction record (JSON):\n\n"
        + record.model_dump_json(indent=2, exclude_none=True)
        + "\n\nSource documents:\n\n"
        + _documents_block(documents)
    )
    report = await engine.generate_structured(
        prompt,
        VerificationReport,
        task=LLMTask.VERIFY,
        system_prompt=VERIFY_SYSTEM,
    )
    logger.info(
        "intake_record_verified",
        issues=len(report.issues),
        safe_to_proceed=report.safe_to_proceed,
    )
    return report
