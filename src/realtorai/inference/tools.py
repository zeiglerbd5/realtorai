"""Tool definitions for LLM function calling."""

from typing import Any

# Tool definitions in OpenAI function format
# These will be expanded as we add more integrations

SEND_EMAIL_TOOL = {
    "type": "function",
    "function": {
        "name": "send_email",
        "description": "Send an email to a recipient. The email will be queued for agent "
        "approval before actually sending.",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Email address of the recipient",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line",
                },
                "body": {
                    "type": "string",
                    "description": "Email body content",
                },
                "reply_to_id": {
                    "type": "string",
                    "description": "Message ID if this is a reply to an existing email",
                },
            },
            "required": ["to", "subject", "body"],
        },
    },
}

SCHEDULE_EVENT_TOOL = {
    "type": "function",
    "function": {
        "name": "schedule_event",
        "description": "Schedule a calendar event. The event will be queued for agent approval.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Event title",
                },
                "start_time": {
                    "type": "string",
                    "description": "Start time in ISO format",
                },
                "end_time": {
                    "type": "string",
                    "description": "End time in ISO format",
                },
                "location": {
                    "type": "string",
                    "description": "Event location or address",
                },
                "attendees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of attendee email addresses",
                },
                "description": {
                    "type": "string",
                    "description": "Event description or notes",
                },
            },
            "required": ["title", "start_time", "end_time"],
        },
    },
}

CREATE_REMINDER_TOOL = {
    "type": "function",
    "function": {
        "name": "create_reminder",
        "description": "Create a follow-up reminder or task for the agent.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Reminder title",
                },
                "due_date": {
                    "type": "string",
                    "description": "When the reminder is due (ISO format or relative like "
                    "'tomorrow')",
                },
                "related_contact": {
                    "type": "string",
                    "description": "Email or name of related contact",
                },
                "related_transaction": {
                    "type": "string",
                    "description": "Related property address or transaction ID",
                },
                "notes": {
                    "type": "string",
                    "description": "Additional notes",
                },
            },
            "required": ["title", "due_date"],
        },
    },
}

UPDATE_CLIENT_NOTES_TOOL = {
    "type": "function",
    "function": {
        "name": "update_client_notes",
        "description": "Add a note to a client's profile.",
        "parameters": {
            "type": "object",
            "properties": {
                "client_email": {
                    "type": "string",
                    "description": "Client's email address",
                },
                "note": {
                    "type": "string",
                    "description": "Note to add",
                },
                "category": {
                    "type": "string",
                    "enum": ["preference", "interaction", "requirement", "general"],
                    "description": "Category of note",
                },
            },
            "required": ["client_email", "note"],
        },
    },
}

# MLS/Spark API Tools
SEARCH_LISTINGS_TOOL = {
    "type": "function",
    "function": {
        "name": "search_listings",
        "description": "Search MLS listings for properties matching criteria. "
        "Use this to find homes for clients.",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "City to search in",
                },
                "postal_code": {
                    "type": "string",
                    "description": "ZIP code to search in",
                },
                "min_price": {
                    "type": "integer",
                    "description": "Minimum list price",
                },
                "max_price": {
                    "type": "integer",
                    "description": "Maximum list price",
                },
                "min_beds": {
                    "type": "integer",
                    "description": "Minimum number of bedrooms",
                },
                "min_baths": {
                    "type": "integer",
                    "description": "Minimum number of bathrooms",
                },
                "property_type": {
                    "type": "string",
                    "enum": ["Residential", "Condo", "Townhouse", "Land", "Multi-Family"],
                    "description": "Type of property",
                },
                "status": {
                    "type": "string",
                    "enum": ["Active", "Pending", "Sold"],
                    "description": "Listing status (default: Active)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results to return (default: 10)",
                },
            },
            "required": [],
        },
    },
}

GET_LISTING_DETAILS_TOOL = {
    "type": "function",
    "function": {
        "name": "get_listing_details",
        "description": "Get full details for a specific MLS listing by its ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "listing_id": {
                    "type": "string",
                    "description": "The MLS listing ID",
                },
            },
            "required": ["listing_id"],
        },
    },
}

