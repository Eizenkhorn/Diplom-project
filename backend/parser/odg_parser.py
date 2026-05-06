import logging
import math
import re
import zipfile
import xml.etree.ElementTree as ET
from typing import Optional

from models.parsed import ParsedDocument, ParsedShape

logger = logging.getLogger(__name__)

PX_PER_INCH = 96.0

_DRAW  = "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
_SVG   = "urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"
_TEXT  = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
_STYLE = "urn:oasis:names:tc:opendocument:xmlns:style:1.0"
_FO    = "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"

_SHAPE_TAGS     = {"rect", "custom-shape", "frame", "path", "polygon",
                   "polyline", "ellipse", "circle", "image", "object-ole"}
_CONNECTOR_TAGS = {"line", "connector"}


def _to_px(val: str) -> float:
    """Convert an ODF measurement string (e.g. '3.5cm', '21mm') to pixels."""
    if not val:
        return 0.0
    m = re.match(r"([-+]?\d*\.?\d+)\s*(cm|mm|in|pt|px)?", val.strip())
    if not m:
        return 0.0
    num = float(m.group(1))
    unit = (m.group(2) or "cm").lower()
    if unit == "cm":
        return num / 2.54 * PX_PER_INCH
    if unit == "mm":
        return num / 25.4 * PX_PER_INCH
    if unit == "in":
        return num * PX_PER_INCH
    if unit == "pt":
        return num / 72.0 * PX_PER_INCH
    return num  # px


def _parse_rotation(transform: str) -> float:
    """Extract rotation in degrees from a draw:transform attribute string."""
    m = re.search(r"rotate\s*\(\s*([-\d.eE+]+)", transform or "")
    return round(math.degrees(float(m.group(1))), 4) if m else 0.0


def _get_text(elem: ET.Element) -> Optional[str]:
    parts = []
    for p in elem.iter(f"{{{_TEXT}}}p"):
        t = (p.text or "") + "".join(s.text or "" for s in p)
        parts.append(t)
    raw = "".join(parts).replace("\r", "").replace("\n", "").strip()
    return raw or None


def parse_odg(odg_path: str) -> ParsedDocument:
    """Parse a LibreOffice Draw .odg file into a flat list of ParsedShape."""
    with zipfile.ZipFile(odg_path) as zf:
        content_root = ET.fromstring(zf.read("content.xml"))
        styles_root  = ET.fromstring(zf.read("styles.xml"))

    # Page dimensions come from fo:page-width / fo:page-height in styles.xml
    page_w_px = page_h_px = 0.0
    for pl in styles_root.iter(f"{{{_STYLE}}}page-layout-properties"):
        page_w_px = _to_px(pl.get(f"{{{_FO}}}page-width", ""))
        page_h_px = _to_px(pl.get(f"{{{_FO}}}page-height", ""))
        break

    logger.info("ODG page: %.1f×%.1f px", page_w_px, page_h_px)

    counter = [0]
    result: list[ParsedShape] = []

    def _next_id() -> str:
        counter[0] += 1
        return str(counter[0])

    def traverse(elem: ET.Element, parent_id: Optional[str]) -> None:
        ns  = elem.tag.split("}")[0][1:] if "}" in elem.tag else ""
        tag = elem.tag.split("}")[-1]  if "}" in elem.tag else elem.tag

        if ns != _DRAW:
            return

        if tag == "g":
            gid = _next_id()
            result.append(ParsedShape(
                id=gid, text=None,
                x=0.0, y=0.0, width=0.0, height=0.0,
                rotation=0.0, shape_type="Group", parent_id=parent_id,
            ))
            for child in elem:
                traverse(child, gid)
            return

        if tag in _SHAPE_TAGS:
            x   = _to_px(elem.get(f"{{{_SVG}}}x",     ""))
            y   = _to_px(elem.get(f"{{{_SVG}}}y",     ""))
            w   = _to_px(elem.get(f"{{{_SVG}}}width",  ""))
            h   = _to_px(elem.get(f"{{{_SVG}}}height", ""))
            rot = _parse_rotation(elem.get(f"{{{_DRAW}}}transform", ""))
            stype = "Foreign" if tag in ("image", "object-ole") else "Shape"
            result.append(ParsedShape(
                id=_next_id(), text=_get_text(elem),
                x=round(x, 3), y=round(y, 3),
                width=round(max(w, 0.0), 3), height=round(max(h, 0.0), 3),
                rotation=rot, shape_type=stype, parent_id=parent_id,
            ))
            return

        if tag in _CONNECTOR_TAGS:
            x1 = _to_px(elem.get(f"{{{_SVG}}}x1", ""))
            y1 = _to_px(elem.get(f"{{{_SVG}}}y1", ""))
            x2 = _to_px(elem.get(f"{{{_SVG}}}x2", ""))
            y2 = _to_px(elem.get(f"{{{_SVG}}}y2", ""))
            # Also accept bbox form (draw:connector uses svg:x/y/width/height)
            bx = _to_px(elem.get(f"{{{_SVG}}}x",     ""))
            by = _to_px(elem.get(f"{{{_SVG}}}y",     ""))
            bw = _to_px(elem.get(f"{{{_SVG}}}width",  ""))
            bh = _to_px(elem.get(f"{{{_SVG}}}height", ""))
            if x1 or x2:
                bx = min(x1, x2); by = min(y1, y2)
                bw = abs(x2 - x1); bh = abs(y2 - y1)
            rot = _parse_rotation(elem.get(f"{{{_DRAW}}}transform", ""))
            result.append(ParsedShape(
                id=_next_id(), text=_get_text(elem),
                x=round(bx, 3), y=round(by, 3),
                width=round(max(bw, 0.0), 3), height=round(max(bh, 0.0), 3),
                rotation=rot, shape_type="Connector", parent_id=parent_id,
            ))
            return

        # Other draw: elements — recurse to pick up nested shapes
        for child in elem:
            traverse(child, parent_id)

    for page in content_root.iter(f"{{{_DRAW}}}page"):
        for child in page:
            traverse(child, None)
        break  # first page only

    group_count = sum(1 for s in result if s.shape_type == "Group")
    logger.info("Parsed %d shapes from ODG (%d groups)", len(result), group_count)

    return ParsedDocument(
        page_width=round(page_w_px, 2),
        page_height=round(page_h_px, 2),
        shapes=result,
    )
