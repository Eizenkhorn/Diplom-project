import tempfile
import os
import logging

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from models.parsed import ParsedDocument
from parser.vsdx_parser import parse_vsdx

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="МПРК API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/parse", response_model=ParsedDocument)
async def parse(file: UploadFile = File(...)) -> ParsedDocument:
    filename = file.filename or ""
    if not filename.lower().endswith((".vsdx", ".vsd")):
        raise HTTPException(status_code=400, detail="Only .vsdx files are supported")

    suffix = os.path.splitext(filename)[1]
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        return parse_vsdx(tmp_path)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        os.unlink(tmp_path)
