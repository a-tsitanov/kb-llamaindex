# MCP у фидера: управление источниками — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** харнесс может найти телеграм-каналы, показать их пользователю, после кода подтверждения подключить их в папку с историей в 100 сообщений, оценить качество канала и выставить ему доверие или выйти из него.

**Architecture:** реестр источников — новая таблица в схеме графа, владение у контура приёма (`src/intake/sources/`). MCP-сервер живёт В ПРОЦЕССЕ фидера (один токен = один поллер, значит один `TelegramClient`, разделяемый свипом и инструментами под блокировкой). Доверие канала доезжает до записи графа дополнительным полем контракта и подменяет групповое число в уже существующем механизме разрешения противоречий.

**Tech Stack:** Python 3.12, FastMCP (как `src/mcp/*_server.py`), Telethon, psycopg 3, Temporal (контракты), pytest.

**Spec:** `docs/superpowers/specs/2026-10-23-feeder-mcp-design.md`

## Global Constraints

- Запись в телеграм-аккаунт (вступление, правка папки, выход) — только с совпадающим **кодом подтверждения** из `sources_propose`; предложение одноразовое.
- Доверие действует **только вперёд**: уже записанные связи не перештамповываются и не переингестятся.
- Один аккаунт = один граф: MCP отказывает любому графу, кроме `KB_GRAPH` контейнера.
- Папки агент **не создаёт**; допустимые группы — ровно `GROUP_SET` (`src/retrieval/groups.py`): `news, analytics, digest, opinion, official, data`.
- Личность канала — `peer_id`; слаг (`@username`) — изменяемая подпись, история собирается по всем известным слагам.
- Право на инструменты — новое узкое действие `sources`, НЕ `admin`; проверка права не зависит от `AUTHZ_MODE` (как доставка наблюдения).
- Бутстрап новой подписки — 100 последних сообщений, через обычный `POST /ingest`.
- Пустой реестр = сегодняшнее поведение всей системы.
- Тесты: `uv run --extra dev pytest -q -p no:cacheprovider <путь>`; линт `uv run --extra dev ruff check <путь>`. Живые проверки стенда — только по отдельному разрешению пользователя.

## Review Focus

1. `sources_apply` с чужим, просроченным или уже использованным кодом — должен отказать и ничего не записать в аккаунт (Задача 5).
2. Токен с графом, отличным от `KB_GRAPH` фидера — отказ, а не запись строки реестра в чужую схему (Задача 3).
3. Flood-wait посреди подключения пачки — часть каналов подключена, часть нет; ответ обязан перечислить оба списка, а реестр содержать только подключённые (Задача 5).
4. Канал сменил `@username` между подключением и отчётом — отчёт и доверие продолжают работать по `peer_id`, история не теряется (Задачи 1, 7).
5. `source_trust_set` со значением вне 0..1 или на неизвестный канал — отказ с внятным текстом, таблица не меняется (Задача 6).

---

### Task 1: Реестр источников

**Files:**
- Modify: `src/storage/pg_schema.py` (новый `_SOURCE_DDL`, запись в `GRAPH_DDL` после `_DOCUMENT_DOWNLOAD_DDL`)
- Create: `src/intake/sources/__init__.py`, `src/intake/sources/repository.py`
- Test: `tests/test_intake/test_sources_repository.py`, `tests/test_scripts/test_setup_db_sources.py`

**Interfaces:**
- Consumes: `graph_connection`, `GraphContext` (как `src/intake/repository.py`).
- Produces:
  - `SourceRow` (NamedTuple): `peer_id: int`, `slug: str`, `title: str`, `group_name: str`, `trust: float | None`, `state: str`, `added_by: str`, `note: str`
  - `class SourceRepository(dsn=None, *, graph: GraphContext)` с методами:
    - `async add(peer_id, slug, title, group_name, *, added_by) -> None`
    - `async get(peer_id) -> SourceRow | None`
    - `async by_slug(slug) -> SourceRow | None`
    - `async list_active() -> list[SourceRow]`
    - `async set_trust(peer_id, trust: float | None) -> bool`
    - `async set_group(peer_id, group_name) -> bool`
    - `async mark_left(peer_id) -> bool`
    - `async trust_for_channel(slug) -> float | None`
    - `async slugs_of(peer_id) -> list[str]`
    - `async remember_slug(peer_id, slug) -> None`

