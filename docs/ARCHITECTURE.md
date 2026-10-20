# Архитектура

`kb-llamaindex` — это RAG-сервис с несколькими хранилищами и
надёжным (durable) исполнением. Он принимает документы на любом языке,
нормализует граф знаний к русскому языку (имена сущностей + описания +
связи), сохраняя при этом текст чанков на языке оригинала ради точности
цитирования, и предоставляет четыре режима поиска (`local` / `global` /
`drift` / `auto`) с возрастающей агентной сложностью.

Этот документ — **высокоуровневая карта**. Более глубокие документы
детализируют каждый слой:

| Документ | Что охватывает |
|---|---|
| [`INGEST.md`](INGEST.md) | Конвейер приёма (ingest) — активности, очереди, staging по схеме claim-check, деградация |
| [`SEARCH-FLOW.md`](SEARCH-FLOW.md) / [`SEARCH.md`](SEARCH.md) | Четыре режима поиска + детерминированный конвейер извлечения + GraphRAG map-reduce |
| [`QUEUES.md`](QUEUES.md) | Очереди задач Temporal + лимиты конкурентности по каждой очереди |
| [`FEATURES.md`](FEATURES.md) | Каждая функция: что / зачем / как + управляющая переменная окружения |
| [`MODELS.md`](MODELS.md) | Рекомендации по моделям для каждой роли + процедура замены |
| [`DEPLOYMENT.md`](DEPLOYMENT.md) | Docker-стек + эксплуатация |
| [`runbook/`](runbook/) | Эксплуатационные сценарии (mcp, search-usage, multimodel, analytics, wikibase, wiki-editor, er-native-vector-knn) |

> Диаграмма: [`diagrams/system_architecture.svg`](diagrams/system_architecture.svg)
> (исходник [`diagrams/system_architecture.d2`](diagrams/system_architecture.d2)).
> Диаграммы отдельных потоков лежат рядом со своими документами (`diagrams/ingest_flow.*`,
> `diagrams/search_modes.*`, `diagrams/kb_search_flow.*`).

---

## 1. Компоненты с высоты птичьего полёта

Два долгоживущих процесса плюс набор stateful-бэкендов:

- **API** (`src/api/`) — FastAPI на `:8000`. Тонкий HTTP-слой
  (`/search/*`, `/ingest`, `/documents/{id}`, `/admin/*`), аутентификация
  через `X-API-Key`. Маршруты валидируют, запускают воркфлоу Temporal и
  стримят результаты — бизнес-логика живёт в модулях
  workflow/activity/graph, а не в маршрутах.
- **Воркер Temporal** (`src/workflow/worker.py`) — содержит определения
  воркфлоу и все активности в нескольких пулах `Worker` (по одному на
  каждую очередь задач) в рамках одного процесса. Надёжное исполнение:
  автоматические повторы, heartbeat-ы, идемпотентные активности,
  безопасный к replay код.
- **Серверы MCP** (`src/mcp/`) — два опциональных слоя (stdio + HTTP/SSE),
  которые предоставляют поиск внешним LLM-клиентам (OpenWebUI / Claude
  Desktop / Cursor): **MCP-1** `:9001` (`kb_search`, запускает воркфлоу
  поиска) и **MCP-2** `:9002` (8 атомарных in-process инструментов
  извлечения). См. [`runbook/mcp.md`](runbook/mcp.md).

Сквозные компоненты:

- **Прокси LiteLLM** `:4000` — единый шлюз к моделям. Все вызовы чата и
  эмбеддингов идут через него (модели по ролям: extraction / judge /
  search / synthesis; многоязычные эмбеддинги).
- **LLMPool** (`src/retrieval/llm_pool.py`) — per-process регулятор
  конкурентности, который стоит *выше* лимитов очередей Temporal:
  потолок на каждый tier (small = ёмкость GPU, large = бюджет API) плюс
  отдельные дорожки (lanes) на каждую роль, захватываемые сначала по
  дорожке, затем глобально по tier. Лимиты Temporal заданы с запасом, так
  что именно пул является реальным арбитром конкурентных LLM-вызовов.

---

## 2. Хранилища данных — что в каждом

