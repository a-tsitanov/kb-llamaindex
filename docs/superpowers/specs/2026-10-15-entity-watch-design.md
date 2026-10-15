# Отслеживание сущностей (watch) — журналы в Postgres + детекторы

Дата: 2026-10-15. Связано: Arc-2 монитор (`src/workflow/monitor/`),
`fact_supersede` (`src/graph/edge_conflicts.py`), таблица `entity`
(`2026-08-21-entity-search-table-design.md`).

## Задача

Пользователь ставит сущность «на контроль» и получает ленту: в каких новых
документах она встретилась, какие у неё появились связи и идентификаторы,
где новый документ противоречит старому.

Старый Arc-2 путь на это не годится:

- флаг `Entity.watched` в Nebula стирался при каждом повторном упоминании
  (`upsert_nodes` делал `INSERT VERTEX` без этой колонки; исправлено —
  `nebula_store._PRESERVED`);
- граф не хранит связь «документ → сущности» (только `first_doc_id`), значит
  «новое упоминание» не увидеть вовсе;
- детект шёл сканом графа по окну дат, а не по тому, что реально пришло.

Решение: ingest пишет **журналы** в Postgres (что появилось, из какого
документа), детекторы раз в 5 минут читают журналы **по курсору** и пишут
события только для сущностей с подпиской.

## Таблицы

| Таблица | Кто пишет | Когда | Кто читает |
|---|---|---|---|
| `entity_mention` | `build_property_graph` | каждый документ, все сущности | sweep (`new_mention`) |
| `edge_new` | `build_property_graph` | пара (src,tgt), которой не было в графе | sweep (`new_connection`, `new_identifier`, `new_event`) |
| `fact_supersede` (есть) | `build_property_graph` / `edge_conflicts` | конфликт фактов | sweep (`contradiction`) |
| `watch` | MCP `kb_watch` / `kb_unwatch` | подписка | sweep, лента |
| `watch_event` | sweep | найдено событие | MCP `kb_watch_feed` |
| `watch_seen` | MCP `kb_watch_feed` / `kb_ack` | показано / подтверждено | лента |
| `monitor_cursor` | sweep | каждый прогон | sweep |
| `risk_snapshot` | (позже) пересчёт риска | — | (позже) `risk_rise` |

Схемы — `scripts/setup_db.py` (`_WATCH_DDL`, `_WATCH_INDEXES_DDL`). Ключевое:

- `entity_mention` PK `(entity_vid, doc_id)`, `id BIGSERIAL UNIQUE` — курсор;
- `edge_new` UNIQUE `(src_vid, tgt_vid)` — только первое появление пары;
- `watch` UNIQUE `(owner, entity_vid)`; `owner='default'` пока в панели нет
  пользователей;
- `watch_event.dedup_key` UNIQUE — повторный прогон не плодит дубли;
- события **общие** на сущность; прочитанность — по пользователю в
  `watch_seen`.

`entity_vid` = тот же `entity_vid(name)`, что ключ вершины в Nebula и строки
в `entity`.

## Запись при ingest

После `upsert_nodes` / `upsert_relations` (ER уже отработал, имена
канонические):

- `entity_mention` — строка на каждую сущность документа,
  `ON CONFLICT DO NOTHING`;
- `edge_new` — пары, которых не было в read-back `upsert_relations`
  (метод теперь возвращает новые пары; при сбое read-back — пусто, т.е.
  лучше пропустить событие, чем выдать ложное);
- `backfill` (из `IngestParams.backfill`, по умолчанию false) — перезаливка
  пишет журналы, но sweep по таким строкам событий не создаёт.

Сбой записи журнала логируется и **не валит** ingest.

## Слияние в ER

`_cleanup_stored_losers` после успешного `merge_loser_into_canonical`
переписывает `vid` проигравшего на канонический в `watch`, `entity_mention`,
`edge_new`, `watch_event`. При конфликте уникальности (обе формы уже есть)
строка проигравшего удаляется. Подписка на «Исаев В.И.» переживает слияние в
«Исаев Валентин Игоревич».

## Sweep (каждые 5 минут)

Активность `sweep_watch` в `MonitorSweepWorkflow` (первым шагом; старые
`detect_alerts`/`deliver_alerts` остаются для risk_rise/burst по
Nebula-флагу). `MONITOR_SWEEP_INTERVAL_MINUTES` по умолчанию 5.

Для каждого журнала (`entity_mention`, `edge_new`, `fact_supersede`):

1. `last_id` из `monitor_cursor` (нет строки — 0);
2. строки `id > last_id`, старше 60 с (запас на транзакции, закоммиченные не
   по порядку id), порциями до 1000;
3. чистые детекторы → события только для `vid` из `watch`;
4. `INSERT … ON CONFLICT (dedup_key) DO NOTHING` + сдвиг курсора — одна
   транзакция.

| Детектор | Источник | Условие | dedup_key |
|---|---|---|---|
| `new_mention` | `entity_mention` | сущность на контроле, не backfill | `new_mention:{vid}:{doc_id}` |
| `new_identifier` | `edge_new` | вторая сторона — тип из `IdentifierType` (телефон, адрес, ИНН, …), кроме DocumentDate/Amount | `new_identifier:{vid}:{other_vid}` |
| `new_event` | `edge_new` | вторая сторона — EventOrAction | `new_event:{vid}:{other_vid}` |
| `new_connection` | `edge_new` | вторая сторона — прочее | `new_connection:{vid}:{other_vid}` |

Связи со второй стороной DocumentDate, Document, Concept, Metric, Other событий
не дают: документ и его даты уже есть в `new_mention`, остальное — шум
извлечения (по живому тесту 2026-10-15).
| `contradiction` | `fact_supersede` | src или tgt на контроле | `contradiction:{vid}:{id}` |

Позже: `risk_rise` (после materialize, по `risk_snapshot`), `burst`, дневной
дайджест.

## MCP (`kb-llamaindex-tools`)

| Инструмент | Что делает |
|---|---|
| `kb_watch(name, kinds?, note?)` | ищет сущность в `entity` (exact → substring); один кандидат — подписка, несколько — список кандидатов |
| `kb_unwatch(name_or_vid)` | снять подписку |
| `kb_watchlist()` | подписки владельца |
| `kb_watch_feed(include_acked=false, limit=50)` | события по подпискам, сгруппированы в карточки по документу, со ссылкой `/api/v1/documents/{id}`; помечает `seen_at` |
| `kb_ack(event_ids? , all?)` | `acked_at` — убирает из непрочитанного |

Лента показывает события, найденные **после** подписки
(`detected_at >= watch.created_at`), с учётом `kinds` и `muted_until`.

## Чистка

`scripts/wipe_db.py` чистит журналы, события, прочитанность, курсоры и
`risk_snapshot`. `watch` сохраняется: `vid` — хэш имени, подписки остаются
валидными после перезаливки.

## Не делаем сейчас

Дозаполнение журналов для уже загруженных документов; webhook-доставку;
пользователей (owner — `default`).
