"""Дедуп приёма по ``content_sha256``: повторная заливка того же тела.

Головная цель контура: второй POST того же тела в тот же граф НЕ доходит
ни до MinIO, ни до очереди.  Поэтому почти каждый тест ниже проверяет не
только код ответа, но и то, что побочных действий не было —
``build_minio_storage`` не звали вовсе, ``put_object`` не вызывали,
``submit_document`` не ждали.

Стиль — как в ``tests/test_api/test_ingest.py``: реальное приложение через
ASGITransport, а инфраструктура (MinIO, Postgres, Temporal) подменена
патчами на ``src.intake.api.ingest.*`` и на методы ``IntakeRepository``.

Здесь же живёт общий ``no_duplicate()`` — его импортируют тесты приёма в
``tests/test_api/``, которым дедуп не интересен.
"""

from __future__ import annotations

import hashlib
import uuid
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from psycopg.errors import UniqueViolation

from src.config import settings
from src.intake.repository import ON_DUPLICATE
from src.tenancy.api_keys import ApiKeyRecord

_BODY = b"the very same body"
_SHA = hashlib.sha256(_BODY).hexdigest()

# Фидер: заливать можно, читать — нельзя.  `tenant_id='default'` — тот же
# арендатор, что у графа по умолчанию, иначе отказ пришёл бы раньше дедупа.
_WRITE_ONLY = ApiKeyRecord(
    owner="feeder", tenant_id="default", scopes=frozenset({"write"}), graph_ids=None,
)


class _Store:
    """Хранилище ключей на один ключ — по образцу tests/test_api/test_graph_binding."""

    def __init__(self, rec: ApiKeyRecord):
        self.rec = rec

    async def lookup(self, _raw: str) -> ApiKeyRecord:
        return self.rec


def _api_key_header() -> dict[str, str]:
    return {"X-API-Key": settings.api.keys_list[0]}


def no_duplicate():
    """Подмена дедупа для тестов, которым он не интересен.

    Маршрут читает ``documents`` по ``content_sha256`` ДО заливки в MinIO,
    поэтому без этой подмены любой тест приёма пошёл бы в живой Postgres.
    Тело у них всегда новое — чтение отвечает «не найдено».  Хелпер лежит
    рядом с самими тестами дедупа и импортируется из ``tests/test_api/``,
    как ``tests/test_retrieval`` берёт фейки из ``tests/test_graph``.
    """
    from src.intake.repository import IntakeRepository

    return patch.object(
        IntakeRepository, "find_by_sha", new=AsyncMock(return_value=None),
    )


def _canon(
    doc_id: uuid.UUID, intake_status: str = "accepted", *, path: str | None = None,
) -> Any:
    """Владелец тела, каким его возвращает чтение по хешу."""
    from src.intake.repository import CanonicalDoc

    return CanonicalDoc(
        doc_id, intake_status, path or f"s3://kb-uploads/{doc_id}/t.txt",
    )


@dataclass
class _Run:
    """Исход одного POST'а вместе со всеми подменёнными зависимостями."""

    resp: Any
    storage: MagicMock
    build: MagicMock
    find: AsyncMock
    accept: AsyncMock
    submit: AsyncMock
    sighting: AsyncMock

    @property
    def detail(self) -> dict[str, str]:
        return self.resp.json()["detail"]

    @property
    def doc_prefix(self) -> str:
        """Префикс документа в MinIO — из ключа, которым звали put_object."""
        key = self.storage.put_object.call_args_list[0].args[0]
        return f"{key.split('/')[0]}/"


