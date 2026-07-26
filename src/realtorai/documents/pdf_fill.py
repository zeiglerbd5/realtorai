"""Shared AcroForm fill: write values onto every matching field dict.

Used by the Transaction Worksheet and Master Information Sheet fillers.
Values are written directly onto AcroForm field dictionaries AND page widget
annotations — some agency templates (the 2025 TW) carry damaged xrefs that
clone into two copies of each field, and viewers draw the annotation copy.
`NeedAppearances` is set so viewers regenerate the visual text.

Checkbox values are passed as appearance-state names ("/On", "/Off", "/Yes");
everything else is written as text.
"""

from pathlib import Path

import structlog

logger = structlog.get_logger()


def fill_acroform(template_path: Path, values: dict[str, str], out_path: Path) -> int:
    """Fill `template_path` with `values` and write to `out_path`.

    Returns the number of distinct fields written.
    """
    from pypdf import PdfWriter
    from pypdf.generic import BooleanObject, NameObject, TextStringObject

    writer = PdfWriter(clone_from=str(template_path))
    acroform = writer._root_object["/AcroForm"]

    candidates: list = list(acroform["/Fields"])
    for page in writer.pages:
        candidates.extend(page.get("/Annots") or [])

    written: set[int] = set()
    for ref in candidates:
        try:
            field = ref.get_object()
            name = str(field.get("/T", ""))
            if name not in values or id(field) in written:
                continue
            value = values[name]
            if field.get("/FT") == "/Btn":
                state = NameObject(value if value.startswith("/") else f"/{value}")
                field[NameObject("/V")] = state
                field[NameObject("/AS")] = state
            else:
                field[NameObject("/V")] = TextStringObject(value)
                if "/AP" in field:
                    del field[NameObject("/AP")]
            written.add(id(field))
        except Exception as e:  # broken widget refs — skip, keep going
            logger.warning("acroform_field_write_failed", error=str(e))
    acroform[NameObject("/NeedAppearances")] = BooleanObject(True)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        writer.write(f)
    logger.info(
        "acroform_filled",
        template=template_path.name,
        out=str(out_path),
        fields_matched=len(written),
    )
    return len(written)