| Хранилище | Что хранит | Подключение (по умолчанию) |
|---|---|---|
| **Milvus** | Векторный индекс чанков — одна запись на чанк (`id, text, embedding, metadata`). `text` — это чанк **на языке оригинала**; эмбеддинги получены из многоязычной embed-модели через LiteLLM. ANN-индекс — **HNSW** (`MILVUS_INDEX_TYPE`, `FLAT` для точного). | `MILVUS_HOST:MILVUS_PORT` (`localhost:19530`); коллекция `MILVUS_COLLECTION` |
| **NebulaGraph** | Property-граф: вершины с тегом `Entity` (тип сущности — свойство `label`) + типизированные рёбра (имена/описания **на русском** после слияния; рёбра несут осмысленный `weight` = счётчик co-occurrence + дискретные `tags` + логическую полярность `polarity` (`affirmed`/`negated`/`uncertain`) + окно валидности `valid_from`/`valid_to`), плюс иерархия `Community` (чанки — не вершины графа: тексты в Postgres, векторы в Milvus). Nebula **не имеет** in-graph векторного индекса, поэтому эмбеддинги сущностей (`graph_search` kNN), ER-kNN-вектора (`er_vec`) и `community_report_vec` живут в **Milvus** (отдельные коллекции — см. `src/graph/entity_vector_store_milvus.py` / `community_vector_store_milvus.py`); по имени сущности (`find_entity_by_name`) — префиксный LOOKUP по нативному Nebula-индексу `entity_name_idx`, не full-text. | `NEBULA_HOST:NEBULA_PORT` (`localhost:9669`), space — свой у каждого графа (`GraphContext.nebula_space`: `kb` у `default`, `g_<id>` у остальных) |
| **Postgres** | Таблица заданий/статусов `documents` (doc_id → статус → метаданные) и `ingest_metrics` (длительности по каждой активности + теги моделей по ролям для аналитики). | `POSTGRES_*` |
| **MinIO** | Загруженные исходные файлы (отдаются обратно через `GET /documents/{id}`) **и** staging-блобы по схеме claim-check — тяжёлое состояние приёма (распарсенные узлы, KG, слитые сущности), сериализованное через pickle и передаваемое между активностями по URI. | `MINIO_*` (консоль `:9001`, S3 API `:9000`) |
| **Wikibase / MediaWiki** | Курируемый **канонический якорь**: self-hosted Wikibase Item на каждую сущность (`push_wikibase`, opt-in) + страницы статей MediaWiki на каждую сущность, создаваемые непрерывным редактором wiki. WDQS предоставляет SPARQL-эндпоинт. | контейнеры `wikibase` / `wdqs` |

Вспомогательная инфраструктура: **etcd** + **MinIO** обслуживают Milvus;
**wikibase-mysql** (MariaDB) обслуживает Wikibase; **temporal**
(+ **temporal-ui** `:8080`) — бэкенд надёжного исполнения; **Prometheus** +
**Grafana** — наблюдаемость. См. [`DEPLOYMENT.md`](DEPLOYMENT.md) /
`docker-compose.yml`.

**Прод-топология:** `Dockerfile` + `docker-compose.prod.yml` поднимают в
одном compose всё приложение (API + воркер) вместе с бэкендами и redis,
**исключая** litellm/ollama — они внешние и доступны через
`LITELLM_BASE_URL`. Wikibase прячется за `--profile wikibase`.

Сбросить всё: `uv run python -m scripts.wipe_db --yes`.

---

## 2a. Графы и изоляция

Все данные принадлежат **графу** — изолированной базе знаний со своими
физическими хранилищами. Базовый граф — `default` (прежние имена хранилищ,
без миграции данных); прочие графы создаются и удаляются **только явно**,
через `POST` / `DELETE /admin/graphs` (действие `admin`; порядок операций —
[`multi-graph-ops.md`](multi-graph-ops.md)), автопровижининга нет нигде.
Арендаторы и API-ключи, наоборот, через API не заводятся принципиально —
только CLI [`scripts/tenant_admin.py`](../scripts/tenant_admin.py).