- [ ] **Шаг 1: Написать падающие тесты DDL** в `tests/test_scripts/test_setup_db_sources.py`: `source` и `source_slug` создаются идемпотентно (`CREATE TABLE IF NOT EXISTS source (` и `source_slug` в `_SOURCE_DDL`), PK у `source` — `peer_id`, у `source_slug` — `(peer_id, slug)`, `state` под CHECK `('active','left')`, таблицы входят в `graph_tables()`.

- [ ] **Шаг 2: Прогнать — падает** `uv run --extra dev pytest -q tests/test_scripts/test_setup_db_sources.py` → FAIL (`_SOURCE_DDL` нет).

- [ ] **Шаг 3: Добавить `_SOURCE_DDL`** в `src/storage/pg_schema.py` и строку в `GRAPH_DDL`. Колонки `source`: `peer_id BIGINT PRIMARY KEY`, `slug TEXT NOT NULL`, `title TEXT NOT NULL DEFAULT ''`, `group_name TEXT NOT NULL`, `trust DOUBLE PRECISION`, `state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active','left'))`, `added_by TEXT NOT NULL DEFAULT ''`, `added_at TIMESTAMPTZ NOT NULL DEFAULT now()`, `left_at TIMESTAMPTZ`, `note TEXT NOT NULL DEFAULT ''`. Вторая таблица `source_slug (peer_id BIGINT NOT NULL, slug TEXT NOT NULL, seen_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (peer_id, slug))` — исторические слаги канала, по ним отчёт собирает документы. В комментарии DDL написать, почему личность — `peer_id`, а не слаг.

- [ ] **Шаг 4: Прогнать — проходит.**

- [ ] **Шаг 5: Написать падающие тесты репозитория** в `tests/test_intake/test_sources_repository.py` по образцу `tests/test_intake/test_repository.py` (фейковое соединение, сверка текста SQL и привязки значений): `add` пишет и строку `source`, и строку `source_slug` одной транзакцией; `set_trust(None)` сбрасывает к групповому; `mark_left` ставит `state='left'` и `left_at`, не удаляя строку; `trust_for_channel` ищет по слагу через `source_slug` и отдаёт `None`, когда строки нет или `state='left'`; `remember_slug` идемпотентен (`ON CONFLICT DO NOTHING`).

- [ ] **Шаг 6: Прогнать — падает.**

- [ ] **Шаг 7: Реализовать `SourceRepository`** в `src/intake/sources/repository.py`. Соединение — через `graph_connection(self._graph)`, как в `IntakeRepository`.

- [ ] **Шаг 8: Прогнать — проходит; линт.**

- [ ] **Шаг 9: Коммит** `feat(intake): реестр источников — таблица и репозиторий`

---

### Task 2: Доверие на канал доезжает до записи графа

**Files:**
- Modify: `src/analytics/source_trust.py`, `src/workflow/contracts.py` (`IngestParams`, `Ctx`), `src/intake/api/ingest.py` (сборка `IngestParams`), `src/workflow/activities/fetch_source.py` (две точки сборки `Ctx`), `src/workflow/activities/build_property_graph.py:113-130`
- Test: `tests/test_analytics/test_source_trust.py`, `tests/test_workflow/test_build_property_graph.py`, `tests/test_api/test_ingest_source_channel.py`

**Interfaces:**
- Consumes: `SourceRepository.trust_for_channel` (Задача 1).
- Produces: `trust_for(group: str, channel_trust: float | None = None) -> float` — канальное число побеждает групповое; `IngestParams.channel: str = ""`, `Ctx.channel: str = ""`.

- [ ] **Шаг 1: Написать падающие тесты `trust_for`**: `trust_for("news", channel_trust=0.9) == 0.9`; `trust_for("news", channel_trust=None)` берёт групповое; `channel_trust` вне диапазона зажимается в 0..1; `trust_for("")` без канала — умолчание.

- [ ] **Шаг 2: Прогнать — падает** (лишний аргумент).

- [ ] **Шаг 3: Расширить `trust_for`** вторым необязательным аргументом. Модуль остаётся чистым: никакого ввода-вывода, число приносит вызывающий.

- [ ] **Шаг 4: Прогнать — проходит.**

