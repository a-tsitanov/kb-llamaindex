# Арендаторы и авторизация доступа к графу — дизайн

Дата: 2026-10-18. Статус: **реализовано** (план
[`2026-10-18-tenancy-authz.md`](../plans/2026-10-18-tenancy-authz.md), шаги S1–S12).
Отклонения от буквы спеки и принятые остаточные риски перечислены в §10 плана.
Связано: `2026-09-24-multi-graph-design.md` (изоляция графов, Plan A + Plan B,
влито в main `c3191cef`), `docs/superpowers/plans/2026-10-17-project-boundaries.md`
(§2 — карта контуров).

## Задача

Сегодня графы изолированы физически, но не защищены: **любой валидный API-ключ
работает с любым графом**. Это прямое следствие амендмента 2026-10-17 «keys
authenticate only», который вынес контроль доступа «в отдельный слой». Слой не
построен, поэтому проверки нет нигде.

Конкретные последствия в текущем коде:

- `GET /admin/graphs` любым ключом перечисляет все графы системы со slug'ами;
- `DELETE /admin/graphs/{id}?confirm=<id>` любым ключом запускает
  `DeleteGraphWorkflow`: снос пространства Nebula, коллекций Milvus, схемы
  Postgres и префикса MinIO **чужого** графа;
- `X-Graph: <чужой_slug>` на любом маршруте данных отдаёт чужие документы,
  сущности и оригиналы файлов.

Критерий успеха: ключ арендатора A не может ни прочитать, ни изменить, ни даже
обнаружить существование графа арендатора B — ни через HTTP, ни через MCP, ни
через админские маршруты.

## Отношение к амендменту 2026-10-17

Амендмент сохраняется в части «политика может жить снаружи» и отменяется в части
«проверки в этом сервисе нет».

Разделение, на котором стоит дизайн:

- **Политика** (кто чей арендатор, какие права) — за подменяемым интерфейсом.
  Версия 1 читает собственные таблицы; версия 2 сможет читать claims внешнего
  провайдера, не трогая точки применения.
- **Применение** — обязано быть внутри сервиса. Снаружи его не поставить: MCP
  резолвит граф на каждый вызов инструмента, фидеры и воркеры ходят внутри сети
  мимо любого шлюза, а доставка уведомлений вообще не имеет входящего запроса.

## Решения

| # | Решение |
|---|---|
| A1 | Субъект прав — **API-ключ**. Пользователей и ролей внутри арендатора нет: человеку, фидеру, боту, агенту выписывается свой ключ. |
| A2 | Ключ принадлежит арендатору; граф принадлежит арендатору. Ключ не адресует граф чужого арендатора даже зная slug. |
| A3 | Права на ключе — множество действий (`scopes`) плюс необязательное сужение до конкретных графов (`graph_ids`); `NULL` = все графы своего арендатора. |
| A4 | Действия: `read`, `write`, `download_original`, `admin`. `download_original` отделён от `read` намеренно. |
| A5 | **Арендатор создаётся только скриптом на хосте.** HTTP-маршрута для создания арендатора и выписки ключа не существует. |
| A6 | `admin` действует только внутри своего арендатора. Платформенного суперключа нет. |
| A7 | Выкат через наследование и флаг: существующие ключи попадают в арендатора `default` со всеми правами; режим `AUTHZ_MODE` позволяет сутки смотреть отказы, не выдавая их. |
| A8 | Авторизации в воркере нет: `graph_id` в входах воркфлоу уже пришёл из авторизованного входа. |

## 1. Модель данных

Всё в схеме `public` — это директория, а не данные графа.