**`GraphContext`** ([`src/tenancy/context.py`](../src/tenancy/context.py)) —
единственное, что нужно коду хранения, чтобы знать, какой граф он трогает.
Физические имена живут только в нём (и в строке реестра), никогда — в
Temporal-payload'ах:

| Поле | `default` | прочие графы (`<id>`) |
|---|---|---|
| `nebula_space` | `kb` | `g_<id>` |
| `chunks_collection` (Milvus) | `MILVUS_COLLECTION` | `g_<id>_chunks` |
| `er_vec_collection` / `report_vec_collection` (Milvus) | `entity_er_vec` / `community_report_vec` | `g_<id>_er_vec` / `g_<id>_report_vec` |
| `pg_schema` (Postgres) | `public` | `g_<id>` |
| `minio_prefix` (ключи объектов в upload-bucket'е) | `""` | `<id>/` |

Id графа — slug `^[a-z][a-z0-9_]{1,30}$` (он подставляется в DDL);
`default` зарезервирован.

**Реестр** ([`src/tenancy/registry.py`](../src/tenancy/registry.py)) —
таблица `public.graphs` (id → статус + физические имена), TTL-кэш 30 с в
каждом процессе. `get(id)` отдаёт `GraphContext` только для графа в статусе
`ready`; иначе `GraphNotFound` / `GraphNotReady`. Если строки `default` нет
(или PG недоступен при запросе `default`), используется встроенный контекст
`default` с предупреждением в логе.

**API-ключи и арендаторы** ([`src/tenancy/api_keys.py`](../src/tenancy/api_keys.py),
[`src/tenancy/authz.py`](../src/tenancy/authz.py)) — `public.api_keys`:
sha256-хэш ключа → `owner, tenant_id, scopes, graph_ids` (кэш 30 с, кэшируется
и отсутствие). Строка читается схемонезависимо (`SELECT to_jsonb(k) -
'key_hash'`), поэтому код переживает выкат раньше миграции: строка без колонки
`scopes` трактуется **fail-open** (полные права + однократный warning), а не
роняет все ключи БД в env-фолбэк. Ключ, которого нет в таблице, но есть в env
`API_KEYS`, валиден и полноправен в арендаторе `default` (`owner = legacy-env`).

**Ключ аутентифицирует И авторизует** (спека
[`2026-10-18-tenancy-authz-design.md`](superpowers/specs/2026-10-18-tenancy-authz-design.md);
отменяет ту часть амендмента 2026-10-17, где проверок в сервисе нет).
Решение принимает чистая функция `authz.guard(key, graph_id, graph_tenant,
action)`; действия — `read` / `write` / `download_original` / `admin`
(выдача оригинала файла — отдельное право, не часть `read`). Правила строго по
порядку: действие вне `scopes` → `scope`; арендатор графа неизвестен →
`unknown`; граф чужого арендатора → `tenant`; граф не входит в `graph_ids`
ключа → `graph`. Чужой граф неотличим от несуществующего (404 / `ToolError`
с телом `graph not found`, без slug'а), своему графу без права — 403.
Граф по-прежнему выбирается только заголовком `X-Graph` (нет заголовка →
`default`). Арендаторы и ключи создаются только CLI
[`scripts/tenant_admin.py`](../scripts/tenant_admin.py) — HTTP-маршрута для
этого нет принципиально.

Тумблер `AUTHZ_MODE` (`off` | `log` | `enforce`, по умолчанию `log`) —
единственный переключатель: он управляет и `guard`, и фильтрами арендатора
уровня репозитория (`authz.tenant_filter`). В `off` не фильтрует и не
отказывает ничто (аварийный откат к поведению до фичи), в `log` отказ
пишется строкой `authz would-deny …` и запрос пропускается, в `enforce`
применяется. Арендатор графа (`public.graphs.tenant_id`) едет в
`GraphContext` / `GraphNotReady`, так что шов решает без второго похода
в реестр.

**Как граф доходит до хранилищ:**

1. **HTTP** — `graph_for(action)` ([`src/api/graph_dep.py`](../src/api/graph_dep.py)):
   каждый запрос с валидным `X-API-Key` (нет → 401, невалидный → 403)
   привязан ровно к одному графу: `X-Graph: <id>`, без заголовка — `default`.
   Маршрут берёт одну из четырёх зависимостей по своему действию
   (`resolve_graph` / `_write` / `_download` / `_admin`) — ровно одну, иначе
   граф резолвился бы дважды (гард-тест `tests/test_api/test_route_actions.py`).
   Невалидный slug → 400 `invalid X-Graph`; неизвестный ИЛИ чужой граф → 404
   `graph not found`; свой не-`ready` → 409. Отказ реестра придерживается до
   решения: чужой `provisioning`-граф не выдаёт себя 409-м.
2. **MCP** — `current_graph(action)` ([`src/mcp/_shared.py`](../src/mcp/_shared.py)):
   граф = заголовок `X-Graph`, если он есть, иначе env `KB_MCP_GRAPH` (по
   умолчанию `default`) — одинаково для HTTP с токеном и без и для stdio (там
   заголовка нет). `RegistryTokenVerifier` кладёт права ключа в claims токена
   (`owner`, `tenant_id`, `scopes`, `graph_ids`), а решение принимается **на
   каждый вызов инструмента**: одна сессия переживает сколько угодно значений
   `X-Graph`. Невалидный slug / неизвестный / чужой / не-`ready` граф →
   `ToolError`. Без токена (stdio или `KB_MCP_REQUIRE_AUTH=false`) проверки
   нет — явная ветка с однократным warning.
3. **Temporal** — входы workflow и storage-активностей несут `graph_id`
   (не физические имена; старые payload'ы без поля читаются как `default`),
   дочерние workflow наследуют его. Активность резолвит граф сама —
   `resolve_graph_for_activity` ([`src/tenancy/activity.py`](../src/tenancy/activity.py));
   неизвестный/не-`ready` граф → `ApplicationError(type="GraphUnavailable",
   non_retryable=True)`, даже у fail-safe активностей. Id workflow —
   `graph_scoped_id`: у `default` они прежние (`<prefix>-<suffix>`), у прочих
   `<prefix>-<graph>-<suffix>`.
4. **Ingest-очередь** — ключ допуска в scheduler'е и `message_id` в RabbitMQ
   = `<graph>:<doc_id>` (у `default` — голый `doc_id`), так что одинаковые
   `doc_id` разных графов не схлопываются.
5. **Хранилища** — билдеры принимают граф обязательным аргументом
   (`build_graph_store(graph)` → одна Nebula-сессия на space, `USE` +
   идемпотентный DDL на каждой новой сессии; Milvus-сторы по коллекциям графа;
   Postgres — `graph_connection(graph)` ставит `search_path` `<pg_schema>,
   public`, пул сбрасывает его при возврате соединения). Глобальные таблицы
   (`graphs`, `api_keys`, таблицы бота) живут в `public`.
6. **CLI/скрипты** — `--graph` (по умолчанию `default`) через
   `cli_graph_context` (без PG: `default` → встроенный контекст, иначе имена
   по соглашению). Бот шлёт `X-Graph: $BOT_GRAPH` в каждом запросе к API.

**Только `default`:** wiki (`/admin/wiki/*`, `WikiSweepWorkflow`) и
мониторинг (`/admin/monitor/*`, `MonitorSweepWorkflow`) — для другого графа
API отвечает 409, активность пометки wiki-сущностей пропускает не-`default`.

Инварианты зафиксированы тестом `tests/test_tenancy/test_guards.py`: в
`src/` нет переходного `transitional_default_graph` вне `src/tenancy/context.py`,
`settings.milvus.collection` и захардкоженные имена space/коллекций
(`SPACE_NAME`, `entity_er_vec`, `community_report_vec`, `` USE `kb` ``) читаются
только там, а `build_graph_store` / `build_nebula_graph_store` требуют граф.
Там же — три гарда авторизации: `authorize` вызывается только через `guard`
(иначе `AUTHZ_MODE=off` перестал бы быть тумблером), фильтр арендатора в
вызовах `list_rows` / `patch_row` / `mark_deleting` приходит только из
`authz.tenant_filter(key)`, а `AUTHZ_MODE` нигде в тестах не переключается
через окружение (`settings.authz` — `cached_property`, setenv был бы молчаливой
пустышкой; поведенческие тесты пиннят режим присваиванием).

---

## 3. Путь приёма (ingest)

`POST /ingest` загружает файл в MinIO, вставляет строку `pending` в
Postgres, снимает снапшот имён моделей по ролям и запускает надёжный
**`DocumentIngestWorkflow`** (очередь `kb-ingest`). Воркфлоу выполняет
фиксированную последовательность активностей; тяжёлое состояние
путешествует как **блобы MinIO по URI** (claim-check), так что по
payload-ам Temporal едут только небольшие контракты.

**Опциональный классификатор:** между `fetch_source` и `parse_and_chunk`
может стоять шаг `classify_document` (opt-in `CLASSIFIER_ENABLED`,
`src/intake/classifier.py`) — детерминированные правила + LLM-гейт
отсеивают мусор; документ-мусор завершается новым статусом `skipped`
вместо прохода через конвейер. `force=true` на `/ingest` обходит правила
и форсирует приём.

Две половины, намеренно разделённые:

- **Векторная половина** — `fetch_source` → (`classify_document`) →
  `parse_and_chunk` (разбиение → детерминированная канонизация
  идентификаторов → опциональный перевод на русский) → `index_vector`
  (эмбеддинг → Milvus). Если это падает, приём падает (`mark_failed`).
- **Графовая половина** — `inject_canonical` (сущности-идентификаторы в
  граф) → `extract_kg` (LightRAG, один LLM-вызов на чанк, очередь
  `kb-ingest-llm`) → дочерний **`GraphBuildWorkflow`** (очередь
  `kb-ingest-merge`): `merge_and_resolve` (межчанковое слияние →
  консолидация телефонов → разрешение сущностей) → `build_property_graph`
  (upsert в граф).

**Деградация:** если графовая половина бросает исключение / истекает по
таймауту, родитель ловит это и выставляет `graph_status = "vector_only"` —
документ всё ещё доступен для векторного поиска, граф просто пропускается
(а вместе с ним и `push_wikibase`). Граф — это дополнение, а не
блокирующий фактор.

Best-effort хвосты: `mark_entities_dirty` (помечает сущности для
редактора wiki) и `push_wikibase` (проецирование в якорь Wikibase, только
если граф завершился), затем `finalize` записывает финальный статус +
`ingest_metrics`.

**Опциональный контроль допуска (admission control)** (opt-in
`INGEST_ADMISSION_ENABLED`, `INGEST_ADMISSION_MAX_INFLIGHT`) — singleton
`IngestSchedulerWorkflow` (`src/workflow/ingest_scheduler.py`,
`src/workflow/admission.py`) допускает к исполнению не более K документов
одновременно, проводя каждый до завершения по FIFO. Когда выключен,
документы запускаются сразу, как раньше.

Полная таблица активностей, диаграмма последовательности, staging-контракты → [`INGEST.md`](INGEST.md).

---

## 4. Путь поиска

`POST /search/{local,global,drift,auto}` — все четыре являются надёжными
воркфлоу Temporal, запускаемыми из `src/api/routes/search_v2.py` и
разделяющими одну форму `SearchRequest` / `SearchResponse` (включая
управляемую клиентом `history` для многоходовых диалогов).

| Режим | Воркфлоу | Форма |
|---|---|---|
| `local` | `SearchOrchestratorWorkflow` | планирование подвопросов → параллельный fan-out `SubQueryRetrievalWorkflow` → merge/dedup → проверка покрытия → bge rerank → синтез на large-tier |
| `global` | `GlobalSearchWorkflow` | GraphRAG map-reduce по отчётам сообществ (MAP на small-tier по каждому сообществу → REDUCE на large-tier один раз) |
| `drift` | `DriftSearchWorkflow` | локальный проход, затем глобальное расширение, засеянное локальными источниками; деградирует до локального ответа, если глобальный падает |
| `auto` | `AutoSearchWorkflow` | `route_query` классифицирует → диспетчеризует local/global/drift (fail-safe → local) |

Отдельно от поиска живёт **аналитика по графу** — `POST /api/v1/analyze`
(`AnalyticalQueryWorkflow`, та же search-очередь): LLM-планировщик выбирает
до `ANALYTICS_MAX_STEPS` детерминированных примитивов из каталога 42
(`src/analytics/`; nGQL-запросы к NebulaGraph или вычисления в воркере),
синтез собирает ответ, а `provenance` несёт запрос/метку операции (поле
`cypher`) и сырые строки каждого шага. Центральность/risk (link-prediction на NebulaGraph — no-op) предвычисляет
`AnalyticsMaterializeWorkflow` (`POST /admin/graph/materialize`, очередь
graph-build). Подробности → [`runbook/graph-analytics.md`](runbook/graph-analytics.md).

Ключевые свойства:

- **Детерминированное извлечение, а не цикл ReAct.** Каждый подвопрос
  выполняет фиксированную последовательность инструментов — `vector_search`
  (Milvus) → `graph_search` (Milvus kNN по эмбеддингам сущностей +
  LLM-синонимы) → `find_entity_by_name` (префиксный LOOKUP по нативному
  Nebula-индексу `entity_name_idx`) → `graph_walk` (ограниченный N-hop
  обход, засеянный из двух источников — топ graph_search и найденной по
  имени сущности). Результаты сливаются и дедуплицируются по `chunk_id`.
  (Старый путь Self-RAG / ReAct был **удалён** при переходе на R7b.)
- **История диалога** — когда присутствует `history`, активность
  `contextualize_query` один раз в начале воркфлоу переписывает
  follow-up в самостоятельный вопрос.
- **Иерархические сообщества** — global/drift выбирают по Leiden-**иерархии**
  узлов `:Community` со структурированными отчётами через
  лексический / семантический-kNN / спуск-по-иерархии отбор. Leiden
  запускается **взвешенным** (по `weight` связей = co-occurrence).
  Сообщества строятся **офлайн** через `CommunityBuildWorkflow` (очередь
  `kb-graph-build`, запускается админом), полностью отвязанные от горячего
  пути запроса.
- **Вывод только на русском** — `synthesize_answer` оборачивает запрос
  инструкцией выдавать ответ на русском, так что язык ответа совпадает с
  нормализацией графа независимо от языка исходных чанков.
- **Шаблон ответа** — поле запроса `answer_template`
  (`src/retrieval/answer_template.py`) задаёт форму синтезируемого ответа:
  именованный шаблон из `prompts/answer_templates/<name>.md` или inline-текст;
  пустое значение → шаблон по умолчанию.

**Анализ графа (admin):** набор read-only эндпоинтов
`/admin/graph/{stats,pagerank,personalized-pagerank,components,shortest-path}`
(`src/graph/analysis.py`; алгоритмы считаются в воркере на igraph по
экспорту взвешенных рёбер, глобальный PageRank читает материализованное
свойство `pagerank`) даёт сводную статистику,
PageRank (глобальный и **персонализированный/seed-смещённый**), компоненты
связности и кратчайшие пути по графу знаний — вне горячего пути запроса. Те
же функции продублированы как инструменты MCP-2 (`graph_pagerank`,
`graph_personalized_pagerank`, `graph_components`, `graph_shortest_path`,
`graph_stats`) для внешних LLM-клиентов.

Режимы, инструменты извлечения, отбор сообществ → [`SEARCH-FLOW.md`](SEARCH-FLOW.md)
и [`SEARCH.md`](SEARCH.md).

---

## 5. Надёжное исполнение и очереди

Воркер содержит по одному пулу `Worker` на каждую очередь задач, чтобы
давление по GPU / LLM на одну нагрузку не могло заморить другую (блокировка
головы очереди, head-of-line blocking). Очереди:

| Очередь | Что содержит | Лимит (по умолчанию) |
|---|---|---|
| `kb-ingest` | `DocumentIngestWorkflow` + активности IO/эмбеддинга | 4 |
| `kb-ingest-llm` | только `extract_kg` (дорожка extract) | 18 |
| `kb-ingest-merge` | `GraphBuildWorkflow` + merge/build (дорожка merge) | 14 |
| `kb-search-small` | воркфлоу поиска + активности plan/retrieve/coverage/rerank/route/map | 4 |
| `kb-search-large` | только `synthesize_answer` (финальный синтез на large-tier) | 2 |
| `kb-graph-build` | `CommunityBuildWorkflow` (офлайн-сообщества Leiden — leidenalg в воркере) | 2 |
| `kb-wiki` | `WikiSweepWorkflow` (непрерывный редактор MediaWiki по сущностям) | 4 |
| `kb-monitor` | монитор-свип Arc-2 (opt-in `MONITOR_ENABLED`; новые связи / рост risk / burst событий / доставка алертов) | 2 |

Лимиты Temporal по каждой очереди ограничивают, сколько активностей
*планируется*; per-process **LLMPool** затем ограничивает, сколько
LLM-вызовов реально выполняется конкурентно (потолок tier + дорожки
ролей). Лимиты держатся ≥ потолков дорожек пула, чтобы пул арбитрировал
первым. Полное обоснование + ручки `TEMPORAL_*_ACTIVITY_CONCURRENCY` → [`QUEUES.md`](QUEUES.md).

---

## 6. Якорь знаний и редактор wiki

Помимо RAG-хранилищ, сущности попадают в курируемый слой идентичности:

- **Популятор Wikibase** (`push_wikibase`, opt-in `WIKIBASE_ENABLED`) —
  приём создаёт/патчит Wikibase Item на каждую сущность с ключом
  `wikibase_qid`, сворачивая сущности типа идентификатор в
  external-id-утверждения; запрашивается через WDQS SPARQL.
- **Непрерывный редактор wiki** (`WikiSweepWorkflow`, очередь `kb-wiki`,
  opt-in `WIKI_ENABLED`) — приём помечает затронутые сущности
  `wiki_dirty`; запланированный проход (sweep) переписывает управляемую
  ботом секцию статьи MediaWiki по каждой сущности **только из фактов
  графа** (anti-drift, с цитированием), сохраняя правки людей и пропуская
  неизменившиеся сущности по хешу подграфа.

→ [`runbook/wikibase.md`](runbook/wikibase.md),
[`runbook/wiki-editor.md`](runbook/wiki-editor.md), [`FEATURES.md`](FEATURES.md#3-knowledge-anchors).

---

## 7. Наблюдаемость

- **Temporal UI** `:8080` — таймлайны воркфлоу/активностей, повторы,
  падения.
- **Prometheus** + **Grafana** — воркер экспортирует метрики Temporal SDK
  через Prometheus-экспортёр (`src/workflow/worker.py::_build_runtime`,
  под флагом `METRICS_ENABLED`); дашборды Grafana (Ingest Overview,
  Version compare, Run drill-down) читают их плюс таблицу Postgres
  `ingest_metrics`.
- **`ingest_metrics`** — длительности по каждой активности + теги моделей
  по ролям (зафиксированы при запуске), так что дашборды атрибутируют
  каждый шаг точной модели, которая его выполнила, даже после замены
  модели.
- **Оценка качества ответов** — `tests/eval/` оценивает ответы эндпоинтов
  (полнота фактов/сущностей, точность цитирования, граница галлюцинаций)
  детерминированно и офлайн.

→ [`runbook/analytics.md`](runbook/analytics.md).

---

## 8. Конфигурация

Все настройки проходят через `src/config.py` (pydantic-settings, читает
`.env`), с пространствами имён по подсистемам: `API_`, `MILVUS_`, `NEBULA_`,
`POSTGRES_`, `MINIO_`, `LITELLM_`, `TEMPORAL_`, `INGESTION_`, `AGENT_`,
`LLM_POOL_`, `WIKIBASE_` / `WIKI_`, `METRICS_`. Тумблеры новых функций
(история диалога, dual walk-seed, иерархические сообщества, тип индекса
Milvus) перечислены в
[`FEATURES.md`](FEATURES.md#config-quick-reference-new-feature-env-vars);
процедура замены модели — в [`MODELS.md`](MODELS.md).

---

## 9. Ещё не подключено

- Гибридный ретривер (BM25 + векторный RRF) существует в
  `src/retrieval/hybrid.py`, но не входит в живой путь извлечения.
- Мультитенантная изоляция данных — `department` проходит через
  метаданные, но не применяется на этапе извлечения.
- Настроенное Temporal **Schedule** для перестроек сообществ/wiki (сегодня
  они запускаются админом).
