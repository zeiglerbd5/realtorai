#!/usr/bin/env python3
"""Test DocuSign Rooms integration.

Usage:
    python scripts/docusign_test.py connect     # Authenticate with DocuSign
    python scripts/docusign_test.py status      # Check connection status
    python scripts/docusign_test.py disconnect  # Clear credentials

    # Reference Data
    python scripts/docusign_test.py roles       # List available roles
    python scripts/docusign_test.py offices     # List offices
    python scripts/docusign_test.py templates   # List room templates
    python scripts/docusign_test.py sides       # List transaction sides
    python scripts/docusign_test.py tasktpl     # List task list templates

    # Rooms
    python scripts/docusign_test.py rooms       # List rooms
    python scripts/docusign_test.py room <id>   # Get room details

    # Forms
    python scripts/docusign_test.py libraries   # List form libraries
    python scripts/docusign_test.py forms <library_id>  # List forms in library
"""

import asyncio
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from realtorai.integrations.docusign import (
    docusign_auth,
    get_rooms,
    get_room,
    get_roles,
    get_offices,
    get_room_templates,
    get_form_libraries,
    get_form_library_forms,
    get_room_documents,
    get_room_users,
    get_room_task_lists,
    get_task_list_templates,
    get_transaction_sides,
    format_room_summary,
)
from realtorai.config.settings import get_settings


async def check_status():
    """Check DocuSign connection status."""
    settings = get_settings()

    print("DocuSign Rooms Status")
    print("-" * 40)

    configured = await docusign_auth.is_configured()
    print(f"Configured: {configured}")

    if not configured:
        print("\nMissing credentials. Set these in .env:")
        print("  DOCUSIGN_INTEGRATION_KEY=your_integration_key")
        print("  DOCUSIGN_SECRET_KEY=your_secret_key")
        print("  DOCUSIGN_ACCOUNT_ID=your_account_id")
        print("  DOCUSIGN_USER_ID=your_user_id")
        return

    connected = await docusign_auth.is_connected()
    print(f"Connected: {connected}")

    if not connected:
        print("\nNot authenticated. Run: python scripts/docusign_test.py connect")


async def connect():
    """Authenticate with DocuSign."""
    print("Connecting to DocuSign...")
    print("This will open a browser for OAuth authentication.\n")

    if not await docusign_auth.is_configured():
        print("Error: DocuSign not configured.")
        print("Set credentials in .env first.")
        return False

    success = await docusign_auth.connect()

    if success:
        print("\nSuccess! Connected to DocuSign Rooms.")
    else:
        print("\nFailed to connect. Check credentials and try again.")

    return success


async def disconnect():
    """Clear DocuSign credentials."""
    await docusign_auth.disconnect()
    print("Disconnected from DocuSign. Credentials cleared.")


async def list_rooms():
    """List transaction rooms."""
    if not await docusign_auth.is_connected():
        print("Not connected. Run: python scripts/docusign_test.py connect")
        return

    print("Fetching rooms...")
    print("-" * 40)

    rooms = await get_rooms(count=10)

    if not rooms:
        print("No rooms found.")
        return

    print(f"Found {len(rooms)} rooms:\n")

    for room in rooms:
        print(format_room_summary(room))
        print()


async def list_roles():
    """List available roles."""
    if not await docusign_auth.is_connected():
        print("Not connected. Run: python scripts/docusign_test.py connect")
        return

    print("Available Roles")
    print("-" * 40)

    roles = await get_roles()

    if not roles:
        print("No roles found.")
        return

    for role in roles:
        print(f"  {role.get('roleId')}: {role.get('name')}")


async def list_offices():
    """List offices."""
    if not await docusign_auth.is_connected():
        print("Not connected. Run: python scripts/docusign_test.py connect")
        return

    print("Offices")
    print("-" * 40)

    offices = await get_offices()

    if not offices:
        print("No offices found.")
        return

    for office in offices:
        print(f"  {office.get('officeId')}: {office.get('name')}")


async def list_templates():
    """List room templates."""
    if not await docusign_auth.is_connected():
        print("Not connected. Run: python scripts/docusign_test.py connect")
        return

    print("Room Templates")
    print("-" * 40)

    templates = await get_room_templates()

    if not templates:
        print("No templates found.")
        return

    for template in templates:
        print(f"  {template.get('roomTemplateId')}: {template.get('name')}")


