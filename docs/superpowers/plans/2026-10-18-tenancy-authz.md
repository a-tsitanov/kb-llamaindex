# Арендаторы и авторизация доступа к графу — план реализации
Дата: 2026-10-18. Статус: **реализовано**, S1–S12, коммитов нет (коммитит пользователь).
Спека: [`2026-10-18-tenancy-authz-design.md`](../specs/2026-10-18-tenancy-authz-design.md). База: main `c3191cef`.
План составлен прогоном `code-plan`: разведка → план → независимый критик → ревизия. Семь возражений, из них два блокирующих; разбор в §5.
Что сделано иначе, чем написано в спеке, и какие каналы утечки приняты осознанно — §10.
Решение пользователя по возражению №6 (fail-open `tenant_id` в `_context_from_row`): оставлено как в плане, возражение не применено.

---

## 1. Сводка ревизии

Ревизия плана реализации `docs/superpowers/specs/2026-10-18-tenancy-authz-design.md` (арендаторы + авторизация доступа к графу), /Users/a.tsitanov/projects/kb-llamaindex, ветка main (c3191cef). Все пять возражений проверены по коду и подтверждены; два оказались шире, чем заявлено. Ниже — что изменилось относительно прежней версии плана.

РАЗРЕШЁННЫЕ ВОЗРАЖЕНИЯ

1 (blocker, порядок выката). Прежняя митигация «порядок уже обеспечен compose» — ложь. Подтверждено: `docker-compose.prod.yml:143/173/190` дают `init: service_completed_successfully` только api/worker/ingest-consumer; mcp-search (:199), mcp-tools (:218), mcp-stats (:236) зависимости на init НЕ имеют. В `deploy/offline/stack/docker-compose.srv02.yml:84..112` все семь app-сервисов делают `depends_on: !reset {}`, а `deploy/offline/DEPLOYMENT.md:390` предписывает прогон `init` «однократно, на чистой базе» — то есть при апгрейде существующей установки init может не запуститься вовсе. Тройная починка: (а) загрузчик ключей становится схемонезависимым — `SELECT to_jsonb(k) - 'key_hash' ...` вместо перечисления колонок, поэтому до-миграционная таблица больше не бросает UndefinedColumn и не роняет все ключи БД в env-фолбэк; (б) `init` добавляется в depends_on трёх mcp-сервисов + yaml-гард-тест; (в) отдельный абзац про апгрейд офлайн-кластера в `deploy/offline/DEPLOYMENT.md` и `docs/DEPLOYMENT.md §5a`.

2 (blocker, режим в тестах). Подтверждено: `src/config.py:1231-1245` — все под-настройки это `cached_property`, `settings = Settings()` на :1384. `monkeypatch.setenv("AUTHZ_MODE")` после первого обращения к `settings.authz` — пустышка. Домашний паттерн — `monkeypatch.setattr(settings.wiki, "enabled", True)` (`tests/test_api/test_admin_wiki.py:43`, `tests/test_api/test_ingest_priority.py:24`). Починка: `authz._mode()` читает `settings.authz.mode` на каждом вызове; КАЖДЫЙ поведенческий тест авторизации пиннит режим через `setattr(settings.authz, "mode", ...)` и никогда через setenv; `tests/test_config/test_authz_settings.py` проверяет умолчание через `AuthzSettings.model_fields["mode"].default` (паттерн `tests/test_config/test_settings.py:33`), потому что в корне репозитория ЕСТЬ `.env` (134 строки) и голый `AuthzSettings()` читал бы его; критерий завершения переформулирован в «сюита зелёная И без AUTHZ_MODE в окружении, И с AUTHZ_MODE=enforce», плюс regex-гард, что setenv AUTHZ_MODE встречается только в тесте настроек.

3 (major, аварийный тумблер). Подтверждено по дизайну: фильтры репозитория шли мимо `guard`. Починка: новая чистая функция `authz.tenant_filter(key) -> str | None`, возвращающая `key.tenant_id` ТОЛЬКО в режиме `enforce` и None в `off`/`log`. Через неё идут `list_rows`, `mark_deleting` и ветка resume/conflict в `create_or_resume`. `off` снова настоящий тумблер; инвариант «в `log` поведение как сегодня» снова истинен (в `log` список не фильтруется, а пишет одну сводную строку would-deny с числом чужих строк).

4 (major, утечка через POST). Подтверждено: `src/tenancy/graph_repo.py:92` делает безарендаторный `SELECT status FROM public.graphs WHERE id = %s`, а `src/api/routes/graphs_admin.py:58` выдаёт `graph 'acme' is ready|provisioning|deleting`. Починка: конфликтная ветка выбирает ещё и `tenant_id`; при заданном `tenant_filter` чужая строка даёт `CreateOutcome("conflict", "unavailable")`, а маршрут отвечает ОДНИМ непрозрачным телом `graph id is not available` для ЛЮБОГО конфликта (иначе тело своего графа остаётся оракулом). Это ломает `test_post_existing_ready_is_409:90` — тест переписывается. Остаточное: сам факт «slug занят» POST выдаёт всегда, и устранить это нельзя, пока физические имена (`nebula_space`, коллекции Milvus, `pg_schema`) выводятся из id, то есть пространство идентификаторов глобально — вынесено в риски как принятое.

5 (major, KeyError и ложное «тесты не трогаем»). Подтверждено и шире заявленного. Читаем fail-closed: `tenant = row.get("tenant_id") if row else None` → `unknown` → 404, а не 500. И правятся НЕ три, а пять тестов в `tests/test_api/test_graphs_admin.py`: :122, :131, :146 получают `"tenant_id": "default"`; :138 (`test_delete_start_failure_marks_failed_only_from_deleting`) сейчас полагается на `row=None` и под новым маршрутом получил бы 404 вместо 500, потому что DELETE (`graphs_admin.py:96-122`) сегодня `get_row` вообще не вызывает, а по плану начнёт; :87 переписывается под непрозрачный 409. Плюс мехaническая правка шести мест `ApiKeyRecord(owner=...)` в тестах (`test_current_graph.py:22`, `test_api_keys.py:27/35/51`, `test_auth.py:37`, `test_resolve_graph.py:9`, `test_graph_binding.py:16`, `test_graphs_admin.py:65`) на `ApiKeyRecord.full(...)`.

Сохранённые проектные решения прежней версии: `tenant_id` едет в `GraphContext` (а не второй поход в реестр из `authorize`); `authorize` — чистая синхронная функция `(key, graph_id, graph_tenant, action)` плюс обёртка `guard`, применяющая режим; три шва применения (`src/api/graph_dep.py`, `src/mcp/_shared.py::current_graph`, `src/api/routes/graphs_admin.py`); воркер не трогаем.

---

## 2. Шаги

### S1 — ApiKeyRecord несёт права; загрузчик схемонезависим и переживает выкат кода раньше миграции; legacy-env ключ полноправен в арендаторе default
**Файлы:** `src/tenancy/authz.py`, `src/tenancy/api_keys.py`, `src/api/auth.py`, `tests/test_tenancy/test_api_keys.py`, `tests/test_api/test_auth.py`, `tests/test_api/test_resolve_graph.py`, `tests/test_api/test_graph_binding.py`, `tests/test_api/test_graphs_admin.py`, `tests/test_mcp/test_current_graph.py`

**Изменение**

Создать `src/tenancy/authz.py` пока только с `class Action(StrEnum)` (READ/WRITE/DOWNLOAD_ORIGINAL/ADMIN) и `ALL_ACTIONS: frozenset[str]`. Константу `DEFAULT_TENANT_ID = "default"` положить в `src/tenancy/context.py` рядом с `DEFAULT_GRAPH_ID` (там нет цикла), `authz.py` и `api_keys.py` импортируют её оттуда. В `src/tenancy/api_keys.py`: `ApiKeyRecord` → `owner: str, tenant_id: str, scopes: frozenset[str], graph_ids: tuple[str, ...] | None` (без значений по умолчанию, как в спеке) плюс классметод `ApiKeyRecord.full(owner, tenant_id=DEFAULT_TENANT_ID)`.

ГЛАВНОЕ ИЗМЕНЕНИЕ ПРОТИВ ПРЕЖНЕГО ПЛАНА (возражение 1): `_load_key_row` НЕ перечисляет новые колонки, а читает строку целиком: `SELECT to_jsonb(k) - 'key_hash' AS j FROM public.api_keys k WHERE key_hash = %s` (timeout=1 сохранить), возвращает `row["j"] if row else None` — то есть контракт загрузчика (`dict | None`) не меняется и все существующие заглушки, возвращающие `{"owner": "acme"}`, продолжают работать. Причина: `mcp-search/mcp-tools/mcp-stats` в `docker-compose.prod.yml` не зависят от `init`, а офлайн-кластер сбрасывает `depends_on` целиком, поэтому код реально может подняться раньше миграции; перечисление колонок дало бы UndefinedColumn, которую глотает `except Exception` (:65) и уронило бы ВСЕ ключи из БД в env-фолбэк (403 на каждый ключ, закешированный на 30 с).

`_record_from_row(j) -> ApiKeyRecord` (чистая):
- `tenant_id = j.get("tenant_id") or DEFAULT_TENANT_ID`;
- `scopes = frozenset(j["scopes"] or ()) if "scopes" in j else ALL_ACTIONS` — ОТСУТСТВИЕ ключа (до-миграционная таблица) означает полные права, то есть ровно сегодняшнее поведение; присутствие пустого списка означает бесправный ключ. Асимметрия осознанная: для ключей отсутствие колонки — это «миграция ещё не прошла», и fail-closed здесь означал бы отказ в обслуживании, тогда как в S8 для строки графа отсутствие `tenant_id` трактуется fail-closed (404). Зафиксировать обе трактовки в докстринге, чтобы ревьюер не «выровнял» их;
- `graph_ids = tuple(j["graph_ids"]) if j.get("graph_ids") is not None else None`;
- при ветке «колонки scopes нет» — однократный на процесс `logger.warning("authz: public.api_keys has no scopes column — pre-migration fallback, run scripts.setup_db")`.

В `ApiKeyStore.lookup` строка → `_record_from_row(row)`, env-фолбэк (:71) → `ApiKeyRecord.full("legacy-env")`. Механику кеша (TTL 30 с, кеширование None, глобальный стор, `reset_api_key_store_for_tests`) НЕ трогать. Обновить докстринги `api_keys.py` и `src/api/auth.py` (ключ больше не «только аутентифицирует»); сигнатура и коды `require_api_key` (401/403) не меняются. `authz` НЕ импортирует `api_keys` в рантайме (только под `TYPE_CHECKING`).

Механическая правка всех шести тестовых мест конструирования (`ApiKeyRecord(owner=...)` → `ApiKeyRecord.full(...)`): tests/test_mcp/test_current_graph.py:22, tests/test_tenancy/test_api_keys.py:27/35/51, tests/test_api/test_auth.py:37, tests/test_api/test_resolve_graph.py:9, tests/test_api/test_graph_binding.py:16, tests/test_api/test_graphs_admin.py:65. Без этого всё падает на TypeError, а не на логике.

**Тесты**

tests/test_tenancy/test_api_keys.py: `test_record_has_no_authorization_fields` (:61) → `test_record_carries_tenant_scopes_graphs` (`set(ApiKeyRecord.__dataclass_fields__) == {"owner","tenant_id","scopes","graph_ids"}`); `test_loader_query_selects_owner_only` (:66) → `test_loader_query_is_schema_agnostic`: SQL содержит `to_jsonb`, НЕ содержит литералов `scopes`/`graph_ids`/`tenant_id` (чтобы никто не «починил» обратно на перечисление колонок), `timeout == 1`. Новые: `test_lookup_maps_full_row` (`{"owner":"acme","tenant_id":"t1","scopes":["read","write"],"graph_ids":["a"]}` → `ApiKeyRecord("acme","t1",frozenset({"read","write"}),("a",))`); `test_pre_migration_row_is_full_rights` (строка `{"owner":"acme"}` без ключа scopes → `ApiKeyRecord.full("acme")`, и это ЯВНО названный в докстринге теста путь деградации до прогона setup_db); `test_empty_scopes_is_powerless` (`scopes=[]` → frozenset()); `test_null_graph_ids_means_all`; `test_legacy_env_key_is_full_rights_in_default_tenant` (:30). Существующий `test_loader_error_falls_back_to_env_keys` (:45) остаётся зелёным. tests/test_api/test_auth.py:36 — сравнение с `ApiKeyRecord.full("legacy-env")`.

### S2 — Единственное место решения: пять правил §2 как чистая функция
**Файлы:** `src/tenancy/authz.py`, `tests/test_tenancy/test_authz.py`

**Изменение**

В `src/tenancy/authz.py` добавить `@dataclass(frozen=True) class Decision: allowed: bool; reason: str = ""` и `def authorize(key: ApiKeyRecord, graph_id: str, graph_tenant: str | None, action: Action) -> Decision`. Порядок правил строго по спеке: (1) `action not in key.scopes` → `Decision(False, "scope")`; (2) `graph_tenant is None` → `"unknown"`; (3) `graph_tenant != key.tenant_id` → `"tenant"`; (4) `key.graph_ids is not None and graph_id not in key.graph_ids` → `"graph"`; (5) иначе `Decision(True, "")`. Никакого I/O, ни обращения к реестру, ни к БД. В докстринге зафиксировать осознанное отклонение от буквы спеки (в спеке `async def authorize(key, graph_id, action)`): арендатор графа приходит снаружи, потому что он уже разрезолвлен во всех трёх швах и второй поход в кеш реестра не нужен, а особый случай «встроенного» графа `default` без строки в БД иначе давал бы ложный `unknown`.

**Тесты**

tests/test_tenancy/test_authz.py (новый): параметризованная таблица «права × граф × действие → (allowed, reason)» на все пять правил; `graph_ids=None` разрешает любой граф своего арендатора; `graph_ids=("a",)` запрещает `b` своего арендатора с reason `graph`; порядок правил — ключ без нужного scope на НЕСУЩЕСТВУЮЩИЙ граф даёт `scope`, а не `unknown`; ключ с правом на несуществующий граф даёт `unknown`; чужой арендатор даёт `tenant`. Плюс `test_authorize_is_sync_and_pure` — функция не корутина и вызывается без event loop.

