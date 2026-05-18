"""Extract locomotive regime bands from the traction_modes band.

Algorithm (v2 — Y-group based):

1. Find all horizontal COLOURED lines (RGB saturation > threshold) in
   band + work_area.  Black / gray lines are excluded because they are
   frame/grid elements, not regime segments.
2. Group coloured lines by cy (±5 px tolerance) → each Y-group represents
   one locomotive series.  Expect 2–4 groups on a typical map.
3. For each Y-group, find label text(s) LEFT of work_area on the same Y
   (±15 px).  Multiple text pieces at same Y are merged left-to-right.
4. Y-groups without a matching label are discarded (warning issued).
5. Parse label: extract locomotive series name and train weight.
6. Find mode-label texts inside work_area at the same Y (±10 px).
   Match each line segment to the nearest mode text (≤ 500 px).
7. Classify mode from text content (выбег / тяг / тормож / unknown).
"""
from __future__ import annotations

import re
import statistics
from typing import Optional

from extractors.coordinate_ruler import CoordinateMapping
from models.export import LocomotiveRegimeBand, LocomotiveRegimeSegment
from models.markup import HorizontalBand, WorkArea
from models.parsed import ParsedShape

_WEIGHT_RE = re.compile(r"(\d+)\s*т\b", re.IGNORECASE)

_Y_GROUP_TOL_PX   = 5.0    # group coloured lines by cy (±)
_LABEL_Y_TOL_PX   = 15.0   # label-text Y tolerance vs group cy (±)
_MODE_Y_TOL_PX    = 10.0   # mode-text Y tolerance vs group cy (±)
_MIN_LINE_W_PX    = 10.0   # minimum width to count as a line
_MAX_MODE_DIST_PX = 500.0  # max X dist: mode text → line centre
_COLOR_SAT_THR    = 60     # max(R,G,B) − min(R,G,B) > this → coloured


def _cx(s: ParsedShape) -> float:
    return s.x + s.width / 2

def _cy(s: ParsedShape) -> float:
    return s.y + s.height / 2


def _is_horizontal_line(s: ParsedShape) -> bool:
    if s.width < _MIN_LINE_W_PX:
        return False
    if s.height < 0.1:
        return True
    return s.width >= s.height * 3.0


def _is_coloured(color: str | None) -> bool:
    """True if color has real chroma (not black / gray / white)."""
    if not color or len(color) != 7 or color[0] != "#":
        return False
    try:
        r = int(color[1:3], 16)
        g = int(color[3:5], 16)
        b = int(color[5:7], 16)
        return max(r, g, b) - min(r, g, b) > _COLOR_SAT_THR
    except ValueError:
        return False


def _effective_color(s: ParsedShape) -> str | None:
    return s.line_color or s.fill_color


def _mode_from_label(label: str) -> str:
    low = label.lower()
    if "выбег" in low:
        return "coasting"
    if "тяг" in low:
        return "traction"
    if "тормож" in low or "торм" in low:
        return "braking"
    return "unknown"


def _parse_loco_label(text: str) -> tuple[str, int | None]:
    """'2ТЭ116 2500т' → ('2ТЭ116', 2500).  Last weight match wins."""
    matches = list(_WEIGHT_RE.finditer(text))
    if matches:
        m = matches[-1]
        loco_type = text[: m.start()].strip().rstrip("-").strip()
        return loco_type or text.strip(), int(m.group(1))
    return text.strip(), None


def _group_by_y(
    lines: list[ParsedShape], tol: float
) -> list[list[ParsedShape]]:
    """Group shapes by cy, merging those within ±tol of the running mean."""
    if not lines:
        return []
    srt = sorted(lines, key=_cy)
    groups: list[list[ParsedShape]] = [[srt[0]]]
    for s in srt[1:]:
        g_cy = statistics.mean(_cy(x) for x in groups[-1])
        if abs(_cy(s) - g_cy) <= tol:
            groups[-1].append(s)
        else:
            groups.append([s])
    return groups


