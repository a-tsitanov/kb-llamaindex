# Контур наблюдения (P2) — план реализации

Спека: `docs/superpowers/specs/2026-10-20-watch-contour-design.md`.
Ветка: `a-tsitanov/intake-contour` (продолжение, P1 закрыт).

Порядок обязателен: S1 трогает те же файлы, что S2–S4, и переносить
код после того, как он изменился, значит делать работу дважды.

## S1 — пакет `src/watch/`

Чистый перенос, поведение не меняется.

| Из | В |
|---|---|
| `src/graph/watch_journal.py` | `src/watch/journal.py` |
| `src/workflow/monitor/watch_sweep.py` | `src/watch/sweep.py` |
| `src/storage/watch.py` | `src/watch/repository.py` |
| `src/workflow/monitor/delivery.py` | `src/watch/delivery.py` |
| `src/workflow/monitor/activities.py` | `src/watch/activities.py` |
| `src/workflow/monitor/workflow.py` | `src/watch/workflow.py` |

Правятся импортёры: `src/workflow/worker.py`, `src/api/routes/admin.py`,
`scripts/setup_monitor_schedule.py`, `src/workflow/activities/build_property_graph.py`,
`src/mcp/tools_server.py`, тесты.

Имена классов и активностей НЕ меняются (Temporal-расписание).

Тест: `tests/test_watch/test_boundaries.py` — ядро не импортирует
`src.watch`, кроме `build_property_graph`; `src.watch` не импортирует
`src.intake`, кроме `repository` (под §S3).

Критерий: `MONITOR_ACTIVITIES` и `MonitorSweepWorkflow` регистрируются
воркером из нового места, набор тестов прежний зелёный.

## S2 — вывод дуги `:Alert`

Удалить: `detect_alerts`, `deliver_alerts`, `src/graph/alerts.py`,
`src/graph/alert_store.py`, запись/чтение флага `Entity.watched`,
burst-настройки, `MONITOR_WEBHOOK_URL`/`_TIMEOUT_S`.

Добавить детектор `risk_rise` в `src/watch/sweep.py`: чтение
`risk_score`/`risk_score_prev` у наблюдаемых сущностей (перенести
`_read_risk_rise`), событие с `dedup_key = risk_rise:<vid>:<score:.2f>`.

Критерий: `grep -r "Alert" src/` не находит ни записи, ни чтения;
`risk_rise` появляется в `watch_event`, а не в графе.

## S3 — провенанс приёма в событии

`IntakeRepository.provenance_of(doc_ids)` → `{doc_id: {source_kind,
intake_status, duplicate_of, doc_date}}`, один запрос на пачку.
`run_watch_sweep` зовёт его и кладёт в `detail["provenance"]`.

Критерий: событие по документу из перепоста несёт
`provenance.intake_status = 'duplicate'` и ссылку на владельца тела.

## S4 — доставка

1. Схема: `watch.webhook_url`, `watch.daily_push_limit`, таблица
   `watch_delivery` (PK `(owner, event_id)`), идемпотентный DDL в
   `GRAPH_DDL`.
2. `records_for_owner` в `src/tenancy/api_keys.py`.
3. `src/watch/delivery.py`: отправка одного события, ретрай по счётчику
   попыток, суточный потолок, сводка остатка, проверка права перед
   КАЖДОЙ отправкой.
4. Активность `deliver_watch` в `src/watch/activities.py`, вызов из
   `MonitorSweepWorkflow` после свипа.

Критерии: повторный проход не доставляет то же событие дважды; отзыв
всех ключей владельца останавливает доставку; сверх потолка приходит
одна сводка, а лента остаётся полной.

## S5 — документация

`docs/runbook/watch.md` (новый), карта контуров в `CLAUDE.md` (строка
«Наблюдение» получает свой пакет), `docs/BACKLOG.md` (burst,
`risk_snapshot`), CHANGELOG.

## Риски

* **Temporal-расписание** живёт по имени воркфлоу — имена не меняем, но
  воркер обязан перезапуститься с новым кодом, иначе активность не
  найдётся. Это выкат, а не код.
* **Удаление `:Alert`** необратимо для уже записанных узлов: они
  останутся в графе мусором. Чистка — отдельная операторская задача, в
  объём не входит (записываем в runbook).
* **Webhook на подписку** — пользовательский ввод в исходящий запрос.
  Схему URL валидировать (`http`/`https`), иначе подписка становится
  инструментом запросов во внутреннюю сеть.
