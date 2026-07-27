"""Local simulator for the DocuSign Rooms API (v2).

Our brokerage account does not have Rooms API access enabled, so this module
implements the subset of the Rooms REST surface that `rooms.py` calls against
a JSON-persisted local state. `MockDocuSignClient` exposes the exact same
interface as the real `DocuSignClient`, so every function in `rooms.py` works
unchanged — flipping `DOCUSIGN_BACKEND=live` in `.env` is the only change
needed once broker API approval lands.

Behavioral notes mirrored from the real API:
  - Rooms auto-fill forms from room *field data*: when a form is added to a
    room, the fields it consumes are snapshotted from the room's current
    field data (`prefilledFields` on the form instance). This is how
    "fill out the template from the master information document" works in
    real Transaction Rooms — write the field data, then attach the form.
  - PUT /rooms/{id}/field_data merges the provided fields.
  - Reference data (roles, offices, form libraries, task list templates) is
    seeded with the Maine forms and the agency team task lists.

State lives in `data/mock_docusign/state.json`; uploaded document bytes in
`data/mock_docusign/files/<room_id>/`.
"""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from realtorai.config.settings import get_settings

logger = structlog.get_logger()


class MockAPIError(Exception):
    """Simulates an HTTP error from the Rooms API."""

    def __init__(self, status_code: int, message: str):
        super().__init__(f"{status_code}: {message}")
        self.status_code = status_code


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat() + "Z"


# =============================================================================
# Seeded reference data
# =============================================================================

ROLES: list[dict[str, Any]] = [
    {"roleId": 1, "name": "Default Admin", "isDefaultForAdmin": True},
    {"roleId": 2, "name": "Agent", "isDefaultForAgent": True},
    {"roleId": 3, "name": "Transaction Coordinator"},
]

OFFICES: list[dict[str, Any]] = [
    {
        "officeId": 1,
        "name": "The Agency — Bangor",
        "address1": "100 Main Street",
        "city": "Bangor",
        "stateId": "US-ME",
        "postalCode": "04401",
    },
]

TRANSACTION_SIDES: list[dict[str, Any]] = [
    {"transactionSideId": "buy", "name": "Buy Side"},
    {"transactionSideId": "sell", "name": "List Side"},
    {"transactionSideId": "listbuy", "name": "List & Buy Side"},
    {"transactionSideId": "refi", "name": "Refinance"},
]

PROPERTY_TYPES: list[dict[str, Any]] = [
    {"propertyTypeId": "resd", "name": "Residential Detached"},
    {"propertyTypeId": "resa", "name": "Residential Attached"},
    {"propertyTypeId": "multi", "name": "Multi-Family"},
    {"propertyTypeId": "land", "name": "Land"},
    {"propertyTypeId": "comm", "name": "Commercial"},
]

FORM_LIBRARIES: list[dict[str, Any]] = [
    {"formsLibraryId": "lib-maine-ar", "name": "Maine Association of REALTORS®", "formCount": 6},
    {"formsLibraryId": "lib-mrec", "name": "Maine Real Estate Commission", "formCount": 2},
]

