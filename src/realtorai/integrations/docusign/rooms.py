"""DocuSign Rooms API functions.

Based on the official OpenAPI spec:
https://github.com/docusign/OpenAPI-Specifications/blob/master/rooms.rest.swagger-v2.json

Provides functions for managing transaction rooms, documents, forms, and tasks.
"""

from typing import Any

import httpx
import structlog

from realtorai.integrations.docusign.client import get_docusign_client

logger = structlog.get_logger()


# =============================================================================
# Rooms - Core CRUD operations
# =============================================================================


async def get_rooms(
    count: int = 25,
    start_position: int = 0,
    room_status: str | None = None,
    office_id: int | None = None,
) -> list[dict[str, Any]]:
    """Get list of rooms.

    Args:
        count: Number of rooms to return (max 100)
        start_position: Starting position for pagination
        room_status: Filter by status (Active, Pending, Closed)
        office_id: Filter by office

    Returns:
        List of room objects
    """
    client = get_docusign_client()

    params = {
        "count": min(count, 100),
        "startPosition": start_position,
    }

    if room_status:
        params["roomStatus"] = room_status
    if office_id:
        params["officeId"] = office_id

    try:
        data = await client.get("/rooms", params=params)
        rooms = data.get("rooms", [])

        logger.info("rooms_retrieved", count=len(rooms))
        return rooms

    except Exception as e:
        logger.error("rooms_get_error", error=str(e))
        return []


async def get_room(room_id: int, include_field_data: bool = False) -> dict[str, Any] | None:
    """Get details for a specific room.

    Args:
        room_id: The room ID
        include_field_data: Whether to include field data in response

    Returns:
        Room object or None if not found
    """
    client = get_docusign_client()

    params = {}
    if include_field_data:
        params["includeFieldData"] = "true"

    try:
        data = await client.get(f"/rooms/{room_id}", params=params if params else None)
        logger.info("room_retrieved", room_id=room_id)
        return data

    except Exception as e:
        logger.error("room_get_error", room_id=room_id, error=str(e))
        return None


