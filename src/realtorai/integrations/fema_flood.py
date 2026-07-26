"""Live FEMA flood determination + pinned flood map — no browser required.

Replaces the manual msc.fema.gov lookup with three keyless government APIs:

  1. Census Bureau geocoder      — address -> lat/lon
  2. FEMA NFHL layer 28 query    — flood zone, subtype, SFHA flag, static BFE
     FEMA NFHL layer 3 query     — FIRM panel + effective date
  3. NFHL map export (+ USGS topo basemap underlay, composited locally with
     a pin and caption) — the "flood map with the parcel pinned" artifact

Total wall time is a few seconds per property vs. minutes of browser
automation. All endpoints are public government services; be polite.
"""

import io
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()

CENSUS_GEOCODER = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
NFHL_BASE = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer"
USGS_TOPO = "https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/export"

FLOOD_ZONE_LAYER = 28  # Flood Hazard Zones
FIRM_PANEL_LAYER = 3   # FIRM Panels
# Panel labels, BFE lines, cross sections, zone polygons — the useful overlay set
EXPORT_LAYERS = "show:3,16,20,27,28"

TIMEOUT = httpx.Timeout(30.0, connect=10.0)
USER_AGENT = "RealtorAI/0.1 (transaction-coordinator tooling; flood determination)"


class FloodDetermination(BaseModel):
    """Point flood determination from the FEMA National Flood Hazard Layer."""

    address: str
    matched_address: str | None = None
    latitude: float
    longitude: float
    flood_zone: str | None = None       # X, AE, A, VE, ...
    zone_subtype: str | None = None     # e.g. "AREA OF MINIMAL FLOOD HAZARD"
    in_sfha: bool | None = None         # Special Flood Hazard Area
    static_bfe: float | None = None     # Base Flood Elevation where defined
    firm_panel: str | None = None
    panel_effective_date: str | None = None  # ISO date
    fetched_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    source: str = "FEMA NFHL (hazards.fema.gov)"

    @property
    def summary(self) -> str:
        zone = f"Zone {self.flood_zone}" if self.flood_zone else "Zone unknown"
        if self.zone_subtype:
            zone += f" — {self.zone_subtype.title()}"
        sfha = (
            "IN a Special Flood Hazard Area"
            if self.in_sfha
            else "not in a Special Flood Hazard Area"
            if self.in_sfha is not None
            else "SFHA status unknown"
        )
        return f"{zone}; {sfha}"


# ---------------------------------------------------------------------------
# API calls
# ---------------------------------------------------------------------------


async def geocode_address(address: str) -> tuple[float, float, str]:
    """Address -> (lat, lon, matched_address) via the Census geocoder."""
    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
        response = await client.get(
            CENSUS_GEOCODER,
            params={"address": address, "benchmark": "Public_AR_Current", "format": "json"},
        )
        response.raise_for_status()
        matches = response.json()["result"]["addressMatches"]
    if not matches:
        raise ValueError(f"Census geocoder found no match for: {address}")
    match = matches[0]
    coords = match["coordinates"]
    return coords["y"], coords["x"], match.get("matchedAddress", address)


async def _query_point(
    client: httpx.AsyncClient, layer: int, lat: float, lon: float, out_fields: str
) -> dict[str, Any] | None:
    """Query one NFHL layer at a point; returns first feature's attributes."""
    response = await client.get(
        f"{NFHL_BASE}/{layer}/query",
        params={
            "geometry": f"{lon},{lat}",
            "geometryType": "esriGeometryPoint",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": out_fields,
            "returnGeometry": "false",
            "f": "json",
        },
    )
    response.raise_for_status()
    features = response.json().get("features", [])
    return features[0]["attributes"] if features else None


def _epoch_ms_to_iso(value: Any) -> str | None:
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC).date().isoformat()


def determination_from_attrs(
    address: str,
    matched: str | None,
    lat: float,
    lon: float,
    zone_attrs: dict[str, Any] | None,
    panel_attrs: dict[str, Any] | None,
) -> FloodDetermination:
    """Assemble a FloodDetermination from raw NFHL attributes (pure, testable)."""
    zone_attrs = zone_attrs or {}
    panel_attrs = panel_attrs or {}
    static_bfe = zone_attrs.get("STATIC_BFE")
    if static_bfe in (None, -9999, -9999.0):
        static_bfe = None
    sfha = zone_attrs.get("SFHA_TF")
    return FloodDetermination(
        address=address,
        matched_address=matched,
        latitude=lat,
        longitude=lon,
        flood_zone=zone_attrs.get("FLD_ZONE"),
        zone_subtype=zone_attrs.get("ZONE_SUBTY") or None,
        in_sfha={"T": True, "F": False}.get(sfha),
        static_bfe=static_bfe,
        firm_panel=panel_attrs.get("FIRM_PAN"),
        panel_effective_date=_epoch_ms_to_iso(panel_attrs.get("EFF_DATE")),
    )


# ---------------------------------------------------------------------------
# Map rendering
# ---------------------------------------------------------------------------