FIND_COMPS_TOOL = {
    "type": "function",
    "function": {
        "name": "find_comps",
        "description": "Find comparable sold properties for pricing analysis or CMA.",
        "parameters": {
            "type": "object",
            "properties": {
                "listing_id": {
                    "type": "string",
                    "description": "Source listing ID to find comps for",
                },
                "city": {
                    "type": "string",
                    "description": "City to search in",
                },
                "price": {
                    "type": "integer",
                    "description": "Target price for comp range (+/- 20%)",
                },
                "beds": {
                    "type": "integer",
                    "description": "Number of bedrooms (+/- 1)",
                },
                "sqft": {
                    "type": "integer",
                    "description": "Square footage (+/- 20%)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum comps to return (default: 10)",
                },
            },
            "required": [],
        },
    },
}

GET_MARKET_STATS_TOOL = {
    "type": "function",
    "function": {
        "name": "get_market_stats",
        "description": "Get market statistics for an area including active listings, "
        "recent sales, and median prices.",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "City name",
                },
                "postal_code": {
                    "type": "string",
                    "description": "ZIP code",
                },
            },
            "required": [],
        },
    },
}

# Client Profile Tools
CREATE_CLIENT_TOOL = {
    "type": "function",
    "function": {
        "name": "create_client",
        "description": "Create a new client record with a markdown profile file. "
        "Use this when the agent mentions a new client.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Client's full name",
                },
                "email": {
                    "type": "string",
                    "description": "Client's email address",
                },
                "phone": {
                    "type": "string",
                    "description": "Client's phone number",
                },
                "transaction_type": {
                    "type": "string",
                    "enum": ["buy", "sell", "both"],
                    "description": "Whether client is buying, selling, or both",
                },
                "property_address": {
                    "type": "string",
                    "description": "Property address (for sellers) or target area (for buyers)",
                },
                "price": {
                    "type": "number",
                    "description": "Price (asking price for sellers, budget for buyers)",
                },
            },
            "required": ["name"],
        },
    },
}

LIST_CLIENTS_TOOL = {
    "type": "function",
    "function": {
        "name": "list_clients",
        "description": "List all clients, optionally filtered by status.",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["lead", "active", "pending", "closed", "inactive"],
                    "description": "Filter by client status",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum clients to return (default: 20)",
                },
            },
            "required": [],
        },
    },
}

READ_CLIENT_PROFILE_TOOL = {
    "type": "function",
    "function": {
        "name": "read_client_profile",
        "description": "Read a client's full markdown profile including notes and history. "
        "Use this to get context about a client.",
        "parameters": {
            "type": "object",
            "properties": {
                "client_id": {
                    "type": "integer",
                    "description": "The client's ID",
                },
                "client_name": {
                    "type": "string",
                    "description": "Search by client name if ID unknown",
                },
            },
            "required": [],
        },
    },
}

UPDATE_CLIENT_PROFILE_TOOL = {
    "type": "function",
    "function": {
        "name": "update_client_profile",
        "description": "Update a client's profile. "
        "Can add notes, update status, or modify details.",
        "parameters": {
            "type": "object",
            "properties": {
                "client_id": {
                    "type": "integer",
                    "description": "The client's ID",
                },
                "note": {
                    "type": "string",
                    "description": "Note to append to the client's profile",
                },
                "status": {
                    "type": "string",
                    "enum": ["lead", "active", "pending", "closed", "inactive"],
                    "description": "Update client status",
                },
                "property_address": {
                    "type": "string",
                    "description": "Update property address",
                },
                "price": {
                    "type": "number",
                    "description": "Update price/budget",
                },
            },
            "required": ["client_id"],
        },
    },
}