### S3 — AUTHZ_MODE: off/log/enforce, обёртка guard, tenant_filter как часть того же тумблера, переменная и порядок старта доезжают до прод- и офлайн-контейнеров
**Файлы:** `src/config.py`, `src/tenancy/authz.py`, `scripts/make_env.py`, `.env.reference`, `.env.example`, `docker-compose.prod.yml`, `tests/test_tenancy/test_authz.py`, `tests/test_config/test_authz_settings.py`, `tests/test_scripts/test_compose_authz.py`

**Изменение**

`src/config.py`: `class AuthzSettings(BaseSettings)` с `model_config = SettingsConfigDict(env_prefix="AUTHZ_", env_file=".env", extra="ignore")`, поле `mode: str = Field(default="log", description=...)` и `field_validator`, допускающий только `off|log|enforce`; `Settings.authz` как `cached_property` рядом с остальными.

`src/tenancy/authz.py`:
- `def _mode() -> str: return settings.authz.mode` — читать НА КАЖДОМ вызове, никакого кеширования в модуле (возражение 2: `settings.authz` — `cached_property` на процессном синглтоне `settings`, поэтому режим в тестах переключается только присваиванием атрибута);
- `def guard(key, graph_id, graph_tenant, action) -> Decision`: `off` → `Decision(True)` НЕ вызывая `authorize`; `log` → вычислить решение, при отказе `logger.warning("authz would-deny key_owner={o} tenant={t} graph={g} action={a} reason={r}")` и вернуть `Decision(True)`; `enforce` → `logger.warning("authz deny ...")` и вернуть само решение;
- НОВОЕ (возражение 3): `def tenant_filter(key: ApiKeyRecord) -> str | None: return key.tenant_id if _mode() == "enforce" else None`. Единственный источник арендатора для фильтров уровня репозитория (S8). Благодаря ему `off` остаётся настоящим аварийным тумблером (ничего нигде не фильтруется), а `log` действительно не меняет внешнее поведение. В докстринге прямо написать: «фильтр репозитория обязан ходить через эту функцию, прямое `key.tenant_id` в SQL-вызове — ошибка».

`scripts/make_env.py`: строка про `AUTHZ_MODE` в `_ENV_DESCRIPTIONS` (русская, формат соседей), затем регенерация `.env.reference` через `uv run python -m scripts.make_env --reference`; в `.env.example` — `AUTHZ_MODE=log` в секцию API с комментарием.

`docker-compose.prod.yml`: (а) `AUTHZ_MODE: ${AUTHZ_MODE:-log}` в якорь `x-app-env` (прод-сервисы получают только явный allow-list, без `env_file`); (б) ВОЗРАЖЕНИЕ 1: добавить `init: {condition: service_completed_successfully}` в `depends_on` сервисов `mcp-search` (:199), `mcp-tools` (:218), `mcp-stats` (:236) — сейчас его там нет, и network-MCP может подняться раньше миграции схемы. Офлайн-кластер (`deploy/offline/stack/docker-compose.srv02.yml:84..112`, `depends_on: !reset {}`) кодом не чинится — для него правка документации в S12.

**Тесты**

tests/test_config/test_authz_settings.py (новый): умолчание проверяется БЕЗ инстанцирования — `AuthzSettings.model_fields["mode"].default == "log"` (в корне репозитория есть `.env` на 134 строки, и голый `AuthzSettings()` прочитал бы и его, и ambient-окружение; домашний паттерн env-независимой проверки умолчания — tests/test_config/test_settings.py:33); `test_env_override` — `monkeypatch.setenv("AUTHZ_MODE","enforce")` + СВЕЖИЙ `AuthzSettings()`; `test_bad_value_rejected` — мусор → ValidationError на свежем объекте.

tests/test_tenancy/test_authz.py: все поведенческие тесты пиннят режим через `monkeypatch.setattr(settings.authz, "mode", ...)` — НИКОГДА через setenv. `test_mode_off_skips_decision` (режим off + `authz.authorize` подменён взрывающейся заглушкой → guard всё равно allowed); `test_mode_log_allows_and_writes_line` (временный sink loguru `logger.add(records.append, format="{message}")`, строка ровно `authz would-deny key_owner=u tenant=t1 graph=acme action=write reason=tenant`); `test_mode_enforce_denies`; `test_tenant_filter_only_in_enforce` (off → None, log → None, enforce → `key.tenant_id`).

tests/test_scripts/test_compose_authz.py (новый, `yaml.safe_load`, как tests/test_mcp/test_hermes_config_example.py): `x-app-env` содержит `AUTHZ_MODE`; КАЖДЫЙ сервис, читающий `public.api_keys` (api, worker, ingest-consumer, mcp-search, mcp-tools, mcp-stats), имеет `depends_on.init.condition == "service_completed_successfully"` — гард против повторного расхождения порядка старта.

Дрейф env: `uv run python -m scripts.make_env --check` → `env check: OK`; `uv run pytest tests/test_scripts/test_make_env.py` зелёный.

### S4 — Арендатор графа доезжает до точек применения: tenant_id в строке реестра, в GraphContext и в GraphNotReady
**Файлы:** `src/tenancy/context.py`, `src/tenancy/registry.py`, `tests/test_tenancy/test_context.py`, `tests/test_tenancy/test_registry.py`

**Изменение**

`src/tenancy/context.py`: `DEFAULT_TENANT_ID = "default"` рядом с `DEFAULT_GRAPH_ID`; поле `tenant_id: str = DEFAULT_TENANT_ID` в `GraphContext` — ПОСЛЕДНИМ, после `generation` (есть значение по умолчанию, поэтому все существующие конструкции и равенства сохраняются); `new_graph_context(graph_id, *, nebula_partition_num=10, tenant_id=DEFAULT_TENANT_ID)`. `src/tenancy/registry.py`: `_COLS` (:18) += `, tenant_id` (следствие: `graph_repo.ROW_COLS` подхватывает её автоматически и `tenant_id` появляется в телах `/admin/graphs*`); `_context_from_row` → `tenant_id=row.get("tenant_id") or DEFAULT_TENANT_ID` (через `.get`, чтобы ручной SELECT в `scripts/setup_db.py:346` и фикстуры тестов остались рабочими); `GraphNotReady(graph_id, status, tenant_id=DEFAULT_TENANT_ID)` — третий параметр со значением по умолчанию, `GraphRegistry.get` поднимает его с арендатором из строки. Негативный кеш и TTL не трогать.

**Тесты**

tests/test_tenancy/test_registry.py: `test_cols_include_tenant`; `test_context_carries_row_tenant` (строка с `tenant_id="t1"` → `ctx.tenant_id == "t1"`); `test_row_without_tenant_defaults` (существующий `_row()` без ключа → `"default"`, т.е. `test_get_ready_graph_builds_context` (:26) зелёный без правок); `test_not_ready_carries_tenant`. tests/test_tenancy/test_context.py: `test_default_context_tenant_is_default`, `test_new_graph_context_tenant_override`; существующие равенства (:32, :46) не меняются.

### S5 — HTTP-шов: фабрика graph_for(action), коды §5 и неразличимость чужого графа от несуществующего
**Файлы:** `src/api/graph_dep.py`, `tests/test_api/test_resolve_graph.py`, `tests/test_api/test_graph_dep_authz.py`

**Изменение**

`src/api/graph_dep.py`: `choose_graph_id` (:13) не трогать (на него завязан MCP через `src/mcp/_shared.py:14`). Добавить `GRAPH_NOT_FOUND_DETAIL = "graph not found"` — единый текст БЕЗ slug'а и для несуществующего, и для чужого графа (сейчас :35 интерполирует `{gid!r}`; текст меняется осознанно, иначе разные тела — оракул существования). `def graph_for(action: Action) -> Callable[..., Awaitable[GraphContext]]` с той же сигнатурой зависимости `(key: ApiKeyRecord = Depends(require_api_key), x_graph: str | None = Header(default=None, alias="X-Graph"))`, чтобы позиционный вызов из тестов сохранился. Порядок: `gid = choose_graph_id(x_graph)` (400) → `await get_graph_registry().get(gid)`, откуда `ctx`/`tenant`: `GraphNotFound` → `tenant=None` + отложенная 404, `GraphNotReady` → `tenant=exc.tenant_id` + отложенная 409 с прежним текстом `graph {gid!r} is {status}` → `d = authz.guard(key, gid, tenant, action)` → при отказе 403 (`reason in {"scope","graph"}`, detail без slug'а, `f"{action} not allowed for this key"`) либо 404 `GRAPH_NOT_FOUND_DETAIL` (`reason in {"unknown","tenant"}`) → иначе поднять отложенную ошибку → иначе вернуть `ctx`. Проверка арендатора ДО проверки готовности: иначе чужой `provisioning`-граф отвечает 409 и тем подтверждает существование. Экспортировать четыре готовых объекта-зависимости на уровне модуля (а не создавать в каждом `Depends`): `resolve_graph = graph_for(Action.READ)` (имя сохраняется), `resolve_graph_write`, `resolve_graph_download`, `resolve_graph_admin` — один и тот же коллабл позволяет FastAPI дедуплицировать зависимость внутри запроса.

**Тесты**

tests/test_api/test_graph_dep_authz.py (новый, на реальном `src.api.main.app`, заглушки стора ключей и реестра как в test_graph_binding; режим пиннится `monkeypatch.setattr(settings.authz, "mode", "enforce")`, не через env): параметризованная таблица §5 — нет `X-API-Key` → 401; неизвестный ключ → 403; `X-Graph: Bad;Id` → 400 `invalid X-Graph`; несуществующий граф → 404; чужой граф → 404, причём `r.json()["detail"]` побайтово равен телу для несуществующего и не содержит slug'а; свой не-ready → 409; чужой не-ready → 404 (тот же текст); действие вне `scopes` → 403; граф вне `graph_ids` → 403. Отдельно `test_log_mode_lets_foreign_graph_through` (`setattr(settings.authz,"mode","log")` → 200/202 и строка `would-deny` в журнале) — пиннинг атрибутом обязателен, иначе тест ломается во втором (enforce) прогоне сюиты. tests/test_api/test_resolve_graph.py: `test_resolve_graph_maps_registry_errors` (:40) остаётся рабочим (позиционный вызов), добавить проверку нового текста 404; комментарий «нет авторизации на этом слое» (:12, :16-17) переписать.

### S6 — Каждый маршрут объявляет своё действие; исчезает двойной резолв графа
**Файлы:** `src/api/routes/ingest.py`, `src/api/routes/documents.py`, `src/api/routes/search_v2.py`, `src/api/routes/analyze.py`, `src/api/routes/entities.py`, `src/api/routes/stats.py`, `src/api/routes/stats_data.py`, `src/api/routes/graph_admin.py`, `src/api/routes/admin.py`, `tests/test_api/test_route_actions.py`, `tests/test_api/test_graph_binding.py`

**Изменение**

Проставить зависимости по таблице §3.1: `ingest.py:86` POST /api/v1/ingest → `resolve_graph_write`, `ingest.py:278` GET /api/v1/ingest/{job_id} → read; `documents.py:37` GET /api/v1/documents/{doc_id} → `resolve_graph_download` (включая `?variant=text`); `search_v2.py:157/189/225/261` → read, `search_v2.py:297` rebuild_communities → `resolve_graph_admin`; `analyze.py:33`, `entities.py:59`, `stats.py:64/86` → read; `stats_data.py:180` POST /statistics/load → write; `graph_admin.py:48/58/70/81/95/105/121` и `admin.py:26/63/81` → admin. Убрать дублирующие зависимости уровня маршрутизатора `dependencies=[Depends(resolve_graph)]` в `stats.py:25` и `stats_data.py:34`: все эндпоинты этих маршрутизаторов уже объявляют графовую зависимость сами, а с фабрикой это были бы ДВЕ разные зависимости → write-ключ получал бы 403 от read-зависимости маршрутизатора. `dependencies=[Depends(require_api_key)]` на уровне `admin.py:20/58`, `graph_admin.py:27`, `search_v2.py:293` оставить (это аутентификация, не резолв графа).

**Тесты**

tests/test_api/test_route_actions.py (новый, без моков воркфлоу): обойти `app.routes`, собрать графовые зависимости через `route.dependant` (сравнение `.call` с четырьмя экспортируемыми объектами `graph_dep`) и утверждать (а) точное соответствие таблице §3.1 «метод+путь → действие» (таблица в тесте — копия таблицы спеки), (б) не более ОДНОЙ графовой зависимости на маршрут, считая уровень маршрутизатора, (в) ни один маршрут данных не остался без графовой зависимости, кроме `/health` и `/admin/graphs*`. Прогнать `uv run pytest tests/test_api` и в режиме по умолчанию, и с `AUTHZ_MODE=enforce` — 18 файлов, шлющих X-API-Key, остаются зелёными (legacy-env ключ полноправен, граф резолвится в арендатора default).

### S7 — MCP-шов: запись ключа в AccessToken и проверка на каждый вызов инструмента
**Файлы:** `src/mcp/_shared.py`, `src/mcp/tools_server.py`, `tests/test_mcp/test_current_graph.py`, `tests/test_mcp/test_auth.py`, `tests/test_mcp/test_tool_authz.py`

**Изменение**

