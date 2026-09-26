# Runbook: аналитика по графу (analytical-query layer)

> Не путать с [`analytics.md`](analytics.md) — тот runbook про **ingest-метрики**
> (Grafana / Prometheus / `ingest_metrics`). Здесь — про **аналитические запросы
> к графу знаний**: слой `src/analytics/` (Waves 0–3), каталог из 42
> детерминированных примитивов, `/api/v1/analyze`, материализация и мониторинг.
> Теория за инструментами (центральности, Leiden, link prediction, риск) —
> в [`../ANALYTICS-GUIDE.md`](../ANALYTICS-GUIDE.md).

## 1. Обзор

Слой отвечает на **количественно-структурные** вопросы («сколько», «кто самый
центральный», «как связаны», «что изменилось») по конвейеру
**plan → compute → synthesize**:

1. **Plan** — LLM-планировщик получает каталог примитивов
   (`src/analytics/planner.py`, `render_catalog_for_planner`) и раскладывает
   вопрос на ≤ `ANALYTICS_MAX_STEPS` вызовов примитивов с параметрами.
2. **Compute** — каждый примитив это детерминированный запрос к графовому
   хранилищу (NebulaGraph; `src/analytics/primitives/*`), никакого LLM.
3. **Synthesize** — LLM собирает человекочитаемый ответ из строк примитивов.

Исполняется как Temporal `AnalyticalQueryWorkflow` на очереди **search**-пула
(`src/workflow/analytics/workflow.py`). Для «что говорят документы» используйте
поиск (`/search/*`, `kb_search`) — не этот слой.

## 2. Поверхности

| Поверхность | Что | Auth |
|---|---|---|
| `POST /api/v1/analyze` | Полный plan→compute→synthesize | `X-API-Key` |
| MCP-1 `kb_analyze(query, top_n)` | То же самое через MCP (`src/mcp/search_server.py`) | `Authorization: Bearer <API_KEYS>` |
| `POST /admin/graph/{stats,pagerank,personalized-pagerank,components,shortest-path}` | Прямые графовые алгоритмы (igraph в воркере / материализованный `pagerank`) без LLM | `X-API-Key` |
| `POST /admin/graph/materialize` | Запуск офлайн-материализации (§6) | `X-API-Key` |
| MCP-2 `graph_pagerank`, `graph_personalized_pagerank`, `graph_components`, `graph_shortest_path`, `graph_stats` | Графовые аналитические тулы для агентских клиентов | Bearer |

## 3. Контракт запроса/ответа

Запрос: `{"query": "<вопрос>", "top_n": 20}`. Ответ:

```jsonc
{
  "query": "...",
  "answer": "...",              // LLM-синтез — глосса, НЕ источник истины
  "provenance": {
    "route": "catalog",
    "plan_reason": "...",       // почему планировщик выбрал эти примитивы
    "steps": [{
      "primitive": "count_relationships",
      "params": {"rel_type": null, "polarity": null},
      "cypher": "MATCH ...",    // точный выполненный запрос
      "rows": [{"n": 578}],     // сырые строки — ИСТОЧНИК ИСТИНЫ
      "row_count": 1,
      "source_chunks": [],
      "truncated": false,
      "error": "",               // непусто ⇒ примитив не смог выполниться (см. ниже)
      "error_detail": ""         // операторская расшифровка error; никогда не идёт в LLM-синтез
    }],
    "elapsed_ms": 6669
  },
  "latency_ms": 6669
}
```

> ⚠️ **Правило provenance.** Всё численное/фактическое читайте из
> `provenance.steps[].rows`, а `answer` воспринимайте как пересказ. Малые модели
> путаются в цифрах: зафиксированный случай (2026-07-03, gemma e2b) — примитив
> вернул `{"n": 578}` (число связей), синтез написал «одна сущность с номером
> 578 и ноль связей».