- [ ] **Шаг 5: Написать падающий тест протаскивания канала**: в `tests/test_api/test_ingest_source_channel.py` добавить проверку, что `submit_document` получает `IngestParams.channel`, равный полю формы `channel`; в `tests/test_workflow/test_build_property_graph.py` — что активность зовёт `trust_for` с `channel_trust`, прочитанным по `ctx.channel`.

- [ ] **Шаг 6: Прогнать — падает.**

- [ ] **Шаг 7: Добавить поле `channel`** в `IngestParams` и `Ctx` (дополнительное, с умолчанием `""` — летящие сообщения очереди десериализуются по-прежнему); передать его в `src/intake/api/ingest.py` рядом с `group=group` и перенести в `Ctx` в обеих точках `fetch_source`.

- [ ] **Шаг 8: Открыть ворота конфликтного пути по документу** в `build_property_graph`: прочитать `channel_trust = await SourceRepository(graph=graph).trust_for_channel(ctx.channel)` (пустой канал → `None`), условие стало `if relations and (settings.signals.source_trust or channel_trust is not None)`, вызов — `trust_for(ctx.group, channel_trust)`. В комментарии написать, почему ворота по документу, а не по наличию строк в реестре.

- [ ] **Шаг 9: Прогнать оба файла тестов — проходят; линт.**

- [ ] **Шаг 10: Коммит** `feat(intake): доверие на канал участвует в разрешении противоречий`

---

### Task 3: Право `sources` и отказ чужому графу

**Files:**
- Modify: `src/tenancy/authz.py` (`Action`), `docs/multi-graph-ops.md` (§4 — перечень действий)
- Create: `src/intake/sources/auth.py`
- Test: `tests/test_tenancy/test_authz_sources.py`, `tests/test_intake/test_sources_auth.py`

**Interfaces:**
- Consumes: `Action`, `authorize` (`src/tenancy/authz.py`), `_record_from_token`, `get_access_token` (`src/mcp/_shared.py`).
- Produces: `async require_sources_access(feeder_graph_id: str) -> GraphContext` — возвращает контекст графа фидера либо бросает `ToolError`.

- [ ] **Шаг 1: Написать падающие тесты прав**: `Action.SOURCES == "sources"`; ключ с `scopes={'read','write'}` НЕ проходит `authorize(..., Action.SOURCES)`; ключ с `sources` проходит; ключ чужого арендатора не проходит.

- [ ] **Шаг 2: Прогнать — падает.**

- [ ] **Шаг 3: Добавить `SOURCES = "sources"`** в `Action` и строку в таблицу действий `docs/multi-graph-ops.md`.

- [ ] **Шаг 4: Прогнать — проходит.**

- [ ] **Шаг 5: Написать падающие тесты шва** в `tests/test_intake/test_sources_auth.py`: без токена — `ToolError`; токен с графом, отличным от графа фидера, — `ToolError` с текстом про чужой граф и **без** обращения к реестру; токен без права `sources` — `ToolError` даже при `AUTHZ_MODE=log` (в этом и смысл: зовётся `authorize`, не `guard`); токен с правом и своим графом — возвращается `GraphContext`.

- [ ] **Шаг 6: Прогнать — падает.**

- [ ] **Шаг 7: Реализовать `require_sources_access`** в `src/intake/sources/auth.py`: взять токен, получить запись ключа, сверить запрошенный граф (заголовок `X-Graph`, если есть) с `feeder_graph_id`, позвать `authorize(record, feeder_graph_id, tenant, Action.SOURCES)`. В докстринге — почему `authorize`, а не `guard`.

- [ ] **Шаг 8: Прогнать — проходит; линт.**

- [ ] **Шаг 9: Коммит** `feat(tenancy): узкое право sources и шов доступа у фидера`

---

### Task 4: Телеграм-операции под разделяемым клиентом

**Files:**
- Create: `src/intake/sources/telegram.py`
- Test: `tests/test_intake/test_sources_telegram.py`

