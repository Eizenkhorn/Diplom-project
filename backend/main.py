import logging
import mimetypes
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from models.markup import BandType, HorizontalBand, MarkPoint, SessionMarkup, StationPoint, WorkArea
from models.markup_types import BAND_TYPES, MARK_SUBTYPES
from models.parsed import ParsedDocument, ParsedShape
from parser import parse_visio_file
from session.store import create_session, get_session
from extractors.coordinate_ruler import extract_coordinate_ruler, CoordinateMapping, CoordSegment
from extractors.locomotive_regime import extract_locomotive_regimes
from extractors.profile import extract_profile
from extractors.speed_limits import extract_speed_limits, _is_red
from extractors.stations import extract_stations
from extractors.track_plan import extract_track_plan

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="МПРК API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── response models ────────────────────────────────────────────────────────────

class SessionCreateResponse(BaseModel):
    session_id: str
    page_width: float
    page_height: float
    shape_count: int
    svg_url: str | None


class ShapesPageResponse(BaseModel):
    shapes: list[ParsedShape]
    total: int
    offset: int
    limit: int


# ── markup request bodies ──────────────────────────────────────────────────────

class BandCreate(BaseModel):
    type: BandType
    y_top: float
    y_bottom: float
    km_hint_start: int | None = None
    km_hint_end: int | None = None


class BandUpdate(BaseModel):
    type: BandType | None = None
    y_top: float | None = None
    y_bottom: float | None = None


class StationCreate(BaseModel):
    x: float
    name: str


class StationUpdate(BaseModel):
    x: float | None = None
    name: str | None = None


class MarkCreate(BaseModel):
    x: float
    y: float
    subtype: str
    meta: dict = {}


class MarkUpdate(BaseModel):
    x: float | None = None
    y: float | None = None
    subtype: str | None = None
    meta: dict | None = None


# ── helpers ────────────────────────────────────────────────────────────────────