# libraryFormId -> form summary. Names match the actual Maine form set the
# agency team uses; IDs are deterministic for readability (real API uses GUIDs).
FORMS: dict[str, dict[str, Any]] = {
    "form-erts": {
        "libraryFormId": "form-erts",
        "formsLibraryId": "lib-maine-ar",
        "name": "Exclusive Right to Sell Listing Agreement",
        "lastUpdatedDate": "2026-01-01T00:00:00Z",
    },
    "form-ps": {
        "libraryFormId": "form-ps",
        "formsLibraryId": "lib-maine-ar",
        "name": "Purchase and Sale Agreement — Residential",
        "lastUpdatedDate": "2026-01-01T00:00:00Z",
    },
    "form-spd": {
        "libraryFormId": "form-spd",
        "formsLibraryId": "lib-maine-ar",
        "name": "Seller's Property Disclosure",
        "lastUpdatedDate": "2026-01-01T00:00:00Z",
    },
    "form-lead": {
        "libraryFormId": "form-lead",
        "formsLibraryId": "lib-maine-ar",
        "name": "Lead Based Paint Hazard Disclosure",
        "lastUpdatedDate": "2026-01-01T00:00:00Z",
    },
    "form-ebra": {
        "libraryFormId": "form-ebra",
        "formsLibraryId": "lib-maine-ar",
        "name": "Exclusive Buyer Representation Agreement",
        "lastUpdatedDate": "2026-01-01T00:00:00Z",
    },
    "form-multi-addendum": {
        "libraryFormId": "form-multi-addendum",
        "formsLibraryId": "lib-maine-ar",
        "name": "Multi-Unit Addendum (Leases, Deposits, Income)",
        "lastUpdatedDate": "2026-01-01T00:00:00Z",
    },
    "form-brf": {
        "libraryFormId": "form-brf",
        "formsLibraryId": "lib-mrec",
        "name": "Brokerage Relationship Form (MREC Form #3)",
        "lastUpdatedDate": "2026-01-01T00:00:00Z",
    },
    "form-rebg": {
        "libraryFormId": "form-rebg",
        "formsLibraryId": "lib-mrec",
        "name": "Real Estate Brokerage Relationships Guide",
        "lastUpdatedDate": "2026-01-01T00:00:00Z",
    },
}

# Which room field-data keys each form auto-fills from. Mirrors real Rooms
# behavior: forms pull from room details at the moment they're added.
FORM_FIELD_MAP: dict[str, list[str]] = {
    "form-erts": [
        "address1", "city", "state", "postalCode", "county",
        "seller1", "seller2", "listingAgent1", "listingAgent2",
        "contractAmount", "listSideCommission", "contractDate",
        "legalDescription", "taxId",
    ],
    "form-ps": [
        "address1", "city", "state", "postalCode",
        "seller1", "buyer1", "listingAgent1", "buyerAgent1",
        "contractAmount", "earnestMoneyAmount", "entityHoldingEarnestMoney",
        "contractDate", "expectedClosingDate", "inspectionContingencyDate",
        "loanContingencyDate", "financingType",
    ],
    "form-spd": [
        "address1", "city", "state", "postalCode", "seller1", "seller2", "yearBuilt",
    ],
    "form-lead": [
        "address1", "city", "state", "postalCode", "seller1", "seller2", "yearBuilt",
    ],
    "form-ebra": [
        "buyer1", "buyer2", "buyerAgent1", "buyerAgent2", "buyerSideCommission",
    ],
    "form-multi-addendum": [
        "address1", "city", "state", "postalCode", "seller1", "buyer1",
    ],
    "form-brf": [
        "seller1", "seller2", "buyer1", "buyer2",
        "listingAgent1", "buyerAgent1",
    ],
    "form-rebg": [],
}