```sql
CREATE TABLE IF NOT EXISTS public.tenants (
    id         TEXT PRIMARY KEY,                 -- slug, те же правила, что у graph id
    name       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.graphs
    ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default'
    REFERENCES public.tenants(id);

ALTER TABLE public.api_keys
    ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default'
    REFERENCES public.tenants(id);
ALTER TABLE public.api_keys
    ADD COLUMN IF NOT EXISTS scopes TEXT[] NOT NULL DEFAULT '{read}';
ALTER TABLE public.api_keys
    ADD COLUMN IF NOT EXISTS graph_ids TEXT[];    -- NULL = все графы своего арендатора

CREATE INDEX IF NOT EXISTS graphs_tenant_idx   ON public.graphs (tenant_id);
CREATE INDEX IF NOT EXISTS api_keys_tenant_idx ON public.api_keys (tenant_id);
```

`graphs.owner` остаётся как свободное описание и **перестаёт нести смысл
доступа**. Удалять его в этой итерации не будем: колонка читается в ответах
`/admin/graphs` и в тестах.

Порядок DDL важен: `tenants` создаётся и наполняется строкой `default` до того,
как внешние ключи добавляются к `graphs` и `api_keys`, иначе `ALTER` падает на
существующих строках.

`scopes` валидируется на запись (в репозитории, не в БД): множество из
`{read, write, download_original, admin}`, пустое запрещено.

### `ApiKeyRecord`

Сейчас — `owner: str`. Становится:

```python
@dataclass(frozen=True)
class ApiKeyRecord:
    owner: str
    tenant_id: str
    scopes: frozenset[str]
    graph_ids: tuple[str, ...] | None   # None = все графы арендатора
```

Кеш ключей в `src/tenancy/api_keys.py` уже есть (TTL); форма записи меняется,
механика кеша — нет.

## 2. Решение: `src/tenancy/authz.py`

Единственное место, где принимается решение.

```python
class Action(StrEnum):
    READ = "read"
    WRITE = "write"
    DOWNLOAD_ORIGINAL = "download_original"
    ADMIN = "admin"

@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str          # пусто при allowed

async def authorize(key: ApiKeyRecord, graph_id: str, action: Action) -> Decision
```

Правила, по порядку:

1. Действие не входит в `key.scopes` → отказ `scope`.
2. Граф не найден в реестре → отказ `unknown` (см. §5 про код ответа).
3. `graph.tenant_id != key.tenant_id` → отказ `tenant`.
4. `key.graph_ids is not None` и `graph_id` не в нём → отказ `graph`.
5. Иначе — разрешено.

Функция **не** ходит в сеть сверх того, что уже делает реестр графов: запись
ключа и запись графа обе читаются из кешей, которые есть.

Источник политики подменяем: `authorize` принимает уже загруженный
`ApiKeyRecord`. Когда права переедут во внешний токен, меняется только то, как
собирается `ApiKeyRecord` — точки применения не переписываются.

## 3. Точки применения

Швов ровно три. Проверено по коду 2026-10-18.

### 3.1 HTTP — `src/api/graph_dep.py`

Все маршруты данных уже без исключения проходят через `resolve_graph`:
`ingest`, `search_v2`, `analyze`, `documents`, `entities`, `stats`,
`stats_data`, `graph_admin`, `admin/wiki`, `admin/monitor`. Поэтому проверка
ставится в одном месте.

Вместо одной функции — фабрика:

```python
def graph_for(action: Action) -> Callable[..., Awaitable[GraphContext]]
resolve_graph = graph_for(Action.READ)      # имя сохраняется, умолчание read
```

Маршрут объявляет действие явно:

| Маршрут | Действие |
|---|---|
| `POST /ingest` | `write` |
| `GET /ingest/{job_id}` | `read` |
| `GET /documents/{doc_id}` | `download_original` |
| `POST /search/*`, `POST /analyze`, `GET /entities/*`, `GET /stats*` | `read` |
| `POST /stats/load` | `write` |
| `/admin/graph/*` (статистика, pagerank, компоненты, materialize) | `admin` |
| `/admin/wiki/*`, `/admin/monitor/*`, `POST /admin/communities/rebuild` | `admin` |

`GET /documents/{doc_id}?variant=text` тоже требует `download_original`:
выдаётся полный текст документа, а не фрагмент. Разделять два варианта одного
маршрута разными правами — ложная точность.