async def create_room(
    name: str,
    role_id: int,
    transaction_side_id: str,
    template_id: int | None = None,
    office_id: int | None = None,
    field_data: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Create a new transaction room.

    Args:
        name: Room name (typically property address)
        role_id: Role ID for the creator
        transaction_side_id: "buy", "sell", or "listbuy"
        template_id: Room template ID (optional, for pre-configured rooms)
        office_id: Office ID (optional)
        field_data: Custom field data for the room

    Returns:
        Created room object or None on failure
    """
    client = get_docusign_client()

    room_data: dict[str, Any] = {
        "name": name,
        "roleId": role_id,
        "transactionSideId": transaction_side_id,
    }

    if template_id:
        room_data["templateId"] = template_id
    if office_id:
        room_data["officeId"] = office_id
    if field_data:
        room_data["fieldData"] = {"data": field_data}

    try:
        data = await client.post("/rooms", json_data=room_data)
        logger.info("room_created", room_id=data.get("roomId"), name=name)
        return data

    except Exception as e:
        logger.error("room_create_error", name=name, error=str(e))
        return None


async def delete_room(room_id: int) -> bool:
    """Delete a room.

    Args:
        room_id: The room ID

    Returns:
        True if successful
    """
    client = get_docusign_client()

    try:
        await client.delete(f"/rooms/{room_id}")
        logger.info("room_deleted", room_id=room_id)
        return True

    except Exception as e:
        logger.error("room_delete_error", room_id=room_id, error=str(e))
        return False


# =============================================================================
# Room Users - Manage parties in a transaction
# =============================================================================


async def get_room_users(
    room_id: int,
    count: int = 100,
    start_position: int = 0,
) -> list[dict[str, Any]]:
    """Get users/parties in a room.

    Args:
        room_id: The room ID
        count: Number of users to return
        start_position: Starting position for pagination

    Returns:
        List of user objects (buyers, sellers, agents, etc.)
    """
    client = get_docusign_client()

    params = {
        "count": min(count, 100),
        "startPosition": start_position,
    }

    try:
        data = await client.get(f"/rooms/{room_id}/users", params=params)
        users = data.get("users", [])

        logger.info("room_users_retrieved", room_id=room_id, count=len(users))
        return users

    except Exception as e:
        logger.error("room_users_error", room_id=room_id, error=str(e))
        return []


async def add_user_to_room(
    room_id: int,
    email: str,
    role_id: int,
    first_name: str | None = None,
    last_name: str | None = None,
    transaction_side_id: str | None = None,
) -> dict[str, Any] | None:
    """Add a user to a room.

    Args:
        room_id: The room ID
        email: User's email address
        role_id: Role ID for the user in this room
        first_name: User's first name
        last_name: User's last name
        transaction_side_id: Which side (buy/sell) the user is on

    Returns:
        User object or None on failure
    """
    client = get_docusign_client()

    user_data: dict[str, Any] = {
        "email": email,
        "roleId": role_id,
    }

    if first_name:
        user_data["firstName"] = first_name
    if last_name:
        user_data["lastName"] = last_name
    if transaction_side_id:
        user_data["transactionSideId"] = transaction_side_id

    try:
        data = await client.post(f"/rooms/{room_id}/users", json_data=user_data)
        logger.info("user_added_to_room", room_id=room_id, email=email)
        return data

    except Exception as e:
        logger.error("add_user_error", room_id=room_id, email=email, error=str(e))
        return None


async def revoke_user_access(room_id: int, user_id: int) -> bool:
    """Revoke a user's access to a room.

    Args:
        room_id: The room ID
        user_id: The user ID to revoke

    Returns:
        True if successful
    """
    client = get_docusign_client()

    try:
        await client.post(f"/rooms/{room_id}/users/{user_id}/revoke_access", json_data={})
        logger.info("user_access_revoked", room_id=room_id, user_id=user_id)
        return True

    except Exception as e:
        logger.error("revoke_access_error", room_id=room_id, user_id=user_id, error=str(e))
        return False


async def restore_user_access(room_id: int, user_id: int) -> bool:
    """Restore a revoked user's access to a room.

    Args:
        room_id: The room ID
        user_id: The user ID to restore

    Returns:
        True if successful
    """
    client = get_docusign_client()

    try:
        await client.post(f"/rooms/{room_id}/users/{user_id}/restore_access", json_data={})
        logger.info("user_access_restored", room_id=room_id, user_id=user_id)
        return True

    except Exception as e:
        logger.error("restore_access_error", room_id=room_id, user_id=user_id, error=str(e))
        return False


# =============================================================================
# Room Field Data - Transaction details
# =============================================================================


async def get_room_field_data(room_id: int) -> dict[str, Any]:
    """Get field data for a room (transaction details).

    Args:
        room_id: The room ID

    Returns:
        Field data dictionary
    """
    client = get_docusign_client()

    try:
        data = await client.get(f"/rooms/{room_id}/field_data")
        logger.info("room_field_data_retrieved", room_id=room_id)
        return data.get("data", data)

    except Exception as e:
        logger.error("room_field_data_error", room_id=room_id, error=str(e))
        return {}


async def update_room_field_data(room_id: int, field_data: dict[str, Any]) -> bool:
    """Update field data for a room.

    Args:
        room_id: The room ID
        field_data: Dictionary of field values to update

    Returns:
        True if successful
    """
    client = get_docusign_client()

    try:
        await client.put(f"/rooms/{room_id}/field_data", json_data={"data": field_data})
        logger.info("room_field_data_updated", room_id=room_id)
        return True

    except Exception as e:
        logger.error("room_field_data_update_error", room_id=room_id, error=str(e))
        return False


# =============================================================================
# Documents - Upload and manage documents in rooms
# =============================================================================


async def get_room_documents(room_id: int) -> list[dict[str, Any]]:
    """Get documents in a room.

    Args:
        room_id: The room ID

    Returns:
        List of document objects with documentId, name, ownerId, size, etc.
    """
    client = get_docusign_client()

    try:
        data = await client.get(f"/rooms/{room_id}/documents")
        documents = data.get("documents", [])

        logger.info("room_documents_retrieved", room_id=room_id, count=len(documents))
        return documents

    except Exception as e:
        logger.error("room_documents_error", room_id=room_id, error=str(e))
        return []


async def upload_document_to_room(
    room_id: int,
    file_name: str,
    file_content: bytes,
) -> dict[str, Any] | None:
    """Upload a document to a room.

    Uses multipart/form-data as required by the API.

    Args:
        room_id: The room ID
        file_name: Name for the document file
        file_content: Document bytes (PDF, etc.)

    Returns:
        Created document object or None
    """
    from realtorai.integrations.docusign.auth import docusign_auth
    from realtorai.config.settings import get_settings

    settings = get_settings()
    token = await docusign_auth.get_access_token()
    if not token:
        logger.error("document_upload_no_token")
        return None

    account_id = settings.docusign_account_id
    url = f"https://demo.rooms.docusign.com/restapi/v2/accounts/{account_id}/rooms/{room_id}/documents/contents"

    try:
        async with httpx.AsyncClient() as http_client:
            response = await http_client.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                files={"file": (file_name, file_content)},
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()

        logger.info("document_uploaded", room_id=room_id, name=file_name)
        return data

    except Exception as e:
        logger.error("document_upload_error", room_id=room_id, error=str(e))
        return None


async def get_document(document_id: int) -> dict[str, Any] | None:
    """Get document info (outside room context).

    Args:
        document_id: The document ID

    Returns:
        Document info or None
    """
    client = get_docusign_client()

    try:
        data = await client.get(f"/documents/{document_id}")
        return data

    except Exception as e:
        logger.error("document_get_error", document_id=document_id, error=str(e))
        return None


async def delete_document(document_id: int) -> bool:
    """Delete a document.

    Args:
        document_id: The document ID

    Returns:
        True if successful
    """
    client = get_docusign_client()

    try:
        await client.delete(f"/documents/{document_id}")
        logger.info("document_deleted", document_id=document_id)
        return True

    except Exception as e:
        logger.error("document_delete_error", document_id=document_id, error=str(e))
        return False


# =============================================================================
# Form Libraries - Template forms available to add to rooms
# =============================================================================


async def get_form_libraries() -> list[dict[str, Any]]:
    """Get available form libraries.

    Returns:
        List of form library objects with formsLibraryId and name
    """
    client = get_docusign_client()

    try:
        data = await client.get("/form_libraries")
        libraries = data.get("formsLibrarySummaries", [])

        logger.info("form_libraries_retrieved", count=len(libraries))
        return libraries

    except Exception as e:
        logger.error("form_libraries_error", error=str(e))
        return []


async def get_form_library_forms(
    library_id: str,
    count: int = 100,
    start_position: int = 0,
) -> list[dict[str, Any]]:
    """Get forms available in a form library.

    Args:
        library_id: The form library ID
        count: Number of forms to return
        start_position: Starting position for pagination

    Returns:
        List of form objects with libraryFormId and name
    """
    client = get_docusign_client()

    params = {
        "count": min(count, 100),
        "startPosition": start_position,
    }

    try:
        data = await client.get(f"/form_libraries/{library_id}/forms", params=params)
        forms = data.get("forms", [])

        logger.info("form_library_forms_retrieved", library_id=library_id, count=len(forms))
        return forms

    except Exception as e:
        logger.error("form_library_forms_error", library_id=library_id, error=str(e))
        return []


async def get_form_details(form_id: str) -> dict[str, Any] | None:
    """Get details for a specific form including its fields.

    Args:
        form_id: The form ID (GUID)

    Returns:
        Form details object or None
    """
    client = get_docusign_client()

    try:
        # Per API spec: /forms/{formId}/details
        data = await client.get(f"/forms/{form_id}/details")
        logger.info("form_details_retrieved", form_id=form_id)
        return data

    except Exception as e:
        logger.error("form_details_error", form_id=form_id, error=str(e))
        return None


# =============================================================================
# Room Forms - Forms added to a specific room
# =============================================================================


async def get_room_forms(room_id: int) -> list[dict[str, Any]]:
    """Get forms that have been added to a room.

    Args:
        room_id: The room ID

    Returns:
        List of form objects in the room
    """
    client = get_docusign_client()

    try:
        data = await client.get(f"/rooms/{room_id}/forms")
        forms = data.get("forms", [])

        logger.info("room_forms_retrieved", room_id=room_id, count=len(forms))
        return forms

    except Exception as e:
        logger.error("room_forms_error", room_id=room_id, error=str(e))
        return []


async def add_form_to_room(room_id: int, form_id: str) -> dict[str, Any] | None:
    """Add a form from library to a room.

    Args:
        room_id: The room ID
        form_id: The form ID (libraryFormId from form library)

    Returns:
        Created form instance or None
    """
    client = get_docusign_client()

    try:
        data = await client.post(
            f"/rooms/{room_id}/forms",
            json_data={"formId": form_id}
        )
        logger.info("form_added_to_room", room_id=room_id, form_id=form_id)
        return data

    except Exception as e:
        logger.error("add_form_error", room_id=room_id, form_id=form_id, error=str(e))
        return None


# =============================================================================
# Task Lists - Manage checklist items for transactions
# =============================================================================


async def get_task_list_templates() -> list[dict[str, Any]]:
    """Get available task list templates.

    Returns:
        List of task list template objects
    """
    client = get_docusign_client()

    try:
        data = await client.get("/task_list_templates")
        templates = data.get("taskListTemplates", [])

        logger.info("task_list_templates_retrieved", count=len(templates))
        return templates

    except Exception as e:
        logger.error("task_list_templates_error", error=str(e))
        return []


async def get_room_task_lists(room_id: int) -> list[dict[str, Any]]:
    """Get task lists for a room.

    Each task list contains an array of tasks.

    Args:
        room_id: The room ID

    Returns:
        List of task list objects (each with embedded 'tasks' array)
    """
    client = get_docusign_client()

    try:
        data = await client.get(f"/rooms/{room_id}/task_lists")
        task_lists = data.get("taskLists", [])

        logger.info("room_task_lists_retrieved", room_id=room_id, count=len(task_lists))
        return task_lists

    except Exception as e:
        logger.error("room_task_lists_error", room_id=room_id, error=str(e))
        return []


async def add_task_list_to_room(room_id: int, task_list_template_id: int) -> dict[str, Any] | None:
    """Add a task list to a room from a template.

    Args:
        room_id: The room ID
        task_list_template_id: The task list template ID

    Returns:
        Created task list object or None
    """
    client = get_docusign_client()

    try:
        data = await client.post(
            f"/rooms/{room_id}/task_lists",
            json_data={"taskListTemplateId": task_list_template_id}
        )
        logger.info("task_list_added", room_id=room_id, template_id=task_list_template_id)
        return data

    except Exception as e:
        logger.error("add_task_list_error", room_id=room_id, error=str(e))
        return None


async def delete_task_list(task_list_id: int) -> bool:
    """Delete a task list.

    Note: This endpoint is outside the room context.

    Args:
        task_list_id: The task list ID

    Returns:
        True if successful
    """
    client = get_docusign_client()

    try:
        await client.delete(f"/task_lists/{task_list_id}")
        logger.info("task_list_deleted", task_list_id=task_list_id)
        return True

    except Exception as e:
        logger.error("delete_task_list_error", task_list_id=task_list_id, error=str(e))
        return False


# =============================================================================
# Room Envelopes - eSignature integration
# =============================================================================


async def create_room_envelope(
    room_id: int,
    document_ids: list[int] | None = None,
) -> dict[str, Any] | None:
    """Create an eSignature envelope for room documents.

    Args:
        room_id: The room ID
        document_ids: Optional list of specific document IDs to include

    Returns:
        Envelope info or None
    """
    client = get_docusign_client()

    json_data: dict[str, Any] = {}
    if document_ids:
        json_data["documentIds"] = document_ids

    try:
        data = await client.post(f"/rooms/{room_id}/envelopes", json_data=json_data)
        logger.info("room_envelope_created", room_id=room_id)
        return data

    except Exception as e:
        logger.error("room_envelope_error", room_id=room_id, error=str(e))
        return None


# =============================================================================
# Room Templates - Pre-configured room structures
# =============================================================================


async def get_room_templates() -> list[dict[str, Any]]:
    """Get available room templates.

    Returns:
        List of room template objects with roomTemplateId and name
    """
    client = get_docusign_client()

    try:
        data = await client.get("/room_templates")
        templates = data.get("roomTemplates", [])

        logger.info("room_templates_retrieved", count=len(templates))
        return templates

    except Exception as e:
        logger.error("room_templates_error", error=str(e))
        return []


# =============================================================================
# Reference Data - Roles, Offices, etc.
# =============================================================================


async def get_roles() -> list[dict[str, Any]]:
    """Get available roles for rooms.

    Returns:
        List of role objects with roleId and name
    """
    client = get_docusign_client()

    try:
        data = await client.get("/roles")
        roles = data.get("roles", [])

        logger.info("roles_retrieved", count=len(roles))
        return roles

    except Exception as e:
        logger.error("roles_get_error", error=str(e))
        return []


async def get_offices() -> list[dict[str, Any]]:
    """Get offices for the account.

    Returns:
        List of office objects with officeId and name
    """
    client = get_docusign_client()

    try:
        data = await client.get("/offices")
        offices = data.get("officeSummaries", [])

        logger.info("offices_retrieved", count=len(offices))
        return offices

    except Exception as e:
        logger.error("offices_get_error", error=str(e))
        return []


async def get_room_assignable_roles(room_id: int) -> list[dict[str, Any]]:
    """Get roles that can be assigned to users in a specific room.

    Args:
        room_id: The room ID

    Returns:
        List of assignable role objects
    """
    client = get_docusign_client()

    try:
        data = await client.get(f"/rooms/{room_id}/assignable_roles")
        roles = data.get("roles", [])

        logger.info("assignable_roles_retrieved", room_id=room_id, count=len(roles))
        return roles

    except Exception as e:
        logger.error("assignable_roles_error", room_id=room_id, error=str(e))
        return []


# =============================================================================
# Global Reference Data - No account ID required
# =============================================================================


async def get_transaction_sides() -> list[dict[str, Any]]:
    """Get transaction side types (buy, sell, listbuy).

    Note: Uses a different base URL pattern (no account ID).
    """
    from realtorai.integrations.docusign.auth import docusign_auth

    token = await docusign_auth.get_access_token()
    if not token:
        return []

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://demo.rooms.docusign.com/restapi/v2/transaction_sides",
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            data = response.json()
        return data.get("transactionSides", [])

    except Exception as e:
        logger.error("transaction_sides_error", error=str(e))
        return []


async def get_property_types() -> list[dict[str, Any]]:
    """Get property types (residential, commercial, etc.)."""
    from realtorai.integrations.docusign.auth import docusign_auth

    token = await docusign_auth.get_access_token()
    if not token:
        return []

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://demo.rooms.docusign.com/restapi/v2/property_types",
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            data = response.json()
        return data.get("propertyTypes", [])

    except Exception as e:
        logger.error("property_types_error", error=str(e))
        return []


# =============================================================================
# Utilities
# =============================================================================


def format_room_summary(room: dict[str, Any]) -> str:
    """Format a room as a human-readable summary.

    Args:
        room: Room object from API

    Returns:
        Formatted string summary
    """
    name = room.get("name", "Unknown")
    status = room.get("roomStatus", "Unknown")
    room_id = room.get("roomId", "")
    created = room.get("createdDate", "")[:10] if room.get("createdDate") else ""

    return f"{name}\nID: {room_id} | Status: {status} | Created: {created}"