> ⚠️ **`rows: []` — не всегда «нашли ноль».** Каждый шаг несёт поле `error`.
> Пустая строка значит «примитив выполнился штатно» (пустой `rows` в этом
> случае — честный факт: в графе действительно ничего не нашлось). Непустой
> `error` значит, что примитив вообще не смог выполниться — например, backend
> `nebula` пока не умеет параметризованные запросы и структурно отказывает в
> них (`NebulaGraphStore.structured_query` бросает `NotImplementedError` на
> непустой `param_map`) — и `rows: []` здесь не результат, а последствие сбоя.
> Синтез в этом случае прямо пишет «не удалось вычислить», а не выдаёт эту
> пустоту за измеренный ноль. При чтении provenance всегда проверяйте `error`
> раньше, чем интерпретировать пустой `rows`.
>
> `error` — короткая, безопасная для показа причина (её же видит LLM-синтез,
> поэтому там нет внутренних деталей вроде «nGQL» / «param_map» / «Phase 2»).
> Полный текст исключения — в `error_detail`, только для операторов
> (диагностика, логи); в промпт синтеза он никогда не попадает. Строку
> `execute_step primitive=... cannot run on this backend...` также ищите в
> логах воркера уровня ERROR — это то же событие, что и `error_detail`, но
> агрегируемое по времени, а не по одному запросу.

## 4. Каталог примитивов (42)

Актуальный список — `CATALOG` в `src/analytics/catalog.py` (регистрируется при
импорте `src.analytics.primitives`). По группам:

| Группа | Примитивы |
|---|---|
| Обзор/счётчики | `count_entities`, `count_relationships`, `distribution_by_type`, `distribution_by_polarity`, `distribution_by_relation_type`, `numeric_rollup`, `communication_stats` |
| Центральность/важность | `top_central_entities`, `top_entities_by_degree`, `top_entities_by_mentions`, `personalized_pagerank` |
| Сообщества | `community_overview`, `entity_communities` |
| Связи/расследование | `entity_dossier`, `connection_path`, `common_connections`, `cooccurrence`, `neighbors_by_relation`, `investigate_next`, `identifier_lookup`, `shared_identifier_entities`, `entity_activity` |
| Динамика/время | `whats_changed`, `topic_trend`, `trending_events`, `event_timeline`, `event_dossier`, `new_events`, `entity_new_connections`, `relationship_timeline`, `polarity_evolution` |
| Качество графа | `orphans`, `incomplete_entities`, `merge_candidates`, `recommended_merges`, `review_queue`, `contradictions`, `issue_resolution_stats` |
| Риск/прогноз | `risk_score`, `circular_ownership`, `link_prediction`, `alerts` |

### Доверие к источнику и разрешение конфликтов фактов

