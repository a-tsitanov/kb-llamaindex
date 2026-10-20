"""``mark_skipped`` — вердикт отказа пишет приём, а не обработка.

Тест переехал сюда из ``tests/test_workflow/test_finalize.py`` вместе с
самой активностью: соглашение репозитория — одна активность на модуль.
"""

from __future__ import annotations

import importlib
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.workflow.contracts import Ctx, SkipIn

# ``activities/__init__.py`` реэкспортирует функцию ``mark_skipped``, то есть
# перебивает одноимённый атрибут-подмодуль: ``import ... as ms`` вернул бы
# функцию, а не модуль, и проверка его пространства имён стала бы бессмысленной.
ms = importlib.import_module("src.workflow.activities.mark_skipped")


@pytest.mark.asyncio
async def test_mark_skipped_rejects_intake_and_never_writes_processing(tmp_path):
    """Вердикт классификатора пишет приём, а не обработка.

    Домен ``doc_processing.status`` намеренно не содержит 'skipped', так что
    прежний ``update_status(status='skipped')`` на живом стеке упал бы на
    CHECK, а активность ушла бы в бесконечный ретрай.  Поэтому отказ едет
    через ``IntakeRepository.reject``: вердикт в ``documents`` плюс удаление
    строки обработки.  ``AsyncPostgres`` здесь не строится вовсе.

    Возврат активности проверяется целиком: ``IngestResult.graph_status``
    объявлен ``IngestOutcome`` (``src/workflow/contracts.py``), и 'skipped'
    в домене ВЫХОДА воркфлоу допустимо — в отличие от домена обработки.
    """
    cleanup_dir = tmp_path / "cache" / "doc-s"
    cleanup_dir.mkdir(parents=True)
    (cleanup_dir / "x.txt").write_bytes(b"x")

    intake = MagicMock()
    intake.reject = AsyncMock()
    staging = MagicMock()

    ctx = Ctx(
        doc_id="11111111-1111-1111-1111-111111111111",
        local_path=str(cleanup_dir / "x.txt"),
        cleanup_dir=str(cleanup_dir),
        workflow_run_id="run-s",
    )
    with patch(
        "src.workflow.activities.mark_skipped.IntakeRepository", return_value=intake,
    ), patch(
        "src.workflow.activities.mark_skipped.build_staging_store",
        return_value=staging,
    ), patch(
        "src.workflow.activities.mark_skipped.activity"
    ):
        out = await ms.mark_skipped(SkipIn(ctx=ctx, reason="not relevant"))

    intake.reject.assert_awaited_once_with(uuid.UUID(ctx.doc_id), "not relevant")
    # «AsyncPostgres не строится вовсе» теперь утверждение строже патча:
    # ядровый класс обработки в модуль отказа не импортирован совсем,
    # поэтому проверяется само отсутствие имени, а не число вызовов.
    assert not hasattr(ms, "AsyncPostgres")
    staging.delete_prefix.assert_called_once_with("run-s")
    assert not cleanup_dir.exists()

    assert out.doc_id == ctx.doc_id
    assert out.graph_status == "skipped"
    assert out.chunk_count == 0
    assert out.wikibase_status == "skipped"
