"""Generate docs/field-utilization.md — field reuse across all fill targets.

Cross-reference: which destinations consume each canonical record field.

Destinations = every piece of paperwork / online form the workflow fills:
  ROOM  DocuSign room field data (auto-syncs into Rooms)
  ERTS  Exclusive Right to Sell form fill
  BRF   Brokerage Relationship Form (MREC #3) fill
  EBRA  Exclusive Buyer Representation Agreement fill (buyer side)
  MLS   MLS feeder -> Spark draft payload
  MID   Master Information Document (internal)
  MIS   Master Information Sheet PDF (agency)
  TW    Transaction Worksheet PDF (under contract)
Plus REQ49 marks fields in the 49 MLS-required set.
"""

import inspect
import pathlib
import re
from collections import defaultdict

from realtorai.documents import master_info, mis_filler, tw_filler
from realtorai.integrations.docusign.field_mapper import (
    SCALAR_MAP,
)
from realtorai.integrations.docusign.mock import FORM_FIELD_MAP
from realtorai.integrations.spark import record_bridge
from realtorai.schemas import mls_required
from realtorai.schemas.transaction import TransactionRecord

ATTR_RE = re.compile(r"\brecord\.([a-z_0-9]+)")
VALID = set(TransactionRecord.model_fields)


def scan_source(*objs) -> set[str]:
    attrs: set[str] = set()
    for obj in objs:
        src = inspect.getsource(obj)
        attrs |= {a for a in ATTR_RE.findall(src) if a in VALID}
    return attrs


usage: dict[str, list[str]] = defaultdict(list)

# 1. Room field data: SCALAR_MAP keys + parties
docusign_to_canonical = {v: k for k, v in SCALAR_MAP.items()}
for attr in SCALAR_MAP:
    usage[attr].append("ROOM")
usage["sellers[] (name/phone/email/addr)"].append("ROOM")
usage["buyers[] (name/phone/email/addr)"].append("ROOM")

# 2-4. Form fills from room field data (map DocuSign field names back)
FORM_TAGS = {
    "form-erts": "ERTS",
    "form-ps": "P&S",
    "form-spd": "SPD",
    "form-lead": "LEAD",
    "form-ebra": "EBRA",
    "form-multi-addendum": "ADDM",
    "form-brf": "BRF",
    "form-rebg": "REBG",
}

party_prefixes = ("seller1", "seller2", "buyer1", "buyer2")
for form_id, fields in FORM_FIELD_MAP.items():
    tag = FORM_TAGS[form_id]
    for ds_field in fields:
        if ds_field in docusign_to_canonical:
            usage[docusign_to_canonical[ds_field]].append(tag)
        elif ds_field.startswith(party_prefixes):
            side = "sellers" if ds_field.startswith("seller") else "buyers"
            usage[f"{side}[] (name/phone/email/addr)"].append(tag)
        else:
            usage[f"(room-only: {ds_field})"].append(tag)

# 5. MLS feeder / Spark payload
for attr in sorted(scan_source(record_bridge.record_to_feeder_updates)):
    usage[attr].append("MLS")

# 6. Master Information Document (whole module renders from record)
for attr in sorted(scan_source(master_info)):
    usage[attr].append("MID")

# 7. MIS PDF
for attr in sorted(scan_source(mis_filler.mis_field_values)):
    usage[attr].append("MIS")

# 8. TW PDF
for attr in sorted(
    scan_source(tw_filler.tw_field_values, tw_filler._address_line)
):
    usage[attr].append("TW")

# Party usage in MID/MIS/TW (they render sellers/buyers too)
for mod, tag in ((master_info, "MID"), (mis_filler, "MIS"), (tw_filler, "TW")):
    src = inspect.getsource(mod)
    if "sellers" in src:
        usage["sellers[] (name/phone/email/addr)"].append(tag)
    if "buyers" in src:
        usage["buyers[] (name/phone/email/addr)"].append(tag)
if "sellers" in inspect.getsource(record_bridge):
    usage["sellers[] (name/phone/email/addr)"].append("MLS")

# 49-required flags
req_attrs: set[str] = set()
req_src = inspect.getsource(mls_required)
for attr in VALID:
    if re.search(rf"\b{attr}\b", req_src):
        req_attrs.add(attr)

rows = []
for attr, dests in usage.items():
    dests = sorted(set(dests))
    rows.append((len(dests), attr, dests, attr in req_attrs))
rows.sort(key=lambda r: (-r[0], r[1]))

out = pathlib.Path(__file__).resolve().parent.parent / "docs" / "field-utilization.md"
lines = [
    "# Field utilization across the workflow's paperwork and online forms",
    "",
    "Every destination one captured fact flows into. Counts = separate",
    "manual entries the deterministic fill replaces.",
    "",
    "| Key | Destination |",
    "|---|---|",
    "| ROOM | DocuSign room field data (auto-syncs into Rooms) |",
    "| ERTS | Exclusive Right to Sell (listing agreement) |",
    "| BRF | Brokerage Relationship Form (MREC #3) |",
    "| REBG | Real Estate Brokerage Guide/disclosure |",
    "| EBRA | Exclusive Buyer Representation Agreement |",
    "| P&S | Purchase & Sale Agreement (under contract) |",
    "| SPD | Seller Property Disclosure |",
    "| LEAD | Lead Paint Disclosure (pre-1978) |",
    "| ADDM | Multi-offer addendum |",
    "| MLS | MLS feeder -> Spark draft payload |",
    "| MID | Master Information Document (internal) |",
    "| MIS | Master Information Sheet PDF (agency) |",
    "| TW | Transaction Worksheet PDF (under contract) |",
    "",
    "| Uses | Field | MLS-required | Destinations |",
    "|---:|---|:---:|---|",
]
total_entries = 0
for count, attr, dests, req in rows:
    total_entries += count
    lines.append(
        f"| {count} | `{attr}` | {'yes' if req else ''} | {', '.join(dests)} |"
    )
lines += [
    "",
    f"**Canonical fields tracked: {len(rows)}** · "
    f"**total field-entries across destinations: {total_entries}** · "
    f"**MLS-required fields reused beyond the MLS: "
    f"{sum(1 for c, a, d, r in rows if r and c > 1)}/49**",
]
out.write_text("\n".join(lines))
print(f"wrote {out} ({len(rows)} fields, {total_entries} entries)")