async def list_transaction_sides():
    """List transaction sides."""
    if not await docusign_auth.is_connected():
        print("Not connected. Run: python scripts/docusign_test.py connect")
        return

    print("Transaction Sides")
    print("-" * 40)

    sides = await get_transaction_sides()

    if not sides:
        print("No transaction sides found.")
        return

    for side in sides:
        print(f"  {side.get('transactionSideId')}: {side.get('name')}")


async def list_task_templates():
    """List task list templates."""
    if not await docusign_auth.is_connected():
        print("Not connected. Run: python scripts/docusign_test.py connect")
        return

    print("Task List Templates")
    print("-" * 40)

    templates = await get_task_list_templates()

    if not templates:
        print("No task list templates found.")
        return

    for template in templates:
        print(f"  {template.get('taskListTemplateId')}: {template.get('name')}")


async def get_room_detail(room_id: int):
    """Get detailed info for a room."""
    if not await docusign_auth.is_connected():
        print("Not connected. Run: python scripts/docusign_test.py connect")
        return

    print(f"Room {room_id} Details")
    print("-" * 40)

    room = await get_room(room_id, include_field_data=True)
    if not room:
        print("Room not found.")
        return

    print(f"Name: {room.get('name')}")
    print(f"Status: {room.get('roomStatus')}")
    print(f"Created: {room.get('createdDate')}")
    print(f"Transaction Side: {room.get('transactionSideId')}")

    # Get users
    print("\nUsers:")
    users = await get_room_users(room_id)
    if users:
        for user in users:
            print(f"  - {user.get('firstName')} {user.get('lastName')} ({user.get('email')})")
    else:
        print("  (none)")

    # Get documents
    print("\nDocuments:")
    docs = await get_room_documents(room_id)
    if docs:
        for doc in docs:
            print(f"  - {doc.get('name')} (ID: {doc.get('documentId')})")
    else:
        print("  (none)")

    # Get task lists
    print("\nTask Lists:")
    task_lists = await get_room_task_lists(room_id)
    if task_lists:
        for tl in task_lists:
            print(f"  - {tl.get('name')} (ID: {tl.get('taskListId')})")
            tasks = tl.get("tasks", [])
            for task in tasks[:5]:  # Show first 5 tasks
                print(f"      * {task.get('name')}")
            if len(tasks) > 5:
                print(f"      ... and {len(tasks) - 5} more tasks")
    else:
        print("  (none)")


async def list_form_libraries():
    """List form libraries."""
    if not await docusign_auth.is_connected():
        print("Not connected. Run: python scripts/docusign_test.py connect")
        return

    print("Form Libraries")
    print("-" * 40)

    libraries = await get_form_libraries()

    if not libraries:
        print("No form libraries found.")
        return

    for lib in libraries:
        print(f"  {lib.get('formsLibraryId')}: {lib.get('name')}")
        if lib.get("formCount"):
            print(f"    Forms count: {lib.get('formCount')}")


async def list_library_forms(library_id: str):
    """List forms in a library."""
    if not await docusign_auth.is_connected():
        print("Not connected. Run: python scripts/docusign_test.py connect")
        return

    print(f"Forms in Library {library_id}")
    print("-" * 40)

    forms = await get_form_library_forms(library_id)

    if not forms:
        print("No forms found.")
        return

    for form in forms:
        print(f"  {form.get('libraryFormId')}: {form.get('name')}")
        if form.get("lastUpdatedDate"):
            print(f"    Updated: {form.get('lastUpdatedDate')[:10]}")


async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    command = sys.argv[1].lower()

    if command == "status":
        await check_status()
    elif command == "connect":
        await connect()
    elif command == "disconnect":
        await disconnect()
    elif command == "rooms":
        await list_rooms()
    elif command == "room":
        if len(sys.argv) < 3:
            print("Usage: python scripts/docusign_test.py room <room_id>")
            return
        await get_room_detail(int(sys.argv[2]))
    elif command == "roles":
        await list_roles()
    elif command == "offices":
        await list_offices()
    elif command == "templates":
        await list_templates()
    elif command == "sides":
        await list_transaction_sides()
    elif command == "tasktpl":
        await list_task_templates()
    elif command == "libraries":
        await list_form_libraries()
    elif command == "forms":
        if len(sys.argv) < 3:
            print("Usage: python scripts/docusign_test.py forms <library_id>")
            return
        await list_library_forms(sys.argv[2])
    else:
        print(f"Unknown command: {command}")
        print(__doc__)


if __name__ == "__main__":
    asyncio.run(main())