`src/mcp/_shared.py`: `RegistryTokenVerifier.verify_token` (:73) кладёт в `AccessToken` `scopes=sorted(rec.scopes)` и `claims={"owner":…, "tenant_id":…, "scopes": sorted(...), "graph_ids": list|None}` — только JSON-примитивы (fastmcp может сериализовать/логировать claims), плюс обратная `_record_from_token(tok) -> ApiKeyRecord`. Импортировать `get_access_token` из `fastmcp.server.dependencies` (fastmcp 3.3.1: вне HTTP-запроса и при выключенном auth возвращает None). `current_graph(action: Action = Action.READ)`: после `choose_graph_id`/резолва (порядок тот же, что в HTTP-шве — арендатор ДО готовности) при наличии токена вызвать `authz.guard`; отказ → `ToolError` с текстом `graph not found` для `unknown`/`tenant` (ровно как у несуществующего графа) и `forbidden: <action> not allowed` для `scope`/`graph`. Ветка «токена нет» (stdio, `KB_MCP_REQUIRE_AUTH=false`) — явная, с комментарием и однократным `logger.warning`; поведение не меняется (спека §3.2). `src/mcp/tools_server.py`: `_watch_graph(action: Action = Action.READ)`; `kb_watch` (:1050), `kb_unwatch` (:1069), `kb_ack` (:1087) передают `Action.WRITE`; `kb_watchlist`/`kb_watch_feed` остаются read; остальные ~25 вызовов `current_graph()` не трогаем. В докстринге `_shared.py` (:64-71) зафиксировать, что проверка на каждый вызов инструмента, а не на рукопожатии (спека §3.2 новее, чем `docs/superpowers/plans/2026-10-17-project-boundaries.md:139`). Отдельно отметить в докстринге: mcp-сервисы теперь ждут `init` (S3), поэтому схема к моменту первого `lookup` уже мигрирована; схемонезависимый загрузчик (S1) — второй рубеж на случай офлайн-кластера, где `depends_on` сброшен.

**Тесты**

tests/test_mcp/test_auth.py:50 и tests/test_mcp/test_current_graph.py:19 (`test_verifier_claims_are_minimal`) переписать: claims содержат owner/tenant_id/scopes/graph_ids, `tok.scopes == sorted(ALL_ACTIONS)` для legacy-env ключа. `test_current_graph_http_any_graph_allowed` (:37) → `test_current_graph_foreign_graph_is_tool_error` (тот же текст, что у несуществующего). tests/test_mcp/test_tool_authz.py (новый; режим — `monkeypatch.setattr(settings.authz, "mode", "enforce")`): инструмент чтения ключом без `read` → `ToolError`; `kb_watch` ключом без `write` → `ToolError` и репозиторий watch НЕ вызван; `kb_watch_feed` тем же ключом проходит; `test_no_access_token_skips_authz` (`get_access_token` → None → граф резолвится, отказа нет); `test_log_mode_allows_and_logs` (режим пиннится атрибутом). Существующие `test_current_graph_stdio_uses_configured_graph` (:78) и `test_current_graph_honours_x_graph_without_access_token` (:85) остаются зелёными без правок.

### S8 — Арендатор у графа: колонка, фильтры репозитория через тот же тумблер, непрозрачный 409 и fail-closed чтение tenant_id
**Файлы:** `src/tenancy/graph_repo.py`, `src/api/routes/graphs_admin.py`, `tests/test_tenancy/test_graph_repo.py`, `tests/test_api/test_graphs_admin.py`, `tests/test_api/test_graphs_admin_tenancy.py`

**Изменение**