**Interfaces:**
- Consumes: `dialog_slug`, `resolve_folders`, `resolve_group_map`, `_filter_title` (`scripts/tg_ingest.py`).
- Produces:
  - `class TelegramOps(client, lock)` с методами:
    - `async search(query: str, limit: int) -> list[Candidate]`
    - `async resolve(handle: str) -> Candidate | None`
    - `async join(peer_id: int) -> None`
    - `async add_to_folder(peer_id: int, folder: str) -> None`
    - `async remove_from_folder(peer_id: int, folder: str) -> None`
    - `async leave(peer_id: int) -> None`
    - `async folders() -> list[str]`
  - `Candidate` (NamedTuple): `peer_id: int`, `slug: str`, `title: str`, `participants: int | None`, `public: bool`
  - `class FloodWait(RuntimeError)` с полем `seconds: int`

- [ ] **Шаг 1: Написать падающие тесты** с фейковым клиентом (как `_FakeMsg`/`_Client` в `tests/test_scripts/test_tg_ingest*.py`): `search` отдаёт только публичные каналы и не больше `limit`; `resolve` принимает `@handle`, `handle` и ссылку `https://t.me/handle`, на несуществующем отдаёт `None`; `add_to_folder` читает текущий фильтр, добавляет пира и пишет фильтр обратно (read-modify-write, остальные пиры целы); `add_to_folder` на несуществующую папку бросает ошибку и НЕ создаёт её; `join` на `FloodWaitError` телеграма поднимает `FloodWait` с секундами; каждый метод берёт блокировку (фейк проверяет, что при занятой блокировке вызов ждёт).

- [ ] **Шаг 2: Прогнать — падает.**

- [ ] **Шаг 3: Реализовать `TelegramOps`.** Блокировка — `asyncio.Lock`, переданный конструктором: свип и инструменты делят один клиент, и одновременные запросы к MTProto недопустимы. Операции: `contacts.Search` для поиска, `ResolveUsernameRequest` для разбора, `JoinChannelRequest`, `GetDialogFiltersRequest` + `UpdateDialogFilterRequest` для папок, `LeaveChannelRequest` для выхода.

- [ ] **Шаг 4: Прогнать — проходит; линт.**

- [ ] **Шаг 5: Коммит** `feat(intake): телеграм-операции над источниками под общей блокировкой`

---

### Task 5: Предложение с кодом и подключение

**Files:**
- Create: `src/intake/sources/proposals.py`, `src/intake/sources/service.py`
- Test: `tests/test_intake/test_sources_proposals.py`, `tests/test_intake/test_sources_apply.py`

**Interfaces:**
- Consumes: `TelegramOps` (Задача 4), `SourceRepository` (Задача 1), общий клиент приёма `src/intake/client.py::post_document`.
- Produces:
  - `class ProposalStore(ttl_s: int = 900, clock=time.monotonic)`: `create(items: list[ProposalItem]) -> Proposal`, `take(proposal_id: str, code: str) -> Proposal` (одноразово; бросает `BadProposal`)
  - `Proposal`: `id: str`, `code: str`, `items: list[ProposalItem]`
  - `ProposalItem`: `peer_id: int`, `slug: str`, `title: str`, `group_name: str`
  - `class BadProposal(ValueError)`
  - `async apply_proposal(store, ops, repo, proposal_id, code, peer_ids, *, added_by, bootstrap) -> ApplyResult`
  - `ApplyResult`: `connected: list[int]`, `skipped: list[tuple[int, str]]`, `bootstrapped: int`

- [ ] **Шаг 1: Написать падающие тесты предложений**: код из `create` — шесть символов, непохожих на похожие (`0OIl1` исключены); `take` с верным кодом отдаёт предложение; второй `take` того же предложения — `BadProposal`; `take` с чужим кодом — `BadProposal`; просроченное (часы сдвинуты фейковыми) — `BadProposal`; группа каждого элемента обязана быть из `GROUP_SET`, иначе `create` отказывает.

- [ ] **Шаг 2: Прогнать — падает.**

- [ ] **Шаг 3: Реализовать `ProposalStore`** в памяти процесса (одного фидера достаточно: предложение живёт минуты). Код генерируется `secrets.choice`.

- [ ] **Шаг 4: Прогнать — проходит.**

- [ ] **Шаг 5: Написать падающие тесты подключения** в `tests/test_intake/test_sources_apply.py` с фейковыми `TelegramOps` и репозиторием: при верном коде канал вступлен, положен в папку из ПРЕДЛОЖЕНИЯ (не из аргумента), строка реестра записана с `added_by`, подтянуто `bootstrap` сообщений через клиент приёма; при неверном коде — ни одного вызова в телеграм и пустой реестр; `FloodWait` на втором канале из трёх — первый в `connected`, второй и третий в `skipped` с причиной, реестр содержит только первый; канал, уже подключённый и `state='left'`, подключается заново и становится `active`.

