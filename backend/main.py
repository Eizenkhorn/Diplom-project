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
from extractors.coordinate_ruler import extract_coordinate_ruler, CoordinateMapping
from extractors.profile import extract_profile
from extractors.speed_limits import extract_speed_limits
from extractors.stations import extract_stations

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
    doc, svg_path, tmpdirs = await _save_and_parse(file, background_tasks)
    sid = create_session(doc, svg_path, tmpdirs)
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
    band = HorizontalBand(id=str(uuid.uuid4()), **body.model_dump())
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

    # Derive a human-readable name from the stored filename (session has no filename
    # field yet; fall back to the session id prefix)
    doc_name = session_id[:8]

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
                points=[(wa.x_start, 0), (wa.x_end, int((wa.x_end - wa.x_start) // 1000))],
                direction="ascending",
            )
    else:
        if markup.work_area is None:
            raise HTTPException(status_code=400, detail="Work area must be marked before export")
        ruler_band = ruler_bands[0]
        coord_mapping, w = extract_coordinate_ruler(shapes, ruler_band, markup.work_area)
        all_warnings.extend(w)
        if coord_mapping.points:
            kms = [km for _, km in coord_mapping.points]
            ruler_log = {
                "found_kilometers": len(coord_mapping.points),
                "direction": coord_mapping.direction,
                "range": [min(kms), max(kms)],
            }

    if coord_mapping is None:
        raise HTTPException(
            status_code=400,
            detail="Cannot export: mark the work area and coordinate ruler band first",
        )

    wa = markup.work_area

    # ── Coordinate ruler → coordinateRuler.segments ───────────────────────────
    ruler_segments: list[dict] = []
    if coord_mapping.points:
        kms = [km for _, km in coord_mapping.points]
        ruler_segments = [{
            "startCoordinate": kms[0] if coord_mapping.direction == "descending" else kms[-1],
            "endCoordinate": kms[-1] if coord_mapping.direction == "descending" else kms[0],
            "adjustments": [],
        }]

    # ── Profile ───────────────────────────────────────────────────────────────
    profile_bands = [b for b in markup.bands if b.type == "profile" and not b.is_informational]
    profile_segs: list[dict] = []
    profile_log: dict = {"found_segments": 0, "total_length_meters": 0}

    if profile_bands and wa:
        segs, w = extract_profile(shapes, profile_bands[0], wa)
        all_warnings.extend(w)
        profile_segs = [s.model_dump() for s in segs]
        total_m = segs[-1].end if segs else 0
        profile_log = {"found_segments": len(segs), "total_length_meters": total_m}

    # ── Speed limits ──────────────────────────────────────────────────────────
    speed_bands = [b for b in markup.bands if b.type == "speed_limits" and not b.is_informational]
    speed_segs: list[dict] = []
    speed_log: dict = {"found_segments": 0, "value_scale_points": [], "used_color_filter": False}

    if speed_bands and wa:
        segs, stats, w = extract_speed_limits(shapes, speed_bands[0], wa, coord_mapping)
        all_warnings.extend(w)
        speed_segs = [s.model_dump() for s in segs]
        speed_log = stats

    # ── Stations ─────────────────────────────────────────────────────────────
    stations_list, w = extract_stations(markup.stations, coord_mapping)
    all_warnings.extend(w)
    stations_log = {"count": len(stations_list)}

    # ── Marks (MarkPoints → output marks array) ───────────────────────────────
    output_marks = [
        {
            "subtype": mk.subtype,
            "coordinate": round(coord_mapping.x_to_network_coord(mk.x)),
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
        "warnings": all_warnings,
    }

    return {
        "_extraction_log": extraction_log,
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
        "trackPlan": [],
        "optimalSpeedCurve": [],
        "speedCurve": [],
        "optimalRegimeBands": [],
        "locomotiveRegimeBands": [],
        "longitudinalForces": [],
        "marks": output_marks,
    }


# ── extract (preview) ──────────────────────────────────────────────────────────

@app.get("/api/sessions/{session_id}/extract")
def sessions_extract(session_id: str):
    """Run all extractors and return structured results + log for preview."""
    return _run_extraction(session_id)


# ── export (download) ──────────────────────────────────────────────────────────

@app.get("/api/sessions/{session_id}/export")
def sessions_export(session_id: str):
    """Same as extract but omits the internal _extraction_log field."""
    result = _run_extraction(session_id)
    result.pop("_extraction_log", None)
    return result


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
