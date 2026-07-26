"""Live tax map with the parcel pinned — Maine GeoLibrary statewide parcels.

Maine publishes a statewide parcel layer (Maine GeoLibrary, "Maine Parcels
Organized Towns") as a public ArcGIS FeatureServer. This module finds the
subject parcel, pulls its polygon plus the surrounding parcels, and renders a
tax-map artifact locally: USGS topo basemap, parcel boundaries with lot
labels, the subject lot highlighted and pinned, caption bar with Map/Lot.

Lookup strategy (in order):
  1. Attribute match — TOWN + "22 PENOBSCOT%" against PROP_LOC. Precise and
     immune to geocoder drift.
  2. Buffered point query (25 m) around geocoded coordinates — the Census
     geocoder interpolates along street centerlines, so a bare point-in-
     polygon test usually lands in the right-of-way and misses.

The MAP_BK_LOT that comes back is cross-checked against the record's map/lot
from the tax card — a free consistency check between two official sources.

Coverage note: town participation in the statewide layer is voluntary. When a
town (or match) is missing, callers fall back to the manual pull sheet.
"""

import io
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import structlog
from pydantic import BaseModel, Field

from realtorai.integrations.spark.record_bridge import split_street_address

logger = structlog.get_logger()

PARCELS_LAYER = (
    "https://services1.arcgis.com/RbMX0mRVOFNTdLzd/arcgis/rest/services/"
    "Maine_Parcels_Organized_Towns/FeatureServer/10"
)
USGS_TOPO = "https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/export"

TIMEOUT = httpx.Timeout(45.0, connect=10.0)
USER_AGENT = "RealtorAI/0.1 (transaction-coordinator tooling; tax map)"

Feature = dict[str, Any]


class ParcelInfo(BaseModel):
    """Subject-parcel facts from the statewide layer."""

    town: str | None = None
    county: str | None = None
    state_id: str | None = None
    map_bk_lot: str | None = None
    prop_loc: str | None = None
    matched_by: str = "address"  # address | point
    source_org: str | None = None
    source_updated: str | None = None
    centroid_lat: float | None = None
    centroid_lon: float | None = None
    record_map_lot: str | None = None
    map_lot_matches_record: bool | None = None
    fetched_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    source: str = "Maine GeoLibrary — Maine Parcels Organized Towns"

    @property
    def summary(self) -> str:
        bits = [f"Map/Lot {self.map_bk_lot}" if self.map_bk_lot else "Map/Lot unknown"]
        if self.map_lot_matches_record is True:
            bits.append("matches tax-card map/lot")
        elif self.map_lot_matches_record is False:
            bits.append(f"DOES NOT match record map/lot {self.record_map_lot} - reconcile")
        return "; ".join(bits)


def normalize_map_lot(value: str | None) -> tuple[str, ...] | None:
    """Split a map/lot reference into comparable segments.

    '020/003/082', '20-03-082', and 'Map 20 Lot 3-82' all normalize to
    comparable digit groups with leading zeros stripped.
    """
    if not value:
        return None
    segments = [seg.lstrip("0") or "0" for seg in re.split(r"[^0-9A-Za-z]+", value) if seg]
    # Drop pure-word tokens ("Map", "Lot") that some towns embed
    segments = [seg for seg in segments if not seg.isalpha()]
    return tuple(segments) or None


def _where_for_address(town: str, street_address: str) -> str | None:
    parts = split_street_address(street_address)
    if not parts["street_number"] or not parts["street_name"]:
        return None
    prefix = f"{parts['street_number']} {parts['street_name']}".upper().replace("'", "''")
    town_escaped = town.replace("'", "''")
    return f"TOWN='{town_escaped}' AND UPPER(PROP_LOC) LIKE '{prefix}%'"


def _rings_bounds(rings: list[list[list[float]]]) -> tuple[float, float, float, float]:
    xs = [p[0] for ring in rings for p in ring]
    ys = [p[1] for ring in rings for p in ring]
    return min(xs), min(ys), max(xs), max(ys)


def _centroid(rings: list[list[list[float]]]) -> tuple[float, float]:
    x0, y0, x1, y1 = _rings_bounds(rings)
    return (x0 + x1) / 2, (y0 + y1) / 2


async def _query(client: httpx.AsyncClient, params: dict[str, Any]) -> list[Feature]:
    response = await client.get(f"{PARCELS_LAYER}/query", params=params)
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        raise RuntimeError(f"Parcel service error: {data['error']}")
    return data.get("features", [])


