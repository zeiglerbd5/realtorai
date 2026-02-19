"""Client markdown file management.

Each client has a profile.md file that both the agent and LLM can read/write.
The database stores metadata; the markdown file stores detailed content.
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from realtorai.config.settings import get_settings

logger = structlog.get_logger()


def slugify(name: str) -> str:
    """Convert a name to a filesystem-safe slug."""
    # Lowercase, replace spaces with hyphens, remove non-alphanumeric
    slug = name.lower().strip()
    slug = re.sub(r'\s+', '-', slug)
    slug = re.sub(r'[^a-z0-9\-]', '', slug)
    return slug or "unknown"


def get_client_dir(client_id: int, name: str) -> Path:
    """Get the directory path for a client."""
    settings = get_settings()
    slug = slugify(name)
    # Include ID to handle name collisions
    return settings.clients_dir / f"{client_id}-{slug}"


def get_client_file_path(client_id: int, name: str) -> Path:
    """Get the profile.md path for a client."""
    return get_client_dir(client_id, name) / "profile.md"


PROFILE_TEMPLATE = '''# {name}

**Status:** {status} | **Type:** {transaction_type}

## Contact
- Email: {email}
- Phone: {phone}

## Property
- Address: {property_address}
- Price: {price}

## Key Dates
- First contact: {created_date}

## Notes

'''


def create_client_file(
    client_id: int,
    name: str,
    email: str | None = None,
    phone: str | None = None,
    transaction_type: str | None = None,
    property_address: str | None = None,
    price: float | None = None,
    status: str = "lead",
) -> Path:
    """Create a new client profile markdown file.

    Returns the path to the created file.
    """
    client_dir = get_client_dir(client_id, name)
    client_dir.mkdir(parents=True, exist_ok=True)

    file_path = client_dir / "profile.md"

    # Format price
    price_str = f"${price:,.0f}" if price else "TBD"

    content = PROFILE_TEMPLATE.format(
        name=name,
        status=status.replace("_", " ").title(),
        transaction_type=(transaction_type or "TBD").title(),
        email=email or "—",
        phone=phone or "—",
        property_address=property_address or "TBD",
        price=price_str,
        created_date=datetime.now().strftime("%Y-%m-%d"),
    )

    file_path.write_text(content, encoding="utf-8")
    logger.info("client_file_created", client_id=client_id, path=str(file_path))

    return file_path


def read_client_file(client_id: int, name: str) -> str | None:
    """Read a client's profile markdown file.

    Returns the markdown content or None if file doesn't exist.
    """
    file_path = get_client_file_path(client_id, name)

    if not file_path.exists():
        logger.warning("client_file_not_found", client_id=client_id, path=str(file_path))
        return None

    return file_path.read_text(encoding="utf-8")


def write_client_file(client_id: int, name: str, content: str) -> bool:
    """Write content to a client's profile markdown file.

    Returns True if successful.
    """
    file_path = get_client_file_path(client_id, name)

    if not file_path.parent.exists():
        file_path.parent.mkdir(parents=True, exist_ok=True)

    file_path.write_text(content, encoding="utf-8")
    logger.info("client_file_written", client_id=client_id, path=str(file_path))

    return True


def append_note(
    client_id: int,
    name: str,
    note: str,
    source: str = "agent",
) -> bool:
    """Append a timestamped note to a client's profile.

    Args:
        client_id: The client's database ID
        name: The client's name (for file path)
        note: The note content
        source: Who added it - "agent" or "llm"

    Returns True if successful.
    """
    content = read_client_file(client_id, name)

    if content is None:
        logger.error("cannot_append_note_no_file", client_id=client_id)
        return False

    # Format the note entry
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    note_entry = f"\n### {timestamp} ({source})\n{note}\n"

    # Find the Notes section and append
    if "## Notes" in content:
        # Append after the Notes header
        content = content.rstrip() + note_entry
    else:
        # Add Notes section if missing
        content = content.rstrip() + "\n\n## Notes" + note_entry

    return write_client_file(client_id, name, content)


def update_client_header(
    client_id: int,
    name: str,
    status: str | None = None,
    transaction_type: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    property_address: str | None = None,
    price: float | None = None,
    room_id: int | None = None,
) -> bool:
    """Update the header section of a client's profile.

    Only updates fields that are provided (non-None).
    """
    content = read_client_file(client_id, name)

    if content is None:
        return False

    lines = content.split("\n")
    new_lines = []

    for line in lines:
        # Update status/type line
        if line.startswith("**Status:**") and (status or transaction_type):
            current_status = status.replace("_", " ").title() if status else None
            current_type = transaction_type.title() if transaction_type else None

            # Parse existing values
            if not current_status and "Status:" in line:
                match = re.search(r'\*\*Status:\*\* ([^|]+)', line)
                current_status = match.group(1).strip() if match else "Lead"
            if not current_type and "Type:" in line:
                match = re.search(r'\*\*Type:\*\* (\w+)', line)
                current_type = match.group(1).strip() if match else "TBD"

            room_part = ""
            if room_id:
                room_part = f" | **Room:** #{room_id}"
            elif "Room:" in line:
                match = re.search(r'\*\*Room:\*\* #?\d+', line)
                room_part = f" | {match.group(0)}" if match else ""

            line = f"**Status:** {current_status} | **Type:** {current_type}{room_part}"

        # Update contact fields
        elif line.startswith("- Email:") and email:
            line = f"- Email: {email}"
        elif line.startswith("- Phone:") and phone:
            line = f"- Phone: {phone}"

        # Update property fields
        elif line.startswith("- Address:") and property_address:
            line = f"- Address: {property_address}"
        elif line.startswith("- Price:") and price:
            line = f"- Price: ${price:,.0f}"

        new_lines.append(line)

    return write_client_file(client_id, name, "\n".join(new_lines))


def add_pending_item(
    client_id: int,
    name: str,
    description: str,
    waiting_on: str,
) -> bool:
    """Add a pending item checkbox to the client's profile."""
    content = read_client_file(client_id, name)

    if content is None:
        return False

    item = f"- [ ] {description} (waiting on {waiting_on})"

    if "## Pending Items" in content:
        # Find the section and append
        lines = content.split("\n")
        new_lines = []
        found_section = False

        for i, line in enumerate(lines):
            new_lines.append(line)
            if line.strip() == "## Pending Items":
                found_section = True
            elif found_section and (line.startswith("## ") or line.startswith("# ")):
                # Insert before next section
                new_lines.insert(-1, item)
                found_section = False

        if found_section:
            # Section was at end, append
            new_lines.append(item)

        content = "\n".join(new_lines)
    else:
        # Add Pending Items section
        content = content.rstrip() + f"\n\n## Pending Items\n{item}\n"

    return write_client_file(client_id, name, content)