Ингест сливает извлечение каждого документа отдельно и перезаписывает ребро
(`nebula` держит одно ребро на пару vid'ов, rank 0), поэтому менее достоверный
документ раньше молча переворачивал факт, утверждённый более достоверным —
побеждал последний писавший. Теперь побеждает **более доверенный источник**.

Политика (`src/graph/edge_conflicts.py`, доверие — `src/analytics/source_trust.py`):

| Ситуация | Что происходит |
|---|---|
| Ребра ещё нет / полярность совпадает | пишем как раньше; на ребре остаётся максимальное виденное доверие |
| Полярность противоположна, доверие нового ≥ хранимого | новое убеждение побеждает, `superseded_at` = день ингеста |
| Полярность противоположна, доверие нового ниже | хранимая полярность сохраняется; описание/вес/окно валидности всё равно обновляются |

Ребро `RELATED` получило две колонки: `source_trust` (доверие документа,
задавшего текущую полярность) и `superseded_at` (день, когда прежнее
противоположное убеждение было снято; 0 — конфликта не было). Само снятое
убеждение живёт в Postgres-таблице **`fact_supersede`** — это аудиторский след
(что граф считал, что заявил новый документ, кто победил и с каким доверием):

```sql
SELECT decided_at, src, rel, tgt, stored_polarity, new_polarity,
       stored_trust, new_trust, winner
  FROM fact_supersede ORDER BY decided_at DESC LIMIT 20;
```

Knobs:

- `SIGNALS_SOURCE_TRUST` — JSON-карта `группа документа → доверие 0..1`,
  например `{"analytics": 0.9, "news": 0.4}`. **Пустая карта (default)
  полностью выключает проход** — ни read-back, ни записи в лог, поведение
  ровно как до фичи.
- `SIGNALS_SOURCE_TRUST_DEFAULT` — доверие для группы вне карты (default 0.5).

Группа берётся из `group`, который `/ingest` уже проставляет документу, поэтому
перенастройка политики не требует переингеста. Рёбра, записанные до фичи, имеют
`source_trust = 0.0` — первый же доверенный документ их перебьёт; бэкфилл не
нужен.

Тем же доверием взвешивается consensus на уровне утверждений
(`src/analytics/contradictions.py`): версия ранжируется суммой доверия
подтвердивших её источников, а не числом источников — один отчёт перевешивает
три перепечатки слуха. Без карты доверия вес = число источников (прежнее
поведение).

Настройки планировщика: `ANALYTICS_MAX_STEPS` (default 3, макс. примитивов в
одном плане), `ANALYTICS_DEFAULT_TOP_N` (default 20). Даты запроса на уровне
`/analyze` пока не прокидываются — планировщик задаёт даты per-primitive
(Wave-0 ограничение, см. `src/api/routes/analyze.py:_to_params`).

## 5. Материализация (Wave 1)

`top_central_entities`, `link_prediction`, `risk_score` читают **предвычисленные**
значения. Пересчёт — офлайн-джоб:

```bash
curl -X POST -H "X-API-Key: $API_KEY" http://localhost:8000/admin/graph/materialize
# → 202 {"workflow_id": "analytics-materialize-<hex>", "status": "started"}
```

Fire-and-forget: `AnalyticsMaterializeWorkflow` на очереди **graph_build**
считает pagerank/betweenness/eigenvector (weighted, igraph в воркере) +
link-prediction + risk и пишет обратно в граф (`src/analytics/materialize.py`).
Параллелизм — `TEMPORAL_ANALYTICS_MATERIALIZE_CONCURRENCY`.

**Когда запускать:** после каждого bulk-ингеста (например, tg_ingest); без прогона центральность/прогнозы отражают старый граф.
Прогресс смотреть в Temporal UI (`analytics-materialize-*`).

## 6. Мониторинг Arc-2 (opt-in, выключен по умолчанию)

Периодический свип по Temporal Schedule в пуле воркера **monitor**: детект
новых связей, рост risk_score, burst событий (E3); алерты складываются в граф
(читаются примитивами `alerts` / `review_queue`) и опционально пушатся в webhook.

| Env | Default | Что |
|---|---|---|
| `MONITOR_ENABLED` | `false` | Главный флаг; включить + пересоздать worker |
| `MONITOR_SWEEP_INTERVAL_MINUTES` | `30` | Период свипа |
| `MONITOR_TASK_QUEUE` | `kb-monitor` | Очередь (пул `monitor` в `WORKER_GROUPS`) |
| `MONITOR_NEW_WINDOW_DAYS` | `7` | Окно детекта новых first_seen-связей |
| `MONITOR_RISK_RISE_DELTA` | `0.1` | Порог роста risk_score для алерта |
| `MONITOR_BURST_ENABLED` | `false` | Burst-детектор событий (E3) |
| `MONITOR_BURST_WINDOW_DAYS` / `_BASELINE_WINDOWS` / `_MIN_COUNT` / `_RATIO` | `7`/`4`/`2`/`3.0` | Окно / базовые окна / мин. событий / порог recent÷base |
| `MONITOR_WEBHOOK_URL` | `""` | Доставка алертов POST'ом (пусто — выключена) |
| `MONITOR_WEBHOOK_TIMEOUT_S` / `MONITOR_DELIVER_BATCH` | `5.0`/`100` | Таймаут / алертов за свип |

> ⚠️ В `docker-compose.prod.yml` переменные `MONITOR_*` (как и
> `ANALYTICS_DEFAULT_TOP_N`/`ANALYTICS_MAX_STEPS`) **не прокинуты в anchor
> `x-app-env`** — значение из `.env` до контейнера не дойдёт (тот же класс
> ловушки, что инцидент с `TEMPORAL_COMMUNITY_BACKEND` 2026-06-30). Перед
> включением мониторинга в прод-компоузе добавьте нужные переменные в anchor.

> ⚠️ **Известные пробелы на NebulaGraph.**
> - **Webhook-доставка не работает.** Если задан `MONITOR_WEBHOOK_URL`,
>   активность `deliver_alerts` (`src/workflow/monitor/activities.py`) шлёт
>   Cypher (`MATCH (a:Alert) … LIMIT $cap`) с `param_map`, который
>   `NebulaGraphStore.structured_query` отвергает (`NotImplementedError`) —
>   активность ловит исключение и **всегда** возвращает `DeliverResult` с
>   `error`, ничего не доставлено и `pushed_at` не проставлен. Алерты при этом
>   пишутся в граф и читаются примитивом `alerts`. Порт на nGQL — в бэклоге.
> - **Burst-детектор в свипе пропускается**: `_read_burst` возвращает `[]` без
>   запроса (watched-only burst не портирован), так что
>   `MONITOR_BURST_ENABLED=true` алертов burst не даёт.

Ручное управление (без ожидания расписания):

```bash
# разовый свип прямо сейчас
curl -X POST -H "X-API-Key: $API_KEY" http://localhost:8000/admin/monitor/sweep
# пометить сущности наблюдаемыми (watch-list для свипа)
curl -X POST -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '["БРИКС","Газпром"]' "http://localhost:8000/admin/monitor/watch?watched=true"
```

## 7. Смоук + плейбук проверки качества

```bash
curl -s http://localhost:8000/api/v1/analyze \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"query":"Сколько сущностей каждого типа?"}' | jq '.provenance.steps[0].rows'
```

Рекомендуемый цикл после наполнения: **ингест → materialize → серия вопросов**.
Минимальный набор на покрытие: счётчики (`distribution_by_type`), центральность
(`top_central_entities` — после §5), досье (`entity_dossier` на хаб-сущность),
динамика (`whats_changed`, `trending_events` — требует настоящих
`document_date`), качество (`orphans`, `incomplete_entities`,
`merge_candidates` — главный детектор слабой extraction-модели), связи
(`common_connections`, `connection_path`), негативный вопрос вне корпуса
(ответ обязан честно сказать «нет данных»).

Метрики качества extraction, за которыми следить от прогона к прогону: доля
сущностей типа `Other`, доля связей `RELATED` (нетипизированных), появление
названий типов как сущностей (ловится `merge_candidates`/`review_queue`).

## 8. Диагностика

| Симптом | Причина | Действие |
|---|---|---|
| `answer` противоречит цифрам | Слабая модель синтеза (e2b) | Верить `provenance.steps[].rows`; поднять tier до e4b |
| `top_central_entities` / `link_prediction` пусто или устарело | Материализация не гонялась | §5 `POST /admin/graph/materialize` |
| 500 `Analyze failed` | Search-пул воркера не поднят / Temporal недоступен | `docker logs kb-llamaindex-worker-1`, пул `search` в `WORKER_GROUPS` |
| Всё по нулям при живом графе | Приложение смотрит не в тот граф (env) | Сверить `NEBULA_HOST`/`NEBULA_PORT`/`NEBULA_SPACE` контейнера с ожидаемым |
| `kb_analyze` не виден в MCP-клиенте | Старый образ mcp-search / клиент не переподключился | Пересобрать, `/mcp` reconnect |
| Алертов нет при включённом мониторе | `MONITOR_ENABLED` не дошёл до воркера (env только в `.env`, не в compose-anchor) | Проверить `docker exec worker env \| grep MONITOR_`; пересоздать worker |