### 3.2 MCP — `src/mcp/_shared.py`

`current_graph()` резолвит граф **на каждый вызов инструмента** (заголовок
`X-Graph`, иначе `KB_MCP_GRAPH`). Значит и проверка — на каждый вызов; привязки
к соединению в текущей реализации нет.

`verify_token` кладёт `ApiKeyRecord` в `AccessToken`; `current_graph` читает его
оттуда и вызывает `authorize`. Умолчание — `read`; инструменты, меняющие
состояние (`kb_watch`, `kb_watch_ack`), объявляют `write`. Отказ — `ToolError`
с текстом, не раскрывающим чужой граф.

Режим без аутентификации (`KB_MCP_REQUIRE_AUTH=false`, stdio) остаётся как есть:
нет ключа — нет и проверки, это локальный режим разработки. Описать в
`docs/multi-graph-ops.md` как небезопасный для сетевого выката.

### 3.3 Управление графами — `src/api/routes/graphs_admin.py`

Единственный маршрутизатор мимо `resolve_graph`: он работает с самими графами,
а не внутри графа. Поэтому у него своя проверка.

| Маршрут | Поведение |
|---|---|
| `POST /admin/graphs` | требует `admin`; создаёт граф **в арендаторе ключа**, `tenant_id` из тела игнорируется |
| `GET /admin/graphs` | возвращает только графы своего арендатора |
| `GET /admin/graphs/{id}` | чужой или несуществующий → 404 |
| `PATCH /admin/graphs/{id}` | требует `admin` в своём арендаторе, иначе 404 |
| `DELETE /admin/graphs/{id}` | требует `admin` в своём арендаторе, иначе 404 |

Создания арендаторов здесь нет и не появится (A5).

### 3.4 Воркер — без изменений

`resolve_graph_for_activity(graph_id)` (≈25 мест) выполняется после
авторизации: `graph_id` попал во вход воркфлоу с авторизованного входа. Добавлять
проверку туда значит проверять решение, принятое системой, а не клиентом.

## 4. Создание арендатора — скрипт

`scripts/tenant_admin.py` (новый), подкоманды:

```
create  --id <slug> --name <name>
key     --tenant <slug> --owner <name> --scopes read,write[,download_original][,admin]
        [--graphs a,b]        # по умолчанию все графы арендатора
revoke  --key-hash <hash>
list                           # арендаторы, графы, ключи (хеши, не ключи)
```

Сырой ключ печатается один раз при создании и нигде не сохраняется — в БД лежит
только sha256. Подкоманда `create` идемпотентна по `id`.

## 5. Коды отказа

| Ситуация | HTTP | MCP |
|---|---|---|
| Нет `X-API-Key` | 401 | ошибка рукопожатия |
| Ключ неизвестен | 403 | ошибка рукопожатия |
| Неверный slug в `X-Graph` | 400 | `ToolError` |
| Граф не существует | 404 | `ToolError` |
| **Граф чужого арендатора** | **404** | `ToolError` с тем же текстом, что у несуществующего |
| Граф не `ready` | 409 | `ToolError` |
| Граф свой, но действие вне `scopes` | 403 | `ToolError` |
| Граф свой, но не в `graph_ids` ключа | 403 | `ToolError` |

Чужой граф отдаёт **404, а не 403**: 403 подтверждает, что такой граф есть.
Собственный граф без нужного права отдаёт 403 — здесь скрывать нечего.

## 6. Выкат

Настройка `AUTHZ_MODE` (`AuthzSettings`, env `AUTHZ_MODE`):

| Значение | Поведение |
|---|---|
| `off` | `authorize` не вызывается. Аварийный тумблер. |
| `log` | решение вычисляется, отказ **не выдаётся**; пишется строка `authz would-deny key_owner=… tenant=… graph=… action=… reason=…`. Умолчание на период выката. |
| `enforce` | отказ выдаётся. |

Бутстрап в `setup_db` (идемпотентный):