ADD_PENDING_ITEM_TOOL = {
    "type": "function",
    "function": {
        "name": "add_pending_item",
        "description": "Add a pending item to track something we're waiting on for a client.",
        "parameters": {
            "type": "object",
            "properties": {
                "client_id": {
                    "type": "integer",
                    "description": "The client's ID",
                },
                "description": {
                    "type": "string",
                    "description": "What we're waiting on (e.g., 'Pre-approval letter')",
                },
                "waiting_on": {
                    "type": "string",
                    "enum": ["client", "lender", "agent", "attorney", "title", "other"],
                    "description": "Who we're waiting on",
                },
                "due_date": {
                    "type": "string",
                    "description": "Due date in ISO format (optional)",
                },
            },
            "required": ["client_id", "description", "waiting_on"],
        },
    },
}

# Matterport Tools
GET_MATTERPORT_TOUR_TOOL = {
    "type": "function",
    "function": {
        "name": "get_matterport_tour",
        "description": "Download a Matterport 3D tour and still images to a client's folder. "
        "Requires the Matterport model ID (found in the tour URL).",
        "parameters": {
            "type": "object",
            "properties": {
                "client_id": {
                    "type": "integer",
                    "description": "The client's ID",
                },
                "model_id": {
                    "type": "string",
                    "description": "Matterport model ID from the tour URL (e.g., 'SxQL3iGyoDo')",
                },
                "max_images": {
                    "type": "integer",
                    "description": "Maximum number of still images to download (default: 40)",
                },
            },
            "required": ["client_id", "model_id"],
        },
    },
}

LIST_MATTERPORT_MODELS_TOOL = {
    "type": "function",
    "function": {
        "name": "list_matterport_models",
        "description": "List available Matterport 3D tours in the account.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of models to return (default: 50)",
                },
            },
            "required": [],
        },
    },
}

DOWNLOAD_MATTERPORT_ZIP_TOOL = {
    "type": "function",
    "function": {
        "name": "download_matterport_zip",
        "description": "Download Matterport assets from a zip link (typically from a "
        "Matterport email notification) and extract to a client's folder. "
        "Use this when you receive an email from Matterport with a download link.",
        "parameters": {
            "type": "object",
            "properties": {
                "client_id": {
                    "type": "integer",
                    "description": "The client's ID to route the files to",
                },
                "download_url": {
                    "type": "string",
                    "description": "The Matterport download URL from the email",
                },
                "email_body": {
                    "type": "string",
                    "description": "Optionally provide the full email body to auto-extract "
                    "the download URL",
                },
            },
            "required": ["client_id"],
        },
    },
}

# MLS Feeder Tool
UPDATE_MLS_FEEDER_TOOL = {
    "type": "function",
    "function": {
        "name": "update_mls_feeder",
        "description": "Update the MLS listing feeder with property details extracted from "
        "emails, documents, or conversations. The feeder accumulates information until "
        "ready for MLS submission. Use this whenever you learn new details about a "
        "property listing.",
        "parameters": {
            "type": "object",
            "properties": {
                "client_id": {
                    "type": "integer",
                    "description": "The client's ID",
                },
                "address": {
                    "type": "object",
                    "description": "Property address fields",
                    "properties": {
                        "street_number": {"type": "string"},
                        "street_name": {"type": "string"},
                        "street_suffix": {"type": "string"},
                        "unit_number": {"type": "string"},
                        "city": {"type": "string"},
                        "state": {"type": "string"},
                        "postal_code": {"type": "string"},
                    },
                },
                "property": {
                    "type": "object",
                    "description": "Property details",
                    "properties": {
                        "type": {
                            "type": "string",
                            "description": "Residential, Condo, Townhouse, Land, Multi-Family",
                        },
                        "year_built": {"type": "integer"},
                        "bedrooms": {"type": "integer"},
                        "bathrooms_full": {"type": "integer"},
                        "bathrooms_half": {"type": "integer"},
                        "living_area_sqft": {"type": "integer"},
                        "lot_size_sqft": {"type": "integer"},
                        "garage_spaces": {"type": "integer"},
                    },
                },
                "listing": {
                    "type": "object",
                    "description": "Listing information",
                    "properties": {
                        "price": {"type": "integer"},
                        "showing_instructions": {"type": "string"},
                    },
                },
                "marketing": {
                    "type": "object",
                    "description": "Marketing content",
                    "properties": {
                        "public_remarks": {
                            "type": "string",
                            "description": "Main listing description",
                        },
                        "private_remarks": {"type": "string", "description": "Agent-only notes"},
                        "virtual_tour_url": {"type": "string"},
                    },
                },
                "features": {
                    "type": "object",
                    "description": "Property features and amenities",
                    "properties": {
                        "heating": {"type": "array", "items": {"type": "string"}},
                        "cooling": {"type": "array", "items": {"type": "string"}},
                        "appliances": {"type": "array", "items": {"type": "string"}},
                        "interior_features": {"type": "array", "items": {"type": "string"}},
                        "exterior_features": {"type": "array", "items": {"type": "string"}},
                    },
                },
                "source": {
                    "type": "string",
                    "description": "Where this info came from (email, document, conversation)",
                },
            },
            "required": ["client_id"],
        },
    },
}

