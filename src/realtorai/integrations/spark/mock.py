"""Local simulator for MLS draft-listing submission.

Maine Listings (MREIS) runs on FBS's Flexmls platform; programmatic listing
entry goes through the Spark API, which requires MLS approval we don't yet
have. This module stores draft listings locally in the exact shape the Spark
`POST /listings` call would send, so the submission workflow, validation, and
review UI all behave identically — flipping `MLS_BACKEND=live` swaps in the
real API with no other changes.

State lives in `data/mock_mls/listings.json`.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from realtorai.config.settings import get_settings

logger = structlog.get_logger()


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat() + "Z"


class MockSparkMLS:
    """JSON-persisted stand-in for the Spark API listing endpoints."""

    def __init__(self, state_dir: Path | None = None):
        settings = get_settings()
        self.state_dir = state_dir or settings.mock_mls_dir
        self.state_path = self.state_dir / "listings.json"
        self._state: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if self.state_path.exists():
            try:
                with open(self.state_path) as f:
                    return json.load(f)
            except Exception as e:
                logger.error("mock_mls_state_read_error", error=str(e))
        return {"next_listing_number": 1660001, "listings": {}}

    def _save(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with open(self.state_path, "w") as f:
            json.dump(self._state, f, indent=2)

    def reset(self) -> None:
        self._state = {"next_listing_number": 1660001, "listings": {}}
        self._save()

    # ---- Spark-shaped operations ------------------------------------------

    def create_listing(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Store a draft listing; payload is the Spark `POST /listings` body."""
        number = self._state["next_listing_number"]
        self._state["next_listing_number"] = number + 1

        listing_key = f"mock-{number}"
        listing_id = str(number)
        listing = {
            "ListingKey": listing_key,
            "ListingId": listing_id,
            "StandardStatus": "Draft",
            "MlsStatus": "Draft — pending agent review",
            "CreatedTimestamp": _now(),
            "ModificationTimestamp": _now(),
            "Payload": payload,
            "Photos": [],
        }
        self._state["listings"][listing_key] = listing
        self._save()
        logger.info(
            "mock_mls_draft_created",
            listing_key=listing_key,
            fields=len(payload),
            address=payload.get("StreetName"),
        )
        return {"listing_key": listing_key, "listing_id": listing_id, "status": "draft"}

    def add_photo(self, listing_key: str, name: str, is_primary: bool = False) -> str:
        listing = self._state["listings"].get(listing_key)
        if listing is None:
            raise KeyError(f"Mock MLS: listing {listing_key} not found")
        photo_id = f"photo-{len(listing['Photos']) + 1}"
        listing["Photos"].append({"Id": photo_id, "Name": name, "Primary": is_primary})
        listing["ModificationTimestamp"] = _now()
        self._save()
        return photo_id

    def set_listing_status(self, listing_key: str, status: str) -> bool:
        """Update a listing's RESO status fields (e.g. Draft -> Pending)."""
        listing = self._state["listings"].get(listing_key)
        if listing is None:
            return False
        listing["StandardStatus"] = status.title()
        listing["MlsStatus"] = status.title()
        listing["ModificationTimestamp"] = _now()
        self._save()
        return True

    def get_listing(self, listing_key: str) -> dict[str, Any] | None:
        return self._state["listings"].get(listing_key)

    def list_listings(self) -> list[dict[str, Any]]:
        return sorted(
            self._state["listings"].values(),
            key=lambda listing: listing["CreatedTimestamp"],
            reverse=True,
        )


_mock_mls: MockSparkMLS | None = None


def get_mock_mls() -> MockSparkMLS:
    global _mock_mls
    if _mock_mls is None:
        _mock_mls = MockSparkMLS()
    return _mock_mls


def reset_mock_mls() -> None:
    global _mock_mls
    _mock_mls = None