def resolve_pending_item(
    client_id: int,
    name: str,
    description_pattern: str,
) -> bool:
    """Mark a pending item as complete (check the checkbox)."""
    content = read_client_file(client_id, name)

    if content is None:
        return False

    # Replace unchecked with checked for matching item
    pattern = re.compile(
        r'- \[ \] ' + re.escape(description_pattern).replace(r'\.\.\. ', '.*'),
        re.IGNORECASE
    )

    def replacer(match):
        return match.group(0).replace("- [ ]", "- [x]")

    new_content = pattern.sub(replacer, content)

    if new_content != content:
        return write_client_file(client_id, name, new_content)

    return False


def list_client_files() -> list[dict[str, Any]]:
    """List all client profile files.

    Returns a list of dicts with client_id, name, and path.
    """
    settings = get_settings()
    clients_dir = settings.clients_dir

    if not clients_dir.exists():
        return []

    results = []
    for client_dir in clients_dir.iterdir():
        if not client_dir.is_dir():
            continue

        profile = client_dir / "profile.md"
        if not profile.exists():
            continue

        # Parse client_id and name from directory name
        dir_name = client_dir.name
        match = re.match(r'(\d+)-(.+)', dir_name)
        if match:
            client_id = int(match.group(1))
            name_slug = match.group(2)

            # Try to get actual name from file
            content = profile.read_text(encoding="utf-8")
            name_match = re.match(r'# (.+)\n', content)
            name = name_match.group(1) if name_match else name_slug.replace("-", " ").title()

            results.append({
                "client_id": client_id,
                "name": name,
                "path": str(profile),
            })

    return results
