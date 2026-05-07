"""Post-process LibreOffice SVG to fix broken <use xlink:href="#bitmap(N)"> references.

LibreOffice SVG export bug: bitmaps are embedded as <image> elements for the
first occurrence, but subsequent occurrences use <use xlink:href="#bitmap(N)"/>
where N is an internal hash that is never written as an id= attribute anywhere.
The <use> elements render as nothing in any standards-compliant renderer.

Fix strategy (no hash needed):
  For each <use transform="translate(tx,ty)" xlink:href="#bitmap(N)"/>:
    1. Read the sibling <rect class="BoundingBox" x=bx y=by width=bw height=bh/>.
    2. Locate the original <image> at coordinates (bx+tx, by+ty) — the translate
       encodes the vector FROM the desired position TO the original image position.
    3. Replace the <use> with a new <image x=bx y=by width=bw height=bh> carrying
       the same base64 href as the original.

This is verified 370/370 (100%) against the Ртищево-Кочетовка sample SVG.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from lxml import etree

logger = logging.getLogger(__name__)

_XLINK = "http://www.w3.org/1999/xlink"
_SVG_NS = "http://www.w3.org/2000/svg"
_BITMAP_REF = re.compile(r"^#bitmap\(\d+\)$")
_TRANSLATE = re.compile(r"translate\(\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*\)")


def _int_coord(val: Optional[str], default: int = 0) -> int:
    if val is None:
        return default
    try:
        return int(round(float(val)))
    except ValueError:
        return default


def fix_bitmap_refs(svg_in: str, svg_out: str) -> int:
    """Replace broken <use> bitmap refs with proper <image> copies.

    Reads svg_in, writes fixed SVG to svg_out.
    Returns the number of <use> elements successfully replaced.
    """
    parser = etree.XMLParser(huge_tree=True, remove_comments=False)
    tree = etree.parse(svg_in, parser)
    root = tree.getroot()

    # ── 1. Index all <image> elements by (x, y) ─────────────────────────────
    img_by_pos: dict[tuple[int, int], etree._Element] = {}
    for elem in root.iter(f"{{{_SVG_NS}}}image"):
        href = elem.get(f"{{{_XLINK}}}href") or elem.get("href") or ""
        if not href.startswith("data:"):
            continue
        x = _int_coord(elem.get("x"))
        y = _int_coord(elem.get("y"))
        img_by_pos[(x, y)] = elem

    logger.info("svg_postprocess: indexed %d embedded images", len(img_by_pos))

    # ── 2. Replace broken <use> elements ────────────────────────────────────
    replaced = 0
    skipped = 0

    for use_el in list(root.iter(f"{{{_SVG_NS}}}use")):
        href = use_el.get(f"{{{_XLINK}}}href") or use_el.get("href") or ""
        if not _BITMAP_REF.match(href):
            continue

        # Parse translate(tx, ty)
        transform = use_el.get("transform", "")
        m = _TRANSLATE.search(transform)
        if not m:
            skipped += 1
            continue
        tx = int(round(float(m.group(1))))
        ty = int(round(float(m.group(2))))

        # Find sibling BoundingBox rect in the same parent
        parent = use_el.getparent()
        if parent is None:
            skipped += 1
            continue

        bbox = None
        for child in parent:
            if child.get("class") == "BoundingBox":
                bbox = child
                break
        if bbox is None:
            skipped += 1
            continue

        bx = _int_coord(bbox.get("x"))
        by = _int_coord(bbox.get("y"))
        bw = _int_coord(bbox.get("width"))
        bh = _int_coord(bbox.get("height"))

        # Locate source image: the translate stores (orig_x - bx, orig_y - by)
        orig_x = bx + tx
        orig_y = by + ty
        src_img = img_by_pos.get((orig_x, orig_y))
        if src_img is None:
            skipped += 1
            continue

        # Build replacement <image> element
        img_href = src_img.get(f"{{{_XLINK}}}href") or src_img.get("href")
        new_img = etree.Element(f"{{{_SVG_NS}}}image")
        new_img.set("x", str(bx))
        new_img.set("y", str(by))
        new_img.set("width", str(bw))
        new_img.set("height", str(bh))
        new_img.set("preserveAspectRatio", "none")
        new_img.set(f"{{{_XLINK}}}href", img_href)

        # Swap use → image in-place
        idx = list(parent).index(use_el)
        parent.remove(use_el)
        parent.insert(idx, new_img)
        replaced += 1

    logger.info(
        "svg_postprocess: replaced %d <use> bitmap refs, skipped %d",
        replaced, skipped,
    )

    tree.write(svg_out, xml_declaration=True, encoding="UTF-8", pretty_print=False)
    return replaced
