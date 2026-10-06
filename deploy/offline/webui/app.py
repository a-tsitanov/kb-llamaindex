"""Minimal web UI for the offline cluster: upload -> doc2md -> KB ingest, plus search.

Runs inside the kb-app:offline image (fastapi, httpx, python-multipart are already
there), so the air-gapped servers need no extra image. The browser talks only to
this app; the KB X-API-Key stays server-side.

Env:
  KB_API_URL      KB API base, e.g. http://api:8000
  KB_API_KEY      one key from API_KEYS
  DOCS2MD_URL     doc2md base, e.g. http://10.10.113.11:8070
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

KB_API_URL = os.environ["KB_API_URL"].rstrip("/")
KB_API_KEY = os.environ["KB_API_KEY"]
DOCS2MD_URL = os.environ["DOCS2MD_URL"].rstrip("/")
INDEX_HTML = (Path(__file__).parent / "index.html").read_text(encoding="utf-8")
# doc2md exports images as assets/img_N.ext; the KB never gets those files, so keep
# only the alt text (often a useful caption) and drop the dangling link.
ASSET_IMG = re.compile(r"!\[([^\]]*)\]\(assets/[^)]*\)")

# CPU-only cluster: conversions are fast, searches can take minutes under ingest load.
TIMEOUT = httpx.Timeout(900.0, connect=10.0)
KB_HEADERS = {"X-API-Key": KB_API_KEY}

app = FastAPI(title="KB web UI", docs_url=None, redoc_url=None)


def _relay(resp: httpx.Response) -> JSONResponse:
    """Pass an upstream JSON (or error text) through with its status code."""
    try:
        body = resp.json()
    except ValueError:
        body = {"error": {"message": resp.text[:2000]}}
    return JSONResponse(body, status_code=resp.status_code)


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return INDEX_HTML


@app.get("/api/health")
async def health() -> dict:
    out: dict = {}
    async with httpx.AsyncClient(timeout=5.0) as c:
        for name, url in (("kb", f"{KB_API_URL}/health"), ("docs2md", f"{DOCS2MD_URL}/health")):
            try:
                r = await c.get(url)
                out[name] = r.json().get("status", r.status_code)
            except Exception as e:  # noqa: BLE001 — health is best-effort
                out[name] = f"down: {type(e).__name__}"
    return out


@app.post("/api/convert")
async def convert(file: UploadFile = File(...)) -> JSONResponse:
    data = await file.read()
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(
            f"{DOCS2MD_URL}/convert",
            files={"file": (file.filename, data, file.content_type or "application/octet-stream")},
            data={"page_markers": "false"},
        )
    return _relay(r)


@app.post("/api/ingest")
async def ingest(
    markdown: str = Form(...),
    filename: str = Form(...),
    document_date: str = Form(""),
    department: str = Form(""),
) -> JSONResponse:
    # KB picks the reader by extension: always hand it Markdown.
    name = Path(filename).stem + ".md"
    markdown = ASSET_IMG.sub(lambda m: m.group(1), markdown)
    data = {k: v for k, v in (("document_date", document_date), ("department", department)) if v}
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(
            f"{KB_API_URL}/api/v1/ingest",
            headers=KB_HEADERS,
            files={"file": (name, markdown.encode("utf-8"), "text/markdown")},
            data=data,
        )
    return _relay(r)


@app.get("/api/ingest/{job_id}")
async def ingest_status(job_id: str) -> JSONResponse:
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.get(f"{KB_API_URL}/api/v1/ingest/{job_id}", headers=KB_HEADERS)
    return _relay(r)


@app.post("/api/search")
async def search(payload: dict) -> JSONResponse:
    mode = payload.get("mode", "auto")
    if mode not in {"auto", "local", "global", "drift"}:
        mode = "auto"
    body = {"query": payload.get("query", ""), "include_references": True}
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(f"{KB_API_URL}/api/v1/search/{mode}", headers=KB_HEADERS, json=body)
    return _relay(r)


@app.get("/api/documents/{doc_id}", response_class=PlainTextResponse)
async def document(doc_id: str) -> PlainTextResponse:
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.get(f"{KB_API_URL}/api/v1/documents/{doc_id}", headers=KB_HEADERS)
    return PlainTextResponse(r.text, status_code=r.status_code)
