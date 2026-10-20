"""`GET /api/v1/documents/{doc_id}` — download the original source file.

Streams an uploaded file from MinIO.  Two variants (ADR-0014 addendum):
``original`` = the binary the text was converted from
(`documents.original_path`, e.g. .docx/.pdf), ``text`` = the ingested file
(`documents.path`).  Without ``?variant=`` the original is served when one
was stored, else the text.  doc_id is the value search responses expose in
`sources[]` / `documents[]`.

Самая строгая точка контура приёма (§7 карты контуров), и отсюда два
свойства маршрута, которых нет у поиска:

* **Каждая выдача пишется в журнал** (``document_download``) — кто, какой
  документ, какой вариант, когда.  Запись обязательна: не удалось записать
  — не отдаём (503).  Иначе на вопрос «что утекло» при компрометации ключа
  ответить нечем, а именно он задаётся первым.
* **Право отдельное** — ``download_original``: право на поиск не даёт права
  на выгрузку целого файла.
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

from src.api.auth import require_api_key
from src.api.graph_dep import resolve_graph_download
from src.config import settings
from src.intake.repository import IntakeRepository
from src.storage.minio import S3Error, build_minio_storage
from src.tenancy.api_keys import ApiKeyRecord
from src.tenancy.context import GraphContext

router = APIRouter(tags=["documents"])


async def _journal(
    pg: IntakeRepository, doc_id: uuid.UUID, variant: str, path: str,
    key: ApiKeyRecord | None,
) -> None:
    """Записать выдачу — или отказать в ней.

    Fail-CLOSED, в отличие от почти всего остального в проекте: незаписанная
    выдача хуже неслучившейся.  Падение здесь означает недоступный Postgres,
    а он и так нужен был строкой выше, чтобы прочитать реестр, — то есть
    новой зависимости этот отказ не добавляет.
    """
    try:
        await pg.record_download(
            doc_id, variant, path,
            principal=getattr(key, "owner", "") or "",
            tenant_id=getattr(key, "tenant_id", "") or "",
        )
    except Exception as exc:
        logger.exception("document download journal write failed doc_id={d}", d=doc_id)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "download journal unavailable",
        ) from exc


def _legacy_local_file(path: str, graph: GraphContext) -> Path:
    """Разрешить дорелизный путь на диске — или отказать (§7.4).

    Ветка осталась от времён до MinIO: в колонке `documents.path` у части
    исторических строк лежит локальный путь, и маршрут читает его с диска.
    Источник пути серверный, поэтому дыры нет и не было, но под
    арендаторами «прочитать произвольный путь из колонки БД» — слишком
    широкое полномочие, чтобы держать его без границ.

    Границы две, и обе проверяемы без обращения к данным:

    * **только граф `default`** — локальные пути существуют лишь в строках,
      записанных ДО мультиграфа, а они все в `default`; у нового графа
      такая строка означала бы испорченный реестр, а не легаси;
    * **белый список каталога** — ``API_UPLOAD_DIR``; путь разрешается
      (``resolve``) до сравнения, поэтому ни ``..``, ни символическая
      ссылка из каталога не выводят.
    """
    if not graph.is_default:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document source not available")
    root = Path(settings.api.upload_dir).resolve()
    local = Path(path).resolve()
    if not local.is_relative_to(root) or not local.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document source not available")
    return local


@router.get(
    "/documents/{doc_id}",
    summary="Download the original source file of an ingested document",
)
async def download_document(
    doc_id: str,
    graph: GraphContext = Depends(resolve_graph_download),
    # Один и тот же вызов, что внутри зависимости графа: FastAPI кеширует
    # зависимость на запрос по идентичности callable, поэтому ключ
    # проверяется один раз, а не дважды.
    key: ApiKeyRecord = Depends(require_api_key),
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
    # Журналируется ЭФФЕКТИВНЫЙ вариант: без ?variant= маршрут отдаёт
    # оригинал, когда он есть, и текст, когда нет, а запись «variant=None»
    # не отвечала бы, что именно ушло.
    served = "text" if path == row.path else "original"
    doc_uuid = uuid.UUID(doc_id)
    # Legacy local-path docs (pre-MinIO): stream from disk, из белого
    # списка и только в графе `default` (см. _legacy_local_file).
    if not path.startswith("s3://"):
        local = _legacy_local_file(path, graph)
        await _journal(pg, doc_uuid, served, path, key)
        return FileResponse(local, filename=local.name)

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
    # Перед отдачей байт, а не после: оборвавшийся на середине поток —
    # всё равно выдача, и в журнале он обязан быть.
    await _journal(pg, doc_uuid, served, path, key)
    return StreamingResponse(
        storage.stream_object(path), media_type=content_type, headers=headers)
