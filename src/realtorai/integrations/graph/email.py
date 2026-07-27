"""Microsoft Graph API email operations."""

from datetime import datetime
from typing import Any

import httpx
import structlog

from realtorai.integrations.graph.auth import graph_auth

logger = structlog.get_logger()

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"


async def _get_client() -> httpx.AsyncClient:
    """Get an authenticated HTTP client."""
    token = await graph_auth.get_access_token()
    if not token:
        raise RuntimeError("Not authenticated with Microsoft Graph")

    return httpx.AsyncClient(
        base_url=GRAPH_BASE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        timeout=30.0,
    )


async def get_emails(
    folder: str = "inbox",
    unread_only: bool = False,
    since: datetime | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Get emails from a folder.

    Args:
        folder: Folder name (inbox, sentitems, drafts, etc.)
        unread_only: Only return unread emails
        since: Only return emails received after this time
        limit: Maximum number of emails to return

    Returns:
        List of email objects
    """
    async with await _get_client() as client:
        # Build filter query
        filters = []
        if unread_only:
            filters.append("isRead eq false")
        if since:
            filters.append(f"receivedDateTime ge {since.isoformat()}")

        filter_query = " and ".join(filters) if filters else None

        # Build request
        params: dict[str, Any] = {
            "$top": limit,
            "$orderby": "receivedDateTime desc",
            "$select": "id,conversationId,subject,from,toRecipients,receivedDateTime,"
            "isRead,bodyPreview,body,hasAttachments",
        }
        if filter_query:
            params["$filter"] = filter_query

        response = await client.get(f"/me/mailFolders/{folder}/messages", params=params)
        response.raise_for_status()

        data = response.json()
        emails = data.get("value", [])

        logger.info("emails_fetched", count=len(emails), folder=folder)
        return emails


async def get_email_thread(conversation_id: str, limit: int = 10) -> list[dict[str, Any]]:
    """Get all emails in a conversation thread.

    Args:
        conversation_id: The conversation/thread ID
        limit: Maximum number of messages to return

    Returns:
        List of email objects in the thread, oldest first
    """
    async with await _get_client() as client:
        params = {
            "$filter": f"conversationId eq '{conversation_id}'",
            "$orderby": "receivedDateTime asc",
            "$top": limit,
            "$select": "id,subject,from,toRecipients,receivedDateTime,body,bodyPreview",
        }

        response = await client.get("/me/messages", params=params)
        response.raise_for_status()

        data = response.json()
        messages = data.get("value", [])

        logger.debug("thread_fetched", conversation_id=conversation_id, count=len(messages))
        return messages


async def get_email(email_id: str) -> dict[str, Any]:
    """Get a single email by ID.

    Args:
        email_id: The email/message ID

    Returns:
        Email object
    """
    async with await _get_client() as client:
        response = await client.get(f"/me/messages/{email_id}")
        response.raise_for_status()
        return response.json()


async def send_email(
    to: str | list[str],
    subject: str,
    body: str,
    reply_to_id: str | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    is_html: bool = False,
) -> str:
    """Send an email.

    Args:
        to: Recipient email address(es)
        subject: Email subject
        body: Email body
        reply_to_id: Message ID if this is a reply
        cc: CC recipients
        bcc: BCC recipients
        is_html: Whether body is HTML

    Returns:
        Message ID of sent email
    """
    # Normalize recipients
    if isinstance(to, str):
        to = [to]

    to_recipients = [{"emailAddress": {"address": addr}} for addr in to]
    cc_recipients = [{"emailAddress": {"address": addr}} for addr in (cc or [])]
    bcc_recipients = [{"emailAddress": {"address": addr}} for addr in (bcc or [])]

    message = {
        "subject": subject,
        "body": {
            "contentType": "HTML" if is_html else "Text",
            "content": body,
        },
        "toRecipients": to_recipients,
    }

    if cc_recipients:
        message["ccRecipients"] = cc_recipients
    if bcc_recipients:
        message["bccRecipients"] = bcc_recipients

    async with await _get_client() as client:
        if reply_to_id:
            # Send as reply - Graph API reply endpoint just needs comment
            # The message object is optional and used to modify reply properties
            reply_payload = {"comment": body}
            response = await client.post(
                f"/me/messages/{reply_to_id}/reply",
                json=reply_payload,
            )
        else:
            # Send new email
            response = await client.post(
                "/me/sendMail",
                json={"message": message, "saveToSentItems": True},
            )

        response.raise_for_status()

        logger.info(
            "email_sent",
            to=to,
            subject=subject[:50],
            is_reply=bool(reply_to_id),
        )

        # Both sendMail and reply return empty bodies (202 Accepted)
        # No message ID is returned
        return ""


async def mark_as_read(email_id: str) -> None:
    """Mark an email as read.

    Args:
        email_id: The email/message ID
    """
    async with await _get_client() as client:
        response = await client.patch(
            f"/me/messages/{email_id}",
            json={"isRead": True},
        )
        response.raise_for_status()
        logger.debug("email_marked_read", email_id=email_id)


async def move_email(email_id: str, destination_folder: str) -> None:
    """Move an email to a different folder.

    Args:
        email_id: The email/message ID
        destination_folder: Destination folder name or ID
    """
    async with await _get_client() as client:
        # First, get the destination folder ID
        folders_response = await client.get(
            "/me/mailFolders",
            params={"$filter": f"displayName eq '{destination_folder}'"},
        )
        folders_response.raise_for_status()
        folders = folders_response.json().get("value", [])

        if not folders:
            raise ValueError(f"Folder not found: {destination_folder}")

        folder_id = folders[0]["id"]

        # Move the email
        response = await client.post(
            f"/me/messages/{email_id}/move",
            json={"destinationId": folder_id},
        )
        response.raise_for_status()

        logger.debug("email_moved", email_id=email_id, destination=destination_folder)


def strip_quoted_text(body: str, content_type: str = "text") -> str:
    """Strip quoted/forwarded text from email body.

    Handles common patterns from Gmail, Outlook, and other clients.

    Args:
        body: Email body content
        content_type: 'text' or 'html'

    Returns:
        Body with quoted text removed
    """
    import re

    if not body:
        return body

    if content_type.lower() == "html":
        # Remove Gmail quote blocks
        body = re.sub(r'<div class="gmail_quote">.*', '', body, flags=re.DOTALL | re.IGNORECASE)
        # Remove Outlook quote blocks
        body = re.sub(
            r'<blockquote[^>]*>.*?</blockquote>', '', body, flags=re.DOTALL | re.IGNORECASE
        )
        # Remove dividers and everything after
        body = re.sub(r'<hr[^>]*>.*', '', body, flags=re.DOTALL | re.IGNORECASE)
        # Strip HTML tags for cleaner text
        body = re.sub(r'<style[^>]*>.*?</style>', '', body, flags=re.DOTALL | re.IGNORECASE)
        body = re.sub(r'<[^>]+>', ' ', body)
        body = re.sub(r'\s+', ' ', body).strip()
    else:
        lines = body.split('\n')
        clean_lines = []
        for line in lines:
            # Stop at common quote markers
            stripped = line.strip()
            if stripped.startswith('>'):
                break
            if re.match(r'^On .+ wrote:$', stripped):
                break
            if re.match(r'^-{3,}\s*(Original Message|Forwarded message)', stripped, re.IGNORECASE):
                break
            if re.match(r'^From:\s+.+\s+Sent:\s+', stripped, re.IGNORECASE):
                break
            if stripped.startswith('________________________________'):
                break
            clean_lines.append(line)

        body = '\n'.join(clean_lines).strip()

    return body


def parse_email_address(email_obj: dict[str, Any]) -> tuple[str, str | None]:
    """Extract email address and name from Graph API email address object.

    Args:
        email_obj: Object like {"emailAddress": {"address": "...", "name": "..."}}

    Returns:
        Tuple of (email_address, display_name)
    """
    addr_obj = email_obj.get("emailAddress", {})
    return addr_obj.get("address", ""), addr_obj.get("name")


def format_email_for_display(email: dict[str, Any]) -> dict[str, Any]:
    """Format an email object for display in the UI.

    Args:
        email: Raw email object from Graph API

    Returns:
        Simplified email dict for UI
    """
    from_addr, from_name = parse_email_address(email.get("from", {}))

    # Get body and strip quoted text
    body_obj = email.get("body", {})
    raw_body = body_obj.get("content", "")
    content_type = body_obj.get("contentType", "text")
    clean_body = strip_quoted_text(raw_body, content_type)

    return {
        "id": email.get("id"),
        "conversation_id": email.get("conversationId"),
        "subject": email.get("subject", "(No subject)"),
        "from_email": from_addr,
        "from_name": from_name,
        "received_at": email.get("receivedDateTime"),
        "is_read": email.get("isRead", False),
        "preview": email.get("bodyPreview", ""),
        "body": clean_body,
        "has_attachments": email.get("hasAttachments", False),
    }
