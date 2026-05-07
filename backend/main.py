import logging
import os
import shutil
import tempfile

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

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


# ── helpers ────────────────────────────────────────────────────────────────────

def _validate_ext(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext not in (".vsdx", ".vsd"):
        raise HTTPException(status_code=400, detail="Only .vsdx and .vsd files are supported")
    return ext


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
    # svg tmpdirs are NOT cleaned here — stored in session so /background can serve them

    return doc, svg_path, tmpdirs


# ── endpoints ──────────────────────────────────────────────────────────────────

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


@app.get("/api/sessions/{session_id}/shapes", response_model=ShapesPageResponse)
def sessions_shapes(
    session_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(2000, ge=1, le=5000),
) -> ShapesPageResponse:
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    total = len(session.doc.shapes)
    page = session.doc.shapes[offset : offset + limit]
    return ShapesPageResponse(shapes=page, total=total, offset=offset, limit=limit)


@app.get("/api/sessions/{session_id}/background")
def sessions_background(session_id: str) -> FileResponse:
    import mimetypes
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.svg_path or not os.path.isfile(session.svg_path):
        raise HTTPException(status_code=404, detail="Background image not available")
    mime = mimetypes.guess_type(session.svg_path)[0] or "image/png"
    return FileResponse(session.svg_path, media_type=mime)


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
