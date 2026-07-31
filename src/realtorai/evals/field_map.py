"""Which destinations consume each canonical `TransactionRecord` field.

One extraction pass populates every downstream form, so the question worth
asking continuously is the reverse one: does each captured field actually
*reach* somewhere? A field with no destination is data the pipeline extracted
and then stranded — the failure mode that put personal property, unit count,
and basement moisture into the free-text `comments` blob where no filler could
read them.

This module is the single source of truth for that mapping. `scripts/
field_utilization.py` renders it into docs/field-utilization.md; `evals/
schema_coverage.py` enforces it. Previously the logic lived at module scope in
the script, which meant importing it wrote a file as a side effect and nothing
else could reuse it.

Derivation is by source introspection (`inspect.getsource` + a `record.<field>`
regex), which needs .py files on disk — fine in a checkout or an editable
install, would break from a zipped wheel.
"""

import inspect
import re
from collections import defaultdict

from realtorai.documents import master_info, mis_filler, tw_filler
from realtorai.integrations.docusign.field_mapper import SCALAR_MAP
from realtorai.integrations.docusign.mock import FORM_FIELD_MAP
from realtorai.integrations.spark import record_bridge
from realtorai.schemas import mls_required
from realtorai.schemas.transaction import TransactionRecord

#: Destination tag -> human label. Order is the order they appear in the doc.
DESTINATION_LABELS: dict[str, str] = {
    "ROOM": "DocuSign room field data (auto-syncs into Rooms)",
    "ERTS": "Exclusive Right to Sell (listing agreement)",
    "BRF": "Brokerage Relationship Form (MREC #3)",
    "REBG": "Real Estate Brokerage Guide/disclosure",
    "EBRA": "Exclusive Buyer Representation Agreement",
    "P&S": "Purchase & Sale Agreement (under contract)",
    "SPD": "Seller Property Disclosure",
    "LEAD": "Lead Paint Disclosure (pre-1978)",
    "ADDM": "Multi-offer addendum",
    "MLS": "MLS feeder -> Spark draft payload",
    "MID": "Master Information Document (internal)",
    "MIS": "Master Information Sheet PDF (agency)",
    "TW": "Transaction Worksheet PDF (under contract)",
    "DEAD": "Dashboard deadline board (dated pending items)",
}

#: DocuSign form id -> destination tag.
FORM_TAGS: dict[str, str] = {
    "form-erts": "ERTS",
    "form-ps": "P&S",
    "form-spd": "SPD",
    "form-lead": "LEAD",
    "form-ebra": "EBRA",
    "form-multi-addendum": "ADDM",
    "form-brf": "BRF",
    "form-rebg": "REBG",
}

#: Pseudo-fields for the party blocks, which map many-to-one onto the record.
SELLERS = "sellers[] (name/phone/email/addr)"
BUYERS = "buyers[] (name/phone/email/addr)"

_ATTR_RE = re.compile(r"\brecord\.([a-z_0-9]+)")
_PARTY_PREFIXES = ("seller1", "seller2", "buyer1", "buyer2")


def record_fields() -> set[str]:
    """Every canonical field name on the record."""
    return set(TransactionRecord.model_fields)


def _scan(*objs: object) -> set[str]:
    """Record fields referenced as `record.<field>` in the given sources."""
    valid = record_fields()
    found: set[str] = set()
    for obj in objs:
        found |= {a for a in _ATTR_RE.findall(inspect.getsource(obj)) if a in valid}  # type: ignore[arg-type]
    return found


def deadline_fields() -> set[str]:
    """Fields that drive the dashboard deadline board.

    Imported from `_DEADLINES` rather than re-derived, so adding a deadline
    can't silently leave its field looking stranded. A deadline genuinely is a
    destination — `emd_due_date` reaches the operator through the dashboard
    even though it is not printed on any form.
    """
    from realtorai.workflows.under_contract import _DEADLINES

    return {field for field, _description, _waiting_on in _DEADLINES}


def mls_required_fields() -> set[str]:
    """The record fields named in the 49-field MLS-required set."""
    src = inspect.getsource(mls_required)
    return {attr for attr in record_fields() if re.search(rf"\b{attr}\b", src)}


def destination_map() -> dict[str, list[str]]:
    """Field name -> sorted destination tags it flows into.

    Keys are canonical record fields plus two party pseudo-fields and any
    `(room-only: …)` DocuSign fields that have no canonical counterpart.
    """
    usage: dict[str, list[str]] = defaultdict(list)

    # Room field data: everything the DocuSign scalar map carries, plus parties.
    docusign_to_canonical = {v: k for k, v in SCALAR_MAP.items()}
    for attr in SCALAR_MAP:
        usage[attr].append("ROOM")
    usage[SELLERS].append("ROOM")
    usage[BUYERS].append("ROOM")

    # Form fills read from room field data, so map DocuSign names back.
    for form_id, fields in FORM_FIELD_MAP.items():
        tag = FORM_TAGS.get(form_id)
        if tag is None:  # a new form arrived without a tag — surface it, don't crash
            tag = f"?{form_id}"
        for ds_field in fields:
            if ds_field in docusign_to_canonical:
                usage[docusign_to_canonical[ds_field]].append(tag)
            elif ds_field.startswith(_PARTY_PREFIXES):
                usage[SELLERS if ds_field.startswith("seller") else BUYERS].append(tag)
            else:
                usage[f"(room-only: {ds_field})"].append(tag)

    for attr in _scan(record_bridge.record_to_feeder_updates):
        usage[attr].append("MLS")
    for attr in _scan(master_info):
        usage[attr].append("MID")
    for attr in _scan(mis_filler.mis_field_values):
        usage[attr].append("MIS")
    for attr in _scan(tw_filler.tw_field_values, tw_filler._address_line):
        usage[attr].append("TW")
    for attr in deadline_fields():
        usage[attr].append("DEAD")

    # Party blocks render in the document targets too.
    for mod, tag in ((master_info, "MID"), (mis_filler, "MIS"), (tw_filler, "TW")):
        src = inspect.getsource(mod)
        if "sellers" in src:
            usage[SELLERS].append(tag)
        if "buyers" in src:
            usage[BUYERS].append(tag)
    if "sellers" in inspect.getsource(record_bridge):
        usage[SELLERS].append("MLS")

    return {field: sorted(set(tags)) for field, tags in usage.items()}
