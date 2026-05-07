import logging
import math
import re
from typing import Optional

import vsdx
from lxml import etree

from models.parsed import ParsedDocument, ParsedShape

_VISIO_NS = "http://schemas.microsoft.com/office/visio/2012/main"


def _parse_visio_color(val: str) -> Optional[str]:
    """Convert a Visio cell value to a CSS hex color string, or None."""
    if not val:
        return None
    val = val.strip()
    # RGB(r,g,b) formula
    m = re.match(r"RGB\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", val, re.IGNORECASE)
    if m:
        r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"#{r:02x}{g:02x}{b:02x}"
    # #rrggbb
    if re.match(r"^#[0-9a-fA-F]{6}$", val):
        return val.lower()
    # 0xBBGGRR  — Windows COLORREF (stored as hex integer, BGR byte order)
    m = re.match(r"^0x([0-9a-fA-F]+)$", val, re.IGNORECASE)
    if m:
        n = int(m.group(1), 16)
        b = (n >> 16) & 0xFF
        g = (n >> 8) & 0xFF
        r = n & 0xFF
        return f"#{r:02x}{g:02x}{b:02x}"
    return None


def _cell_color(shape_xml: etree._Element, cell_name: str) -> Optional[str]:
    """Extract a color cell value from a Visio shape XML element."""
    ns = _VISIO_NS
    # Direct Cell child
    cell = shape_xml.find(f"{{{ns}}}Cell[@N='{cell_name}']")
    if cell is None:
        # Inside Section/Row/Cell
        for section in shape_xml.findall(f"{{{ns}}}Section"):
            for row in section.findall(f"{{{ns}}}Row"):
                cell = row.find(f"{{{ns}}}Cell[@N='{cell_name}']")
                if cell is not None:
                    break
            if cell is not None:
                break
    if cell is None:
        return None
    raw = cell.get("V") or cell.get("F") or ""
    return _parse_visio_color(raw)

logger = logging.getLogger(__name__)

PX_PER_INCH: float = 96.0


def _units_to_pixels(value: float, unit: str) -> float:
    """Convert a value in the given Visio display unit to pixels.

    Visio always stores geometry V-values in inches internally; this function
    is provided for edge cases where files deviate from that convention.
    """
    u = (unit or "IN").upper().strip()
    if u in ("IN", "INCH", "INCHES", ""):
        return value * PX_PER_INCH
    if u == "MM":
        return value * PX_PER_INCH / 25.4
    if u == "CM":
        return value * PX_PER_INCH / 2.54
    logger.warning('Unknown Visio unit "%s", falling back to inches', unit)
    return value * PX_PER_INCH


def _to_float(val, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _shape_local_bbox(
    shape: vsdx.Shape,
) -> tuple[float, float, float, float]:
    """Return (bx, by, width, height) in the parent's coordinate system.

    Handles both regular Shapes (PinX/PinY based) and Connectors
    (BeginX/EndX based) without relying on truthy `or` short-circuit
    that breaks when begin_x == 0.0.
    """
    begin_x = shape.begin_x
    begin_y = shape.begin_y
    end_x = shape.end_x
    end_y = shape.end_y

    if begin_x is not None and end_x is not None:
        # Connector / 1-D shape
        bx = min(begin_x, end_x)
        by = min(begin_y, end_y)
        w = abs(end_x - begin_x)
        h = abs(end_y - begin_y)
    else:
        pin_x = _to_float(shape.x)
        pin_y = _to_float(shape.y)
        loc_x = _to_float(shape.loc_x)
        loc_y = _to_float(shape.loc_y)
        bx = pin_x - loc_x
        by = pin_y - loc_y
        w = _to_float(shape.width)
        h = _to_float(shape.height)

    return bx, by, max(w, 0.0), max(h, 0.0)


def _detect_display_unit(page: vsdx.Page) -> str:
    """Read DrawingScale U attribute from PageSheet to log the display unit.

    Note: Visio always stores geometry V-values in inches regardless of
    what U says.  This is used for logging only.
    """
    ns = "http://schemas.microsoft.com/office/visio/2012/main"
    try:
        ps = page._pagesheet_xml
        cell = ps.find(f"{{{ns}}}Cell[@N='DrawingScale']")
        if cell is not None:
            return cell.get("U") or "IN"
    except Exception:
        pass
    return "IN"


def parse_vsdx(file_path: str) -> ParsedDocument:
    """Parse the first page of a .vsdx file into a flat list of ParsedShape."""
    vf = vsdx.VisioFile(file_path)
    page = vf.pages[0]

    display_unit = _detect_display_unit(page)

    # Page dimensions are in inches (Visio internal unit)
    page_w_in = _to_float(page.width)
    page_h_in = _to_float(page.height)
    scale = PX_PER_INCH

    page_w_px = round(page_w_in * scale, 2)
    page_h_px = round(page_h_in * scale, 2)

    logger.info(
        "Page: %.1f×%.1f px  (%.3f×%.3f in)  display_unit=%s",
        page_w_px, page_h_px, page_w_in, page_h_in, display_unit,
    )

    result: list[ParsedShape] = []

    def traverse(
        shape: vsdx.Shape,
        parent_id: Optional[str],
        offset_x: float,
        offset_y: float,
    ) -> None:
        bx, by, w, h = _shape_local_bbox(shape)

        # Absolute coords in Visio page space (origin bottom-left, y up)
        abs_x = offset_x + bx
        abs_y = offset_y + by

        # Convert to Konva space (origin top-left, y down)
        x_px = abs_x * scale
        y_px = (page_h_in - abs_y - h) * scale
        w_px = w * scale
        h_px = h * scale

        angle_rad = _to_float(shape.angle, 0.0)
        rotation_deg = round(math.degrees(angle_rad), 4)

        raw_text = shape.text or ""
        text: Optional[str] = raw_text.replace("\r", "").replace("\n", "").strip() or None

        line_color: Optional[str] = None
        fill_color: Optional[str] = None
        try:
            xml_el = shape.xml  # lxml element exposed by vsdx
            if xml_el is not None:
                line_color = _cell_color(xml_el, "LineColor")
                fill_color = _cell_color(xml_el, "FillForegnd")
        except Exception:
            pass

        result.append(
            ParsedShape(
                id=str(shape.ID),
                text=text,
                x=round(x_px, 3),
                y=round(y_px, 3),
                width=round(w_px, 3),
                height=round(h_px, 3),
                rotation=rotation_deg,
                shape_type=shape.shape_type or "Shape",
                parent_id=parent_id,
                line_color=line_color,
                fill_color=fill_color,
            )
        )

        if shape.shape_type == "Group":
            # Children coords are relative to group's lower-left corner
            child_offset_x = offset_x + bx
            child_offset_y = offset_y + by
            for child in shape.child_shapes:
                traverse(child, str(shape.ID), child_offset_x, child_offset_y)

    for top_shape in page.child_shapes:
        traverse(top_shape, None, 0.0, 0.0)

    group_count = sum(1 for s in result if s.shape_type == "Group")
    logger.info(
        "Parsed %d shapes total, %d groups", len(result), group_count
    )

    return ParsedDocument(
        page_width=page_w_px,
        page_height=page_h_px,
        shapes=result,
    )
