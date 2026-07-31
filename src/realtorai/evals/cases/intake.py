"""Intake-classifier cases: is this email a new-client handoff, or noise?

Modelled on the real monitored inbox — signed-envelope notifications, prose
handoffs, offers and counters, earnest-money notices, staff broadcasts — with
every name and address fictionalised.

`prose-handoff-two-listings` is the one that earns its keep: it caught a real
recall gap where the classifier only recognised paperwork attachments, so a
live agent handoff ("rooms already started, here are the two listings") came
back `other`. The taxonomy was widened and this case locks the fix in.

Two cases carry `xfail_backends=("heuristic",)`. The offline keyword classifier
is genuinely fooled by them — a marketing blast containing the literal words
"new listing", and a draft P&S circulated for review containing "purchase and
sale agreement". Those are the cases where offline and live *should* diverge,
so they are recorded as expected misses rather than quietly lowering a
threshold until the suite goes green.
"""

from realtorai.evals.harness import Case

#: The full label space. Passed to `score` so a label the model never predicts
#: still shows up with recall 0 instead of vanishing from the macro average.
INTAKE_LABELS: tuple[str, ...] = (
    "new_listing_client",
    "new_buyer_client",
    "under_contract",
    "closing",
    "other",
)


def _case(
    case_id: str,
    subject: str,
    body: str,
    attachments: list[str],
    expected: str,
    *,
    tags: tuple[str, ...] = (),
    xfail_backends: tuple[str, ...] = (),
    note: str = "",
) -> Case:
    return Case(
        id=case_id,
        inputs={"subject": subject, "body": body, "attachment_names": attachments},
        expected=expected,
        tags=tags,
        xfail_backends=xfail_backends,
        note=note,
    )