- [ ] **Шаг 6: Прогнать — падает.**

- [ ] **Шаг 7: Реализовать `apply_proposal`** в `src/intake/sources/service.py`: взять предложение, по каждому выбранному пиру — `join`, `add_to_folder`, `repo.add`, затем бутстрап (прочитать последние `bootstrap` сообщений и отправить их через `post_document` с полями `channel`, `group`, `document_date`). `FloodWait` прекращает обход и наполняет `skipped`, а не роняет вызов.

- [ ] **Шаг 8: Прогнать — проходит; линт.**

- [ ] **Шаг 9: Коммит** `feat(intake): подключение источников по коду подтверждения`

---

### Task 6: Перенос, выход и доверие

**Files:**
- Modify: `src/intake/sources/service.py`
- Test: `tests/test_intake/test_sources_service.py`

**Interfaces:**
- Produces: `async move_source(store, ops, repo, proposal_id, code, peer_id, folder) -> None`, `async leave_source(store, ops, repo, proposal_id, code, peer_id) -> None`, `async set_source_trust(repo, peer_id, trust: float | None) -> SourceRow`

- [ ] **Шаг 1: Написать падающие тесты**: `move_source` убирает пира из старой папки, кладёт в новую, обновляет `group_name`, и курсор диалога не трогается (проверка: в фейке нет вызовов, меняющих состояние синка); `move_source` в несуществующую папку — отказ, аккаунт не изменён; `leave_source` вызывает выход, ставит `state='left'`, документы не трогает (репозиторий приёма не вызывается вовсе); `set_source_trust(0.9)` пишет значение; `set_source_trust(1.5)` и `set_source_trust(-0.1)` — отказ `ValueError`, таблица не меняется; `set_source_trust` на неизвестный `peer_id` — отказ; `set_source_trust(None)` сбрасывает к групповому; перенос и выход требуют кода подтверждения (без него — `BadProposal`).

- [ ] **Шаг 2: Прогнать — падает.**

- [ ] **Шаг 3: Реализовать три функции.**

- [ ] **Шаг 4: Прогнать — проходит; линт.**

- [ ] **Шаг 5: Коммит** `feat(intake): перенос, выход и доверие источника`

---

### Task 7: Отчёт по каналу

**Files:**
- Create: `src/intake/sources/report.py`
- Test: `tests/test_intake/test_sources_report.py`

**Interfaces:**
- Consumes: `SourceRepository.slugs_of` (Задача 1).
- Produces: `async channel_report(graph, peer_id, *, days: int = 30) -> dict` с ключами `volume`, `fate`, `origin`, `reposts_of`, `contradictions`, `graph_yield`, `coverage`, `trust`.

- [ ] **Шаг 1: Написать падающие тесты** (фейковое соединение с очередью наборов, как `tests/test_intake/test_intake_stats.py`): документы собираются по ВСЕМ слагам пира, не только по текущему; `origin` различает «принёс тело первым» (строки с хешем) и «перепост» (`intake_status='duplicate'`); `reposts_of` отдаёт топ владельцев тел; `contradictions` считает отмены в обе стороны; `graph_yield` содержит `entities_per_doc` и `new_edges_per_doc`, причём у второго ключа в ответе стоит пометка `first_seen_only: True`; `trust` отдаёт отдельно `set` (выставленное) и `measured` (доля перепостов и частота отмен), и не смешивает их в одно число; пустой канал даёт нули, а не `None`.

- [ ] **Шаг 2: Прогнать — падает.**

- [ ] **Шаг 3: Реализовать `channel_report`.** Запросы к Postgres напрямую из фидера (решение спеки §9): реестр приёма, журналы наблюдения, журнал вытеснения фактов. В докстринге — почему `new_edges_per_doc` честно помечен «первая встреча».

- [ ] **Шаг 4: Прогнать — проходит; линт.**

- [ ] **Шаг 5: Коммит** `feat(intake): отчёт по каналу для оценки качества`

---

### Task 8: MCP-сервер в процессе фидера и выкат