GET_MLS_FEEDER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_mls_feeder",
        "description": "Get the current MLS feeder status and contents for a client. Shows "
        "what property details have been collected and what's still missing.",
        "parameters": {
            "type": "object",
            "properties": {
                "client_id": {
                    "type": "integer",
                    "description": "The client's ID",
                },
            },
            "required": ["client_id"],
        },
    },
}

# Transaction Tracker Tools
GET_TRANSACTION_TOOL = {
    "type": "function",
    "function": {
        "name": "get_transaction",
        "description": "Get the current transaction tracker for a client. Shows deal status, "
        "dates, contacts, milestones, and documents for a property under contract.",
        "parameters": {
            "type": "object",
            "properties": {
                "client_id": {
                    "type": "integer",
                    "description": "The client's ID",
                },
            },
            "required": ["client_id"],
        },
    },
}

UPDATE_TRANSACTION_TOOL = {
    "type": "function",
    "function": {
        "name": "update_transaction",
        "description": "Update the transaction tracker with data extracted from emails, "
        "documents, or conversations. Use this when you learn key dates, contacts, or "
        "financial details about a deal.",
        "parameters": {
            "type": "object",
            "properties": {
                "client_id": {
                    "type": "integer",
                    "description": "The client's ID",
                },
                "property": {
                    "type": "object",
                    "description": "Property details",
                    "properties": {
                        "address": {"type": "string"},
                        "city": {"type": "string"},
                        "state": {"type": "string"},
                        "postal_code": {"type": "string"},
                        "year_built": {
                            "type": "integer",
                            "description": "Important for Lead Paint (pre-1978)",
                        },
                    },
                },
                "dates": {
                    "type": "object",
                    "description": "Key transaction dates",
                    "properties": {
                        "effective_date": {
                            "type": "string",
                            "description": "P&S effective date (ISO format)",
                        },
                        "inspection_deadline": {"type": "string"},
                        "emd_due_date": {
                            "type": "string",
                            "description": "Earnest money deposit due date",
                        },
                        "loan_application_deadline": {"type": "string"},
                        "appraisal_deadline": {"type": "string"},
                        "closing_date": {"type": "string"},
                        "walkthrough_date": {"type": "string"},
                        "financing_contingency": {"type": "string"},
                        "sale_of_property_contingency": {"type": "string"},
                    },
                },
                "financial": {
                    "type": "object",
                    "description": "Financial details",
                    "properties": {
                        "purchase_price": {"type": "integer"},
                        "emd_amount": {
                            "type": "integer",
                            "description": "Earnest money deposit amount",
                        },
                        "emd_delivered": {"type": "boolean"},
                        "loan_amount": {"type": "integer"},
                        "down_payment": {"type": "integer"},
                    },
                },
                "contacts": {
                    "type": "object",
                    "description": "People involved in the transaction",
                    "properties": {
                        "other_agent": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "email": {"type": "string"},
                                "phone": {"type": "string"},
                                "role": {
                                    "type": "string",
                                    "description": "buyer_agent or listing_agent",
                                },
                            },
                        },
                        "lender": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "email": {"type": "string"},
                                "phone": {"type": "string"},
                                "company": {"type": "string"},
                            },
                        },
                        "title_company": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "email": {"type": "string"},
                                "phone": {"type": "string"},
                                "attorney": {"type": "string"},
                            },
                        },
                        "inspector": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "email": {"type": "string"},
                                "phone": {"type": "string"},
                            },
                        },
                    },
                },
                "source": {
                    "type": "string",
                    "description": "Where this info came from (email, document, conversation)",
                },
            },
            "required": ["client_id"],
        },
    },
}