def extract_locomotive_regimes(
    shapes: list[ParsedShape],
    band: HorizontalBand,
    work_area: WorkArea,
    coord_mapping: CoordinateMapping,
) -> tuple[list[LocomotiveRegimeBand], dict, list[str]]:
    """Extract locomotive regime bands from the traction_modes band."""
    warnings: list[str] = []

    # ── Step 1: coloured horizontal lines in band + work_area ─────────────────
    coloured_lines = [
        s for s in shapes
        if band.y_top <= _cy(s) <= band.y_bottom
        and work_area.x_start <= _cx(s) <= work_area.x_end
        and _is_horizontal_line(s)
        and _is_coloured(_effective_color(s))
    ]

    if not coloured_lines:
        warnings.append(
            f"locomotive_regime: no coloured horizontal lines found in band "
            f"y={band.y_top:.0f}–{band.y_bottom:.0f}, "
            f"x={work_area.x_start:.0f}–{work_area.x_end:.0f} "
            f"(saturation threshold {_COLOR_SAT_THR}). "
            "Check band Y bounds, work_area X bounds, and that regime lines "
            "have non-gray line_color."
        )

    # ── Step 2: group by Y ────────────────────────────────────────────────────
    y_groups = _group_by_y(coloured_lines, _Y_GROUP_TOL_PX)

    # All text shapes left of work_area inside band
    texts_left = [
        s for s in shapes
        if s.text and s.text.strip()
        and band.y_top <= _cy(s) <= band.y_bottom
        and _cx(s) < work_area.x_start
    ]

    # Mode-text candidates inside work_area
    mode_texts_all = [
        s for s in shapes
        if s.text and s.text.strip()
        and band.y_top <= _cy(s) <= band.y_bottom
        and work_area.x_start <= _cx(s) <= work_area.x_end
    ]

    log: dict = {
        "y_groups_found":                   [],
        "rejected_y_groups_no_label":       [],
        "rejected_text_outside_work_area":  [],
        "label_parsing":                    [],
        "total_bands":                      0,
        "total_segments":                   0,
    }

    result_bands: list[LocomotiveRegimeBand] = []
    total_segs   = 0
    used_label_ids: set[int] = set()

    for group_lines in y_groups:
        group_cy = statistics.mean(_cy(s) for s in group_lines)

        # Step 3: find label texts at same Y, left of work_area
        label_texts = sorted(
            [s for s in texts_left if abs(_cy(s) - group_cy) <= _LABEL_Y_TOL_PX],
            key=_cx,
        )

        if not label_texts:
            log["rejected_y_groups_no_label"].append({
                "y":           round(group_cy, 1),
                "lines_count": len(group_lines),
            })
            warnings.append(
                f"locomotive_regime: Y-group at y≈{group_cy:.0f}px "
                f"({len(group_lines)} coloured lines) — no loco label left of "
                f"work_area (x_start={work_area.x_start:.0f}px, ±{_LABEL_Y_TOL_PX}px)"
            )
            continue

        for lt in label_texts:
            used_label_ids.add(id(lt))

        # Merge multiple text fragments (e.g. "2ТЭ116" + "2500т" in two shapes)
        raw_label = " ".join(s.text.strip() for s in label_texts)
        loco_type, weight = _parse_loco_label(raw_label)

        log["y_groups_found"].append({
            "y":           round(group_cy, 1),
            "lines_count": len(group_lines),
            "label":       raw_label,
            "weight":      weight,
        })
        log["label_parsing"].append({
            "raw":       raw_label,
            "loco_type": loco_type,
            "weight":    weight,
        })

        # Step 4: mode texts at same Y inside work_area
        group_mode_texts = [
            s for s in mode_texts_all
            if abs(_cy(s) - group_cy) <= _MODE_Y_TOL_PX
        ]

        # Step 5: build segments — one per line in this Y-group
        segments: list[LocomotiveRegimeSegment] = []
        for line in group_lines:
            color    = _effective_color(line) or "#888888"
            line_cx  = _cx(line)

            best_text: Optional[ParsedShape] = None
            best_dist = float("inf")
            for mt in group_mode_texts:
                d = abs(_cx(mt) - line_cx)
                if d < best_dist:
                    best_dist, best_text = d, mt

            if best_text is not None and best_dist <= _MAX_MODE_DIST_PX:
                mode_label = (best_text.text or "").strip()
            else:
                mode_label = ""
                warnings.append(
                    f"locomotive_regime: [{loco_type}] segment at x≈{line_cx:.0f}px "
                    f"has no mode text within {_MAX_MODE_DIST_PX}px"
                )

            mode_str = _mode_from_label(mode_label)
            s_m = round(coord_mapping.x_to_network_coord(line.x))
            e_m = round(coord_mapping.x_to_network_coord(line.x + line.width))
            if s_m > e_m:
                s_m, e_m = e_m, s_m

            segments.append(LocomotiveRegimeSegment(
                start=s_m, end=e_m,
                mode=mode_str,      # type: ignore[arg-type]
                mode_label=mode_label,
                color=color,
            ))

        segments.sort(key=lambda seg: seg.start)
        total_segs += len(segments)

        result_bands.append(LocomotiveRegimeBand(
            locomotive_type=loco_type,
            weight=weight,
            raw_label=raw_label,
            segments=segments,
        ))

    # ── Log: texts left of WA that were NOT used as a label ──────────────────
    log["rejected_text_outside_work_area"] = [
        {"text": s.text, "cx": round(_cx(s), 1), "cy": round(_cy(s), 1)}
        for s in texts_left
        if id(s) not in used_label_ids
    ]
    log["total_bands"]    = len(result_bands)
    log["total_segments"] = total_segs

    if not log["y_groups_found"]:
        warnings.append(
            "Полосы режимов тяги не распознаны автоматически. "
            "Используйте EditPanel для ручного добавления."
        )

    return result_bands, log, warnings
