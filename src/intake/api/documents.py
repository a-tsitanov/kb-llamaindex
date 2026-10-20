"""`GET /api/v1/documents/{doc_id}` — download the original source file.

Streams an uploaded file from MinIO.  Two variants (ADR-0014 addendum):
``original`` = the binary the text was converted from
(`documents.original_path`, e.g. .docx/.pdf), ``text`` = the ingested file
(`documents.path`).  Without ``?variant=`` the original is served when one
was stored, else the text.  doc_id is the value search responses expose in
`sources[]` / `documents[]`.
"""

from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, StreamingResponse
from loguru import logger

from src.api.graph_dep import resolve_graph_download
from src.intake.repository import IntakeRepository
from src.storage.minio import S3Error, build_minio_storage
from src.tenancy.context import GraphContext

router = APIRouter(tags=["documents"])


@router.get(
    "/documents/{doc_id}",
    summary="Download the original source file of an ingested document",
)
async def download_document(
    doc_id: str,
    graph: GraphContext = Depends(resolve_graph_download),
    variant: Literal["original", "text"] | None = Query(
        default=None,
        description="original = uploaded binary (if stored), text = "
                    "ingested text; default original, falling back to text",
    ),
):
    pg = IntakeRepository(graph=graph)
    try:
        row = await pg.get(uuid.UUID(doc_id))
    except (ValueError, TypeError):
        row = None
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")

    original_path = getattr(row, "original_path", None)
    if variant == "original" and not original_path:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "original file not available")
    path = row.path if variant == "text" else (original_path or row.path)
    # Legacy local-path docs (pre-MinIO): stream from disk if present.
    if not path.startswith("s3://"):
        local = Path(path)
        if local.is_file():
            return FileResponse(local, filename=local.name)
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "document source not available")

    try:
        storage = build_minio_storage()
        filename, size, content_type = storage.stat_object(path)
    except S3Error as exc:
        if getattr(exc, "code", "") == "NoSuchKey":
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                "document source not available") from exc
        logger.exception("document download storage error doc_id={d}", d=doc_id)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "storage unavailable") from exc
    except Exception as exc:  # MinIO unreachable, transport errors, etc.
        logger.exception("document download storage error doc_id={d}", d=doc_id)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "storage unavailable") from exc

    # RFC 6266: sanitize the (client-supplied) filename — strip quotes/
    # backslashes/CR/LF for the ASCII fallback and percent-encode the
    # UTF-8 form so a crafted filename can't corrupt or inject headers.
    ascii_name = (
        filename.encode("ascii", "ignore").decode()
        .replace('"', "").replace("\\", "").replace("\r", "").replace("\n", "")
    ) or "document"
    disposition = (
        f'attachment; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )
    headers = {
        "Content-Disposition": disposition,
        "Content-Length": str(size),
    }
    # Browsers often upload as application/octet-stream; the extension is
    # the better signal.  Fall back to whatever MinIO stored.
    content_type = mimetypes.guess_type(filename)[0] or content_type
    return StreamingResponse(
        storage.stream_object(path), media_type=content_type, headers=headers)