SET_MILESTONE_TOOL = {
    "type": "function",
    "function": {
        "name": "set_milestone",
        "description": "Mark a transaction milestone as completed. Use this when an email "
        "confirms a milestone was reached.",
        "parameters": {
            "type": "object",
            "properties": {
                "client_id": {
                    "type": "integer",
                    "description": "The client's ID",
                },
                "milestone": {
                    "type": "string",
                    "description": "Milestone to mark complete",
                    "enum": [
                        # Common milestones
                        "under_contract", "tc_email_sent", "docs_uploaded_dtr",
                        "inspection_scheduled", "inspection_completed", "emd_confirmed",
                        "title_company_chosen", "clear_to_close", "walkthrough_scheduled",
                        "walkthrough_completed", "closing_scheduled", "closed",
                        # Seller milestones
                        "mls_status_updated", "seller_disclosures_signed", "title_services_ordered",
                        "inspection_prep_email_sent", "utility_transfer_coordinated",
                        "closing_statement_reviewed", "closing_gift_reminder",
                        # Buyer milestones
                        "loan_app_received", "proof_of_funds_received",
                        "homeowners_insurance_quoted",
                        "appraisal_ordered", "appraisal_received", "closing_disclosure_received",
                        "closing_disclosure_reviewed", "home_warranty_decision",
                        "utilities_setup_reminder", "comps_prepped_for_appraisal",
                    ],
                },
                "date": {
                    "type": "string",
                    "description": "Date milestone was completed (ISO format, defaults to now)",
                },
            },
            "required": ["client_id", "milestone"],
        },
    },
}

MARK_DOCUMENT_RECEIVED_TOOL = {
    "type": "function",
    "function": {
        "name": "mark_document_received",
        "description": "Mark a transaction document as received. Use this when you learn a "
        "document was received.",
        "parameters": {
            "type": "object",
            "properties": {
                "client_id": {
                    "type": "integer",
                    "description": "The client's ID",
                },
                "document": {
                    "type": "string",
                    "description": "Document type",
                    "enum": [
                        "purchase_sale_agreement", "lead_paint_addendum", "deed",
                        "property_disclosures", "loan_application_letter", "proof_of_funds",
                        "appraisal", "inspection_report", "ica_repairs",
                        "closing_disclosure", "settlement_statement", "mls_spec_sheet",
                    ],
                },
                "date": {
                    "type": "string",
                    "description": "Date received (ISO format, defaults to now)",
                },
                "reviewed": {
                    "type": "boolean",
                    "description": "Whether the document has been reviewed",
                },
            },
            "required": ["client_id", "document"],
        },
    },
}

ADD_TRANSACTION_NOTE_TOOL = {
    "type": "function",
    "function": {
        "name": "add_transaction_note",
        "description": "Add a note to a transaction tracker. Use for observations, issues, "
        "or important info.",
        "parameters": {
            "type": "object",
            "properties": {
                "client_id": {
                    "type": "integer",
                    "description": "The client's ID",
                },
                "content": {
                    "type": "string",
                    "description": "Note content",
                },
                "source": {
                    "type": "string",
                    "description": "Where this came from (email, phone, etc.)",
                },
            },
            "required": ["client_id", "content"],
        },
    },
}

# Web Search Tool
WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web for current information. Use this to look up market "
        "data, property details, neighborhood info, mortgage rates, or anything you "
        "don't know.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum results to return (default: 5)",
                },
            },
            "required": ["query"],
        },
    },
}


