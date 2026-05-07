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

from models.parsed import ParsedDocument, ParsedShape
from models.region import Region, RegionType
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


class RegionCreate(BaseModel):
    type: RegionType
    x: float
    y: float
    width: float
    height: float
    meta: dict = {}


class RegionUpdate(BaseModel):
    type: RegionType | None = None
    x: float | None = None
    y: float | None = None
    width: float | None = None
    height: float | None = None
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


# ── region endpoints ───────────────────────────────────────────────────────────

@app.get("/api/sessions/{session_id}/regions", response_model=list[Region])
def regions_list(session_id: str):
    return _require_session(session_id).regions


@app.post("/api/sessions/{session_id}/regions", response_model=Region, status_code=201)
def regions_create(session_id: str, body: RegionCreate) -> Region:
    session = _require_session(session_id)
    region = Region(id=str(uuid.uuid4()), **body.model_dump())
    session.regions.append(region)
    return region


@app.put("/api/sessions/{session_id}/regions/{region_id}", response_model=Region)
def regions_update(session_id: str, region_id: str, body: RegionUpdate) -> Region:
    session = _require_session(session_id)
    patch = body.model_dump(exclude_none=True)
    for i, r in enumerate(session.regions):
        if r.id == region_id:
            updated = r.model_copy(update=patch)
            session.regions[i] = updated
            return updated
    raise HTTPException(status_code=404, detail="Region not found")


@app.delete("/api/sessions/{session_id}/regions/{region_id}", status_code=204)
def regions_delete(session_id: str, region_id: str) -> None:
    session = _require_session(session_id)
    before = len(session.regions)
    session.regions = [r for r in session.regions if r.id != region_id]
    if len(session.regions) == before:
        raise HTTPException(status_code=404, detail="Region not found")


# ── annotation types ───────────────────────────────────────────────────────────

@app.get("/api/annotation-types")
def annotation_types():
    return [
        {"type": "profile", "label": "Профиль пути", "color": "#10b981"},
        {"type": "speed_limit", "label": "Ограничения скорости", "color": "#ef4444"},
        {"type": "station", "label": "Станции", "color": "#3b82f6"},
        {"type": "coordinate_ruler", "label": "Координатная шкала", "color": "#a855f7"},
        {"type": "track_plan", "label": "План пути", "color": "#f59e0b"},
        {"type": "other", "label": "Прочее", "color": "#6b7280"},
    ]


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
        "_regions": [r.model_dump() for r in session.regions],
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
