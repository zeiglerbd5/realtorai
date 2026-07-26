"""The rooms.py API surface against the mock Rooms backend."""

import pytest

from realtorai.integrations.docusign import rooms


@pytest.fixture
def _env(offline_env):
    yield offline_env


async def _make_room(name: str = "42 Test St, Bangor") -> int:
    room = await rooms.create_room(
        name=name,
        role_id=2,
        transaction_side_id="sell",
        field_data={"address1": "42 Test St", "city": "Bangor", "seller1": {"name": "Jane Doe"}},
    )
    assert room is not None
    return room["roomId"]


async def test_create_and_get_room(_env):
    room_id = await _make_room()
    room = await rooms.get_room(room_id, include_field_data=True)
    assert room["name"] == "42 Test St, Bangor"
    assert room["roomStatus"] == "Active"
    assert room["fieldData"]["data"]["city"] == "Bangor"

    listed = await rooms.get_rooms()
    assert any(r["roomId"] == room_id for r in listed)


async def test_field_data_merges(_env):
    room_id = await _make_room()
    ok = await rooms.update_room_field_data(
        room_id, {"contractAmount": 295000.0, "seller1": {"email": "jane@example.com"}}
    )
    assert ok
    data = await rooms.get_room_field_data(room_id)
    assert data["contractAmount"] == 295000.0
    # Nested party merge keeps prior keys
    assert data["seller1"] == {"name": "Jane Doe", "email": "jane@example.com"}
    assert data["city"] == "Bangor"


async def test_task_list_from_template(_env):
    room_id = await _make_room()
    templates = await rooms.get_task_list_templates()
    names = {t["name"] for t in templates}
    assert {"New Listing", "Buyer Agreement"} <= names

    new_listing = next(t for t in templates if t["name"] == "New Listing")
    task_list = await rooms.add_task_list_to_room(room_id, new_listing["taskListTemplateId"])
    assert task_list is not None
    assert len(task_list["tasks"]) >= 10
    assert all(t["status"] == "Pending" for t in task_list["tasks"])

    on_room = await rooms.get_room_task_lists(room_id)
    assert on_room[0]["name"] == "New Listing"


async def test_form_autofill_snapshot(_env):
    """Adding a form snapshots the room field data it consumes — the auto-fill."""
    room_id = await _make_room()
    libraries = await rooms.get_form_libraries()
    assert libraries

    form_instance = await rooms.add_form_to_room(room_id, "form-erts")
    assert form_instance is not None
    prefilled = form_instance["prefilledFields"]
    assert prefilled["address1"] == "42 Test St"
    assert prefilled["seller1"] == {"name": "Jane Doe"}
    assert form_instance["prefilledFieldCount"] == len(prefilled)


async def test_document_upload(_env):
    room_id = await _make_room()
    doc = await rooms.upload_document_to_room(room_id, "agreement.pdf", b"%PDF-1.4 test")
    assert doc is not None
    assert doc["size"] == len(b"%PDF-1.4 test")

    docs = await rooms.get_room_documents(room_id)
    assert [d["name"] for d in docs] == ["agreement.pdf"]


async def test_reference_data_seeded(_env):
    sides = await rooms.get_transaction_sides()
    assert {"buy", "sell"} <= {s["transactionSideId"] for s in sides}
    roles = await rooms.get_roles()
    assert any(r["name"] == "Agent" for r in roles)
    offices = await rooms.get_offices()
    assert offices


async def test_state_persists_across_clients(_env):
    """A second client instance sees state written by the first (JSON store)."""
    from realtorai.integrations.docusign.client import reset_docusign_client

    room_id = await _make_room()
    reset_docusign_client()
    room = await rooms.get_room(room_id)
    assert room is not None
    assert room["roomId"] == room_id