**Files:**
- Create: `src/intake/sources/mcp_server.py`, `docs/runbook/feeder-sources.md`
- Modify: `scripts/tg_ingest.py` (хостинг сервера рядом со свипом), `docker-compose.tg-ingest.yml` (порт на loopback, env), `docs/CONTOURS.md` (строка про MCP фидера), `CHANGELOG.md`, `docs/BACKLOG.md` (снять задачу, оставить ссылку на спеку)
- Test: `tests/test_intake/test_sources_mcp.py`, `tests/test_scripts/test_tg_ingest_mcp_host.py`

**Interfaces:**
- Consumes: всё из Задач 1–7, `require_sources_access` (Задача 3).
- Produces: `build_sources_mcp(ops, repo_factory, store, feeder_graph_id) -> FastMCP` с инструментами `sources_list`, `sources_search`, `sources_resolve`, `sources_propose`, `sources_apply`, `source_move`, `source_leave`, `source_trust_set`, `source_report`, `feeder_status`; `async serve_sources_mcp(mcp, host, port) -> None`.

- [ ] **Шаг 1: Написать падающие тесты инструментов**: каждый инструмент зовёт `require_sources_access` ДО любой работы (фейк, который бросает, не даёт дойти до телеграма и базы); `sources_apply` и `source_leave` требуют код; `sources_list` отдаёт подключённые с группой, доверием и расхождением с папками Telegram (`in_folder: bool`); `feeder_status` отдаёт курсоры по диалогам, итог последнего раунда и найденные папки.

- [ ] **Шаг 2: Прогнать — падает.**

- [ ] **Шаг 3: Реализовать `build_sources_mcp`** по образцу `src/mcp/tools_server.py` (FastMCP, `@mcp.tool`), где каждый инструмент — тонкая обёртка над Задачами 1–7.

- [ ] **Шаг 4: Прогнать — проходит.**

- [ ] **Шаг 5: Написать падающий тест хостинга** в `tests/test_scripts/test_tg_ingest_mcp_host.py`: при `TG_SOURCES_MCP_PORT` фидер поднимает сервер задачей рядом со свипом и передаёт ему ТОТ ЖЕ `TelegramClient` и ту же блокировку; без переменной сервер не поднимается вовсе; падение сервера не роняет свип.

- [ ] **Шаг 6: Прогнать — падает.**

- [ ] **Шаг 7: Поднять сервер в `scripts/tg_ingest.py`** внутри `async with TelegramClient(...)`: создать `asyncio.Lock`, обернуть свип в ту же блокировку на время раунда, запустить сервер `asyncio.create_task`. В комментарии — почему в одном процессе: один токен = один поллер, второй клиент на той же сессии недопустим.

- [ ] **Шаг 8: Прогнать — проходит; полный прогон набора и линт.**

- [ ] **Шаг 9: Прокинуть порт и переменные** в `docker-compose.tg-ingest.yml`: `TG_SOURCES_MCP_PORT`, публикация **только на loopback** (`127.0.0.1:PORT:PORT`), `KB_MCP_REQUIRE_AUTH` по образцу `mcp-*`.

- [ ] **Шаг 10: Написать runbook** `docs/runbook/feeder-sources.md`: петля «пробел → поиск → список → код → подключение», что делает каждый инструмент, какое право нужно, что доверие действует только вперёд, что папки агент не создаёт, и таблица «не пришло уведомление/канал молчит — где смотреть». Строка в `docs/runbook/README.md`, строка про MCP фидера в `docs/CONTOURS.md`, раздел в `CHANGELOG.md`, в `docs/BACKLOG.md` задача помечена сделанной со ссылкой на спеку и план.

- [ ] **Шаг 11: Коммит** `feat(intake): MCP источников в процессе фидера + документация`

---

## Чего в плане нет

- Перештамп связей и переингест при смене доверия — отклонено пользователем (доверие только вперёд).
- Создание папок агентом — отклонено.
- Счётчик связей на документ (чтобы `new_edges_per_doc` перестал быть «первой встречей») — отдельная задача бэклога.
- Проброс принципала пользователя в харнесс (P3): пока его нет, роль «кто подтвердил» выполняет код подтверждения.
- Второй аккаунт и маршрутизация «папка → граф» — вне объёма (один аккаунт = один граф).