1. `public.tenants` ← строка `default`, имя «Default tenant».
2. Все существующие строки `graphs` и `api_keys` получают `tenant_id='default'`
   (через `DEFAULT` колонки, отдельный `UPDATE` не нужен).
3. Всем ключам, существовавшим до миграции, ставится
   `scopes = {read,write,download_original,admin}`. Это **единоразовый**
   `UPDATE`, а не часть идемпотентного DDL: иначе каждый запуск `setup_db`
   возвращал бы права, отозванные вручную.

   Отметка о выполнении — строка в новой таблице:

   ```sql
   CREATE TABLE IF NOT EXISTS public.schema_migration (
       name       TEXT PRIMARY KEY,
       applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
   );
   ```

   Шаг выполняется под именем `authz_grandfather_v1` и только если такой строки
   нет. Ключи, выписанные после миграции, проходят мимо: у них `scopes` задан
   при выписке.

   Легаси-ключи из env (`API_KEYS`, владелец `legacy-env`) пересоздаются
   `setup_db` при каждом запуске. Чтобы наследование не воскресало для них
   бесконечно, после `authz_grandfather_v1` вставка `legacy-env` ключей
   выписывает `scopes = {read,write,download_original,admin}` явно — они
   остаются полноправными, пока не переведены на выписанные ключи.

Последовательность на живом стенде: выкат с `AUTHZ_MODE=log` → сутки смотрим
журнал → разбираем каждую строку `would-deny` → `enforce`.

Проверить руками в режиме `log` два потребителя: бот (`BOT_GRAPH`, свой ключ) и
`tg_ingest` (нужен `write`).

## 7. Тесты (TDD, расширяем `tests/`)

- `tests/test_tenancy/test_authz.py` — таблица «права × граф × действие →
  решение», все пять правил §2 плюс `graph_ids=None`.
- `tests/test_api/test_graph_dep_authz.py` — параметризованный тест кодов из §5
  на реальном приложении FastAPI; отдельный случай: чужой граф даёт 404 и тело
  ответа не содержит slug.
- `tests/test_api/test_graphs_admin_tenancy.py` — список фильтруется по
  арендатору; `DELETE` чужого даёт 404 и **не запускает воркфлоу** (проверяется
  тем, что клиент Temporal не вызван).
- `tests/test_mcp/test_tool_authz.py` — инструмент чтения под ключом без `read`
  даёт `ToolError`; `kb_watch` под ключом без `write` даёт `ToolError`.
- `tests/test_scripts/test_tenant_admin.py` — `create` идемпотентен, `key`
  печатает сырой ключ один раз, в БД только хеш.
- `tests/test_storage/test_authz_migration.py` — повторный прогон бутстрапа не
  возвращает отозванные права.
- Режимы: тест, что при `AUTHZ_MODE=log` запрос проходит, но строка журнала
  написана; при `enforce` — отказ.

Живая проверка (после «да» пользователя): `scripts/smoke_graph_isolation.py`
расширяется вторым арендатором — ключ A не видит граф B ни в списке, ни по
прямому `X-Graph`.

## 8. Вне объёма

- Пользователи и роли внутри арендатора (A1 — субъект это ключ).
- Платформенный суперключ и создание арендаторов по HTTP (A5, A6).
- Внешний провайдер и JWT — интерфейс к этому готов, реализации нет.
- Квоты и честность приёма между арендаторами (остаётся в бэклоге мультиграфа,
  колонка `graphs.max_inflight` зарезервирована).
- Журнал выдач оригиналов — относится к контуру intake
  (`2026-10-17-project-boundaries.md` §7), не сюда.
- Проверка права при доставке уведомлений — контур наблюдения, P2.
- Отзыв прав на лету: кеш ключей имеет TTL, отзыв вступает в силу не мгновенно.
  Для v1 приемлемо; `revoke` + перезапуск даёт немедленный эффект.

## 9. Открытые вопросы

Нет. Решения A1–A8 приняты пользователем 2026-10-18.