# Task list templates mirror the agency team checklists (docs/policies_and_
# procedures.md + the team's step-by-step checklist docs, imported 2026-07-26).
TASK_LIST_TEMPLATES: list[dict[str, Any]] = [
    {
        "taskListTemplateId": 1,
        "name": "New Listing",
        "taskCount": 21,
        "tasks": [
            "Bring the six listing forms (zipForms, Combo versions)",
            "Pull deed from county Registry of Deeds (confirm most recent transfer)",
            "Pull tax card (town assessing / Realist)",
            "Pull tax / survey map (parcel map & lot)",
            "Pull FEMA flood map (FIRMette — note zone + panel #)",
            "Prepare comps / CMA",
            "Discuss home warranty + franchise seller-security program",
            "Relationship Form — initialed",
            "Listing Agreement (Exclusive Right to Sell, Combo) — initialed & signed",
            "Office Exclusive — initialed & signed (when used)",
            "Property Disclosure — initialed & signed (anchor facts pre-filled from MIS)",
            "Lead Paint Addendum — initialed & signed (required pre-1978)",
            "Upload signed packet to the New Listing task",
            "Gather property data: heat/fuel, septic design, improvements, room measurements",
            "Photos entered in DocuSign Room",
            "Listing input submitted in FlexMLS; remarks with SEO terms",
            "Supra / BrokerBay showing information completed",
            "Submit DocuSign Room task list to agency staff",
            "Lock box on property with key; MLS link + flyer emailed to seller",
            "MLS sheet / directions / sign rider turned in to staff",
            "Marketing: flyers, open house, social",
        ],
    },
    {
        "taskListTemplateId": 2,
        "name": "Buyer Agreement",
        "taskCount": 12,
        "tasks": [
            "Present Residential Property Transaction Booklet",
            "Present Offers & Counteroffers Guidelines",
            "Relationships Form (MREC Form #3) — explained & initialed",
            "Exclusive Buyer Representation Agreement (Combo) — explained & signed",
            "Appointed Agent + Disclosed Dual Agency sections signed",
            "Lead Paint / Arsenic in Treated Wood / Radon info provided",
            "Buyer onboarding sheet completed",
            "Proof of ability to purchase received (verify with lender)",
            "Upload signed docs to the Buyer Agreement task",
            "Add the lead agent to the Room",
            "Connect buyer to lender(s)",
            "FlexMLS auto-feed / portal set up; email campaign; check-in cadence",
        ],
    },
    {
        "taskListTemplateId": 3,
        "name": "Under Contract — Listing Side",
        "taskCount": 17,
        "tasks": [
            "Review all docs for errors (initials, signatures, effective date, deed ref) "
            "— CC agent",
            "Ask agent: Pending or Active Under Contract; set MLS status",
            "Send under-contract email to seller (Template Seller #1)",
            "Complete DTR Under-Contract task: transaction worksheet + docs + change-request form",
            "Track EMD proof (escalate if missed) and proof of loan application",
            "Confirm deed prep preference — recommend closing firm (Template Seller #3)",
            "Verify Maine residency (2.5% non-resident withholding; waiver is proactive)",
            "Seller questionnaire + authorization-to-release (final water/sewer reading)",
            "Send inspection expectations email (Template Seller #2)",
            "Manage due-diligence negotiations; confirm concessions on closing statement",
            "Closing statement ~3 days prior; team review; copy to seller",
            "Schedule closing; determine in-person / remote / POA",
            "Send closing procedure email (Template Seller #4)",
            "Send utilities & fuel proration email (Template Seller #5)",
            "Send condition / final-walkthrough email (Template Seller #6)",
            "Schedule final walkthrough; arrange lock box pickup",
            "Closing gift for seller; update the Room",
        ],
    },
    {
        "taskListTemplateId": 4,
        "name": "Under Contract — Buyer Side",
        "taskCount": 20,
        "tasks": [
            "Review all docs for errors (initials, signatures, effective date, deed ref)",
            "First email to buyer + lender: docs + deadlines in bold (Template Buyer #1)",
            "Enter the deal in Dash (before completing the DTR task)",
            "Add DTR Under-Contract task: transaction worksheet + required docs",
            "Set up EMD task (if held at the agency)",
            "Send inspections email — 3+ building, radon, septic vendors (Template Buyer #2)",
            "Confirm EMD delivered — proof to lender, lead agent, other agent",
            "Send Title Choice email (≥2 options); advise Owner's Title Insurance (Buyer #4)",
            "Deliver proof of loan application to the listing agent",
            "Homeowners insurance reminder ~1 week in (Template Buyer #6)",
            "Home warranty waiver / brochure (Template Buyer #5)",
            "Prep comps for appraisal for lead agent",
            "Confirm appraisal receipt; ask buyer if questions",
            "Verify repairs from the ICA",
            "Confirm Closing Disclosure received; settlement statement to lead agent",
            "Schedule closing; confirm clear-to-close",
            "Send closing procedure email (Template Buyer #8)",
            "Schedule final walkthrough ≤24 hrs before closing (Template Buyer #7)",
            "Utilities reminder + moving resources (Templates Buyer #9/#10)",
            "Homestead exemption info; closing gift; post-close statement mailing",
        ],
    },
    {
        # Applied on the buyer side when the agency holds the deposit
        # (listing-side deals track the other agency's EMD proof instead).
        "taskListTemplateId": 5,
        "name": "Earnest Money Deposit",
        "taskCount": 4,
        "tasks": [
            "Record EMD receipt (cashier's check or Earnnest)",
            "Deposit per office procedure",
            "Send proof of delivery to lender, lead agent, and other agent",
            "Track release / disbursement at closing",
        ],
    },
    {
        # Mirrors the real room's Closing phase: settlement statement,
        # commission check, and the Transaction Worksheet re-filed at close.
        "taskListTemplateId": 6,
        "name": "Closing",
        "taskCount": 10,
        "tasks": [
            "Settlement statement received ~3 days prior — team review "
            "(everything negotiated + all commissions), copy to client",
            "Confirm clear-to-close; schedule closing "
            "(in-person / remote-notarized / POA)",
            "Send closing procedure email (photo ID; funds by check or wire; "
            "client calls the closing company directly)",
            "Utilities & fuel email — closing day is a seller day; fuel "
            "proration form to the closing company ~4 days prior",
            "Schedule final walkthrough ≤24 hrs before closing; condition "
            "email (broom clean, affixed fixtures stay)",
            "Update Transaction Worksheet; file to the Closing folder",
            "File signed closing statement; mail copy to the client post-close",
            "Record commission check; deliver to office",
            "Lock box pickup; update the Room",
            "Homestead exemption info (buyer); closing gift",
        ],
    },
]