async def export_flood_map(
    determination: FloodDetermination,
    out_path: Path,
    *,
    buffer_deg: float = 0.004,
    size: tuple[int, int] = (1200, 900),
) -> Path:
    """Render the pinned flood map: USGS topo basemap + NFHL overlay + caption.

    Falls back to the plain NFHL export if Pillow or the basemap is
    unavailable — the artifact is still produced either way.
    """
    lat, lon = determination.latitude, determination.longitude
    dx = buffer_deg
    dy = buffer_deg * size[1] / size[0]
    bbox = f"{lon - dx},{lat - dy},{lon + dx},{lat + dy}"
    common = {
        "bbox": bbox,
        "bboxSR": "4326",
        "imageSR": "4326",
        "size": f"{size[0]},{size[1]}",
        "format": "png32",
        "f": "image",
    }

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(60.0, connect=10.0), headers={"User-Agent": USER_AGENT}
    ) as client:
        nfhl = await client.get(
            f"{NFHL_BASE}/export",
            params={**common, "layers": EXPORT_LAYERS, "transparent": "true"},
        )
        nfhl.raise_for_status()
        basemap_bytes: bytes | None = None
        try:
            basemap = await client.get(USGS_TOPO, params=common)
            basemap.raise_for_status()
            basemap_bytes = basemap.content
        except Exception as e:
            logger.warning("flood_basemap_unavailable", error=str(e))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        out_path.write_bytes(nfhl.content)
        logger.info("flood_map_saved", path=str(out_path), composite=False)
        return out_path

    overlay = Image.open(io.BytesIO(nfhl.content)).convert("RGBA")
    if basemap_bytes:
        image = Image.open(io.BytesIO(basemap_bytes)).convert("RGBA")
        overlay.putalpha(overlay.getchannel("A").point(lambda a: int(a * 0.65)))
        image = Image.alpha_composite(image, overlay)
    else:
        image = overlay

    # Pin: the property is the exact center of the bbox by construction
    draw = ImageDraw.Draw(image)
    cx, cy = image.width // 2, image.height // 2
    r = 18
    red = (200, 0, 0, 255)
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=red, width=5)
    draw.line([cx, cy - r - 14, cx, cy + r + 14], fill=red, width=5)
    draw.line([cx - r - 14, cy, cx + r + 14, cy], fill=red, width=5)

    # Caption bar. PIL's default bitmap font lacks em-dash/middot glyphs, so
    # keep the drawn text ASCII.
    caption = (
        f"{determination.matched_address or determination.address} - "
        f"{determination.summary}"
    ).replace("—", "-")
    panel_line = (
        f"FIRM panel {determination.firm_panel} eff. {determination.panel_effective_date}"
        if determination.firm_panel
        else "FIRM panel: n/a"
    )
    attribution = f"{panel_line} | FEMA NFHL + USGS topo basemap | not an official FIRMette"
    try:
        font = ImageFont.load_default(size=17)
        small = ImageFont.load_default(size=13)
    except TypeError:  # older Pillow
        font = small = ImageFont.load_default()
    bar_height = 54
    bar = Image.new("RGBA", (image.width, bar_height), (255, 255, 255, 235))
    image.paste(bar, (0, image.height - bar_height), bar)
    draw = ImageDraw.Draw(image)
    draw.text((12, image.height - bar_height + 6), caption, fill=(0, 0, 0, 255), font=font)
    draw.text((12, image.height - bar_height + 32), attribution, fill=(90, 90, 90, 255), font=small)

    image.convert("RGB").save(out_path)
    logger.info("flood_map_saved", path=str(out_path), composite=True)
    return out_path


# ---------------------------------------------------------------------------
# Markdown + top-level fetch
# ---------------------------------------------------------------------------


def render_flood_markdown(determination: FloodDetermination) -> str:
    det = determination
    lines = [
        f"# Flood Determination — {det.matched_address or det.address}",
        "",
        f"**{det.summary}**",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Flood zone | {det.flood_zone or 'n/a'} |",
        f"| Zone subtype | {det.zone_subtype or 'n/a'} |",
        "| Special Flood Hazard Area | "
        + (
            "YES — flag flood insurance disclosure"
            if det.in_sfha
            else "No"
            if det.in_sfha is not None
            else "unknown"
        )
        + " |",
        f"| Static BFE | {det.static_bfe if det.static_bfe is not None else 'n/a'} |",
        f"| FIRM panel | {det.firm_panel or 'n/a'} |",
        f"| Panel effective date | {det.panel_effective_date or 'n/a'} |",
        f"| Coordinates | {det.latitude:.6f}, {det.longitude:.6f} |",
        f"| Source | {det.source}, fetched {det.fetched_at.date().isoformat()} |",
        "",
        "Automated point determination from the National Flood Hazard Layer. "
        "For lender/insurance purposes, generate the official FIRMette at "
        "msc.fema.gov using the FIRM panel above.",
    ]
    return "\n".join(lines) + "\n"


async def fetch_flood_determination(
    address: str, out_dir: Path
) -> tuple[FloodDetermination, Path, Path]:
    """Full pull: geocode -> zone + panel -> pinned map + markdown + JSON.

    Returns (determination, map_png_path, markdown_path). Raises on failure —
    callers fall back to the manual pull sheet.
    """
    lat, lon, matched = await geocode_address(address)

    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
        zone_attrs = await _query_point(
            client, FLOOD_ZONE_LAYER, lat, lon, "FLD_ZONE,ZONE_SUBTY,SFHA_TF,STATIC_BFE"
        )
        panel_attrs = await _query_point(client, FIRM_PANEL_LAYER, lat, lon, "FIRM_PAN,EFF_DATE")

    determination = determination_from_attrs(address, matched, lat, lon, zone_attrs, panel_attrs)

    out_dir.mkdir(parents=True, exist_ok=True)
    map_path = await export_flood_map(determination, out_dir / "flood_map.png")
    md_path = out_dir / "flood_determination.md"
    md_path.write_text(render_flood_markdown(determination))
    (out_dir / "flood_determination.json").write_text(determination.model_dump_json(indent=2))

    logger.info(
        "flood_determination_fetched",
        address=matched,
        zone=determination.flood_zone,
        sfha=determination.in_sfha,
        panel=determination.firm_panel,
    )
    return determination, map_path, md_path