`src/tenancy/graph_repo.py`:
- `create_or_resume(graph_id, owner, partition_num, *, tenant_id=DEFAULT_TENANT_ID, tenant_filter: str | None = None, conn_factory=None)`. Два РАЗНЫХ параметра намеренно: `tenant_id` — данные (чей арендатор пишется в новую строку, пишется ВСЕГДА, в любом режиме, иначе строки получат неверную принадлежность), `tenant_filter` — применение (None = без проверки). Колонка `tenant_id` добавляется В КОНЕЦ списка колонок INSERT, а параметр — в конец кортежа, чтобы `params[:4] == ("acme","team","g_acme",12)` в tests/test_tenancy/test_graph_repo.py:78 осталось верным. Ветка resume (UPDATE … status='failed') получает `AND tenant_id = %s` только когда `tenant_filter` задан.
- ВОЗРАЖЕНИЕ 4: конфликтный SELECT (:92) становится `SELECT status, tenant_id FROM public.graphs WHERE id = %s`; если `tenant_filter` задан и `row.get("tenant_id") != tenant_filter` → `CreateOutcome("conflict", "unavailable")` (fail-closed: отсутствие ключа тоже «чужой»). Иначе прежнее `CreateOutcome("conflict", row["status"])`.
- `list_rows(*, tenant_id: str | None = None)` → `WHERE tenant_id = %s`, когда задан; `patch_row(..., tenant_id: str | None = None)` и `mark_deleting(graph_id, *, tenant_id: str | None = None)` — фильтр ВНУТРИ того же одного оператора (в `mark_deleting` — внутри блокирующего CTE: `old AS (SELECT … WHERE id = %s AND tenant_id = %s FOR UPDATE)`), чтобы между проверкой и записью ничего не проскочило. Единственный вызывающий всех трёх — маршрут `graphs_admin` (проверено grep'ом), воркер их не использует.

`src/api/routes/graphs_admin.py`: маршрутизатор оставляет `dependencies=[Depends(require_api_key)]` (:24), но каждый эндпоинт берёт `key: ApiKeyRecord = Depends(require_api_key)` и делает свою проверку через `authz.guard`, а все фильтры репозитория берут арендатора ТОЛЬКО через `authz.tenant_filter(key)` (возражение 3: иначе `AUTHZ_MODE=off` перестаёт быть аварийным тумблером — список продолжал бы скрывать чужие графы, а DELETE чужого — отдавать 404).
- POST (:51): действие `admin`, `graph_tenant=key.tenant_id` (графа ещё нет), учитывается `key.graph_ids`; `tenant_id` из тела игнорируется (поле в `CreateGraphBody` не добавляем); вызов `create_or_resume(..., tenant_id=key.tenant_id, tenant_filter=authz.tenant_filter(key))`. ЛЮБОЙ конфликт (свой или чужой) → один и тот же непрозрачный `409 "graph id is not available"`; реальный статус уходит в лог. Иначе тело своего 409 (`graph 'acme' is ready`) само становится оракулом, и отличать чужой граф по телу было бы тривиально.
- GET списка (:75): проверка scope `admin` + `list_rows(tenant_id=authz.tenant_filter(key))`; в режиме `log` фильтра нет (список как сегодня), но пишется одна сводная строка `authz would-deny list key_owner=… tenant=… foreign_rows=N`.
- GET/PATCH/DELETE по id: сначала `get_row`, затем ВОЗРАЖЕНИЕ 5 — `tenant = row.get("tenant_id") if row else None` (НЕ `row["tenant_id"]`: строка без колонки иначе даёт KeyError → 500; fail-closed `.get` даёт reason `unknown` → 404), затем `guard(key, gid, tenant, Action.ADMIN)`; отказ `unknown`/`tenant` → 404 с общим текстом `graph not found`, `scope`/`graph` → 403.
- DELETE (:96): проверка стоит ПЕРЕД `mark_deleting` (:103) — сейчас маршрут `get_row` вообще не вызывает, поэтому появление этого чтения меняет поведение существующих тестов (см. ниже); в `mark_deleting` передаётся `tenant_id=authz.tenant_filter(key)`. Порядок прочих проверок (`default` → 409 :98, `confirm` → 400 :100) сохраняется.

**Тесты**

tests/test_tenancy/test_graph_repo.py: INSERT содержит `tenant_id` и параметр последним (`params[:4]` без изменений — существующий тест :78 остаётся зелёным); `create_or_resume(..., tenant_filter="t1")` + конфликтная строка чужого арендатора → `CreateOutcome("conflict","unavailable")`, а своя строка → прежний статус; `test_create_or_resume_conflicts` (:100, строка `{"status": status}` без tenant_id) остаётся зелёным, потому что без `tenant_filter` сравнения нет; `list_rows(tenant_id="t1")` даёт `WHERE tenant_id`, `list_rows()` — прежний SQL; `mark_deleting(tenant_id="t1")` фильтрует ВНУТРИ CTE.

tests/test_api/test_graphs_admin.py — прежнее утверждение «все 10 тестов остаются зелёными» НЕВЕРНО, правятся пять: (1) фикстура :65 → `ApiKeyRecord.full("t")`; (2) :122 `test_delete_provisioning_is_409` и (3) :131 `test_delete_racing_resume_is_409` — в `ctx["row"]` добавить `"tenant_id": "default"`, иначе fail-closed чтение даёт 404 вместо ожидаемого 409; (4) :138 `test_delete_start_failure_marks_failed_only_from_deleting` — сейчас полагается на `row=None` (DELETE его не читал), теперь обязан выставить `ctx["row"] = {"id":"acme","status":"ready","tenant_id":"default"}`, иначе получит 404 вместо 500; (5) :87 `test_post_existing_ready_is_409` — тело стало непрозрачным, утверждение `status in detail` заменяется на `detail == "graph id is not available"` и на то, что статус в теле НЕ встречается. Плюс :146 `test_delete_starts_workflow` получает `"tenant_id": "default"`. Остальные (`test_get_unknown_404` :107 с `row=None`, `test_delete_guards` :111) остаются зелёными. Вся десятка должна проходить и в `enforce`.

tests/test_api/test_graphs_admin_tenancy.py (новый, режим пиннится атрибутом): enforce — список фильтруется (в `list_rows` пришёл `tenant_id` ключа); GET/PATCH чужого → 404 с тем же телом, что у несуществующего; DELETE чужого → 404, `mark_deleting` НЕ вызван И клиент Temporal не вызван; POST игнорирует `tenant_id` из тела; POST на slug чужого графа → 409 с непрозрачным телом, байт в байт равным 409 для собственного существующего графа; ключ без scope `admin` → 403 на всех пяти маршрутах. off — `test_mode_off_lists_all_tenants` (фильтр не передан, чужие строки видны) и `test_mode_off_deletes_foreign_graph` (тумблер действительно возвращает сегодняшнее поведение). log — список не фильтруется, но в журнале есть `would-deny list … foreign_rows=1`.

### S9 — Схема и бутстрап: tenants, schema_migration, колонки, индексы и одноразовое наследование прав
**Файлы:** `scripts/setup_db.py`, `tests/test_scripts/test_setup_db_registry.py`, `tests/test_scripts/test_setup_db_authz.py`

**Изменение**

`scripts/setup_db.py`: новый `_TENANTS_DDL` = `CREATE TABLE IF NOT EXISTS public.tenants (...)` + `INSERT INTO public.tenants (id, name) VALUES ('default','Default tenant') ON CONFLICT (id) DO NOTHING` + `CREATE TABLE IF NOT EXISTS public.schema_migration (name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())`. Вставка строки `default` обязана быть ВНУТРИ этого DDL-блока (многооператорная строка, как `_PG_TRGM_DDL`), потому что `setup_postgres` (:326) прогоняет весь `GLOBAL_DDL` до `_bootstrap_registry`, и `ALTER TABLE … REFERENCES public.tenants(id)` без существующей строки `default` падает по FK на любых существующих строках. `_GRAPHS_DDL` += `ALTER TABLE public.graphs ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default' REFERENCES public.tenants(id);` + `CREATE INDEX IF NOT EXISTS graphs_tenant_idx`. `_API_KEYS_DDL` += три `ADD COLUMN IF NOT EXISTS` (`tenant_id`, `scopes TEXT[] NOT NULL DEFAULT '{read}'`, `graph_ids TEXT[]`) + `api_keys_tenant_idx`. В `GLOBAL_DDL` (:320) `_TENANTS_DDL` строго перед `_GRAPHS_DDL` и `_API_KEYS_DDL`. В `_bootstrap_registry` первым шагом `_grandfather_scopes(cur)`: если в `public.schema_migration` нет строки `authz_grandfather_v1` — один `UPDATE public.api_keys SET scopes = ARRAY['read','write','download_original','admin']` и отметка; повторный прогон не делает ничего (иначе каждый `setup_db` возвращал бы отозванные вручную права). Вставка legacy-env ключей (:190) задаёт `tenant_id` и полный `scopes` явно (`ON CONFLICT (key_hash) DO NOTHING` сохраняется) — иначе `DEFAULT '{read}'` на следующем же прогоне тихо лишил бы env-ключи права на ingest (tg_ingest, offline webui, cron graph_refresh.sh). Логика прунинга (:198/:203) не меняется. Ручной SELECT в `_ready_graphs` (:346) править не нужно: `_context_from_row` читает `tenant_id` через `.get`.

**Тесты**

tests/test_scripts/test_setup_db_registry.py: `test_api_keys_ddl_has_no_authorization_columns` (:17) → `test_api_keys_ddl_has_authorization_columns`; в `test_bootstrap_inserts_default_row_idempotently` (:23) снять `"graph_ids" not in s` (:34) и добавить, что INSERT ключа содержит все четыре права и `tenant_id`; тесты прунинга (:42, :61) и `_ready_graphs` (:99/:107/:115) остаются зелёными без правок. tests/test_scripts/test_setup_db_authz.py (новый, по образцу test_setup_db_bot.py — DDL как текст + фейковый курсор с fetchone): `_TENANTS_DDL` создаёт обе таблицы и вставляет арендатора `default`; порядок в `GLOBAL_DDL` (индекс `_TENANTS_DDL` меньше индексов `_GRAPHS_DDL`/`_API_KEYS_DDL`) и вставка `default` внутри блока — до любого `ALTER … REFERENCES`; `test_grandfather_runs_once`; `test_grandfather_skipped_when_marker_present` (повторный прогон не возвращает отозванные права); `test_legacy_env_insert_sets_full_scopes_explicitly`. Примечание: спека §7 называет файл `tests/test_storage/test_authz_migration.py`; кладём рядом с остальными тестами setup_db — отклонение осознанное, упомянуть в плане-документе.

### S10 — CLI создания арендаторов и выписки ключей (единственный способ, §4/A5)
**Файлы:** `scripts/tenant_admin.py`, `tests/test_scripts/test_tenant_admin.py`

**Изменение**

`scripts/tenant_admin.py` (новый, стиль scripts/setup_db.py: sync `psycopg.connect(settings.postgres.dsn, autocommit=True)`, `configure_logging`, `main() -> int`). Подкоманды argparse: `create --id <slug> --name <name>` (валидация slug'а через `validate_graph_id`; `ON CONFLICT (id) DO NOTHING` → идемпотентно); `key --tenant <slug> --owner <name> --scopes read,write[,download_original][,admin] [--graphs a,b]` (scopes валидируются против `ALL_ACTIONS`, пустое множество запрещено; сырой ключ `secrets.token_urlsafe(32)` печатается ОДИН раз в stdout, в БД уходит только `hash_api_key(raw)`; `--graphs` → `TEXT[]`, отсутствие → NULL); `revoke --key-hash <hash>` (DELETE … RETURNING, сообщение «не найдено» при 0 строк); `list` (арендаторы, их графы, ключи — owner, первые 12 символов хеша, scopes, graph_ids; сырые ключи не печатаются никогда). Ядро вынести в `run(args, conn_factory=...)`. HTTP-маршрута создания арендатора не появляется (A5) — отметить в докстринге. Дополнительно в докстринге: после `revoke` права гаснут не мгновенно (кеш ключей 30 с, S-инвариант), для немедленного эффекта — рестарт api/mcp.

**Тесты**

tests/test_scripts/test_tenant_admin.py (новый, без БД, фейковые conn/cursor как в tests/test_tenancy/test_graph_repo.py): `create` идемпотентен и отвергает невалидный slug; `key` печатает сырой ключ ровно один раз (capsys), и ни один SQL/параметр не содержит сырого ключа — только sha256; `key --scopes read,bogus` → ошибка выхода, записи нет; `key --scopes ''` → ошибка; `--graphs a,b` кладёт список, без флага — NULL; `revoke` удаляет по хешу; `list` читает три таблицы и не печатает сырых ключей.

### S11 — Живой smoke на два арендатора (код; запуск — только после явного «да»)
**Файлы:** `scripts/smoke_graph_isolation.py`, `tests/test_scripts/test_smoke_graph_isolation.py`

**Изменение**

Расширить `run(api_base, api_key, gid, timeout_s)` (:48) до второго арендатора: опциональные `--api-key-b` и `--graph-b` (без них сценарий работает как сейчас). Новая функция `check_cross_tenant(http, key_a, key_b, graph_b)`: граф B отсутствует в `GET /admin/graphs` под ключом A; `GET /admin/graphs/<B>` под A → 404; запрос данных с `X-Graph: <B>` под A → 404 и тело совпадает с телом для заведомо несуществующего slug'а; `POST /admin/graphs` под A со slug'ом B → 409 с непрозрачным телом, равным телу 409 для собственного существующего графа A (проверка возражения 4 на живом стенде); `DELETE /admin/graphs/<B>?confirm=<B>` под A → 404, после чего B под своим ключом всё ещё `ready`. Печать через существующий `_check`. Сам прогон — живой стенд, только после явного «да» пользователя и только при `AUTHZ_MODE=enforce`.

**Тесты**

tests/test_scripts/test_smoke_graph_isolation.py: существующие тесты `wait_for` не трогаем; добавить тест `check_cross_tenant` на `httpx.MockTransport`: сценарий «всё изолировано» проходит; сценарии «чужой граф виден в списке», «DELETE вернул 202» и «409 на чужой slug отличается телом от 409 на свой» падают с `SystemExit(1)`.

### S12 — Документы (включая порядок выката офлайн-кластера), план-артефакт, гарды и синхронизация сгенерированных файлов
**Файлы:** `docs/superpowers/plans/2026-10-18-tenancy-authz.md`, `docs/superpowers/specs/2026-10-18-tenancy-authz-design.md`, `docs/superpowers/plans/2026-10-18-multi-graph-lifecycle.md`, `docs/ARCHITECTURE.md`, `docs/DEPLOYMENT.md`, `deploy/offline/DEPLOYMENT.md`, `docs/multi-graph-ops.md`, `docs/runbook/mcp.md`, `docs/bruno/README.md`, `CHANGELOG.md`, `.env.reference`, `tests/test_tenancy/test_guards.py`, `graphify-out/graph.json`

**Изменение**

План-артефакт `docs/superpowers/plans/2026-10-18-tenancy-authz.md`: шаги, оба зафиксированных проектных решения, отклонения от буквы спеки (сигнатура `authorize`, путь теста миграции, единый текст 404, непрозрачный 409 POST) и раздел «принятые остаточные риски» (временной канал негативного кеша 2 с против 30 с; видимость занятости slug'а через POST; fail-open до миграции).

Контракты, которые сейчас документируют «любой ключ — любой граф»: `docs/ARCHITECTURE.md:125/133/160`; `docs/DEPLOYMENT.md:412 §5a` + таблица :432 — новая строка про `X-API-Key`, про `AUTHZ_MODE`, про порядок выката log → сутки → enforce, про `scripts/tenant_admin.py` И ПРО ПОРЯДОК: сначала `init`/`scripts.setup_db` до конца, только потом рестарт api/worker/mcp-*; `docs/multi-graph-ops.md:6/25/31/45` + §4 Security (арендаторы, выписка ключей, `tenant_id` в ответах `/admin/graphs*`, предупреждение про `KB_MCP_REQUIRE_AUTH=false`); `docs/runbook/mcp.md:289 §6.1` (проверка на каждый вызов инструмента, тексты ToolError); `docs/bruno/README.md:73`.

ВОЗРАЖЕНИЕ 1, документная часть: `deploy/offline/DEPLOYMENT.md:390` сейчас предписывает `init` «однократно, на чистой базе», а compose там сбрасывает `depends_on` целиком — добавить явный шаг апгрейда: перед рестартом api/worker/mcp-* на СУЩЕСТВУЮЩЕЙ базе выполнить `$C run --rm --no-deps init python -m scripts.setup_db` и дождаться завершения; отдельной строкой — что без этого ключи из `public.api_keys` до миграции работают в режиме полных прав (fail-open S1), а не отказывают.

В `docs/superpowers/plans/2026-10-18-multi-graph-lifecycle.md:16` строка «Do not reintroduce is_admin / graph_ids» помечается отменённой спекой 2026-10-18 (`graph_ids` возвращается, `is_admin` — нет, вместо него scope `admin`). Статус спеки → «реализовано». Секция в CHANGELOG.md по формату соседей. `.env.reference` пересобран в S3, `uv run python -m scripts.make_env --check` зелёный. В конце — `graphify update .` (требование CLAUDE.md).

Гарды в tests/test_tenancy/test_guards.py: (а) ни один файл в `src/` кроме `src/tenancy/authz.py` не вызывает `authorize(` напрямую мимо `guard(`; (б) ни один файл в `src/` не передаёт `key.tenant_id` в вызовы `list_rows`/`mark_deleting`/`patch_row` напрямую — только через `authz.tenant_filter(`; (в) `monkeypatch.setenv("AUTHZ_MODE"` встречается только в tests/test_config/test_authz_settings.py (возражение 2: setenv в поведенческом тесте — молчаливая пустышка из-за cached_property).

**Тесты**

Критерий завершения (переформулирован по возражению 2): сюита обязана быть зелёной ДВАЖДЫ — (1) с AUTHZ_MODE, отсутствующим в окружении (`env -u AUTHZ_MODE uv run pytest`), и (2) с `AUTHZ_MODE=enforce uv run pytest`. Это выполнимо только потому, что каждый поведенческий тест авторизации пиннит режим через `setattr(settings.authz, "mode", …)` и ни один не читает ambient-значение; тест умолчания опирается на `model_fields`, а не на инстанцирование (в репозитории есть `.env`). Плюс `uv run python -m scripts.make_env --check` → OK и `uv run ruff check src scripts tests`. Отдельно `docker compose -f docker-compose.prod.yml config | grep -E 'AUTHZ_MODE|init'` перед выкатом.

---

## 3. Инварианты

- Воркер не меняется: `src/tenancy/activity.py:11 resolve_graph_for_activity` и ~25 его вызовов остаются без проверок (спека §3.4, A8) — graph_id попал во вход воркфлоу с уже авторизованного входа.
- `choose_graph_id` остаётся чистой функцией с теми же результатами: нет заголовка → `default`, невалидный slug → HTTPException 400 `invalid X-Graph` (на неё завязан MCP через `src/mcp/_shared.py:14`).
- Коды и тексты аутентификации не меняются: нет `X-API-Key` → 401 `Missing X-API-Key header`, неизвестный ключ → 403 `Invalid X-API-Key`; `/health` остаётся публичным.
- Ключи из env `API_KEYS` остаются валидными и полноправными (арендатор `default`, все четыре действия) — и в коде (`ApiKeyRecord.full`), и после каждого прогона `setup_db`.
- До прогона миграции ключи из `public.api_keys` продолжают работать с полными правами, а не проваливаются в env-фолбэк: загрузчик читает строку через `to_jsonb` и не ссылается на колонки, которых может не быть (схемонезависимость — условие того, что mcp-сервисы и офлайн-кластер переживают выкат кода раньше `setup_db`).
- Отсутствие колонки `scopes` в строке ключа трактуется fail-OPEN (полные права, сегодняшнее поведение), отсутствие `tenant_id` в строке графа — fail-CLOSED (reason `unknown` → 404). Асимметрия намеренная и задокументирована: в первом случае цена ошибки — отказ в обслуживании всем, во втором — один отклонённый админский вызов.
- `AUTHZ_MODE=off` — настоящий аварийный тумблер: inert не только `guard`, но и все фильтры арендатора уровня репозитория (`list_rows`/`mark_deleting`/resume-ветка `create_or_resume` получают арендатора исключительно через `authz.tenant_filter`, который в `off` и `log` возвращает None).
- При `AUTHZ_MODE=log` (значение по умолчанию) внешнее поведение всех существующих маршрутов и MCP-инструментов не меняется, включая НЕфильтрованный `GET /admin/graphs`; видимых отличий ровно два и они общие для всех режимов: тело 404 для графа (теперь без slug'а) и непрозрачное тело 409 у `POST /admin/graphs`.
- Тело 409 у `POST /admin/graphs` одинаково для своего и чужого занятого slug'а (`graph id is not available`); реальный статус уходит только в лог.
- Граф `default` продолжает резолвиться встроенным контекстом, когда строки в `public.graphs` нет (`registry.get` :118-123), и такой запрос авторизуется как принадлежащий арендатору `default`, а не отвергается как `unknown`.
- Один резолв графа на HTTP-запрос: ни у одного маршрута не остаётся двух графовых зависимостей (уровень маршрутизатора + уровень эндпоинта).
- `graphs.owner` остаётся свободным текстом, остаётся в ответах `/admin/graphs*` и в тестах; доступ им больше не управляется (спека §1).
- Физические имена (`nebula_space`, коллекции Milvus, `pg_schema`, префикс MinIO) и ключи кеша `id#generation` не меняются; `GraphContext` получает только новое поле `tenant_id` со значением по умолчанию `default`.
- MCP в stdio и при `KB_MCP_REQUIRE_AUTH=false` продолжает работать без ключа и без проверки (спека §3.2) — это явная, покрытая тестом ветка.
- Гарантии DELETE /admin/graphs сохраняются: `default` → 409, `confirm` ≠ id → 400, `provisioning` → 409; добавляется только то, что чужой граф отбрасывается ДО `mark_deleting`.
- Свой граф не в статусе `ready` по-прежнему отвечает 409 с прежним текстом `graph '<id>' is <status>`; 409 для ЧУЖОГО графа заменяется на 404.
- Механика кешей не меняется: `ApiKeyStore` TTL 30 с (кеширует и None), `GraphRegistry` 30 с / 2 с негативный; `reset_*_for_tests` остаются точками сброса.
- `public.api_keys`/`public.graphs` мигрируются только аддитивно (ADD COLUMN IF NOT EXISTS с DEFAULT): старый код, читающий `SELECT owner`, работает на новой схеме.
- Создание арендаторов и выписка ключей остаются вне HTTP (A5): ни одного нового маршрута для этого не появляется.
- Ни один поведенческий тест авторизации не зависит от ambient `AUTHZ_MODE`: режим всегда пиннится присваиванием `settings.authz.mode`, поэтому сюита зелёная и без переменной, и с `AUTHZ_MODE=enforce`.

---

## 4. Риски

- **Код выкачен раньше миграции. ПРЕЖНЯЯ МИТИГАЦИЯ БЫЛА ЛОЖНОЙ: `init: service_completed_successfully` стоит только у api (:143), worker (:173) и ingest-consumer (:190); mcp-search (:199), mcp-tools (:218), mcp-stats (:236) его не имеют, а `deploy/offline/stack/docker-compose.srv02.yml:84..112` сбрасывает `depends_on` у всех семи app-сервисов. Запрос к колонкам, которых нет, дал бы UndefinedColumn, `except Exception` в `src/tenancy/api_keys.py:64-72` проглотил бы её, и каждый ключ, живущий только в БД, получил бы 403 на 30 с (кеш :73).**  
  _вероятность high, ущерб high_  
  Митигация: Три рубежа: (1) загрузчик стал схемонезависимым (`SELECT to_jsonb(k) - 'key_hash'`), строка без колонки `scopes` даёт полные права и однократный warning — поведение ровно сегодняшнее, без обвала в env-фолбэк (тест `test_pre_migration_row_is_full_rights`, S1); (2) `init: service_completed_successfully` добавляется mcp-search/mcp-tools/mcp-stats + yaml-гард-тест, что ВСЕ шесть читающих api_keys сервисов зависят от init (S3); (3) `deploy/offline/DEPLOYMENT.md` получает шаг апгрейда (`run --rm --no-deps init python -m scripts.setup_db` до рестарта), потому что :390 сегодня предписывает init только «на чистой базе» (S12).
- **Переключение режима в тестах не работает: `settings.authz` — `cached_property` на процессном синглтоне (`src/config.py:1231-1245`, :1384), поэтому `monkeypatch.setenv("AUTHZ_MODE")` после первого обращения ничего не меняет, а тест умолчания через `AuthzSettings()` читал бы и ambient-env, и корневой `.env` (134 строки) — то есть ломался бы во втором, enforce-прогоне сюиты.**  
  _вероятность high, ущерб high_  
  Митигация: Домашний паттерн: `monkeypatch.setattr(settings.authz, "mode", …)` во всех поведенческих тестах (как tests/test_api/test_admin_wiki.py:43), `_mode()` читает настройку на каждом вызове; умолчание проверяется через `AuthzSettings.model_fields["mode"].default` (как tests/test_config/test_settings.py:33), env-override — через свежий `AuthzSettings()`; regex-гард, что setenv AUTHZ_MODE есть только в тесте настроек; критерий завершения — два прогона сюиты (без переменной и с enforce).
- **Сюита зелёная в режиме по умолчанию `log` ничего не доказывает: первое же включение `enforce` в проде ломает непроверенный маршрут.**  
  _вероятность high, ущерб high_  
  Митигация: Обязательный второй прогон всей сюиты с `AUTHZ_MODE=enforce` (S12) плюс гард-тест таблицы действий по маршрутам (S6), который падает при добавлении маршрута данных без графовой зависимости.
- **FK-нарушение на `ALTER TABLE … REFERENCES public.tenants(id)`: `setup_postgres` (:326) прогоняет весь GLOBAL_DDL до `_bootstrap_registry`, а строки арендатора `default` ещё нет.**  
  _вероятность medium, ущерб high_  
  Митигация: Вставка `default` живёт ВНУТРИ `_TENANTS_DDL`, между CREATE TABLE и обоими ALTER; тест на порядок в GLOBAL_DDL и на наличие INSERT внутри блока (S9).
- **Двойной резолв графа: `stats.py:25` и `stats_data.py:34` держат зависимость уровня маршрутизатора, а эндпоинты — свою; с фабрикой это разные коллаблы, FastAPI их не дедуплицирует, и write-ключ получает 403 от read-зависимости маршрутизатора на POST /statistics/load.**  
  _вероятность high, ущерб medium_  
  Митигация: Убрать зависимости уровня маршрутизатора в обоих файлах + гард-тест «не более одной графовой зависимости на маршрут» (S6); четыре зависимости экспортируются модульными объектами, а не создаются на месте.
- **Чужой граф различим по POST: `graph_repo.py:92` делал безарендаторный `SELECT status`, а `graphs_admin.py:58` печатал статус — арендатор t1 мог перебором slug'ов читать и существование, и стадию жизненного цикла графов t2.**  
  _вероятность high, ущерб medium_  
  Митигация: Конфликтная ветка выбирает `tenant_id`, при заданном `tenant_filter` чужая строка даёт `conflict/unavailable`, и маршрут отвечает ОДНИМ непрозрачным телом для любого конфликта (иначе своё тело остаётся оракулом); случай добавлен в таблицу §5, в tests/test_api/test_graphs_admin_tenancy.py и в живой smoke (S11). Переписывается tests/test_api/test_graphs_admin.py:87.
- **ПРИНЯТО: сам факт «slug занят» POST выдаёт всегда — свободный slug даёт 202, занятый чужим даёт 409. Устранить нельзя, пока физические имена (`nebula_space`, коллекции Milvus, `pg_schema`) выводятся из id, то есть пространство идентификаторов графов глобально и два арендатора не могут делить slug.**  
  _вероятность high, ущерб low_  
  Митигация: Тело 409 непрозрачно, так что утекает только занятость идентификатора, без статуса, владельца и арендатора. Зафиксировать в плане-документе как известный остаточный канал; устранение потребовало бы префиксовать физические имена арендатором — отдельная работа, в объём не берётся.
- **Бессмысленный аварийный тумблер: фильтры арендатора в репозитории шли бы мимо `guard`, и `AUTHZ_MODE=off` всё равно скрывал бы чужие графы из списка и отдавал 404 на DELETE — оператор дёргает рубильник, симптом остаётся; попутно рушился бы инвариант «в log поведение не меняется».**  
  _вероятность high, ущерб medium_  
  Митигация: Единственный источник — `authz.tenant_filter(key)` (`enforce` → арендатор, `off`/`log` → None); гард-тест, что `key.tenant_id` не попадает в вызовы репозитория напрямую; тесты `test_mode_off_lists_all_tenants` и `test_mode_off_deletes_foreign_graph` (S8).
- **500 вместо 404 и ложное обещание «тесты не трогаем»: `row["tenant_id"]` падает KeyError на строке без колонки (заглушка, частичный SELECT, будущая правка ROW_COLS), а в tests/test_api/test_graphs_admin.py правок требуют пять тестов, а не ноль — :122, :131, :146 не несут tenant_id, а :138 полагается на `row=None`, потому что DELETE сегодня `get_row` вообще не вызывает (graphs_admin.py:96-122).**  
  _вероятность high, ущерб medium_  
  Митигация: Чтение fail-closed `row.get("tenant_id") if row else None` → reason `unknown` → 404; в S8 перечислены все пять правок поимённо вместо утверждения о неизменности.
- **В режиме `log` разрушительные операции чужого арендатора (DELETE графа) по-прежнему проходят, и список по-прежнему показывает чужие графы.**  
  _вероятность medium, ущерб high_  
  Митигация: Это и есть смысл `log`, и это ровно сегодняшнее поведение (ради честности инварианта фильтр списка тоже выключен в log, но пишется сводная строка would-deny с числом чужих строк). Окно `log` держать коротким (сутки), разобрать каждую строку, затем `enforce`; в DEPLOYMENT.md прямо написать, что `log` — не защита.
- **Вставка legacy-env ключей без явных scopes: `DEFAULT '{read}'` тихо лишает env-ключи прав на запись на следующем же прогоне `setup_db` — ломаются tg_ingest, offline webui, cron graph_refresh.sh.**  
  _вероятность medium, ущерб high_  
  Митигация: INSERT задаёт полный набор прав явно, отдельный тест (S9); наследование прав одноразовое под отметкой `authz_grandfather_v1`, тест на повторный прогон.
- **AUTHZ_MODE не доезжает до прод-контейнеров: `docker-compose.prod.yml` передаёт сервисам только явный allow-list `x-app-env` без `env_file`.**  
  _вероятность high, ущерб medium_  
  Митигация: `AUTHZ_MODE: ${AUTHZ_MODE:-log}` в якорь `x-app-env` (S3), покрыто yaml-гард-тестом; `docker compose -f docker-compose.prod.yml config | grep AUTHZ_MODE` перед выкатом.
- **Изменение сигнатур репозитория ломает существующие вызовы и тесты (`create_or_resume` — пять тестов и позиционный вызов маршрута; INSERT-параметры проверяются срезом `params[:4]`).**  
  _вероятность medium, ущерб low_  
  Митигация: `tenant_id`/`tenant_filter` только keyword-only со значениями по умолчанию; колонка и параметр добавляются В КОНЕЦ INSERT; `create_or_resume` вызывается только из маршрута (проверено grep'ом), `list_rows`/`mark_deleting` — тоже.
- **Отзыв прав не мгновенный: `ApiKeyStore` кеширует запись 30 с, стор — глобальный объект процесса.**  
  _вероятность high, ущерб low_  
  Митигация: Принято спекой (§8). Задокументировать в multi-graph-ops.md и в докстринге `tenant_admin`: revoke + рестарт даёт немедленный эффект; тесты сбрасывают стор через `reset_api_key_store_for_tests()` (автофикстура tests/test_api/conftest.py:19).
- **Утечка существования чужого графа по времени ответа: негативный кеш реестра 2 с против 30 с у ready.**  
  _вероятность low, ущерб low_  
  Митигация: ПРИНЯТО. Тексты и коды выровнены (единый `graph not found`, проверка арендатора до проверки готовности), временной канал зафиксирован в плане-документе как остаточный и в объём не берётся.
- **Ревьюер откатывает изменение, опираясь на `docs/superpowers/plans/2026-10-18-multi-graph-lifecycle.md:16` («Do not reintroduce is_admin / graph_ids») и на тесты, кодирующие обратный инвариант.**  
  _вероятность medium, ущерб low_  
  Митигация: Тесты переписываются на новый инвариант (не патчатся обходом), в старый план добавляется строка об отмене, в план-артефакт — раздел «что эта спека отменяет»; асимметрия fail-open/fail-closed и отклонения от буквы спеки зафиксированы в докстрингах, чтобы их не «чинили» обратно.
- **`get_access_token()` возвращает None в сетевом MCP из-за ошибки конфигурации — проверок молча нет.**  
  _вероятность low, ущерб high_  
  Митигация: Ветка «нет токена» явная, пишет однократный warning; тесты покрывают обе ветки; в runbook/mcp.md предупреждение, что `KB_MCP_REQUIRE_AUTH=false` небезопасен для сетевого выката.
- **Живые данные не проверены (prod-Postgres в этой сессии не опрашивался): неизвестно, сколько строк в `public.api_keys`, сколько из них legacy-env и есть ли графы кроме `default`.**  
  _вероятность medium, ущерб medium_  
  Митигация: Перед включением `enforce` (и только после явного «да» пользователя) два SELECT: `SELECT owner, count(*) FROM public.api_keys GROUP BY 1` и `SELECT id, tenant_id, status FROM public.graphs` — убедиться, что наследование прав накрыло все ключи и все графы в арендаторе `default`.

---

## 5. Возражения критика и что с ними сделано

### 1. BLOCKER

**Проблема.** The plan's mitigation for "code deployed before the migration" asserts «Порядок уже обеспечен compose (`api`/`worker`/`mcp-*` зависят от `init: service_completed_successfully`)». That is false for the three MCP services and for the whole offline cluster. In docker-compose.prod.yml only api, worker and ingest-consumer carry that dependency; mcp-search / mcp-tools / mcp-stats do not. In deploy/offline/stack/docker-compose.srv02.yml every app service (init, api, worker, ingest-consumer, mcp-search, mcp-tools, mcp-stats) sets `depends_on: !reset {}`, so there is no ordering at all. Consequence: the new `SELECT owner, tenant_id, scopes, graph_ids FROM public.api_keys` (S1) runs against the un-migrated table, psycopg raises UndefinedColumn, the broad `except Exception` in ApiKeyStore.lookup swallows it and falls back to the env API_KEYS list — so every key that lives only in public.api_keys is rejected (MCP bearer rejected / HTTP 403), and the negative result is cached for 30 s per hash. The S7 MCP seam is exactly where this bites, and the plan has no test or step covering it.

**Доказательство.** docker-compose.prod.yml:143 (api), :173 (worker), :190 (ingest-consumer) have `init: {condition: service_completed_successfully}`; :199-203 mcp-search, :218-220 mcp-tools, :236-238 mcp-stats have no init dependency. deploy/offline/stack/docker-compose.srv02.yml:84,87,95,100,104,108,112 — `depends_on: !reset {}`. Fallback path: src/tenancy/api_keys.py:64-72 (`except Exception` → row=None → env fallback), cached at :73.

**Предложенная починка.** Add `init: {condition: service_completed_successfully}` to mcp-search / mcp-tools / mcp-stats in docker-compose.prod.yml as part of S3, and add an explicit DEPLOYMENT.md §5a step for the offline cluster (run `init` to completion, then start api/worker/mcp-*, because srv02 resets depends_on). Also make the loader degrade instead of dying: probe `information_schema.columns` once, or select `owner` plus the new columns via `to_jsonb(api_keys)`/`row.get(...)`, so a pre-migration table yields a full-rights default-tenant record rather than dropping every DB key to the env fallback.

### 2. BLOCKER

**Проблема.** The plan's whole verification strategy rests on flipping AUTHZ_MODE per test and on a second full-suite run with `AUTHZ_MODE=enforce`, but `settings.authz` will be a `cached_property` on the module-level `settings` singleton. Once any test touches `guard()`, `AuthzSettings` is built once for the process, so `monkeypatch.setenv("AUTHZ_MODE", ...)` is a no-op — and S5/S7 deliberately put enforce-mode cases and `test_log_mode_lets_foreign_graph_through` / `test_log_mode_allows_and_logs` in the same file/process. Conversely, S12 makes "whole suite green with AUTHZ_MODE=enforce" a mandatory completion criterion, which breaks S3's own `test_authz_settings.py` assertion that the default is `log` (`AuthzSettings()` reads the ambient env and `.env`). As written, the exit criterion and the tests contradict each other.

**Доказательство.** src/config.py:1384 `settings = Settings()`; src/config.py:1231-1245 — "All sub-settings are constructed lazily as cached_property". The house pattern for flipping a setting in a behavioural test is attribute patching, not setenv: tests/test_api/test_admin_wiki.py:43 `monkeypatch.setattr(settings.wiki, "enabled", True)`, tests/test_api/test_ingest_priority.py:24. Env-based tests always build a fresh sub-settings object instead (tests/test_config/test_settings.py:58).

**Предложенная починка.** Specify in S3 that every behavioural authz test flips the mode with `monkeypatch.setattr(settings.authz, "mode", "enforce"|"log"|"off")` (or patches `authz._mode`), never `setenv`; have `tests/test_config/test_authz_settings.py` `monkeypatch.delenv("AUTHZ_MODE", raising=False)` and construct `AuthzSettings()` directly before asserting the `log` default; and restate the S12 exit criterion as "the suite is green with AUTHZ_MODE unset AND with AUTHZ_MODE=enforce in the environment", which only holds once the mode-sensitive tests stop reading the ambient env.

### 3. MAJOR

**Проблема.** `AUTHZ_MODE=off` is sold as the seconds-level emergency rollback that "returns behaviour to today's any-valid-key-any-graph", but S8 hard-wires tenant scoping into the repository calls, outside `guard`: `list_rows(tenant_id=key.tenant_id)`, `mark_deleting(..., tenant_id=key.tenant_id)` and `create_or_resume(..., tenant_id=key.tenant_id)` are unconditional. Once a second tenant exists, flipping the kill switch to `off` still hides graphs from `GET /admin/graphs` and still makes `DELETE` 404 on a foreign graph — the operator pulls the emergency lever and the symptom persists. The same unconditional filter also falsifies the plan's own invariant that `log` leaves external behaviour of existing routes unchanged (`GET /admin/graphs` starts filtering the moment the code ships, with the feature nominally off).

**Доказательство.** Plan S8 change text (`list_rows(tenant_id=key.tenant_id)`, `mark_deleting(graph_id, *, tenant_id=...)` passed `key.tenant_id`) vs. plan rollback level 1 and the invariant «При `AUTHZ_MODE=log` … внешнее поведение всех существующих маршрутов и MCP-инструментов не меняется». Current unfiltered implementations: src/tenancy/graph_repo.py:105 `list_rows`, :154 `mark_deleting`; route src/api/routes/graphs_admin.py:77, :103.

**Предложенная починка.** Route the repository-level tenant filter through the same switch: compute `tenant_filter = None if authz mode is "off" else key.tenant_id` (one helper in authz.py) and pass that to `list_rows` / `mark_deleting` / `create_or_resume`, or gate the filter on `guard` being active. Then add a test `test_mode_off_lists_all_tenants` and correct the invariant to say that `/admin/graphs` list filtering is mode-gated too.

### 4. MAJOR

**Проблема.** `POST /admin/graphs` still discloses a foreign tenant's graph, defeating the spec's success criterion that tenant A must not even detect the existence of B's graph. The plan adds `AND tenant_id = %s` only to the resume UPDATE; when both the insert and the resume miss, `create_or_resume` falls through to an untenanted `SELECT status FROM public.graphs WHERE id = %s` and the route turns that into `409 graph 'acme' is ready|provisioning|deleting`. A tenant-t1 key can therefore enumerate slugs and read back both the existence and the lifecycle status of t2's graphs. The plan's §5 leak analysis covers only the 404 text and the not-ready 409 on the data seam; this third channel is missed.

**Доказательство.** src/tenancy/graph_repo.py:89-92 (`SELECT status FROM public.graphs WHERE id = %s` → `CreateOutcome("conflict", row["status"])`), surfaced at src/api/routes/graphs_admin.py:57-58 (`f"graph {body.id!r} is {outcome.status}"`). Spec success criterion: docs/superpowers/specs/2026-10-18-tenancy-authz-design.md:23-25.

**Предложенная починка.** Make the conflict path tenant-aware in S8: have `create_or_resume` return a distinct outcome when the existing row belongs to another tenant, and have the route answer with a single opaque 409 body (e.g. `"graph id is not available"`) that is byte-identical whether the colliding graph is the caller's or another tenant's. Add the case to the §5 code table and to tests/test_api/test_graphs_admin_tenancy.py alongside the GET/PATCH/DELETE cases.

### 5. MAJOR

**Проблема.** S8 specifies reading the authz input with a bare subscript — `guard(key, gid, row and row["tenant_id"], Action.ADMIN)` — and then claims all ten existing graphs_admin tests stay green with only the fixture's key changed. Three of them override `ctx["row"]` with dicts that have no `tenant_id` key, so that line raises KeyError → 500 and those tests fail. The same subscript is a latent 500 in production for any row that reaches the route without the column (a stub, a partial SELECT, or a future ROW_COLS edit), and the plan has no fallback specified.

**Доказательство.** tests/test_api/test_graphs_admin.py:122 `ctx["row"] = {"id": "acme", "status": "provisioning"}`, :131 `{"id": "acme", "status": "failed"}`, :146 `{"id": "acme", "status": "ready"}`; fixture default `"row": None` at tests/test_api/test_graphs_admin.py:33 and stub at :48-49. Plan S8 test text: «все 10 существующих тестов остаются зелёными и в `enforce`».

**Предложенная починка.** Read it fail-closed: `tenant = row.get("tenant_id") if row else None`, so a row without the column yields reason `unknown` → 404 instead of a 500 or an accidental grant. Update the three tests above to carry `"tenant_id": "default"` explicitly, and say so in S8 instead of claiming they are untouched.

### 6. MINOR

**Проблема.** A missing `tenant_id` silently becomes the privileged `default` tenant on the registry path, and the plan bakes that fail-open into a test. S4 specifies `_context_from_row` → `row.get("tenant_id") or DEFAULT_TENANT_ID`, and S9 explicitly relies on it so the hand-written SELECT in setup_db stays unedited. But `_context_from_row` is the single source of `graph.tenant_id` for the HTTP and MCP seams, and `public.graphs` column lists are duplicated in three places that must stay in sync. If any of them loses the column, every graph resolves as tenant `default`, every `default`-tenant key is granted access to every graph, and nothing fails — the plan's `test_row_without_tenant_defaults` asserts precisely that behaviour.

**Доказательство.** src/tenancy/registry.py:49-61 `_context_from_row`; duplicated column lists at src/tenancy/registry.py:18 `_COLS`, src/tenancy/graph_repo.py:17 `ROW_COLS`, scripts/setup_db.py:342-346 (hand-written SELECT, no `tenant_id`). Plan S4 test: `test_row_without_tenant_defaults`.

**Предложенная починка.** Make the registry path require the column (`row["tenant_id"]`) and keep the dataclass default only for the built-in `default_graph_context()`; add `tenant_id` to the setup_db SELECT at scripts/setup_db.py:342-346 (it is one line and the plan already touches the file) and to the test fixtures at tests/test_tenancy/test_registry.py:7 and tests/test_scripts/test_setup_db_registry.py:80. Keep the S4 guard `"tenant_id" in registry._COLS` and add the same assertion for `graph_repo.ROW_COLS`.

### 7. MINOR

**Проблема.** S1 and S4 contradict each other on where `DEFAULT_TENANT_ID` lives, and S1's justification is factually wrong. S1 says keep the constant in `authz.py` «чтобы `api_keys` не импортировал `context`» (implying an import cycle); S4 says the preferred home is `context.py` next to `DEFAULT_GRAPH_ID`, with `authz` importing it. There is no cycle in either direction: `context.py` imports only `src.config`, which `api_keys.py` already imports. Leaving both variants in the plan guarantees the implementer picks one and a reviewer flags the other.

**Доказательство.** src/tenancy/context.py:14 `from src.config import settings` (no other first-party import); src/tenancy/api_keys.py:16 `from src.config import settings`. Plan S1 («константу арендатора держать здесь») vs S4 («предпочтительно `DEFAULT_TENANT_ID` в `context.py` … `authz.py` импортирует оттуда»).

**Предложенная починка.** Fix S1 to match S4: `DEFAULT_TENANT_ID` lives in `src/tenancy/context.py` beside `DEFAULT_GRAPH_ID`; `authz.py` and `api_keys.py` both import it from there. Delete the import-cycle rationale from S1 so nobody re-litigates it.

---

## 6. Откат

Четыре уровня, от дешёвого к полному.

1. Эксплуатационный (секунды, без выката кода): `AUTHZ_MODE=off` в `.env` / `x-app-env` + рестарт api и mcp-* . Теперь это ПОЛНОЦЕННЫЙ тумблер: `guard` возвращает «разрешено», не вызывая `authorize`, И `authz.tenant_filter` возвращает None, поэтому `list_rows` / `mark_deleting` / resume-ветка `create_or_resume` перестают фильтровать по арендатору. Поведение возвращается к сегодняшнему «любой валидный ключ — любой граф», включая невыфильтрованный `GET /admin/graphs` и работающий `DELETE` чужого графа. (В прежней редакции плана фильтры репозитория шли мимо тумблера и `off` симптом не снимал.) Сохраняются только два косметических отличия: тело 404 без slug'а и непрозрачное тело 409 у `POST /admin/graphs`. Режим `log` для отката не годится — он и так всё разрешает, но ведёт журнал.

2. Откат кода: ветка состоит из последовательных коммитов по шагам, поэтому `git revert` диапазона возвращает прежнее поведение. Схему БД откатывать НЕ нужно и не следует: миграция аддитивная (`ADD COLUMN IF NOT EXISTS` с DEFAULT, новые таблицы `tenants`/`schema_migration`), а прежний код читает `SELECT owner` и работает на новой схеме без изменений.

3. Частичный откат по швам: каждый шов включается отдельной зависимостью/вызовом — можно вернуть `Depends(resolve_graph)` вместо `resolve_graph_write/download/admin` на конкретном маршруте, либо снять вызов `guard` в `current_graph`, не трогая остальное. Данные не затрагиваются.

4. Откат инфраструктурной части: добавленный `init: service_completed_successfully` у mcp-* можно снять, но делать это не нужно — он только упорядочивает старт; схемонезависимый загрузчик ключей (S1) остаётся вторым рубежом и без него.

Чего откат НЕ отменяет: колонки `tenant_id`/`scopes`/`graph_ids`, строка арендатора `default` и отметка `authz_grandfather_v1` остаются; повторная установка плана наследование прав второй раз не выполнит (это и задумано). Чтобы прогнать наследование заново осознанно, оператор удаляет строку `authz_grandfather_v1` из `public.schema_migration` вручную.

---

## 7. Вне объёма

- Пользователи и роли внутри арендатора — субъект прав остаётся ключ (A1).
- Платформенный суперключ и создание арендаторов по HTTP (A5, A6).
- Внешний провайдер политики и JWT: интерфейс готов (решение принимает `authorize` по уже загруженному `ApiKeyRecord`), реализации нет.
- Квоты и честность приёма между арендаторами (`graphs.max_inflight` остаётся зарезервированной).
- Журнал выдач оригиналов — контур intake, `2026-10-17-project-boundaries.md` §7.
- Проверка прав при доставке уведомлений: `src/workflow/monitor/activities.py:270 _watch_graphs()` по-прежнему обходит все ready-графы всех арендаторов и пишет `watch_event`; изоляция обеспечивается read-проверкой на чтении фида через MCP (спека §8).
- Легаси-ветка локального пути в `src/api/routes/documents.py:55` (FileResponse по пути из БД), отмеченная в `2026-10-17-project-boundaries.md:371` — отметить в плане-документе, не чинить здесь.
- Авторизация в воркере (`resolve_graph_for_activity`, ~25 мест) — §3.4.
- Мгновенный отзыв прав (кеш ключей с TTL) — §8.
- Удаление колонки `graphs.owner` — остаётся свободным описанием (§1).
- Сужение `GET /admin/graphs` по `key.graph_ids` внутри своего арендатора: спека требует только фильтр по арендатору.
- Устранение временного канала различения чужого ready-графа и несуществующего (негативный кеш 2 с против 30 с).
- Префиксование физических имён (`nebula_space`, коллекции Milvus, `pg_schema`) арендатором, которое сделало бы пространство graph id не-глобальным и убрало бы утечку занятости slug'а через POST — отдельная работа со сменой схемы хранения.
- Правка `depends_on` в `deploy/offline/stack/docker-compose.srv02.yml`: там `!reset {}` стоит намеренно (бэкенды на другом хосте, порядок держат restart-политики) — закрывается документацией шага апгрейда, а не кодом.

---

## 8. Разрешённые к правке файлы

- `src/tenancy/authz.py`
- `src/tenancy/api_keys.py`
- `src/tenancy/context.py`
- `src/tenancy/registry.py`
- `src/tenancy/graph_repo.py`
- `src/config.py`
- `src/api/auth.py`
- `src/api/graph_dep.py`
- `src/api/routes/graphs_admin.py`
- `src/api/routes/ingest.py`
- `src/api/routes/documents.py`
- `src/api/routes/search_v2.py`
- `src/api/routes/analyze.py`
- `src/api/routes/entities.py`
- `src/api/routes/stats.py`
- `src/api/routes/stats_data.py`
- `src/api/routes/graph_admin.py`
- `src/api/routes/admin.py`
- `src/mcp/_shared.py`
- `src/mcp/tools_server.py`
- `scripts/setup_db.py`
- `scripts/tenant_admin.py`
- `scripts/make_env.py`
- `scripts/smoke_graph_isolation.py`
- `tests/conftest.py`
- `tests/test_tenancy/test_authz.py`
- `tests/test_tenancy/test_api_keys.py`
- `tests/test_tenancy/test_context.py`
- `tests/test_tenancy/test_registry.py`
- `tests/test_tenancy/test_graph_repo.py`
- `tests/test_tenancy/test_guards.py`
- `tests/test_config/test_authz_settings.py`
- `tests/test_api/conftest.py`
- `tests/test_api/test_auth.py`
- `tests/test_api/test_resolve_graph.py`
- `tests/test_api/test_graph_binding.py`
- `tests/test_api/test_graph_dep_authz.py`
- `tests/test_api/test_route_actions.py`
- `tests/test_api/test_graphs_admin.py`
- `tests/test_api/test_graphs_admin_tenancy.py`
- `tests/test_mcp/test_current_graph.py`
- `tests/test_mcp/test_auth.py`
- `tests/test_mcp/test_tool_authz.py`
- `tests/test_mcp/test_watch_tools.py`
- `tests/test_scripts/test_setup_db_registry.py`
- `tests/test_scripts/test_setup_db_authz.py`
- `tests/test_scripts/test_tenant_admin.py`
- `tests/test_scripts/test_make_env.py`
- `tests/test_scripts/test_smoke_graph_isolation.py`
- `tests/test_scripts/test_compose_authz.py`
- `.env.reference`
- `.env.example`
- `docker-compose.prod.yml`
- `deploy/offline/DEPLOYMENT.md`
- `docs/superpowers/plans/2026-10-18-tenancy-authz.md`
- `docs/superpowers/plans/2026-10-18-multi-graph-lifecycle.md`
- `docs/superpowers/specs/2026-10-18-tenancy-authz-design.md`
- `docs/ARCHITECTURE.md`
- `docs/DEPLOYMENT.md`
- `docs/multi-graph-ops.md`
- `docs/runbook/mcp.md`
- `docs/bruno/README.md`
- `CHANGELOG.md`
- `graphify-out/graph.json`

---

## 9. Разведка: швы, потребители, ловушки

### Точки входа

- /Users/a.tsitanov/projects/kb-llamaindex/src/api/graph_dep.py:13 — choose_graph_id(x_graph) (pure, raises HTTPException 400 'invalid X-Graph'); re-used by MCP
- /Users/a.tsitanov/projects/kb-llamaindex/src/api/graph_dep.py:27 — resolve_graph(_key, x_graph); becomes graph_for(action) factory + resolve_graph = graph_for(READ) (spec §3.1). Note `_key` is currently discarded
- /Users/a.tsitanov/projects/kb-llamaindex/src/api/auth.py:17 — require_api_key -> ApiKeyRecord (401 missing / 403 invalid); unchanged signature, but record shape changes
- /Users/a.tsitanov/projects/kb-llamaindex/src/tenancy/api_keys.py:19 — ApiKeyRecord(owner) -> +tenant_id, scopes: frozenset[str], graph_ids: tuple|None
- /Users/a.tsitanov/projects/kb-llamaindex/src/tenancy/api_keys.py:28 — _load_key_row: `SELECT owner FROM public.api_keys` must select tenant_id, scopes, graph_ids
- /Users/a.tsitanov/projects/kb-llamaindex/src/tenancy/api_keys.py:55 — ApiKeyStore.lookup (TTL 30 s, caches None too); row->record at :69, legacy-env fallback at :71 (must get tenant 'default' + full scopes)
- /Users/a.tsitanov/projects/kb-llamaindex/src/tenancy/authz.py — NEW (Action StrEnum, Decision, authorize)
- /Users/a.tsitanov/projects/kb-llamaindex/src/mcp/_shared.py:73 — RegistryTokenVerifier.verify_token: must put the full ApiKeyRecord into AccessToken (claims/scopes)
- /Users/a.tsitanov/projects/kb-llamaindex/src/mcp/_shared.py:94 — current_graph(): add authorize; needs fastmcp get_access_token() (confirmed present in fastmcp 3.3.1 `fastmcp.server.dependencies`), currently not imported
- /Users/a.tsitanov/projects/kb-llamaindex/src/api/routes/graphs_admin.py:24 — router dependencies=[Depends(require_api_key)] only; needs its own tenant/admin check
- /Users/a.tsitanov/projects/kb-llamaindex/src/api/routes/graphs_admin.py:51 create_graph / :75 list_graphs / :80 get_graph / :88 patch_graph / :96 delete_graph — the five endpoints spec §3.3 retunes
- /Users/a.tsitanov/projects/kb-llamaindex/src/tenancy/graph_repo.py:17 ROW_COLS, :46 create_or_resume(graph_id, owner, partition_num), :99 get_row, :105 list_rows, :111 patch_row — need tenant_id column + tenant filter/owning-tenant insert
- /Users/a.tsitanov/projects/kb-llamaindex/src/tenancy/registry.py:18 _COLS / :49 _context_from_row — the only read path authorize() can get graph.tenant_id from (GraphContext has no tenant_id today)
- /Users/a.tsitanov/projects/kb-llamaindex/src/tenancy/context.py:28 GraphContext / :51 default_graph_context / :69 new_graph_context — if tenant_id joins GraphContext, all three change
- /Users/a.tsitanov/projects/kb-llamaindex/scripts/setup_db.py:139 _GRAPHS_DDL, :162 _API_KEYS_DDL — add tenants, schema_migration, tenant_id/scopes/graph_ids, indexes
- /Users/a.tsitanov/projects/kb-llamaindex/scripts/setup_db.py:171 _bootstrap_registry — legacy-env key insert (:190) must emit explicit full scopes; grandfather UPDATE goes here under authz_grandfather_v1
- /Users/a.tsitanov/projects/kb-llamaindex/scripts/setup_db.py:320 GLOBAL_DDL list + :326 setup_postgres — ordering seam (see traps)
- /Users/a.tsitanov/projects/kb-llamaindex/scripts/tenant_admin.py — NEW CLI (create / key / revoke / list)
- /Users/a.tsitanov/projects/kb-llamaindex/src/config.py:1231 Settings — add `authz` cached_property + AuthzSettings(env_prefix='AUTHZ_')
- /Users/a.tsitanov/projects/kb-llamaindex/scripts/make_env.py:210 _ENV_DESCRIPTIONS — AUTHZ_MODE needs a Russian line, and .env.reference must be regenerated
- /Users/a.tsitanov/projects/kb-llamaindex/scripts/smoke_graph_isolation.py:48 run(api_base, api_key, gid, timeout_s) — single-key signature; spec §7 wants a second tenant/key

### Потребители

- HTTP routes depending on resolve_graph (all must declare an action) — src/api/routes/ingest.py:86 (POST /ingest → write), ingest.py:278 (GET /ingest/{job_id} → read); documents.py:37 (GET /documents/{doc_id} → download_original); search_v2.py:157,189,225,261 (search modes → read), search_v2.py:297 rebuild_communities (→ admin); analyze.py:33 (→ read); entities.py:59 (GET /entities → read); stats.py:64,86 (→ read); stats_data.py:180 POST /statistics/load (→ write); graph_admin.py:48,58,70,81,95,105,121 (/admin/graph/* → admin); admin.py:26 /admin/wiki/rebuild, admin.py:63 /admin/monitor/sweep, admin.py:81 /admin/monitor/watch (→ admin)
- ROUTER-LEVEL duplicates of the same dependency (two resolutions per request): src/api/routes/stats.py:25 `dependencies=[Depends(resolve_graph)]` and src/api/routes/stats_data.py:34 — both sit above endpoints that also take Depends(resolve_graph); POST /statistics/load would run a read-action router dep AND a write-action endpoint dep
- MCP tool call sites of current_graph() (per-call authz, spec §3.2) — src/mcp/search_server.py:289,343,399,459,488; src/mcp/stats_server.py:238,264,302; src/mcp/tools_server.py:317,344,365,386,410,441,464,491,512,535,561,579,599,614,640,823,846,873,903 and src/mcp/tools_server.py:936 `_watch_graph()` (used by kb_watch:1050, kb_unwatch:1069, kb_watchlist:1071, kb_watch_feed:1077, kb_ack:1087 → kb_watch/kb_unwatch/kb_ack need `write`)
- src/mcp/_shared.py:14 imports choose_graph_id from src/api/graph_dep.py — any signature change to choose_graph_id hits MCP too
- src/api/main.py:89-100 — router wiring order (health, search_v2, analyze, ingest, documents, entities, stats, stats_data, admin.router, admin.monitor_router, graph_admin.router, graphs_admin.router)
- graph_repo consumers outside the admin router — src/workflow/graph_lifecycle/activities.py:41 (load_context_any_status), :218 (set_status), :301 (delete_row); src/workflow/monitor/activities.py:270 `_watch_graphs()` → graph_repo.list_ready_contexts() sweeps EVERY ready graph across tenants (notification delivery authz is explicitly out of scope, §8)
- Worker-side graph resolution (NOT to be touched, spec §3.4) — src/tenancy/activity.py:11 resolve_graph_for_activity
- HTTP consumers whose keys need the right scopes in `enforce` — src/bot/search_client.py:22 (X-API-Key + X-Graph=BOT_GRAPH → read); src/bot/__main__.py:53; scripts/tg_ingest.py:75 client_headers / :451 --graph (→ write); deploy/offline/webui/app.py:34 KB_HEADERS → /api/v1/ingest:100 (write), /api/v1/ingest/{job}:111 (read), /api/v1/search/{mode}:122 (read), /api/v1/documents/{id}:136 (download_original); deploy/offline/loadtest/loader.py:71 (write); scripts/graph_refresh.sh (cron → admin on /admin/graph/materialize + communities/rebuild); tests/eval/run_answer_eval.py
- Docs/collections that document the current 'any key, any graph' contract and the /admin/graphs response — docs/DEPLOYMENT.md:412 §5a (table at :432), docs/ARCHITECTURE.md:125,133,160, docs/multi-graph-ops.md:6,25,31,45, docs/runbook/mcp.md:289 §6.1, docs/runbook/hermes.md:35, docs/bruno/Admin/*.bru + docs/bruno/README.md:73, .env.reference:98 (BOT_GRAPH), scripts/make_env.py:426
- Superseded prior contracts to re-read before editing — docs/superpowers/specs/2026-09-24-multi-graph-design.md:300 and docs/superpowers/plans/2026-10-18-multi-graph-lifecycle.md:16 ("Do not reintroduce is_admin / graph_ids") — this spec deliberately reverses that

### Данные

- public.api_keys — today: key_hash PK, owner TEXT NOT NULL, created_at (scripts/setup_db.py:163). Adds tenant_id NOT NULL DEFAULT 'default' FK, scopes TEXT[] NOT NULL DEFAULT '{read}', graph_ids TEXT[] NULL, index api_keys_tenant_idx. Read by src/tenancy/api_keys.py:38 (SELECT owner only). Written only by scripts/setup_db.py:190/198/203 (legacy-env rows are deleted+reinserted on EVERY setup_db run)
- public.graphs — id, owner, status, status_error, nebula_space, nebula_partition_num, chunks_collection, er_vec_collection, report_vec_collection, pg_schema, max_inflight, generation, created_at, updated_at (scripts/setup_db.py:140). Adds tenant_id NOT NULL DEFAULT 'default' FK + graphs_tenant_idx. Column lists are duplicated in THREE places that must stay in sync: src/tenancy/registry.py:18 _COLS, src/tenancy/graph_repo.py:17 ROW_COLS (= _COLS + extras), scripts/setup_db.py:346 (_ready_graphs hand-written SELECT)
- NEW public.tenants (id slug PK, name, created_at) and NEW public.schema_migration (name PK, applied_at) — both in `public`, created by setup_db; the one-shot grandfather step is keyed `authz_grandfather_v1`
- graphs.owner stays as free-form text and loses all access meaning (spec §1); it is returned by GET /admin/graphs rows and asserted in tests/test_api/test_graphs_admin.py and tests/test_tenancy/test_graph_repo.py
- Response-key impact: GET/PATCH /admin/graphs rows come from graph_repo ROW_COLS, so adding tenant_id adds a key to every /admin/graphs* JSON body (consumers: docs/multi-graph-ops.md, docs/bruno, scripts/smoke_graph_isolation.py:62 which reads row['status']/row['status_error'])
- PROD DATA NOT QUERIED. There is no mongodb MCP in this session's tool set (this service's directory lives in Postgres, not Mongo), and the kb-search / kb-tools MCP servers failed to connect (ECONNREFUSED). Per the standing rule that any live-stack check needs an explicit «да», I ran no SELECT against a live Postgres. Two facts the plan should confirm live before the enforce flip: (1) how many rows public.api_keys has and how many are owner='legacy-env' (drives the grandfather UPDATE), (2) whether any public.graphs row other than 'default' exists (if not, the migration is free, as docs/superpowers/plans/2026-10-17-project-boundaries.md:170 claims)

### Существующие тесты

- tests/test_api/test_resolve_graph.py::test_choose_graph_ok (:18), ::test_choose_graph_invalid_slug_is_400 (:23), ::test_resolve_graph_maps_registry_errors (:40 — calls graph_dep.resolve_graph(ONE, "acme") positionally, breaks if the signature moves to a factory), ::test_require_api_key_statuses (:53)
- tests/test_api/test_graph_binding.py — whole file is the end-to-end "any valid key, any graph" contract: ::test_admin_routes_accept_plain_valid_key (:62, 'No admin gating'), ::test_any_valid_key_with_x_graph_binds_that_graph (:174), ::test_no_x_graph_binds_default (:181), ::test_invalid_x_graph_is_400 (:188); USER/ADMIN constants at :16-17
- tests/test_api/test_auth.py::test_* (:20 missing key 401, :27 bad key 403, :36 asserts ApiKeyRecord(owner='legacy-env'))
- tests/test_api/test_graphs_admin.py — 10 tests (:70 test_post_creates_and_starts_workflow … :145 test_delete_starts_workflow); its fixture overrides require_api_key at :65 with ApiKeyRecord(owner="t") — the only dependency_overrides in the suite
- tests/test_api/conftest.py:12 `_db_free_auth` (autouse) — stubs _load_key_row and _load_row_from_pg to return None, so every API test authenticates via the legacy-env env fallback and resolves the built-in default graph
- tests/conftest.py:29 `_offline_graph_registry` (autouse, repo-wide) — stubs get_graph_registry so ANY gid resolves to new_graph_context(gid); there is no tenant in that stub, so authz tests must override it or no "unknown graph" / "other tenant" case can be exercised
- tests/test_tenancy/test_api_keys.py::test_record_has_no_authorization_fields (:61 — asserts the dataclass has exactly {'owner'}; DIRECTLY contradicts the spec), ::test_loader_query_selects_owner_only (:66 — asserts 'graph_ids' not in the SQL), plus ::test_lookup_db_row (:21), ::test_legacy_env_key_is_valid (:30), ::test_loader_error_falls_back_to_env_keys (:45)
- tests/test_scripts/test_setup_db_registry.py::test_api_keys_ddl_has_no_authorization_columns (:17 — asserts 'graph_ids'/'is_admin' absent; CONTRADICTS the spec), ::test_bootstrap_inserts_default_row_idempotently (:23, same assertion at :34), ::test_bootstrap_prunes_legacy_env_keys_not_in_env (:42), ::test_bootstrap_with_no_env_keys_deletes_all_legacy_env_rows (:61), ::test_ready_graphs_* (:99/:107/:115 — _SelCur._COLS at :80 is a hand-written column tuple)
- tests/test_tenancy/test_registry.py::test_get_ready_graph_builds_context (:26 asserts reg.get('acme') == new_graph_context('acme')) + _row() helper (:7) which has no tenant_id key
- tests/test_tenancy/test_context.py::test_default_context_uses_legacy_names (:30, full GraphContext equality at :32), ::test_new_graph_context_names (:46)
- tests/test_tenancy/test_graph_repo.py — create_or_resume/list_ready_contexts/patch/mark_deleting SQL-shape tests (:74-:186)
- tests/test_tenancy/test_guards.py — src/-wide regex invariants (:24 no transitional default, :28 settings.milvus.collection, :32 hardcoded names); a new guard for "no authz bypass" would live here
- tests/test_mcp/test_current_graph.py::test_verifier_claims_are_minimal (:19 — asserts tok.claims == {'owner': …}, breaks once the record goes into claims), ::test_current_graph_http_any_graph_allowed (:37 — the exact behaviour being removed), ::test_current_graph_http_uses_header (:31), ::test_current_graph_stdio_uses_configured_graph (:78), ::test_current_graph_honours_x_graph_without_access_token (:85)
- tests/test_mcp/test_auth.py::test_registry_verifier_accepts_legacy_env_key (:50 — asserts tok.claims == {'owner': 'legacy-env'}), ::test_both_servers_wire_sse_auth (:71)
- tests/test_mcp/test_watch_tools.py::test_watch_tools_accept_non_default_graph (:223), ::test_watch_tools_run_on_default_graph (:242) — both monkeypatch ts.current_graph, so they bypass authz entirely
- tests/test_scripts/test_make_env.py::test_every_env_var_has_russian_description (:299), ::test_iter_app_env_vars_covers_known_fields (:217), ::test_build_reference_groups_and_marks_secrets (:286) — AUTHZ_MODE trips these unless make_env is updated
- tests/test_api/{test_documents,test_ingest*,test_search_v2_routes,test_stats_routes,test_stats_data,test_analyze_route,test_graph_admin,test_admin_wiki,test_monitor_route}.py — 18 files send X-API-Key through the real ASGI app; all become sensitive to the default AUTHZ_MODE
- tests/test_scripts/{test_setup_db_bot,test_setup_db_entity}.py — the DDL-as-text + fake-cursor pattern the new setup_db/migration tests should copy; tests/test_scripts has no test_tenant_admin.py yet

### Ловушки

- authorize() needs graph.tenant_id, but GraphContext (src/tenancy/context.py:28) has no tenant field and the registry's _COLS (src/tenancy/registry.py:18) does not select one. Two options, both rippling: add tenant_id to GraphContext (touches default_graph_context:51, new_graph_context:69, _context_from_row:49, and the equality assertions in tests/test_tenancy/test_context.py:32 + test_registry.py:26) or have authz read the registry row via GraphRegistry.get_row (which returns the raw dict and is already TTL-cached). Pick one in the plan; do not do both.
- DDL ORDERING BUG WAITING TO HAPPEN: scripts/setup_db.py:326 runs every GLOBAL_DDL statement first, then _bootstrap_registry(cur) inserts rows. `ALTER TABLE public.graphs ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default' REFERENCES public.tenants(id)` therefore fires BEFORE the 'default' tenant row exists → FK violation on any existing graphs/api_keys row. The INSERT of tenant 'default' must be inside the DDL block, ordered after CREATE TABLE tenants and before the two ALTERs (the spec says so in §1 but the current code shape makes it easy to miss).
- DOUBLE RESOLUTION: src/api/routes/stats.py:25 and stats_data.py:34 declare `dependencies=[Depends(resolve_graph)]` at router level AND each endpoint also takes `graph = Depends(resolve_graph)`. With graph_for(action) these become two DIFFERENT callables, so FastAPI will not dedupe them: POST /statistics/load would be checked for `read` (router) and `write` (endpoint), and a write-only key would get 403 from the router dep. Same pattern on search_v2.py:293 (require_api_key at router + resolve_graph on the endpoint) and admin.py:20/58 + graph_admin.py:27.
- THREE TESTS ENCODE THE OPPOSITE INVARIANT and will fail by design — they must be rewritten, not patched around: tests/test_tenancy/test_api_keys.py:61 (`ApiKeyRecord` fields == {'owner'}), :98 ('graph_ids' not in the lookup SQL), tests/test_scripts/test_setup_db_registry.py:19 ('graph_ids'/'is_admin' not in _API_KEYS_DDL). docs/superpowers/plans/2026-10-18-multi-graph-lifecycle.md:16 also states 'Do not reintroduce is_admin / graph_ids' — note in the plan that this spec supersedes it.
- MCP has no access token in current_graph today. The spec requires reading the ApiKeyRecord from AccessToken; fastmcp 3.3.1 exposes `get_access_token()` in fastmcp.server.dependencies (verified) and AccessToken fields are {token, client_id, scopes, expires_at, resource, claims}. In stdio and with KB_MCP_REQUIRE_AUTH=false it returns None — the fail-open branch must be explicit and tested, or a misconfigured network deployment silently has no authz.
- TTL CACHES MAKE REVOCATION LAZY AND TESTS ORDER-SENSITIVE: ApiKeyStore caches records (and None) for 30 s keyed by hash (src/tenancy/api_keys.py:52-74) and is a process global (:78 get_api_key_store); GraphRegistry caches rows 30 s / 2 s negative (src/tenancy/registry.py:69-99) and is also a global. Scope/tenant changes do not take effect until the TTL expires. Tests must call reset_api_key_store_for_tests()/reset_graph_registry_for_tests() (the autouse fixture in tests/test_api/conftest.py:19 already does).
- legacy-env KEYS ARE RE-CREATED ON EVERY setup_db RUN (scripts/setup_db.py:190 insert, :198/:203 prune). If their INSERT does not set scopes explicitly, the DEFAULT '{read}' silently downgrades every env-key deployment on the next init — ingest from tg_ingest / the offline webui would start failing in `enforce`. The spec calls this out; make it a test.
- AUTHZ_MODE DEFAULTS TO `log`, i.e. the feature ships OFF. Every behavioural test must set the mode explicitly, and the plan must not treat a green suite in `log` as proof of enforcement. Also: the `log` line format is a contract for the 24-h review, so pin it in a test.
- ADDING AuthzSettings BREAKS THE ENV DRIFT GUARD: `make env-check` runs `scripts.make_env --check`, and tests/test_scripts/test_make_env.py:299 asserts every var from iter_app_env_vars() has a Russian entry in _ENV_DESCRIPTIONS (scripts/make_env.py:210). AUTHZ_MODE needs that entry plus a regenerated .env.reference in the same commit.
- 404-NOT-403 FOR A FOREIGN GRAPH (spec §5) is easy to leak: the current handlers interpolate the slug into the detail string (src/api/graph_dep.py:35 `f"graph {gid!r} not found"`, graphs_admin.py:84/92/105, _shared.py:116). The foreign-graph 404 body must be byte-identical to the unknown-graph 404 — and the response must not differ in timing-visible ways either (the registry negative cache is 2 s vs 30 s for ready graphs, so a foreign READY graph answers from a 30 s-cached entry while a truly absent one re-hits PG every 2 s).
- DELETE /admin/graphs/{id} IS NOT IDEMPOTENT AND IS DESTRUCTIVE: graphs_admin.py:103 `mark_deleting` flips the row to 'deleting' BEFORE the workflow starts (and before any tenant check, if the check is added in the wrong place). A foreign-tenant DELETE must 404 before mark_deleting, otherwise a rejected request has already wedged someone else's graph. The spec's test for this ("Temporal client not called") is necessary but not sufficient — also assert mark_deleting was not called.
- POST /admin/graphs must ignore tenant_id from the body and take it from the key (spec §3.3). graph_repo.create_or_resume (src/tenancy/graph_repo.py:46) has a fixed positional signature (graph_id, owner, partition_num) used by graphs_admin.py:54 and five tests — changing it is a cross-file edit.
- THREE DUPLICATED COLUMN LISTS for public.graphs must be updated together or the tenant column is invisible to one of the three readers: src/tenancy/registry.py:18 _COLS, src/tenancy/graph_repo.py:17 ROW_COLS, scripts/setup_db.py:346. The test fixtures mirror them (tests/test_tenancy/test_registry.py:7, tests/test_scripts/test_setup_db_registry.py:80).
- SPEC-vs-PLAN CONFLICT on where MCP authorizes: docs/superpowers/plans/2026-10-17-project-boundaries.md:139 says "MCP — верификатор токена при handshake"; the spec §3.2 says per tool call because current_graph() re-resolves every call. The spec is newer and correct for this code; say so in the plan so a reviewer does not 'fix' it back.
- The monitor sweep (src/workflow/monitor/activities.py:270) iterates every ready graph across all tenants and writes watch_event rows; kb_watch_feed then serves them per graph. Cross-tenant leakage there is governed by the MCP read check on the graph, not by the sweep — but notification DELIVERY authz is explicitly deferred (spec §8), so do not let the plan quietly expand into it.
- tests/conftest.py:29 autouse `_offline_graph_registry` resolves ANY graph id successfully for the whole suite. Any new authz test that relies on 'graph not found' or 'graph belongs to another tenant' must override it locally; otherwise the test passes for the wrong reason.
- Legacy local-path branch in src/api/routes/documents.py:55 (`if not path.startswith("s3://")` → FileResponse of a DB-supplied path) is already flagged in docs/superpowers/plans/2026-10-17-project-boundaries.md:371 as something to restrict under multi-tenancy. It is NOT in this spec's scope; note it, do not fix it here.
- No CI exists (.github is absent); `make env-check` is the only drift guard and it is manual. Plan steps must say which commands to run locally (uv run pytest, uv run python -m scripts.make_env --check). Project rule: no git commit/push without explicit user approval, and no live-stack run without an explicit «да» — the §7 smoke-script extension is a live check.

---

## 10. Что сделано иначе, чем в спеке, и что принято как остаточный риск

### 10.1 Отклонения от буквы спеки (осознанные, зафиксированы в докстрингах)

| Спека | Реализация | Почему |
|---|---|---|
| `async def authorize(key, graph_id, action)` — сама ходит за арендатором графа | `def authorize(key, graph_id, graph_tenant, action)` — чистая, синхронная, арендатор приходит снаружи | Все три шва уже разрезолвили граф к моменту вызова, второй поход в кеш реестра ничего не даёт; а встроенный граф `default`, у которого строки в `public.graphs` может не быть, иначе возвращал бы ложный `unknown` → 404 на умолчательном графе. Арендатор едет в `GraphContext` и в `GraphNotReady` |
| Тест миграции — `tests/test_storage/test_authz_migration.py` | `tests/test_scripts/test_setup_db_authz.py` | Миграция живёт в `scripts/setup_db.py`, а не в `src/storage/`; тест лежит рядом с соседним `tests/test_scripts/test_setup_db_registry.py` и переиспользует его заглушки курсора |
| §5: «Граф не существует → 404», текст не задан | Единое тело `graph not found` **без slug'а** для несуществующего И для чужого | 404, эхом возвращающий id одного графа и не возвращающий другого, сам становится оракулом существования. Тело должно быть байт-в-байт одинаковым |
| §3.3: POST на занятый slug → 409 со статусом | Непрозрачное `graph id is not available` для ЛЮБОГО конфликта | Иначе тело конфликта на СВОЁМ графе (`graph 'x' is ready`) остаётся оракулом, по которому чужой slug отличается от своего. Реальный статус уходит только в лог (возражение №4) |
| §7: `monkeypatch.setenv("AUTHZ_MODE", …)` подразумевался как способ переключения режима | Поведенческие тесты пиннят режим `setattr(settings.authz, "mode", …)`; setenv разрешён только в `tests/test_config/test_authz_settings.py` | `settings.authz` — `cached_property` на процессном синглтоне: после первого обращения setenv молчаливо ничего не меняет. Закреплено гардом в `tests/test_tenancy/test_guards.py` (возражение №2) |
| §4: права ключа читаются перечислением колонок | Загрузчик читает строку целиком (`SELECT to_jsonb(k) - 'key_hash'`) | Код может подняться раньше миграции (mcp-* в офлайн-кластере сбрасывают `depends_on`); перечисление колонок дало бы `UndefinedColumn`, которую глотает `except Exception`, и уронило бы ВСЕ ключи БД в env-фолбэк на 30 с (возражение №1) |

Решение пользователя: fail-open в `_context_from_row` (`row.get("tenant_id") or DEFAULT_TENANT_ID`) оставлен как в плане — возражение критика №6 не применялось. Строка графа без `tenant_id` в `graphs_admin._row_tenant` при этом читается fail-CLOSED (`unknown` → 404): реестр отдаёт контекст только для графа, который он уже признал существующим, а админский маршрут работает с сырой строкой.

### 10.2 Принятые остаточные риски (не чинятся в этом объёме)

1. **Занятость slug'а видна всегда.** `POST /admin/graphs` отвечает 202 на свободный id и 409 на занятый — любым ключом. Тело 409 непрозрачно, так что утекает ровно один бит («id занят»), без статуса, владельца и арендатора. Устранить нельзя, пока физические имена (`nebula_space`, коллекции Milvus, `pg_schema`, префикс MinIO) выводятся из id: пространство идентификаторов глобально, два арендатора не могут делить slug. Устранение = префиксовать физические имена арендатором — отдельная работа.
2. **Временной канал негативного кеша.** `GraphRegistry` кеширует `ready`-строку 30 с, а отсутствие/неготовность — 2 с. Поэтому чужой `ready`-граф отвечает 404 из кеша, а заведомо несуществующий — после похода в Postgres: разница во времени ответа различает их, хотя коды и тела совпадают. Принято: цена выравнивания — либо отказ от негативного кеша (нагрузка на PG), либо искусственная задержка.
3. **Fail-open до миграции.** Пока `scripts.setup_db` не прогнан, строка `public.api_keys` без колонки `scopes` читается как полные права (+ однократный warning). Это сознательный выбор доступности против отказа: цена ошибки в другую сторону — 403 на каждый ключ, живущий только в БД, закешированный на 30 с, во всех шести сервисах сразу. Следствие: на немигрированной базе `AUTHZ_MODE=enforce` не ограничивает ничего — порядок «миграция до конца, потом рестарт» вынесен в `docs/DEPLOYMENT.md` §5a и `deploy/offline/DEPLOYMENT.md` §11.
4. **`log` — не защита.** В умолчательном режиме чужой граф по-прежнему читается и удаляется, а `GET /admin/graphs` показывает все графы: фильтры арендатора выключены вместе с `guard`, иначе инвариант «в `log` поведение не меняется» был бы ложью. Окно `log` держать коротким (сутки).
5. **Отзыв прав не мгновенный.** `ApiKeyStore` кеширует запись (и её отсутствие) 30 с в каждом процессе api/mcp. Немедленный эффект — `revoke` + рестарт.
6. **Доставка уведомлений не авторизуется** (спека §8) и **локальная ветка выдачи файла** в `src/api/routes/documents.py` не ограничена — оба пункта вне объёма, зафиксированы в §7.

### 10.3 Как это проверено

Сюита прогоняется ДВАЖДЫ и обязана быть зелёной в обоих прогонах: `env -u AUTHZ_MODE uv run --extra dev pytest -q -p no:cacheprovider tests` и `AUTHZ_MODE=enforce uv run --extra dev pytest -q -p no:cacheprovider tests`. Это возможно только потому, что ни один поведенческий тест не читает ambient-режим. Плюс `uv run python -m scripts.make_env --check` → OK, `uv run ruff check src scripts tests` и, перед выкатом, `docker compose -f docker-compose.prod.yml config | grep -E 'AUTHZ_MODE|init'`. Живой smoke на два арендатора (`scripts/smoke_graph_isolation.py --api-key-b/--graph-b`) — только по явному «да» пользователя и только при `AUTHZ_MODE=enforce`.