async def find_parcel(
    client: httpx.AsyncClient,
    town: str,
    street_address: str | None,
    lat: float | None = None,
    lon: float | None = None,
) -> tuple[Feature, str] | None:
    """Locate the subject parcel. Returns (feature, matched_by) or None."""
    common = {"outFields": "*", "returnGeometry": "true", "outSR": "4326", "f": "json"}

    if street_address:
        where = _where_for_address(town, street_address)
        if where:
            features = await _query(client, {"where": where, **common})
            if features:
                return features[0], "address"

    if lat is not None and lon is not None:
        features = await _query(
            client,
            {
                "geometry": f"{lon},{lat}",
                "geometryType": "esriGeometryPoint",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
                "distance": "25",
                "units": "esriSRUnit_Meter",
                **common,
            },
        )
        if features:
            number = (split_street_address(street_address or "")["street_number"] or "").upper()
            for feature in features:
                loc = (feature["attributes"].get("PROP_LOC") or "").upper()
                if number and loc.startswith(number + " "):
                    return feature, "point"
            return features[0], "point"
    return None


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


async def render_tax_map(
    client: httpx.AsyncClient,
    subject: Feature,
    out_path: Path,
    *,
    caption: str,
    size: tuple[int, int] = (1400, 1000),
) -> Path:
    """Basemap + neighborhood parcel lines + highlighted subject + pin."""
    width, height = size
    rings = subject["geometry"]["rings"]
    cx, cy = _centroid(rings)
    _, y0, _, y1 = _rings_bounds(rings)

    lat_cos = math.cos(math.radians(cy)) or 1.0
    dy = max((y1 - y0) * 2.2, 0.0011)
    dx = dy * (width / height) / lat_cos
    bbox = (cx - dx, cy - dy, cx + dx, cy + dy)

    neighbors = await _query(
        client,
        {
            "geometry": json.dumps(
                {
                    "xmin": bbox[0],
                    "ymin": bbox[1],
                    "xmax": bbox[2],
                    "ymax": bbox[3],
                    "spatialReference": {"wkid": 4326},
                }
            ),
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "MAP_BK_LOT",
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "json",
        },
    )

    basemap_bytes: bytes | None = None
    try:
        response = await client.get(
            USGS_TOPO,
            params={
                "bbox": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
                "bboxSR": "4326",
                "imageSR": "4326",
                "size": f"{width},{height}",
                "format": "png32",
                "f": "image",
            },
        )
        response.raise_for_status()
        basemap_bytes = response.content
    except Exception as e:
        logger.warning("tax_map_basemap_unavailable", error=str(e))

    from PIL import Image, ImageDraw, ImageFont

    if basemap_bytes:
        image = Image.open(io.BytesIO(basemap_bytes)).convert("RGBA")
    else:
        image = Image.new("RGBA", (width, height), (255, 255, 255, 255))

    def to_px(lon: float, lat: float) -> tuple[float, float]:
        return (
            (lon - bbox[0]) / (bbox[2] - bbox[0]) * width,
            (bbox[3] - lat) / (bbox[3] - bbox[1]) * height,
        )

    try:
        font = ImageFont.load_default(size=13)
        caption_font = ImageFont.load_default(size=17)
        small_font = ImageFont.load_default(size=13)
    except TypeError:  # older Pillow
        font = caption_font = small_font = ImageFont.load_default()

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    subject_lot = subject["attributes"].get("MAP_BK_LOT")

    for feature in neighbors:
        attrs = feature["attributes"]
        is_subject = attrs.get("MAP_BK_LOT") == subject_lot
        feature_rings = feature["geometry"]["rings"]
        for ring in feature_rings:
            points = [to_px(x, y) for x, y in ring]
            if is_subject:
                draw.polygon(points, fill=(220, 30, 30, 55), outline=(190, 0, 0, 255), width=5)
            else:
                draw.line(points + [points[0]], fill=(60, 60, 60, 210), width=2)
        # Lot label when the parcel is big enough on screen to stay readable
        pixel_points = [to_px(x, y) for ring in feature_rings for x, y in ring]
        w_px = max(p[0] for p in pixel_points) - min(p[0] for p in pixel_points)
        h_px = max(p[1] for p in pixel_points) - min(p[1] for p in pixel_points)
        map_bk_lot = attrs.get("MAP_BK_LOT") or ""
        if w_px * h_px > 2600 and map_bk_lot:
            label = map_bk_lot.split("-")[-1].lstrip("0") or map_bk_lot
            label_x = sum(p[0] for p in pixel_points) / len(pixel_points)
            label_y = sum(p[1] for p in pixel_points) / len(pixel_points)
            draw.text((label_x, label_y), label, fill=(30, 30, 120, 255), font=font, anchor="mm")

    image = Image.alpha_composite(image, overlay)
    draw = ImageDraw.Draw(image)

    pin_x, pin_y = to_px(cx, cy)
    red = (190, 0, 0, 255)
    draw.ellipse([pin_x - 14, pin_y - 14, pin_x + 14, pin_y + 14], outline=red, width=4)
    draw.line([pin_x, pin_y - 26, pin_x, pin_y + 26], fill=red, width=4)
    draw.line([pin_x - 26, pin_y, pin_x + 26, pin_y], fill=red, width=4)

    bar_height = 54
    bar = Image.new("RGBA", (width, bar_height), (255, 255, 255, 235))
    image.paste(bar, (0, height - bar_height), bar)
    draw = ImageDraw.Draw(image)
    attribution = (
        "Maine GeoLibrary parcels + USGS topo basemap | boundaries approximate - "
        "not a recorded survey"
    )
    draw.text((12, height - bar_height + 6), caption, fill=(0, 0, 0, 255), font=caption_font)
    draw.text(
        (12, height - bar_height + 32), attribution, fill=(90, 90, 90, 255), font=small_font
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(out_path)
    logger.info("tax_map_saved", path=str(out_path), neighbors=len(neighbors))
    return out_path


# ---------------------------------------------------------------------------
# Markdown + top-level fetch
# ---------------------------------------------------------------------------


def parcel_info_from_feature(
    feature: Feature, matched_by: str, record_map_lot: str | None
) -> ParcelInfo:
    """Assemble ParcelInfo from a service feature (pure, testable)."""
    attrs = feature["attributes"]
    lon, lat = _centroid(feature["geometry"]["rings"])
    map_bk_lot = attrs.get("MAP_BK_LOT")
    matches: bool | None = None
    if record_map_lot and map_bk_lot:
        matches = normalize_map_lot(record_map_lot) == normalize_map_lot(map_bk_lot)
    return ParcelInfo(
        town=attrs.get("TOWN"),
        county=attrs.get("COUNTY"),
        state_id=attrs.get("STATE_ID"),
        map_bk_lot=map_bk_lot,
        prop_loc=attrs.get("PROP_LOC"),
        matched_by=matched_by,
        source_org=attrs.get("FMSRCORG"),
        source_updated=attrs.get("FMUPDAT"),
        centroid_lat=lat,
        centroid_lon=lon,
        record_map_lot=record_map_lot,
        map_lot_matches_record=matches,
    )


def render_parcel_markdown(info: ParcelInfo) -> str:
    if info.map_lot_matches_record is True:
        match_line = "Matches the record's map/lot from the tax card. ✓"
    elif info.map_lot_matches_record is False:
        match_line = (
            f"⚠️ Does NOT match the record's map/lot ({info.record_map_lot}) — reconcile "
            "with the town assessor before filing."
        )
    else:
        match_line = "No record map/lot available to cross-check."
    lines = [
        f"# Tax Map — {info.prop_loc or 'parcel'}, {info.town or ''}".rstrip(", "),
        "",
        f"**{info.summary}**",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Map/Block/Lot | {info.map_bk_lot or 'n/a'} |",
        f"| State parcel ID | {info.state_id or 'n/a'} |",
        f"| Town / County | {info.town or 'n/a'} / {info.county or 'n/a'} |",
        f"| Situs (per layer) | {info.prop_loc or 'n/a'} |",
        f"| Matched by | {info.matched_by} |",
        f"| Layer source / updated | {info.source_org or 'n/a'} / {info.source_updated or 'n/a'} |",
        f"| Centroid | {info.centroid_lat:.6f}, {info.centroid_lon:.6f} |"
        if info.centroid_lat is not None
        else "| Centroid | n/a |",
        f"| Source | {info.source}, fetched {info.fetched_at.date().isoformat()} |",
        "",
        match_line,
        "",
        "Boundaries are the state digital parcel layer — approximate, not a recorded "
        "survey. For the official town tax map sheet, see the town assessor.",
    ]
    return "\n".join(lines) + "\n"


async def fetch_tax_map(
    street_address: str,
    town: str,
    out_dir: Path,
    *,
    record_map_lot: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> tuple[ParcelInfo, Path, Path]:
    """Full pull: locate parcel -> pinned tax map + markdown + JSON.

    Raises if the parcel can't be found (town not in the statewide layer,
    no address match) — callers fall back to the manual pull sheet.
    """
    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
        if lat is None or lon is None:
            try:
                from realtorai.integrations.fema_flood import geocode_address

                lat, lon, _ = await geocode_address(f"{street_address}, {town}, ME")
            except Exception:
                lat = lon = None  # address match may still succeed

        found = await find_parcel(client, town, street_address, lat=lat, lon=lon)
        if found is None:
            raise ValueError(
                f"Parcel not found in the statewide layer for {street_address}, {town}"
            )
        feature, matched_by = found
        info = parcel_info_from_feature(feature, matched_by, record_map_lot)

        out_dir.mkdir(parents=True, exist_ok=True)
        caption = f"{info.prop_loc or street_address}, {info.town} - {info.summary}".replace(
            "—", "-"
        )
        map_path = await render_tax_map(
            client, feature, out_dir / "tax_map.png", caption=caption
        )

    md_path = out_dir / "tax_map.md"
    md_path.write_text(render_parcel_markdown(info))
    (out_dir / "parcel.json").write_text(info.model_dump_json(indent=2))

    logger.info(
        "tax_map_fetched",
        map_lot=info.map_bk_lot,
        matched_by=matched_by,
        matches_record=info.map_lot_matches_record,
    )
    return info, map_path, md_path