def _validate_ext(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext not in (".vsdx", ".vsd"):
        raise HTTPException(status_code=400, detail="Only .vsdx and .vsd files are supported")
    return ext


def _require_session(session_id: str):
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


async def _save_and_parse(
    file: UploadFile,
    background_tasks: BackgroundTasks,
) -> tuple[ParsedDocument, str, list[str]]:
    filename = file.filename or "upload"
    ext = _validate_ext(filename)

    upload_dir = tempfile.mkdtemp(prefix="vsdx_upload_")
    upload_path = os.path.join(upload_dir, os.path.basename(filename) or f"upload{ext}")

    try:
        with open(upload_path, "wb") as fh:
            fh.write(await file.read())
        doc, svg_path, tmpdirs = parse_visio_file(upload_path)
    except (ValueError, RuntimeError) as exc:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    background_tasks.add_task(shutil.rmtree, upload_dir, True)
    return doc, svg_path, tmpdirs


# ── session endpoints ──────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/sessions", response_model=SessionCreateResponse)
async def sessions_create(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
) -> SessionCreateResponse:
    original_name = os.path.splitext(file.filename or "")[0]
    doc, svg_path, tmpdirs = await _save_and_parse(file, background_tasks)
    sid = create_session(doc, svg_path, tmpdirs, original_filename=original_name)
    return SessionCreateResponse(
        session_id=sid,
        page_width=doc.page_width,
        page_height=doc.page_height,
        shape_count=len(doc.shapes),
        svg_url=f"/api/sessions/{sid}/background" if svg_path else None,
    )


@app.get("/api/sessions/{session_id}", response_model=SessionCreateResponse)
def sessions_get(session_id: str) -> SessionCreateResponse:
    session = _require_session(session_id)
    return SessionCreateResponse(
        session_id=session_id,
        page_width=session.doc.page_width,
        page_height=session.doc.page_height,
        shape_count=len(session.doc.shapes),
        svg_url=f"/api/sessions/{session_id}/background" if session.svg_path else None,
    )


@app.get("/api/sessions/{session_id}/shapes", response_model=ShapesPageResponse)
def sessions_shapes(
    session_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(2000, ge=1, le=5000),
) -> ShapesPageResponse:
    session = _require_session(session_id)
    total = len(session.doc.shapes)
    page = session.doc.shapes[offset : offset + limit]
    return ShapesPageResponse(shapes=page, total=total, offset=offset, limit=limit)


@app.get("/api/sessions/{session_id}/background")
def sessions_background(session_id: str) -> FileResponse:
    session = _require_session(session_id)
    if not session.svg_path or not os.path.isfile(session.svg_path):
        raise HTTPException(status_code=404, detail="Background image not available")
    mime = mimetypes.guess_type(session.svg_path)[0] or "image/png"
    return FileResponse(session.svg_path, media_type=mime)


# ── markup endpoints ───────────────────────────────────────────────────────────

@app.get("/api/sessions/{session_id}/markup", response_model=SessionMarkup)
def markup_get(session_id: str) -> SessionMarkup:
    return _require_session(session_id).markup


@app.put("/api/sessions/{session_id}/markup/work-area", response_model=SessionMarkup)
def markup_set_work_area(session_id: str, body: WorkArea) -> SessionMarkup:
    session = _require_session(session_id)
    session.markup = session.markup.model_copy(update={"work_area": body})
    return session.markup


# ── bands ──────────────────────────────────────────────────────────────────────

@app.post("/api/sessions/{session_id}/markup/bands", response_model=HorizontalBand, status_code=201)
def markup_create_band(session_id: str, body: BandCreate) -> HorizontalBand:
    session = _require_session(session_id)
    data = body.model_dump(exclude={"km_hint_start", "km_hint_end"})
    extracted: dict = {}
    if body.km_hint_start is not None:
        extracted["km_hint_start"] = body.km_hint_start
    if body.km_hint_end is not None:
        extracted["km_hint_end"] = body.km_hint_end
    if extracted:
        data["extracted"] = extracted
    band = HorizontalBand(id=str(uuid.uuid4()), **data)
    session.markup.bands.append(band)
    return band


@app.put("/api/sessions/{session_id}/markup/bands/{band_id}", response_model=HorizontalBand)
def markup_update_band(session_id: str, band_id: str, body: BandUpdate) -> HorizontalBand:
    session = _require_session(session_id)
    patch = body.model_dump(exclude_none=True)
    for i, b in enumerate(session.markup.bands):
        if b.id == band_id:
            updated = b.model_copy(update=patch)
            session.markup.bands[i] = updated
            return updated
    raise HTTPException(status_code=404, detail="Band not found")


@app.delete("/api/sessions/{session_id}/markup/bands/{band_id}", status_code=204)
def markup_delete_band(session_id: str, band_id: str) -> None:
    session = _require_session(session_id)
    before = len(session.markup.bands)
    session.markup.bands = [b for b in session.markup.bands if b.id != band_id]
    if len(session.markup.bands) == before:
        raise HTTPException(status_code=404, detail="Band not found")


# ── stations ───────────────────────────────────────────────────────────────────

@app.post("/api/sessions/{session_id}/markup/stations", response_model=StationPoint, status_code=201)
def markup_create_station(session_id: str, body: StationCreate) -> StationPoint:
    session = _require_session(session_id)
    station = StationPoint(id=str(uuid.uuid4()), **body.model_dump())
    session.markup.stations.append(station)
    return station


@app.put("/api/sessions/{session_id}/markup/stations/{station_id}", response_model=StationPoint)
def markup_update_station(session_id: str, station_id: str, body: StationUpdate) -> StationPoint:
    session = _require_session(session_id)
    patch = body.model_dump(exclude_none=True)
    for i, s in enumerate(session.markup.stations):
        if s.id == station_id:
            updated = s.model_copy(update=patch)
            session.markup.stations[i] = updated
            return updated
    raise HTTPException(status_code=404, detail="Station not found")


@app.delete("/api/sessions/{session_id}/markup/stations/{station_id}", status_code=204)
def markup_delete_station(session_id: str, station_id: str) -> None:
    session = _require_session(session_id)
    before = len(session.markup.stations)
    session.markup.stations = [s for s in session.markup.stations if s.id != station_id]
    if len(session.markup.stations) == before:
        raise HTTPException(status_code=404, detail="Station not found")


# ── marks ──────────────────────────────────────────────────────────────────────

@app.post("/api/sessions/{session_id}/markup/marks", response_model=MarkPoint, status_code=201)
def markup_create_mark(session_id: str, body: MarkCreate) -> MarkPoint:
    session = _require_session(session_id)
    mark = MarkPoint(id=str(uuid.uuid4()), **body.model_dump())
    session.markup.marks.append(mark)
    return mark


@app.put("/api/sessions/{session_id}/markup/marks/{mark_id}", response_model=MarkPoint)
def markup_update_mark(session_id: str, mark_id: str, body: MarkUpdate) -> MarkPoint:
    session = _require_session(session_id)
    patch = body.model_dump(exclude_none=True)
    for i, m in enumerate(session.markup.marks):
        if m.id == mark_id:
            updated = m.model_copy(update=patch)
            session.markup.marks[i] = updated
            return updated
    raise HTTPException(status_code=404, detail="Mark not found")


@app.delete("/api/sessions/{session_id}/markup/marks/{mark_id}", status_code=204)
def markup_delete_mark(session_id: str, mark_id: str) -> None:
    session = _require_session(session_id)
    before = len(session.markup.marks)
    session.markup.marks = [m for m in session.markup.marks if m.id != mark_id]
    if len(session.markup.marks) == before:
        raise HTTPException(status_code=404, detail="Mark not found")


# ── markup types справочник ────────────────────────────────────────────────────

@app.get("/api/markup-types")
def markup_types():
    return {"bands": BAND_TYPES, "mark_subtypes": MARK_SUBTYPES}


# ── extraction helpers ─────────────────────────────────────────────────────────

def _run_extraction(session_id: str) -> dict:
    """Run all extractors and return the full export dict + _extraction_log."""
    session = _require_session(session_id)
    markup = session.markup
    shapes = session.doc.shapes
    all_warnings: list[str] = []

    now = datetime.now(timezone.utc).isoformat()
    ts = int(datetime.now(timezone.utc).timestamp() * 1000)

    doc_name = session.original_filename or session_id[:8]

    # ── Coordinate ruler ──────────────────────────────────────────────────────
    ruler_bands = [b for b in markup.bands if b.type == "coordinate_ruler"]
    coord_mapping: CoordinateMapping | None = None
    ruler_log: dict = {"found_kilometers": 0, "direction": None, "range": None}

    if not ruler_bands:
        all_warnings.append(
            "export: no coordinate_ruler band marked — "
            "stations and speed limits will use raw pixel coordinates"
        )
        # Build a trivial 1:1 mapping (pixels = network metres)
        if markup.work_area:
            wa = markup.work_area
            coord_mapping = CoordinateMapping(
                segments=[CoordSegment(
                    points=[(wa.x_start, 0), (wa.x_end, int((wa.x_end - wa.x_start) // 1000))],
                    direction="ascending",
                )]
            )
    else:
        if markup.work_area is None:
            raise HTTPException(status_code=400, detail="Work area must be marked before export")
        ruler_band = ruler_bands[0]
        km_hint_start = ruler_band.extracted.get("km_hint_start")
        km_hint_end = ruler_band.extracted.get("km_hint_end")
        coord_mapping, ruler_log, w = extract_coordinate_ruler(
            shapes, ruler_band, markup.work_area, km_hint_start, km_hint_end
        )
        all_warnings.extend(w)

    if coord_mapping is None:
        raise HTTPException(
            status_code=400,
            detail="Cannot export: mark the work area and coordinate ruler band first",
        )

    wa = markup.work_area

    # ── Coordinate ruler → coordinateRuler.segments ───────────────────────────
    ruler_segments: list[dict] = []
    for _rseg in coord_mapping.segments:
        if not _rseg.points:
            continue
        _kms = [km for _, km in _rseg.points]
        ruler_segments.append({"startCoordinate": _kms[0], "endCoordinate": _kms[-1], "adjustments": []})

    # ── Profile ───────────────────────────────────────────────────────────────
    profile_bands = [b for b in markup.bands if b.type == "profile" and not b.is_informational]
    profile_segs: list[dict] = []
    profile_log: dict = {"found_segments": 0, "total_length_meters": 0}

    if profile_bands and wa:
        segs, profile_log, w = extract_profile(shapes, profile_bands[0], wa, coord_mapping)
        all_warnings.extend(w)
        profile_segs = [s.model_dump() for s in segs]

    # ── Speed limits ──────────────────────────────────────────────────────────
    speed_bands = [b for b in markup.bands if b.type == "speed_limits" and not b.is_informational]
    speed_segs: list[dict] = []
    speed_log: dict = {"found_segments": 0, "value_scale_points": [], "used_color_filter": False}

    if speed_bands and wa:
        segs, stats, w = extract_speed_limits(shapes, speed_bands[0], wa, coord_mapping)
        all_warnings.extend(w)
        speed_segs = [s.model_dump() for s in segs]
        speed_log = stats
        for _spd in segs:
            if coord_mapping.crosses_km_boundary(_spd.start, _spd.end):
                all_warnings.append(
                    f"speed_limits: сегмент {_spd.limit} км/ч "
                    f"({_spd.start}–{_spd.end} м) пересекает границу км-системы"
                )

    # ── Stations ─────────────────────────────────────────────────────────────
    stations_list, stations_log, w = extract_stations(markup.stations, coord_mapping)
    all_warnings.extend(w)

    # ── Track plan ───────────────────────────────────────────────────────────
    track_plan_bands = [b for b in markup.bands if b.type == "track_plan" and not b.is_informational]
    track_plan_curves: list[dict] = []
    track_plan_log: dict = {"shapes_in_band": 0, "blue_shapes": 0, "step_shapes": 0,
                            "curve_texts_found": 0, "curves_matched": 0, "unmatched_texts": 0}

    if track_plan_bands and wa:
        curves, track_plan_log, w = extract_track_plan(
            shapes, track_plan_bands[0], wa, coord_mapping
        )
        all_warnings.extend(w)
        track_plan_curves = [c.model_dump() for c in curves]

    # ── Locomotive regimes ────────────────────────────────────────────────────
    traction_bands = [b for b in markup.bands if b.type == "traction_modes" and not b.is_informational]
    loco_regime_bands: list[dict] = []
    loco_regime_log: dict = {"loco_labels_found": 0, "line_segments_total": 0,
                             "mode_texts_found": 0, "bands_extracted": 0,
                             "total_segments": 0, "loco_labels_raw": [], "per_band": []}

    if traction_bands and wa:
        bands_out, loco_regime_log, w = extract_locomotive_regimes(
            shapes, traction_bands[0], wa, coord_mapping
        )
        all_warnings.extend(w)
        loco_regime_bands = [b.model_dump() for b in bands_out]

    # ── Marks (MarkPoints → output marks array) ───────────────────────────────
    def _safe_round(v: float) -> int:
        """round() that never raises on NaN/Inf."""
        if v != v or v == float("inf") or v == float("-inf"):
            return 0
        return round(v)

    output_marks = [
        {
            "subtype": mk.subtype,
            "coordinate": _safe_round(coord_mapping.x_to_network_coord(mk.x)),
            "x": mk.x,
            "y": mk.y,
            "meta": mk.meta,
        }
        for mk in markup.marks
    ]

    extraction_log = {
        "coordinate_ruler": ruler_log,
        "profile": profile_log,
        "speed_limits": speed_log,
        "stations": stations_log,
        "track_plan": track_plan_log,
        "locomotive_regime": loco_regime_log,
        "warnings": all_warnings,
    }

    return {
        "extraction_log": extraction_log,
        "metadata": {
            "id": f"nsi-2-{ts}",
            "name": doc_name,
            "createdAt": now,
            "updatedAt": now,
        },
        "coordinateRuler": {"segments": ruler_segments},
        "stations": stations_list,
        "profile": profile_segs,
        "speedLimits": speed_segs,
        "locomotives": [],
        "cars": [],
        "canvasLayers": [],
        "trackPlan": track_plan_curves,
        "optimalSpeedCurve": [],
        "speedCurve": [],
        "optimalRegimeBands": [],
        "locomotiveRegimeBands": loco_regime_bands,
        "longitudinalForces": [],
        "marks": output_marks,
        "coord_mapping_points": [
            {"x_px": round(x, 1), "km": km}
            for x, km in coord_mapping.points
        ],
    }


_log = logging.getLogger(__name__)


# ── extract (preview) ──────────────────────────────────────────────────────────

@app.get("/api/sessions/{session_id}/extract")
def sessions_extract(session_id: str):
    """Run all extractors and return structured results + log for preview."""
    try:
        return _run_extraction(session_id)
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("Extraction failed for session %s", session_id)
        raise HTTPException(status_code=500, detail=f"Extraction error: {exc}") from exc


# ── edited-data save ──────────────────────────────────────────────────────────

@app.put("/api/sessions/{session_id}/edited-data")
def sessions_save_edited(session_id: str, body: dict):
    """Store manually-edited extraction result. Overwrites any previous edits."""
    session = _require_session(session_id)
    session.edited_data = body
    return {"ok": True, "saved_at": datetime.now(timezone.utc).isoformat()}


# ── export (download) ──────────────────────────────────────────────────────────

@app.get("/api/sessions/{session_id}/export")
def sessions_export(session_id: str):
    """Return the export JSON. Uses edited_data if saved, otherwise runs extractors."""
    session = _require_session(session_id)
    if session.edited_data is not None:
        now = datetime.now(timezone.utc).isoformat()
        result = dict(session.edited_data)
        if "metadata" in result:
            result["metadata"] = {**result["metadata"], "updatedAt": now}
        return result
    try:
        return _run_extraction(session_id)
    except HTTPException:
        raise
    except Exception as exc:
        _log.exception("Export failed for session %s", session_id)
        raise HTTPException(status_code=500, detail=f"Export error: {exc}") from exc


# ── debug: shapes inside a band ───────────────────────────────────────────────

@app.get("/api/sessions/{session_id}/debug-shapes")
def debug_shapes(
    session_id: str,
    in_band: str = Query("speed_limits", description="Band type to inspect"),
) -> dict:
    """Return all shapes whose center-Y falls inside the first band of the given type.

    Useful for diagnosing why extractors don't find what they should:
    - Are shapes in the band at all?
    - Do they have line_color / fill_color?
    - Which ones are red-ish?
    """
    session = _require_session(session_id)
    markup = session.markup
    shapes = session.doc.shapes

    bands = [b for b in markup.bands if b.type == in_band]
    if not bands:
        return {
            "error": f"No band of type '{in_band}' found. Marked bands: {[b.type for b in markup.bands]}",
            "shapes": [],
        }
    band = bands[0]
    wa = markup.work_area

    result: list[dict] = []
    for s in shapes:
        cy = s.y + s.height / 2
        cx = s.x + s.width / 2
        if not (band.y_top <= cy <= band.y_bottom):
            continue
        in_wa = wa is None or (wa.x_start <= cx <= wa.x_end)
        result.append({
            "id": s.id,
            "shape_type": s.shape_type,
            "x": round(s.x, 1),
            "y": round(s.y, 1),
            "width": round(s.width, 1),
            "height": round(s.height, 1),
            "text": s.text,
            "line_color": s.line_color,
            "fill_color": s.fill_color,
            "is_red": _is_red(s.line_color),
            "in_work_area": in_wa,
        })

    result.sort(key=lambda r: r["x"])

    # Summary stats
    with_line_color = [r for r in result if r["line_color"] is not None]
    red_shapes = [r for r in result if r["is_red"]]
    in_wa_shapes = [r for r in result if r["in_work_area"]]

    # Color frequency table
    color_counts: dict[str, int] = {}
    for r in result:
        c = r["line_color"] or "(none)"
        color_counts[c] = color_counts.get(c, 0) + 1
    top_colors = sorted(color_counts.items(), key=lambda kv: -kv[1])[:20]

    return {
        "band": {
            "type": band.type,
            "y_top": round(band.y_top, 1),
            "y_bottom": round(band.y_bottom, 1),
        },
        "work_area": (
            {"x_start": round(wa.x_start, 1), "x_end": round(wa.x_end, 1)}
            if wa else None
        ),
        "summary": {
            "total_in_band": len(result),
            "in_work_area": len(in_wa_shapes),
            "with_line_color": len(with_line_color),
            "red_ish": len(red_shapes),
            "top_line_colors": [{"color": c, "count": n} for c, n in top_colors],
        },
        "shapes": result,
    }


# ── debug: detailed shapes inside a band ──────────────────────────────────────

@app.get("/api/sessions/{session_id}/debug-shapes-in-band")
def debug_shapes_in_band(
    session_id: str,
    band_type: str = Query("speed_limits", description="Band type to inspect"),
) -> dict:
    """Detailed diagnostic dump of all shapes in a band.

    Returns total counts by shape_type, plus the first 50 line/path-like shapes
    sorted by X with full color and geometry info.
    Note: geometry_points is always [] — the parser stores only bounding boxes.
    """
    session = _require_session(session_id)
    markup = session.markup
    shapes = session.doc.shapes

    bands = [b for b in markup.bands if b.type == band_type]
    if not bands:
        return {
            "error": f"No band of type '{band_type}'. Marked: {[b.type for b in markup.bands]}",
            "band": None,
            "shapes": [],
        }

    band = bands[0]
    wa = markup.work_area

    # All shapes whose center-Y is inside the band
    in_band: list[ParsedShape] = []
    for s in shapes:
        cy = s.y + s.height / 2
        if band.y_top <= cy <= band.y_bottom:
            in_band.append(s)

    in_band.sort(key=lambda s: s.x)

    # Count by shape_type
    by_type: dict[str, int] = {}
    for s in in_band:
        by_type[s.shape_type] = by_type.get(s.shape_type, 0) + 1

    # All shapes regardless of WA (for visibility)
    lines_and_paths = []
    for s in in_band:
        cx = s.x + s.width / 2
        in_wa = wa is None or (wa.x_start <= cx <= wa.x_end)
        lines_and_paths.append({
            "id": s.id,
            "shape_type": s.shape_type,
            "x": round(s.x, 1),
            "y": round(s.y, 1),
            "width": round(s.width, 1),
            "height": round(s.height, 1),
            "stroke_color": s.line_color,
            "fill_color": s.fill_color,
            "text": s.text,
            "in_work_area": in_wa,
            "is_red": _is_red(s.line_color),
            "geometry_points": [],   # not stored by parser (only bbox available)
        })

    # Color frequency
    color_counts: dict[str, int] = {}
    for s in in_band:
        c = s.line_color or "(none)"
        color_counts[c] = color_counts.get(c, 0) + 1
    top_colors = sorted(color_counts.items(), key=lambda kv: -kv[1])[:20]

    return {
        "band": {
            "y_top": round(band.y_top, 1),
            "y_bottom": round(band.y_bottom, 1),
            "x_start": round(wa.x_start, 1) if wa else None,
            "x_end": round(wa.x_end, 1) if wa else None,
        },
        "total_shapes_in_band": len(in_band),
        "by_shape_type": by_type,
        "color_summary": {
            "with_line_color": sum(1 for s in in_band if s.line_color),
            "red_ish": sum(1 for s in in_band if _is_red(s.line_color)),
            "top_line_colors": [{"color": c, "count": n} for c, n in top_colors],
        },
        "lines_and_paths": lines_and_paths[:50],
    }


# kept for existing tests
@app.post("/api/parse", response_model=ParsedDocument)
async def parse(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
) -> ParsedDocument:
    doc, _svg_path, tmpdirs = await _save_and_parse(file, background_tasks)
    for d in tmpdirs:
        background_tasks.add_task(shutil.rmtree, d, True)
    return doc