# =============================================================================
# Simulator
# =============================================================================


class MockRoomsAPI:
    """In-process Rooms API simulator with JSON persistence."""

    def __init__(self, state_dir: Path | None = None):
        settings = get_settings()
        self.state_dir = state_dir or settings.mock_docusign_dir
        self.state_path = self.state_dir / "state.json"
        self.files_dir = self.state_dir / "files"
        self._state: dict[str, Any] = self._load()

    # ---- persistence -------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        if self.state_path.exists():
            try:
                with open(self.state_path) as f:
                    return json.load(f)
            except Exception as e:
                logger.error("mock_rooms_state_read_error", error=str(e))
        return {
            "next_room_id": 2001,
            "next_document_id": 1,
            "next_task_list_id": 1,
            "next_task_id": 1,
            "next_user_id": 1,
            "next_envelope_id": 1,
            "next_room_form_id": 1,
            "rooms": {},
            "documents": {},
            "task_lists": {},
        }

    def _save(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with open(self.state_path, "w") as f:
            json.dump(self._state, f, indent=2)

    def _next(self, counter: str) -> int:
        value = self._state[counter]
        self._state[counter] = value + 1
        return value

    def reset(self) -> None:
        """Wipe all simulator state (used by tests and demo scripts)."""
        self._state = {
            "next_room_id": 2001,
            "next_document_id": 1,
            "next_task_list_id": 1,
            "next_task_id": 1,
            "next_user_id": 1,
            "next_envelope_id": 1,
            "next_room_form_id": 1,
            "rooms": {},
            "documents": {},
            "task_lists": {},
        }
        self._save()

    # ---- helpers -----------------------------------------------------------

    def _room(self, room_id: int | str) -> dict[str, Any]:
        room = self._state["rooms"].get(str(room_id))
        if room is None:
            raise MockAPIError(404, f"Room {room_id} not found")
        return room

    # ---- dispatcher --------------------------------------------------------

    def handle(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        file: tuple[str, bytes] | None = None,
    ) -> dict[str, Any]:
        """Route a (method, path) pair to the matching endpoint handler."""
        params = params or {}
        json_data = json_data or {}
        route = (method.upper(), path.rstrip("/"))

        # Static routes first
        static: dict[tuple[str, str], Any] = {
            ("GET", "/rooms"): lambda: self._list_rooms(params),
            ("POST", "/rooms"): lambda: self._create_room(json_data),
            ("GET", "/form_libraries"): lambda: {"formsLibrarySummaries": FORM_LIBRARIES},
            ("GET", "/task_list_templates"): lambda: {"taskListTemplates": [
                {k: v for k, v in t.items() if k != "tasks"} for t in TASK_LIST_TEMPLATES
            ]},
            ("GET", "/room_templates"): lambda: {"roomTemplates": []},
            ("GET", "/roles"): lambda: {"roles": ROLES},
            ("GET", "/offices"): lambda: {"officeSummaries": OFFICES},
            ("GET", "/transaction_sides"): lambda: {"transactionSides": TRANSACTION_SIDES},
            ("GET", "/property_types"): lambda: {"propertyTypes": PROPERTY_TYPES},
        }
        if route in static:
            return static[route]()

        m = method.upper()
        patterns: list[tuple[str, str, Any]] = [
            ("GET", r"^/rooms/(\d+)$", lambda g: self._get_room(int(g[0]), params)),
            ("DELETE", r"^/rooms/(\d+)$", lambda g: self._delete_room(int(g[0]))),
            ("GET", r"^/rooms/(\d+)/field_data$", lambda g: self._get_field_data(int(g[0]))),
            (
                "PUT",
                r"^/rooms/(\d+)/field_data$",
                lambda g: self._put_field_data(int(g[0]), json_data),
            ),
            ("GET", r"^/rooms/(\d+)/users$", lambda g: self._get_users(int(g[0]))),
            ("POST", r"^/rooms/(\d+)/users$", lambda g: self._add_user(int(g[0]), json_data)),
            (
                "POST",
                r"^/rooms/(\d+)/users/(\d+)/revoke_access$",
                lambda g: self._set_user_access(int(g[0]), int(g[1]), revoked=True),
            ),
            (
                "POST",
                r"^/rooms/(\d+)/users/(\d+)/restore_access$",
                lambda g: self._set_user_access(int(g[0]), int(g[1]), revoked=False),
            ),
            ("GET", r"^/rooms/(\d+)/documents$", lambda g: self._get_documents(int(g[0]))),
            (
                "POST",
                r"^/rooms/(\d+)/documents/contents$",
                lambda g: self._upload_document(int(g[0]), file),
            ),
            ("GET", r"^/documents/(\d+)$", lambda g: self._get_document(int(g[0]))),
            ("DELETE", r"^/documents/(\d+)$", lambda g: self._delete_document(int(g[0]))),
            ("GET", r"^/form_libraries/([\w-]+)/forms$", lambda g: self._get_library_forms(g[0])),
            ("GET", r"^/forms/([\w-]+)/details$", lambda g: self._get_form_details(g[0])),
            ("GET", r"^/rooms/(\d+)/forms$", lambda g: {"forms": self._room(g[0])["forms"]}),
            (
                "POST",
                r"^/rooms/(\d+)/forms$",
                lambda g: self._add_form_to_room(int(g[0]), json_data),
            ),
            ("GET", r"^/rooms/(\d+)/task_lists$", lambda g: self._get_room_task_lists(int(g[0]))),
            (
                "POST",
                r"^/rooms/(\d+)/task_lists$",
                lambda g: self._add_task_list(int(g[0]), json_data),
            ),
            ("DELETE", r"^/task_lists/(\d+)$", lambda g: self._delete_task_list(int(g[0]))),
            (
                "POST",
                r"^/rooms/(\d+)/envelopes$",
                lambda g: self._create_envelope(int(g[0]), json_data),
            ),
            ("GET", r"^/rooms/(\d+)/assignable_roles$", lambda g: {"roles": ROLES}),
        ]
        for pat_method, pattern, handler in patterns:
            if m != pat_method:
                continue
            match = re.match(pattern, path.rstrip("/"))
            if match:
                return handler(match.groups())

        raise MockAPIError(404, f"Mock Rooms API: no route for {method} {path}")

    # ---- rooms -------------------------------------------------------------

    def _list_rooms(self, params: dict[str, Any]) -> dict[str, Any]:
        rooms = list(self._state["rooms"].values())
        status = params.get("roomStatus")
        if status:
            rooms = [r for r in rooms if r.get("roomStatus") == status]
        office_id = params.get("officeId")
        if office_id:
            rooms = [r for r in rooms if r.get("officeId") == int(office_id)]
        rooms.sort(key=lambda r: r["roomId"], reverse=True)
        start = int(params.get("startPosition", 0))
        count = int(params.get("count", 25))
        page = rooms[start : start + count]
        return {"rooms": [self._public_room(r) for r in page], "totalRowCount": len(rooms)}

    def _public_room(
        self, room: dict[str, Any], include_field_data: bool = False
    ) -> dict[str, Any]:
        internal = ("fieldData", "users", "forms", "documentIds", "taskListIds")
        out = {k: v for k, v in room.items() if k not in internal}
        if include_field_data:
            out["fieldData"] = {"data": room.get("fieldData", {})}
        return out

    def _create_room(self, body: dict[str, Any]) -> dict[str, Any]:
        if not body.get("name"):
            raise MockAPIError(400, "Room name is required")
        room_id = self._next("next_room_id")
        room = {
            "roomId": room_id,
            "name": body["name"],
            "officeId": body.get("officeId", OFFICES[0]["officeId"]),
            "roleId": body.get("roleId"),
            "transactionSideId": body.get("transactionSideId"),
            "templateId": body.get("templateId"),
            "roomStatus": "Active",
            "createdDate": _now(),
            "fieldData": (body.get("fieldData") or {}).get("data", {}),
            "users": [],
            "forms": [],
            "documentIds": [],
            "taskListIds": [],
        }
        self._state["rooms"][str(room_id)] = room
        self._save()
        logger.info("mock_room_created", room_id=room_id, name=body["name"])
        return self._public_room(room)

    def _get_room(self, room_id: int, params: dict[str, Any]) -> dict[str, Any]:
        room = self._room(room_id)
        include_fd = str(params.get("includeFieldData", "")).lower() == "true"
        return self._public_room(room, include_field_data=include_fd)

    def _delete_room(self, room_id: int) -> dict[str, Any]:
        room = self._room(room_id)
        for doc_id in room["documentIds"]:
            self._state["documents"].pop(str(doc_id), None)
        for tl_id in room["taskListIds"]:
            self._state["task_lists"].pop(str(tl_id), None)
        del self._state["rooms"][str(room_id)]
        self._save()
        return {}

    # ---- field data --------------------------------------------------------

    def _get_field_data(self, room_id: int) -> dict[str, Any]:
        return {"data": self._room(room_id).get("fieldData", {})}

    def _put_field_data(self, room_id: int, body: dict[str, Any]) -> dict[str, Any]:
        room = self._room(room_id)
        incoming = body.get("data", {})
        field_data = room.setdefault("fieldData", {})
        for key, value in incoming.items():
            if isinstance(value, dict) and isinstance(field_data.get(key), dict):
                field_data[key].update(value)
            else:
                field_data[key] = value
        self._save()
        return {"data": field_data}

    # ---- users -------------------------------------------------------------

    def _get_users(self, room_id: int) -> dict[str, Any]:
        return {"users": self._room(room_id)["users"]}

    def _add_user(self, room_id: int, body: dict[str, Any]) -> dict[str, Any]:
        room = self._room(room_id)
        user = {
            "userId": self._next("next_user_id"),
            "email": body.get("email"),
            "firstName": body.get("firstName"),
            "lastName": body.get("lastName"),
            "roleId": body.get("roleId"),
            "transactionSideId": body.get("transactionSideId"),
            "accessRevoked": False,
        }
        room["users"].append(user)
        self._save()
        return user

    def _set_user_access(self, room_id: int, user_id: int, *, revoked: bool) -> dict[str, Any]:
        room = self._room(room_id)
        for user in room["users"]:
            if user["userId"] == user_id:
                user["accessRevoked"] = revoked
                self._save()
                return {}
        raise MockAPIError(404, f"User {user_id} not in room {room_id}")

    # ---- documents ---------------------------------------------------------

    def _get_documents(self, room_id: int) -> dict[str, Any]:
        room = self._room(room_id)
        store = self._state["documents"]
        docs = [store[str(d)] for d in room["documentIds"] if str(d) in store]
        return {"documents": docs}

    def _upload_document(self, room_id: int, file: tuple[str, bytes] | None) -> dict[str, Any]:
        if not file:
            raise MockAPIError(400, "No file provided")
        room = self._room(room_id)
        file_name, content = file
        doc_id = self._next("next_document_id")

        room_files = self.files_dir / str(room_id)
        room_files.mkdir(parents=True, exist_ok=True)
        stored_path = room_files / f"{doc_id}_{Path(file_name).name}"
        stored_path.write_bytes(content)

        doc = {
            "documentId": doc_id,
            "name": file_name,
            "roomId": room_id,
            "createdDate": _now(),
            "size": len(content),
            "contentStoredAt": str(stored_path),
        }
        self._state["documents"][str(doc_id)] = doc
        room["documentIds"].append(doc_id)
        self._save()
        logger.info("mock_document_uploaded", room_id=room_id, name=file_name)
        return doc

    def _get_document(self, doc_id: int) -> dict[str, Any]:
        doc = self._state["documents"].get(str(doc_id))
        if doc is None:
            raise MockAPIError(404, f"Document {doc_id} not found")
        return doc

    def _delete_document(self, doc_id: int) -> dict[str, Any]:
        doc = self._state["documents"].pop(str(doc_id), None)
        if doc is None:
            raise MockAPIError(404, f"Document {doc_id} not found")
        room = self._state["rooms"].get(str(doc["roomId"]))
        if room and doc_id in room["documentIds"]:
            room["documentIds"].remove(doc_id)
        self._save()
        return {}

    # ---- forms -------------------------------------------------------------

    def _get_library_forms(self, library_id: str) -> dict[str, Any]:
        if library_id not in {lib["formsLibraryId"] for lib in FORM_LIBRARIES}:
            raise MockAPIError(404, f"Form library {library_id} not found")
        forms = [f for f in FORMS.values() if f["formsLibraryId"] == library_id]
        return {"forms": forms}

    def _get_form_details(self, form_id: str) -> dict[str, Any]:
        form = FORMS.get(form_id)
        if form is None:
            raise MockAPIError(404, f"Form {form_id} not found")
        return {**form, "fields": FORM_FIELD_MAP.get(form_id, [])}

    def _add_form_to_room(self, room_id: int, body: dict[str, Any]) -> dict[str, Any]:
        room = self._room(room_id)
        form_id = body.get("formId")
        form = FORMS.get(form_id or "")
        if form is None:
            raise MockAPIError(404, f"Form {form_id} not found")

        # Mirror real Rooms behavior: snapshot the room field data the form
        # consumes at the moment it's added — this IS the auto-fill.
        field_data = room.get("fieldData", {})
        prefilled = {
            key: field_data[key]
            for key in FORM_FIELD_MAP.get(form_id, [])
            if key in field_data and field_data[key] not in (None, "", {})
        }
        instance = {
            "roomFormId": self._next("next_room_form_id"),
            "libraryFormId": form_id,
            "name": form["name"],
            "addedDate": _now(),
            "prefilledFields": prefilled,
            "prefilledFieldCount": len(prefilled),
            "expectedFieldCount": len(FORM_FIELD_MAP.get(form_id, [])),
        }
        room["forms"].append(instance)
        self._save()
        logger.info(
            "mock_form_added", room_id=room_id, form=form["name"], prefilled=len(prefilled)
        )
        return instance

    # ---- task lists --------------------------------------------------------

    def _get_room_task_lists(self, room_id: int) -> dict[str, Any]:
        room = self._room(room_id)
        lists = [
            self._state["task_lists"][str(t)]
            for t in room["taskListIds"]
            if str(t) in self._state["task_lists"]
        ]
        return {"taskLists": lists}

    def _add_task_list(self, room_id: int, body: dict[str, Any]) -> dict[str, Any]:
        room = self._room(room_id)
        template_id = body.get("taskListTemplateId")
        template = next(
            (t for t in TASK_LIST_TEMPLATES if t["taskListTemplateId"] == template_id), None
        )
        if template is None:
            raise MockAPIError(404, f"Task list template {template_id} not found")

        task_list_id = self._next("next_task_list_id")
        tasks = [
            {
                "taskId": self._next("next_task_id"),
                "name": name,
                "status": "Pending",
                "dueDate": None,
            }
            for name in template["tasks"]
        ]
        task_list = {
            "taskListId": task_list_id,
            "name": template["name"],
            "taskListTemplateId": template_id,
            "roomId": room_id,
            "createdDate": _now(),
            "tasks": tasks,
        }
        self._state["task_lists"][str(task_list_id)] = task_list
        room["taskListIds"].append(task_list_id)
        self._save()
        logger.info("mock_task_list_added", room_id=room_id, name=template["name"])
        return task_list

    def _delete_task_list(self, task_list_id: int) -> dict[str, Any]:
        task_list = self._state["task_lists"].pop(str(task_list_id), None)
        if task_list is None:
            raise MockAPIError(404, f"Task list {task_list_id} not found")
        room = self._state["rooms"].get(str(task_list["roomId"]))
        if room and task_list_id in room["taskListIds"]:
            room["taskListIds"].remove(task_list_id)
        self._save()
        return {}

    # ---- envelopes ---------------------------------------------------------

    def _create_envelope(self, room_id: int, body: dict[str, Any]) -> dict[str, Any]:
        self._room(room_id)  # existence check
        envelope = {
            "envelopeId": f"mock-envelope-{self._next('next_envelope_id')}",
            "roomId": room_id,
            "documentIds": body.get("documentIds", []),
            "status": "created",
            "createdDate": _now(),
        }
        self._save()
        return envelope


class MockDocuSignClient:
    """Drop-in replacement for DocuSignClient backed by MockRoomsAPI.

    Same async surface (`get`/`post`/`put`/`delete`/`post_multipart`/
    `get_global`/`close`) so `rooms.py` needs no changes.
    """

    def __init__(self, api: MockRoomsAPI | None = None):
        self.api = api or MockRoomsAPI()

    async def get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.api.handle("GET", endpoint, params=params)

    async def post(self, endpoint: str, json_data: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.api.handle("POST", endpoint, json_data=json_data)

    async def put(self, endpoint: str, json_data: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.api.handle("PUT", endpoint, json_data=json_data)

    async def delete(self, endpoint: str) -> bool:
        self.api.handle("DELETE", endpoint)
        return True

    async def post_multipart(
        self, endpoint: str, file_name: str, file_content: bytes
    ) -> dict[str, Any]:
        return self.api.handle("POST", endpoint, file=(file_name, file_content))

    async def get_global(self, endpoint: str) -> dict[str, Any]:
        return self.api.handle("GET", endpoint)

    async def close(self) -> None:
        return None
