"""Eval: intake classifier vs. a fixture modeled on real inbox traffic.

The intake classifier triages the team inbox: is this email a realtor
handing off a NEW client (start a workflow proposal), or ongoing-deal
chatter / office noise (ignore)? This fixture mirrors the message types
observed in the real monitored inbox — signed-envelope notifications,
prose handoffs, offers/counters, earnest-money notices, staff broadcasts —
with all names and addresses fictionalized.

The prose-handoff case (#2) is here because it caught a real recall gap:
the original classifier prompt only recognized paperwork attachments, and
a live agent handoff ("rooms already started, here are the two listings")
classified as `other`. The taxonomy was widened and this eval locks the
fix in.

Usage:
    python scripts/eval_intake_classifier.py   # needs ANTHROPIC_API_KEY

Exit code 0 when every case matches, 1 otherwise.
"""

import asyncio
import sys

from realtorai.inference.claude_engine import get_claude_engine
from realtorai.workflows.intake import classify_intake_email

# (subject, body, attachment names, expected intent)
CASES: list[tuple[str, str, list[str], str]] = [
    (
        "Completed: Exclusive Right to Sell Listing Agreement (Combo)",
        "All parties have completed Exclusive Right to Sell Listing Agreement "
        "(Combo). This message was sent to you by Agent One who is using the "
        "Docusign Electronic Signature Service.",
        ["Exclusive_Right_to_Sell.pdf", "Lead_Paint_Disclosure.pdf", "Property_Disclosure.pdf"],
        "new_listing_client",
    ),
    (
        "Re: new listings",
        "Hi - Thank you for the help! I have already started rooms and plugged "
        "in some documents in there. The first listing is 14 Ledgeview Drive, "
        "Holden. That's for Pat and Sam Larson. The second listing is 3 Quarry "
        "Road, Orland. That's for Robin and Lee Carver. I appreciate anything "
        "you can do on those. Thanks again! — Agent Two",
        [],
        "new_listing_client",
    ),
    (
        "Completed: Exclusive Buyer Representation Agreement",
        "All parties have completed Exclusive Buyer Representation Agreement "
        "for Jordan Field. Signed copy attached.",
        ["Buyer_Representation_Agreement.pdf"],
        "new_buyer_client",
    ),
    (
        "Completed: Purchase and Sale Agreement - 14 Ledgeview",
        "All parties have completed Purchase and Sale Agreement for 14 "
        "Ledgeview Drive, Holden. This message was sent to you by Agent One "
        "using the Docusign Electronic Signature Service.",
        ["Purchase_and_Sale_Agreement.pdf"],
        "under_contract",
    ),
    (
        "we're under contract!",
        "Great news — the sellers signed last night, we are under contract "
        "on 3 Quarry Road at $310,000. Closing September 15. I'll drop the "
        "EMD off tomorrow morning.",
        [],
        "under_contract",
    ),
    (
        "Seller Counter Offer",
        "Hi both, attached is the seller counter. I'd recommend that you sign "
        "today so we have an extra day for inspections. $285,000 purchase price, "
        "closing date as presented.",
        ["Counter_Offer.pdf"],
        "other",
    ),
    (
        "Offer - 5 Shore Drive",
        "Hi, please find our clients' offer attached. We'd love to put "
        "something together. The buyers are flexible on closing date.",
        ["Offer_Package.pdf"],
        "other",
    ),
    (
        "5 Shore Dr EMD",
        "Hello, the earnest money deposit for 5 Shore Drive was just dropped "
        "off, it's in your mailbox! Thank you, Processing Specialist",
        [],
        "other",
    ),
    (
        "Property Disclosure Draft",
        "Hi, attached is the property disclosure for your review. Please let "
        "me know if you have any edits or additions. Once it is correct, I "
        "will send it out for both of your signatures.",
        ["Property_Disclosure_DRAFT.pdf"],
        "other",
    ),
    (
        "New Listing - 10 Mill St., Lisbon Falls",
        "Hey all, check out this new listing in Lisbon from Agent Three! "
        "MLS#: 1670000 https://example.com/listing/10-mill-st",
        [],
        "other",
    ),
    (
        "MLS Weekly Communication",
        "You don't want to miss this: the MLS app is making updates to help "
        "you find information faster and work more efficiently on the go.",
        [],
        "other",
    ),
    (
        "Office Parking Reminder",
        "Good morning everyone, a quick reminder that on event days the lot "
        "will start to fill in the mid-afternoon.",
        [],
        "other",
    ),
]


async def main() -> int:
    if not get_claude_engine().available:
        print("ANTHROPIC_API_KEY not configured — this eval calls the live classifier.")
        return 1

    failures = 0
    print(f"{'result':7s} {'expected':19s} {'got':19s} {'conf':6s} subject")
    for subject, body, attachments, expected in CASES:
        c = await classify_intake_email(subject, body, attachments)
        ok = c.intent == expected
        failures += 0 if ok else 1
        mark = "PASS" if ok else "FAIL"
        print(f"{mark:7s} {expected:19s} {c.intent:19s} {c.confidence:6s} {subject[:40]}")

    print(f"\n{len(CASES) - failures}/{len(CASES)} correct")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
