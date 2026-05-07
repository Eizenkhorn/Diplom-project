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


# ── export ─────────────────────────────────────────────────────────────────────

@app.get("/api/sessions/{session_id}/export")
def sessions_export(session_id: str):
    session = _require_session(session_id)
    now = datetime.now(timezone.utc).isoformat()
    ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    return {
        "metadata": {
            "id": f"nsi-2-{ts}",
            "name": "",
            "createdAt": now,
            "updatedAt": now,
        },
        "coordinateRuler": {"segments": []},
        "stations": [],
        "profile": [],
        "speedLimits": [],
        "locomotives": [],
        "cars": [],
        "canvasLayers": [],
        "trackPlan": [],
        "optimalSpeedCurve": [],
        "speedCurve": [],
        "optimalRegimeBands": [],
        "locomotiveRegimeBands": [],
        "longitudinalForces": [],
        "marks": [],
        "_markup": session.markup.model_dump(),
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