# Tool sets for different agent roles
EMAIL_AGENT_TOOLS = [
    SEND_EMAIL_TOOL,
    CREATE_REMINDER_TOOL,
]

SCHEDULING_AGENT_TOOLS = [
    SCHEDULE_EVENT_TOOL,
    SEND_EMAIL_TOOL,
    CREATE_REMINDER_TOOL,
]

MLS_TOOLS = [
    SEARCH_LISTINGS_TOOL,
    GET_LISTING_DETAILS_TOOL,
    FIND_COMPS_TOOL,
    GET_MARKET_STATS_TOOL,
    UPDATE_MLS_FEEDER_TOOL,
    GET_MLS_FEEDER_TOOL,
]

TRANSACTION_TOOLS = [
    GET_TRANSACTION_TOOL,
    UPDATE_TRANSACTION_TOOL,
    SET_MILESTONE_TOOL,
    MARK_DOCUMENT_RECEIVED_TOOL,
    ADD_TRANSACTION_NOTE_TOOL,
]

WEB_TOOLS = [
    WEB_SEARCH_TOOL,
]

MATTERPORT_TOOLS = [
    GET_MATTERPORT_TOUR_TOOL,
    LIST_MATTERPORT_MODELS_TOOL,
    DOWNLOAD_MATTERPORT_ZIP_TOOL,
]

CLIENT_TOOLS = [
    CREATE_CLIENT_TOOL,
    LIST_CLIENTS_TOOL,
    READ_CLIENT_PROFILE_TOOL,
    UPDATE_CLIENT_PROFILE_TOOL,
    ADD_PENDING_ITEM_TOOL,
]

FULL_TOOL_SET = [
    SEND_EMAIL_TOOL,
    SCHEDULE_EVENT_TOOL,
    CREATE_REMINDER_TOOL,
    UPDATE_CLIENT_NOTES_TOOL,
    SEARCH_LISTINGS_TOOL,
    GET_LISTING_DETAILS_TOOL,
    FIND_COMPS_TOOL,
    GET_MARKET_STATS_TOOL,
    WEB_SEARCH_TOOL,
    CREATE_CLIENT_TOOL,
    LIST_CLIENTS_TOOL,
    READ_CLIENT_PROFILE_TOOL,
    UPDATE_CLIENT_PROFILE_TOOL,
    ADD_PENDING_ITEM_TOOL,
    GET_MATTERPORT_TOUR_TOOL,
    LIST_MATTERPORT_MODELS_TOOL,
    DOWNLOAD_MATTERPORT_ZIP_TOOL,
    UPDATE_MLS_FEEDER_TOOL,
    GET_MLS_FEEDER_TOOL,
    GET_TRANSACTION_TOOL,
    UPDATE_TRANSACTION_TOOL,
    SET_MILESTONE_TOOL,
    MARK_DOCUMENT_RECEIVED_TOOL,
    ADD_TRANSACTION_NOTE_TOOL,
]

# Extraction agent tools (MLS feeder + transaction tracker)
EXTRACTION_TOOLS = [
    UPDATE_MLS_FEEDER_TOOL,
    GET_MLS_FEEDER_TOOL,
    UPDATE_TRANSACTION_TOOL,
    SET_MILESTONE_TOOL,
    MARK_DOCUMENT_RECEIVED_TOOL,
    ADD_TRANSACTION_NOTE_TOOL,
]


def get_tools_for_agent(agent_type: str) -> list[dict[str, Any]]:
    """Get the appropriate tool set for an agent type."""
    tool_sets = {
        "email": EMAIL_AGENT_TOOLS,
        "scheduling": SCHEDULING_AGENT_TOOLS,
        "mls": MLS_TOOLS,
        "web": WEB_TOOLS,
        "matterport": MATTERPORT_TOOLS,
        "client": CLIENT_TOOLS,
        "transaction": TRANSACTION_TOOLS,
        "extraction": EXTRACTION_TOOLS,
        "full": FULL_TOOL_SET,
    }
    return tool_sets.get(agent_type, EMAIL_AGENT_TOOLS)