INTAKE_CASES: tuple[Case, ...] = (
    # ---- new_listing_client -------------------------------------------------
    _case(
        "erts-envelope",
        "Completed: Exclusive Right to Sell Listing Agreement (Combo)",
        "All parties have completed Exclusive Right to Sell Listing Agreement "
        "(Combo). This message was sent to you by Agent One who is using the "
        "Docusign Electronic Signature Service.",
        ["Exclusive_Right_to_Sell.pdf", "Lead_Paint_Disclosure.pdf", "Property_Disclosure.pdf"],
        "new_listing_client",
        tags=("envelope",),
    ),
    _case(
        "prose-handoff-two-listings",
        "Re: new listings",
        "Hi - Thank you for the help! I have already started rooms and plugged "
        "in some documents in there. The first listing is 14 Ledgeview Drive, "
        "Holden. That's for Pat and Sam Larson. The second listing is 3 Quarry "
        "Road, Orland. That's for Robin and Lee Carver. I appreciate anything "
        "you can do on those. Thanks again! — Agent Two",
        [],
        "new_listing_client",
        tags=("prose", "regression"),
        note="Caught a real recall gap: no attachments, rooms already exist.",
    ),
    _case(
        "coming-soon-handoff",
        "new one coming up",
        "Just got the listing agreement back from the Prescotts for 8 Alder "
        "Lane in Hampden. They want to go coming-soon next week so we have "
        "time for photos. Can you get the room going? I'll send the signed "
        "copy over this afternoon.",
        [],
        "new_listing_client",
        tags=("prose",),
    ),
    # ---- new_buyer_client ---------------------------------------------------
    _case(
        "ebra-envelope",
        "Completed: Exclusive Buyer Representation Agreement",
        "All parties have completed Exclusive Buyer Representation Agreement "
        "for Jordan Field. Signed copy attached.",
        ["Buyer_Representation_Agreement.pdf"],
        "new_buyer_client",
        tags=("envelope",),
    ),
    _case(
        "buyer-prose-handoff",
        "new buyer client",
        "Signed up Dana Whitcomb yesterday — she's pre-approved to $340k and "
        "looking in the Orono / Old Town area. Buyer agreement is signed, I'll "
        "forward the envelope. Can you set her up on the buyer side?",
        [],
        "new_buyer_client",
        tags=("prose",),
    ),
    _case(
        "buyer-agreement-signed-envelope",
        "Completed with Docusign: Buyer Agency Agreement - Okafor",
        "All parties have completed Buyer Agency Agreement. This message was "
        "sent to you by Agent One who is using the Docusign Electronic "
        "Signature Service.",
        ["Buyer_Agency_Agreement_Okafor.pdf"],
        "new_buyer_client",
        tags=("envelope",),
    ),
    # ---- under_contract -----------------------------------------------------
    _case(
        "ps-envelope",
        "Completed: Purchase and Sale Agreement - 14 Ledgeview",
        "All parties have completed Purchase and Sale Agreement for 14 "
        "Ledgeview Drive, Holden. This message was sent to you by Agent One "
        "using the Docusign Electronic Signature Service.",
        ["Purchase_and_Sale_Agreement.pdf"],
        "under_contract",
        tags=("envelope",),
    ),
    _case(
        "uc-prose",
        "we're under contract!",
        "Great news — the sellers signed last night, we are under contract "
        "on 3 Quarry Road at $310,000. Closing September 15. I'll drop the "
        "EMD off tomorrow morning.",
        [],
        "under_contract",
        tags=("prose",),
    ),
    _case(
        "accepted-offer-announcement",
        "8 Alder accepted",
        "They accepted our offer on 8 Alder Lane this morning, fully executed "
        "contract attached. Inspection contingency runs 10 days from today.",
        ["Fully_Executed_Contract.pdf"],
        "under_contract",
        tags=("prose", "envelope"),
    ),
    # ---- closing ------------------------------------------------------------
    _case(
        "settlement-statement",
        "Settlement Statement - 14 Ledgeview Drive",
        "Good afternoon, attached please find the settlement statement for "
        "14 Ledgeview Drive for your review prior to Friday's closing. Let "
        "us know if any changes are needed. — Coastal Title Co.",
        ["Settlement_Statement.pdf"],
        "closing",
        tags=("envelope",),
    ),
    _case(
        "clear-to-close",
        "clear to close!",
        "Lender just confirmed we are clear to close on 3 Quarry Road. "
        "Closing is scheduled for the 15th at 10am at the title company.",
        [],
        "closing",
        tags=("prose",),
    ),
    _case(
        "title-company-scheduling",
        "Scheduling - 8 Alder Lane",
        "Hello, we have everything we need from the lender and are ready to "
        "sit down with your seller. Would Thursday the 22nd at 1pm work at "
        "our Bangor office? Please confirm and we'll send the figures over "
        "the day before. — Penobscot Abstract",
        [],
        "closing",
        tags=("prose", "generalisation"),
        xfail_backends=("heuristic",),
        note="Contains no closing keyword at all — describes a signing "
        "appointment in plain language. Unreachable for a keyword classifier "
        "without false positives; this is the case that shows why the live "
        "model is worth paying for.",
    ),
    # ---- other --------------------------------------------------------------
    _case(
        "seller-counter",
        "Seller Counter Offer",
        "Hi both, attached is the seller counter. I'd recommend that you sign "
        "today so we have an extra day for inspections. $285,000 purchase price, "
        "closing date as presented.",
        ["Counter_Offer.pdf"],
        "other",
    ),
    _case(
        "buyer-offer",
        "Offer - 5 Shore Drive",
        "Hi, please find our clients' offer attached. We'd love to put "
        "something together. The buyers are flexible on closing date.",
        ["Offer_Package.pdf"],
        "other",
    ),
    _case(
        "emd-dropoff",
        "5 Shore Dr EMD",
        "Hello, the earnest money deposit for 5 Shore Drive was just dropped "
        "off, it's in your mailbox! Thank you, Processing Specialist",
        [],
        "other",
    ),
    _case(
        "spd-draft",
        "Property Disclosure Draft",
        "Hi, attached is the property disclosure for your review. Please let "
        "me know if you have any edits or additions. Once it is correct, I "
        "will send it out for both of your signatures.",
        ["Property_Disclosure_DRAFT.pdf"],
        "other",
    ),
    _case(
        "ps-draft-for-review",
        "draft P&S for your review",
        "Before I send this out for signature, can you look over the purchase "
        "and sale agreement I drafted for the Alder Lane offer? Nothing is "
        "signed yet — I want a second set of eyes on the contingency dates.",
        ["Purchase_and_Sale_DRAFT.pdf"],
        "other",
        tags=("hard-negative",),
        xfail_backends=("heuristic",),
        note="Keyword classifier sees 'purchase and sale agreement' -> under_contract.",
    ),
    _case(
        "mls-broadcast-new-listing",
        "New Listing - 10 Mill St., Lisbon Falls",
        "Hey all, check out this new listing in Lisbon from Agent Three! "
        "MLS#: 1670000 https://example.com/listing/10-mill-st",
        [],
        "other",
        tags=("hard-negative",),
        xfail_backends=("heuristic",),
        note="Keyword classifier sees the literal 'new listing' -> new_listing_client.",
    ),
    _case(
        "mls-newsletter",
        "MLS Weekly Communication",
        "You don't want to miss this: the MLS app is making updates to help "
        "you find information faster and work more efficiently on the go.",
        [],
        "other",
    ),
    _case(
        "office-parking",
        "Office Parking Reminder",
        "Good morning everyone, a quick reminder that on event days the lot "
        "will start to fill in the mid-afternoon.",
        [],
        "other",
    ),
)
