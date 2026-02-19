"""DocuSign Rooms integration.

Provides OAuth authentication and access to DocuSign Rooms API
for managing real estate transaction rooms.

API Reference: https://github.com/docusign/OpenAPI-Specifications/blob/master/rooms.rest.swagger-v2.json
"""

from realtorai.integrations.docusign.auth import docusign_auth, DocuSignAuth
from realtorai.integrations.docusign.client import get_docusign_client, DocuSignClient
from realtorai.integrations.docusign.rooms import (
    # Room CRUD
    get_rooms,
    get_room,
    create_room,
    delete_room,
    # Room users
    get_room_users,
    add_user_to_room,
    revoke_user_access,
    restore_user_access,
    # Room field data
    get_room_field_data,
    update_room_field_data,
    # Documents
    get_room_documents,
    upload_document_to_room,
    get_document,
    delete_document,
    # Form libraries
    get_form_libraries,
    get_form_library_forms,
    get_form_details,
    # Room forms
    get_room_forms,
    add_form_to_room,
    # Task lists
    get_task_list_templates,
    get_room_task_lists,
    add_task_list_to_room,
    delete_task_list,
    # Envelopes (eSignature)
    create_room_envelope,
    # Room templates
    get_room_templates,
    # Reference data
    get_roles,
    get_offices,
    get_room_assignable_roles,
    # Global reference data
    get_transaction_sides,
    get_property_types,
    # Utilities
    format_room_summary,
)

__all__ = [
    # Auth
    "docusign_auth",
    "DocuSignAuth",
    # Client
    "get_docusign_client",
    "DocuSignClient",
    # Room CRUD
    "get_rooms",
    "get_room",
    "create_room",
    "delete_room",
    # Room users
    "get_room_users",
    "add_user_to_room",
    "revoke_user_access",
    "restore_user_access",
    # Room field data
    "get_room_field_data",
    "update_room_field_data",
    # Documents
    "get_room_documents",
    "upload_document_to_room",
    "get_document",
    "delete_document",
    # Form libraries
    "get_form_libraries",
    "get_form_library_forms",
    "get_form_details",
    # Room forms
    "get_room_forms",
    "add_form_to_room",
    # Task lists
    "get_task_list_templates",
    "get_room_task_lists",
    "add_task_list_to_room",
    "delete_task_list",
    # Envelopes (eSignature)
    "create_room_envelope",
    # Room templates
    "get_room_templates",
    # Reference data
    "get_roles",
    "get_offices",
    "get_room_assignable_roles",
    # Global reference data
    "get_transaction_sides",
    "get_property_types",
    # Utilities
    "format_room_summary",
]