async def _post(
    data: dict[str, str] | None = None,
    *,
    first: tuple[uuid.UUID, str] | None = None,
    first_path: str = "s3://kb-uploads/canon/t.txt",
    find: AsyncMock | None = None,
    accept: AsyncMock | None = None,
    body: bytes = _BODY,
    delete_error: Exception | None = None,
    key: ApiKeyRecord | None = None,
) -> _Run:
    """POST /api/v1/ingest с подменённой инфраструктурой.

    ``first`` — что находит ``find_by_sha`` (None = тело ещё не известно);
    ``find``/``accept`` — готовые моки, когда тесту нужен side_effect;
    ``delete_error`` — чем падает уборка префикса в MinIO;
    ``key`` — ключ с урезанными правами (None = обычный ключ из ``API_KEYS``,
    то есть ``ApiKeyRecord.full`` со всеми четырьмя действиями).
    """
    from src.api import auth
    from src.api.main import app
    from src.intake.repository import IntakeRepository

    storage = MagicMock()
    storage.put_object.side_effect = lambda key, *_a, **_k: f"s3://kb-uploads/{key}"
    storage.delete_prefix.side_effect = delete_error
    build = MagicMock(return_value=storage)
    canonical = _canon(*first, path=first_path) if first is not None else None
    find = find or AsyncMock(return_value=canonical)
    accept = accept or AsyncMock()
    submit = AsyncMock()
    sighting = AsyncMock()
    with (
        patch.object(auth, "get_api_key_store", lambda: _Store(key))
        if key is not None
        else nullcontext(),
        patch("src.intake.api.ingest.build_minio_storage", build),
        patch.object(IntakeRepository, "find_by_sha", find),
        patch.object(IntakeRepository, "accept_document", accept),
        patch(
            "src.intake.api.ingest.get_temporal_client",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch("src.intake.api.ingest.submit_document", submit),
        patch.object(IntakeRepository, "record_duplicate_sighting", sighting),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/ingest",
                headers=_api_key_header(),
                files={"file": ("t.txt", body, "text/plain")},
                data=data or {},
            )
    return _Run(resp, storage, build, find, accept, submit, sighting)


# ── политика по умолчанию: reject ────────────────────────────────────


@pytest.mark.asyncio
async def test_same_body_rejected_without_upload() -> None:
    first_id = uuid.uuid4()
    run = await _post(first=(first_id, "accepted"))

    assert run.resp.status_code == 409, run.resp.text
    assert run.detail == {
        "message": "duplicate",
        "doc_id": str(first_id),
        "intake_status": "accepted",
    }
    # Хеш считается от тела и ищется ДО любой работы с хранилищем.
    run.find.assert_awaited_once()
    assert run.find.await_args.args[0] == _SHA
    run.storage.put_object.assert_not_called()
    run.accept.assert_not_awaited()
    run.submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_different_body_passes() -> None:
    run = await _post(body=b"a brand new body")

    assert run.resp.status_code == 202, run.resp.text
    run.accept.assert_awaited_once()
    kwargs = run.accept.await_args.kwargs
    # Каноническая строка: хеш записан, ссылки на оригинал нет.
    assert kwargs["content_sha256"] == hashlib.sha256(b"a brand new body").hexdigest()
    assert kwargs["duplicate_of"] is None
    run.submit.assert_awaited_once()


@pytest.mark.asyncio
async def test_rejected_first_doc_still_blocks() -> None:
    """Отклонённый классификатором документ остаётся владельцем хеша.

    Предикат частичного уникального индекса смотрит на ``duplicate_of``,
    а не на ``intake_status``, именно поэтому: тело уже заливали, и 409
    отдаёт вердикт первого документа, чтобы оператор видел причину отказа,
    а не думал, что документ пропал.
    """
    first_id = uuid.uuid4()
    run = await _post(first=(first_id, "rejected"))

    assert run.resp.status_code == 409, run.resp.text
    assert run.detail["doc_id"] == str(first_id)
    assert run.detail["intake_status"] == "rejected"
    run.storage.put_object.assert_not_called()


@pytest.mark.asyncio
async def test_repost_in_another_channel_is_a_duplicate() -> None:
    """Канал в ключ дедупа НЕ входит — записанное решение, а не находка.

    Ключ — sha256 тела в пределах графа (I2/I3), поэтому дословный перепост
    во втором наблюдаемом канале получает 409 и своей строки не заводит:
    тело в базе знаний есть и находится поиском, но ``/stats/messages`` по
    каналу-получателю перепосты недосчитывает.  Синк считает 409 успехом
    прохода и двигает курсор (повтор ничего бы не изменил — тело то же),
    поэтому цена решения именно такая и описана в
    docs/runbook/message-stats.md вместе с двумя альтернативами.

    Тест фиксирует текущее поведение: он обязан упасть, если ключ дедупа
    когда-нибудь сузят до ``(тело, канал)`` — тогда правку ждут и спека, и
    runbook, и этот тест.
    """
    first_id = uuid.uuid4()
    run = await _post({"channel": "second_channel"}, first=(first_id, "accepted"))

    assert run.resp.status_code == 409, run.resp.text
    assert run.detail["doc_id"] == str(first_id)
    # Канал в поиск по хешу не передаётся вовсе — аргумент один.
    assert run.find.await_args.args == (_SHA,)
    run.accept.assert_not_awaited()
    run.submit.assert_not_awaited()


# ── что именно раскрывает тело 409 ───────────────────────────────────


@pytest.mark.asyncio
async def test_write_only_key_gets_no_ids_in_the_409_body() -> None:
    """Идентификаторы в теле 409 — право ЧТЕНИЯ, а не приёма.

    Маршрут объявляет действие ``write``, и тот же write-only ключ получает
    403 и на ``GET /api/v1/ingest/{doc_id}``, и на
    ``GET /api/v1/documents/{doc_id}``.  Раскрывать ему здесь ``doc_id`` и
    вердикт приёма документа, который ему читать не разрешено, значило бы
    обходить своё же правило, поэтому остаётся голое ``duplicate``.
    """
    first_id = uuid.uuid4()
    run = await _post(first=(first_id, "accepted"), key=_WRITE_ONLY)

    assert run.resp.status_code == 409, run.resp.text
    assert run.detail == {"message": "duplicate"}
    assert str(first_id) not in run.resp.text
    # Отказ остаётся отказом приёма: ни хранилища, ни строки, ни очереди.
    run.build.assert_not_called()
    run.accept.assert_not_awaited()
    run.submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_write_only_key_gets_no_ids_in_the_race_409_either() -> None:
    """Вторая ветка отказа (гонка на UniqueViolation) — то же решение."""
    winner = uuid.uuid4()
    run = await _post(
        find=AsyncMock(side_effect=[None, _canon(winner)]),
        accept=AsyncMock(side_effect=UniqueViolation("documents_sha_idx")),
        key=_WRITE_ONLY,
    )

    assert run.resp.status_code == 409, run.resp.text
    assert run.detail == {"message": "duplicate"}
    assert str(winner) not in run.resp.text
    # Уборка за собой от прав ключа не зависит.
    run.storage.delete_prefix.assert_called_once_with(run.doc_prefix)


@pytest.mark.asyncio
async def test_key_with_read_still_sees_the_first_doc() -> None:
    """Ключ фидера со scope ``read`` читает ответ целиком — как раньше."""
    first_id = uuid.uuid4()
    reader_writer = ApiKeyRecord(
        owner="feeder", tenant_id="default",
        scopes=frozenset({"read", "write"}), graph_ids=None,
    )
    run = await _post(first=(first_id, "rejected"), key=reader_writer)

    assert run.resp.status_code == 409, run.resp.text
    assert run.detail == {
        "message": "duplicate",
        "doc_id": str(first_id),
        "intake_status": "rejected",
    }


@pytest.mark.asyncio
async def test_hash_computed_before_put_object() -> None:
    """При найденном дубле ``build_minio_storage`` не звали ВОВСЕ.

    Отдельно от ``put_object``: конструктор хранилища на холодном старте
    сам ходит в сеть (``bucket_exists``), так что «не залили» — ещё не
    «не потревожили MinIO».
    """
    run = await _post(first=(uuid.uuid4(), "accepted"))

    assert run.resp.status_code == 409, run.resp.text
    run.build.assert_not_called()


# ── выбор политики: явное значение, backfill, force ──────────────────


@pytest.mark.asyncio
async def test_on_duplicate_version_creates_second_row() -> None:
    first_id = uuid.uuid4()
    run = await _post({"on_duplicate": "version"}, first=(first_id, "accepted"))

    assert run.resp.status_code == 202, run.resp.text
    run.accept.assert_awaited_once()
    kwargs = run.accept.await_args.kwargs
    assert kwargs["duplicate_of"] == first_id
    # Маршрут передаёт хеш всегда, одним и тем же accept_kwargs; в СТРОКУ
    # версии он не попадёт — инвариант «хеш у канонической строки» держит
    # accept_document (tests/test_intake/test_repository.py
    # ::test_accept_nulls_sha_on_version_row).
    assert kwargs["content_sha256"] == _SHA
    # Версия — полноценный документ: она идёт в пайплайн.
    run.submit.assert_awaited_once()


@pytest.mark.asyncio
async def test_backfill_true_defaults_to_version() -> None:
    """``backfill=true`` без явной политики переингестит, а не 409'ит.

    Флаг задокументирован как «Re-ingest of already-known material» и его
    шлют операторские перезаливки; с умолчанием reject он стал бы no-op'ом.
    """
    first_id = uuid.uuid4()
    run = await _post({"backfill": "true"}, first=(first_id, "accepted"))

    assert run.resp.status_code == 202, run.resp.text
    assert run.accept.await_args.kwargs["duplicate_of"] == first_id


@pytest.mark.asyncio
async def test_explicit_on_duplicate_overrides_backfill() -> None:
    run = await _post(
        {"backfill": "true", "on_duplicate": "reject"},
        first=(uuid.uuid4(), "accepted"),
    )

    assert run.resp.status_code == 409, run.resp.text
    run.accept.assert_not_awaited()


@pytest.mark.asyncio
async def test_force_does_not_affect_dedup() -> None:
    """``force`` — переключатель ТОЛЬКО классификатора (I4).

    Ни на выбор политики, ни на сам дедуп он не влияет: на дубле всё равно
    409, а на новом теле просто уезжает в IngestParams.
    """
    dup = await _post({"force": "true"}, first=(uuid.uuid4(), "accepted"))
    assert dup.resp.status_code == 409, dup.resp.text
    dup.accept.assert_not_awaited()

    fresh = await _post({"force": "true"}, body=b"not seen before")
    assert fresh.resp.status_code == 202, fresh.resp.text
    assert fresh.submit.await_args.args[1].force is True


# ── неизвестные значения политики ────────────────────────────────────


@pytest.mark.asyncio
async def test_replace_is_rejected_for_now() -> None:
    """Политика ``replace`` осознанно отложена (§2.2 спеки).

    Ни один путь чтения не смотрит в ``documents``, поэтому три
    Postgres-оператора вытеснения не убрали бы ни чанка из Milvus, ни узла
    из графа: обе копии остались бы одинаково находимыми, а Postgres
    объявлял бы одну дубликатом.  Пока этого нет — значение неизвестное.
    """
    run = await _post({"on_duplicate": "replace"}, first=(uuid.uuid4(), "accepted"))

    assert run.resp.status_code == 422, run.resp.text
    assert "reject" in run.resp.text and "version" in run.resp.text
    assert ON_DUPLICATE == ("reject", "version")
    # Отказ до чтения тела: ни хеша, ни хранилища.
    run.find.assert_not_awaited()
    run.build.assert_not_called()


@pytest.mark.asyncio
async def test_empty_on_duplicate_is_not_a_policy() -> None:
    """Пустое поле формы = «не указано», а не неизвестная политика.

    Клиент, который шлёт все поля формы незаполненными, не должен получать
    422 на поле, которого он не заполнял: умолчание выбирается по
    вызывающему ровно так же, как если бы поля не было вовсе.  Пробел
    проверяется отдельно: пустое значение маршрут снимает сам, а не
    полагается на то, что FastAPI подменит ``""`` на ``None``.
    """
    first_id = uuid.uuid4()
    for blank_value in ("", "  "):
        blank = await _post({"on_duplicate": blank_value}, first=(first_id, "accepted"))
        assert blank.resp.status_code == 409, blank.resp.text
        assert blank.detail["doc_id"] == str(first_id)

    # И умолчание backfill'а остаётся умолчанием backfill'а.
    with_backfill = await _post(
        {"on_duplicate": "", "backfill": "true"}, first=(first_id, "accepted"),
    )
    assert with_backfill.resp.status_code == 202, with_backfill.resp.text
    assert with_backfill.accept.await_args.kwargs["duplicate_of"] == first_id


@pytest.mark.asyncio
async def test_unknown_on_duplicate_422() -> None:
    run = await _post({"on_duplicate": "obliterate"}, first=(uuid.uuid4(), "accepted"))

    assert run.resp.status_code == 422, run.resp.text
    assert "reject" in run.resp.text and "version" in run.resp.text
    run.find.assert_not_awaited()
    run.build.assert_not_called()
    run.accept.assert_not_awaited()


# ── гонка двух одновременных POST'ов ─────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_insert_loses_on_unique_violation() -> None:
    """Гонку закрывает индекс, а не чтение: проигравший отдаёт 409, не 500.

    Чтение не нашло ничего (оба POST'а пришли на неизвестное тело), но к
    моменту INSERT'а строка победителя уже есть — частичный уникальный
    индекс и называет победителя.  Объекты в MinIO к этому моменту
    записаны, а строки не будет никогда, поэтому префикс документа
    убирается: иначе он остался бы мусором, видимым только при удалении
    всего графа.
    """
    winner = uuid.uuid4()
    run = await _post(
        find=AsyncMock(side_effect=[None, _canon(winner)]),
        accept=AsyncMock(side_effect=UniqueViolation("documents_sha_idx")),
    )

    assert run.resp.status_code == 409, run.resp.text
    assert run.detail["doc_id"] == str(winner)
    assert run.detail["intake_status"] == "accepted"
    # Победителя перечитали, а не угадали.
    assert run.find.await_count == 2
    # Уборка за собой — best-effort, но она обязана быть.
    run.storage.delete_prefix.assert_called_once_with(run.doc_prefix)
    run.submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_insert_under_version_retries_once() -> None:
    """Под ``version`` та же гонка не 500'ит, а повторяет вставку.

    Чтение ничего не нашло → INSERT пошёл с ``duplicate_of=NULL`` и попал
    в тот же индекс.  Повтор ОДИН раз, сославшись на победителя; второй
    UniqueViolation был бы настоящей аномалией и всплыл бы как 500.
    """
    winner = uuid.uuid4()
    run = await _post(
        {"on_duplicate": "version"},
        find=AsyncMock(side_effect=[None, _canon(winner)]),
        accept=AsyncMock(side_effect=[UniqueViolation("documents_sha_idx"), None]),
    )

    assert run.resp.status_code == 202, run.resp.text
    assert run.accept.await_count == 2
    assert run.accept.await_args_list[0].kwargs["duplicate_of"] is None
    assert run.accept.await_args_list[1].kwargs["duplicate_of"] == winner
    # Строка есть — убирать объекты нечего.
    run.storage.delete_prefix.assert_not_called()
    run.submit.assert_awaited_once()


@pytest.mark.asyncio
async def test_cleanup_failure_still_answers_409() -> None:
    """Уборка в MinIO — best-effort: её падение не превращает 409 в 500."""
    winner = uuid.uuid4()
    run = await _post(
        find=AsyncMock(side_effect=[None, _canon(winner)]),
        accept=AsyncMock(side_effect=UniqueViolation("documents_sha_idx")),
        delete_error=OSError("minio gone"),
    )

    assert run.resp.status_code == 409, run.resp.text
    assert run.detail["doc_id"] == str(winner)
    run.storage.delete_prefix.assert_called_once()


# ── наблюдение перепоста ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_repost_from_another_channel_records_a_sighting() -> None:
    """Перепост: работы нет, но канал-получатель остаётся в числах.

    Ключ дедупа — sha256 ТЕЛА в пределах графа, канал в него не входит,
    поэтому дословный перепост во втором наблюдаемом канале получает 409 и
    второй копии в графе не создаёт.  Чтобы канал не исчез из отчётности,
    приём пишет лёгкую строку-ссылку на тот же объект в MinIO.
    """
    first_id = uuid.uuid4()
    run = await _post(
        {"channel": "beta", "group": "news"},
        first=(first_id, "accepted"),
        first_path="s3://kb-uploads/canon/t.txt",
    )

    assert run.resp.status_code == 409, run.resp.text
    run.sighting.assert_awaited_once()
    kwargs = run.sighting.await_args.kwargs
    args = run.sighting.await_args.args
    # Ссылка на канонический документ и на ЕГО объект: второго тела в
    # хранилище не появляется.
    assert args[1] == first_id
    assert args[2] == "s3://kb-uploads/canon/t.txt"
    assert kwargs["source_channel"] == "beta"
    assert kwargs["source_group"] == "news"
    # Ни хранилища, ни очереди, ни строки обработки.
    run.build.assert_not_called()
    run.storage.put_object.assert_not_called()
    run.accept.assert_not_awaited()
    run.submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_duplicate_without_attribution_records_nothing() -> None:
    """Повторная ручная заливка того же файла — не перепост.

    Без канала и группы наблюдение ничего бы не добавило ни одной
    поверхности (обе группировки отчётности идут по ним), а строк в
    ``documents`` стало бы больше на каждый повторный прогон
    ``scripts/ingest_medical.py``.  Поэтому пишем только атрибутированный
    повтор.
    """
    run = await _post(first=(uuid.uuid4(), "accepted"))

    assert run.resp.status_code == 409, run.resp.text
    run.sighting.assert_not_awaited()


@pytest.mark.asyncio
async def test_sighting_is_not_recorded_under_version_policy() -> None:
    """Под `version` документ создаётся по-настоящему — наблюдение излишне."""
    run = await _post(
        {"channel": "beta", "on_duplicate": "version"},
        first=(uuid.uuid4(), "accepted"),
    )

    assert run.resp.status_code == 202, run.resp.text
    run.sighting.assert_not_awaited()
    run.accept.assert_awaited_once()


@pytest.mark.asyncio
async def test_race_under_reject_also_records_a_sighting() -> None:
    """Гонка приводит к тому же итогу, что и обычный дубль.

    Победителя называет БД, и перепост второго канала не должен пропадать
    только потому, что оба POST'а пришли одновременно.
    """
    winner_id = uuid.uuid4()
    find = AsyncMock(side_effect=[None, _canon(winner_id)])
    run = await _post(
        {"channel": "beta"},
        find=find,
        accept=AsyncMock(side_effect=UniqueViolation("duplicate key")),
    )

    assert run.resp.status_code == 409, run.resp.text
    run.sighting.assert_awaited_once()
    assert run.sighting.await_args.args[1] == winner_id
    # Объекты, записанные до проигранной гонки, убраны (§1a C).
    run.storage.delete_prefix.assert_called_once()
    run.submit.assert_not_awaited()


# ── атрибуция источника ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_source_kind_names_the_key_that_wrote(monkeypatch) -> None:
    """Кто принёс документ, видно в строке, а не в журнале.

    До этого шага ``source_kind`` был константой 'upload' у всех, то есть
    по строке нельзя было отличить фидера от ручной заливки и нельзя было
    отозвать один источник, не сломав остальные.  Личность — владелец
    ключа (``api_keys.owner``), реестр ключей и есть реестр источников
    (вариант A шага 1.4).
    """
    run = await _post({"channel": "beta"}, body=b"a body from a feeder", key=_WRITE_ONLY)

    assert run.resp.status_code == 202, run.resp.text
    assert run.accept.await_args.kwargs["source_kind"] == "feeder"


@pytest.mark.asyncio
async def test_sighting_carries_the_same_source(monkeypatch) -> None:
    """Наблюдение перепоста — тоже приём, и его источник тот же."""
    run = await _post(
        {"channel": "beta"}, first=(uuid.uuid4(), "accepted"), key=_WRITE_ONLY,
    )

    assert run.resp.status_code == 409, run.resp.text
    assert run.sighting.await_args.kwargs["source_kind"] == "feeder"


@pytest.mark.asyncio
async def test_manual_upload_keeps_its_own_owner() -> None:
    """Ручная заливка legacy-ключом называет его владельца, а не 'upload'."""
    run = await _post(body=b"a manual body")

    assert run.resp.status_code == 202, run.resp.text
    assert run.accept.await_args.kwargs["source_kind"] == "legacy-env"
