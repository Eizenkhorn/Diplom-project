"""Extract locomotive regime bands from a marked traction_modes band."""
from __future__ import annotations

import re
from typing import Optional

from extractors.coordinate_ruler import CoordinateMapping
from models.export import LocomotiveRegimeBand, LocomotiveRegimeSegment
from models.markup import HorizontalBand, WorkArea
from models.parsed import ParsedShape

# "2500т", "6300т", "7100 т" — last weight occurrence in label
_WEIGHT_RE = re.compile(r"(\d+)\s*т\b", re.IGNORECASE)

_Y_TRACK_TOL_PX = 10.0      # cy of line/text must be within ±this of loco label cy
_MIN_LINE_WIDTH_PX = 10.0   # minimum width to treat a shape as a line segment
_MAX_LABEL_DIST_PX = 500.0  # max X distance: mode text → line centre


def _cx(s: ParsedShape) -> float:
    return s.x + s.width / 2


def _cy(s: ParsedShape) -> float:
    return s.y + s.height / 2


def _is_horizontal_line(s: ParsedShape) -> bool:
    """True for shapes that are clearly horizontal (wide, very short)."""
    if s.width < _MIN_LINE_WIDTH_PX:
        return False
    if s.height < 0.1:
        return True   # zero-height degenerate = line
    return s.width >= s.height * 3.0


def _effective_color(s: ParsedShape) -> Optional[str]:
    return s.line_color or s.fill_color


def _mode_from_label(label: str) -> str:
    lower = label.lower()
    if "выбег" in lower:
        return "coasting"
    if "тяг" in lower:
        return "traction"
    if "тормож" in lower or "торм" in lower:
        return "braking"
    return "unknown"


def _parse_loco_label(text: str) -> tuple[str, Optional[int]]:
    """Parse "2ТЭ116 2500т" → ("2ТЭ116", 2500).

    Uses the LAST weight match so "2x2ТЭ116-6300т" → ("2x2ТЭ116", 6300).
    """
    matches = list(_WEIGHT_RE.finditer(text))
    if matches:
        m = matches[-1]
        weight = int(m.group(1))
        loco_type = text[: m.start()].strip().rstrip("-").strip()
        return loco_type or text.strip(), weight
    return text.strip(), None


def extract_locomotive_regimes(
    shapes: list[ParsedShape],
    band: HorizontalBand,
    work_area: WorkArea,
    coord_mapping: CoordinateMapping,
) -> tuple[list[LocomotiveRegimeBand], dict, list[str]]:
    """Extract locomotive regime bands from the traction_modes band.

    Algorithm:
    1. Find text shapes LEFT of work_area (cx < x_start) within band Y →
       each is a locomotive label defining a horizontal Y-track.
    2. For each Y-track (±_Y_TRACK_TOL_PX):
       a. Collect horizontal coloured line shapes inside work_area.
       b. Collect mode-label texts inside work_area.
       c. For each line, match nearest mode text by X distance.
       d. Convert line X-extents → network metres; classify mode by text.
    3. Parse locomotive_type / weight from raw label.

    Returns (bands, log_dict, warnings).
    """
    warnings: list[str] = []

    # ── 1. Loco labels ────────────────────────────────────────────────────────
    loco_labels = sorted(
        [
            s for s in shapes
            if s.text
            and band.y_top <= _cy(s) <= band.y_bottom
            and _cx(s) < work_area.x_start
        ],
        key=_cy,
    )

    # ── 2. All horizontal coloured lines inside work area ─────────────────────
    line_shapes = [
        s for s in shapes
        if band.y_top <= _cy(s) <= band.y_bottom
        and work_area.x_start <= _cx(s) <= work_area.x_end
        and _is_horizontal_line(s)
        and _effective_color(s) is not None
    ]

    # ── 3. Mode-text candidates inside work area ──────────────────────────────
    mode_texts = [
        s for s in shapes
        if s.text
        and band.y_top <= _cy(s) <= band.y_bottom
        and work_area.x_start <= _cx(s) <= work_area.x_end
    ]

    log: dict = {
        "loco_labels_found": len(loco_labels),
        "line_segments_total": len(line_shapes),
        "mode_texts_found": len(mode_texts),
        "bands_extracted": 0,
        "total_segments": 0,
        "loco_labels_raw": [s.text for s in loco_labels],
        "per_band": [],
    }

    if not loco_labels:
        warnings.append(
            f"locomotive_regime: no loco labels found left of work_area "
            f"(x_start={work_area.x_start:.0f}px) "
            f"in band y={band.y_top:.0f}–{band.y_bottom:.0f}"
        )
        return [], log, warnings

    result_bands: list[LocomotiveRegimeBand] = []
    total_segs = 0

    for loco_shape in loco_labels:
        loco_cy = _cy(loco_shape)
        raw_label = (loco_shape.text or "").strip()
        loco_type, weight = _parse_loco_label(raw_label)

        track_lines = [
            s for s in line_shapes
            if abs(_cy(s) - loco_cy) <= _Y_TRACK_TOL_PX
        ]
        track_mode_texts = [
            s for s in mode_texts
            if abs(_cy(s) - loco_cy) <= _Y_TRACK_TOL_PX
        ]

        if not track_lines:
            warnings.append(
                f"locomotive_regime: no line segments at y≈{loco_cy:.0f}px "
                f"for \"{raw_label}\" (±{_Y_TRACK_TOL_PX}px)"
            )
            result_bands.append(LocomotiveRegimeBand(
                locomotive_type=loco_type, weight=weight,
                raw_label=raw_label, segments=[],
            ))
            log["per_band"].append(
                {"label": raw_label, "lines": 0, "segments": 0, "mode_texts": 0}
            )
            continue

        segments: list[LocomotiveRegimeSegment] = []

        for line in track_lines:
            color = _effective_color(line) or "#000000"
            line_cx = _cx(line)

            # Nearest mode text by X
            best_text: Optional[ParsedShape] = None
            best_dist = float("inf")
            for mt in track_mode_texts:
                d = abs(_cx(mt) - line_cx)
                if d < best_dist:
                    best_dist = d
                    best_text = mt

            mode_label = ""
            if best_text is not None and best_dist <= _MAX_LABEL_DIST_PX:
                mode_label = (best_text.text or "").strip()

            mode_str = _mode_from_label(mode_label)

            start_m = round(coord_mapping.x_to_network_coord(line.x))
            end_m = round(coord_mapping.x_to_network_coord(line.x + line.width))
            if start_m > end_m:
                start_m, end_m = end_m, start_m

            segments.append(LocomotiveRegimeSegment(
                start=start_m,
                end=end_m,
                mode=mode_str,  # type: ignore[arg-type]
                mode_label=mode_label,
                color=color,
            ))

        segments.sort(key=lambda seg: seg.start)
        total_segs += len(segments)

        result_bands.append(LocomotiveRegimeBand(
            locomotive_type=loco_type, weight=weight,
            raw_label=raw_label, segments=segments,
        ))
        log["per_band"].append({
            "label": raw_label,
            "lines": len(track_lines),
            "segments": len(segments),
            "mode_texts": len(track_mode_texts),
        })

    log["bands_extracted"] = len(result_bands)
    log["total_segments"] = total_segs

    return result_bands, log, warnings
