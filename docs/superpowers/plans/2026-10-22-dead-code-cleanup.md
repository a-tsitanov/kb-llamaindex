# Чистка мёртвого кода и файлов — план

Дата: 2026-10-22. Разведка проведена по текущему HEAD ветки
`a-tsitanov/intake-contour` (`07cf4440`). Ничего не удалено — это план.

Повод: после закрытия P1 и P2 в дереве осталось три вида мусора —
дубли живого кода, остатки выведенной дуги `:Alert` и залежавшиеся
worktree. Один остаток того же класса (флаг `Entity.watched`) нашла живая
проверка 2026-10-21, уже после того как юнит-тесты были зелёными: удаление
было сделано наполовину. Этот план закрывает остальные.

## Что найдено

| Находка | Вес | Доказательство |
|---|---|---|
| `src/graph/merge_and_resolve.py` — дубль живой активности | 350 строк | ноль импортёров; живая копия — `src/workflow/activities/merge_and_resolve.py` (в `MERGE_ACTIVITIES`). Копии разъехались на 11 строк, то есть правили одну из них |
| Тег `Alert` в схеме Nebula: `CREATE TAG`, индекс `alert_key_idx`, проба готовности записи | `src/graph/nebula_schema.py` (3 места) | дуга выведена в P2, читателей и писателей нет; схема и проба прогоняются на каждом `ensure_schema` |
| Таблица `risk_snapshot` | DDL + `wipe_db` + 3 теста | ноль упоминаний в коде вне схемы и очистки; прежний риск лежит на узле графа |
| `reset_api_key_store_for_tests`, `reset_graph_registry_for_tests` | 2 функции | ноль ссылок, в том числе из тестов (ср. `reset_nebula_stores_for_tests` — используется) |
| `src/graph/backend.py` — Protocol `KbGraphStore` | 24 строки | никто не импортирует; документация в виде кода |
| `scripts/diag_kg_lightrag.py` | 96 строк | ноль ссылок, включая документацию и Makefile |
| Устаревший докстринг `tests/test_api/test_monitor_route.py` | 1 строка | ссылается на `mark_watched`, удалённый в P2 |
| Worktree в `.claude/worktrees/{anal,calc,capacity-fix,reactive-roaming-robin}` | **1.5 ГБ** | все четыре ветки влиты в HEAD; внутри старые копии `src/` — ломают грепы и индекс graphify |
| 58 влитых локальных веток из 62 | — | не влиты только `feat/nebula-descent-wip`, `feat/search-date-filters`, `feature/redis-llm-cache` |
| `docker-compose.openclaw.yml` | 1 файл | openclaw заменён Hermes 2026-10-20 |
| `deploy/offline/loadtest/er_d1/` | 2 МБ | исследовательский прогон, упомянут только в `docs/BACKLOG.md` |
| Пустые каталоги `worktrees/.orca-worktree-trash`, `.mimocode/plans` | 0 | мусор |

Проверено и мёртвым НЕ является: `stat_indicator` и `stat_observation`
(читает `src/mcp/stats_server.py`), `public.schema_migration` (маркеры
миграций), `src/ingestion/run.py` и скрипты без импортёров — это CLI-входы,
их зовут через `python -m`.

Не мёртвое, но дублированное: отступление на 429 и разбор 409 написаны
трижды — `scripts/tg_ingest.py`, `deploy/offline/loadtest/loader.py`,
`scripts/ingest_medical.py`.

## Отдельно: прод-конфиг вне репозитория

На `.31` живёт `docker-compose.hermes.yml`, который **не отслеживается
git**. Переключение ветки его не тронуло именно поэтому. Конфиг
существует в единственном экземпляре на хосте: потеряем диск — потеряем
описание сервиса. Это не чистка, а дыра, и закрывать её надо раньше
косметики.

## Шаги

Порядок осмысленный: 1 и 9 освобождают место и чистят индекс, ничего не
ломая; 2–7 — удаления, по коммиту на шаг; 8 закрывает дыру; 10 —
рефакторинг, его нельзя смешивать с удалениями.

| № | Шаг | Риск | Как проверить |
|---|---|---|---|
| 1 | `git worktree remove` четырёх worktree, затем `git worktree prune`; удалить два пустых каталога | нет — все ветки влиты | `git worktree list` даёт две записи; `du -sh .claude` меньше на ~1.5 ГБ; `graphify update .` даёт меньше узлов |
| 2 | Удалить `src/graph/merge_and_resolve.py` | низкий, но делать ДО любых правок ER: иначе есть шанс править мёртвую копию | полный прогон тестов, arch-тесты границ, `grep -r "graph.merge_and_resolve"` пусто |
| 3 | Снять из `nebula_schema.py` тег `Alert`, индекс и пробу готовности | низкий; в созданных пространствах тег остаётся, код его не трогает | `tests/test_graph/test_nebula_schema.py`; на стенде `ensure_schema` проходит без пробы Alert |
| 4 | Удалить два неиспользуемых `reset_*_for_tests` | нет | прогон тестов |
| 5 | Снять `risk_snapshot` из `GRAPH_DDL`, `wipe_db` и трёх тестов; живые таблицы НЕ ронять | нет для кода | `tests/test_scripts/test_setup_db_watch.py`, `test_wipe_db.py` |
| 6 | Удалить `scripts/diag_kg_lightrag.py` и `src/graph/backend.py` — либо, если нужны как справка, дать им ссылку из документации | низкий | `ruff`, прогон тестов |
| 7 | Починить докстринг `tests/test_api/test_monitor_route.py` | нет | — |
| 8 | Внести `docker-compose.hermes.yml` с `.31` в репозиторий; удалить `docker-compose.openclaw.yml` | средний: это прод-конфиг | файл в git; `docker compose config` на `.31` не изменился |
| 9 | `git branch -d` по 58 влитым ветками (кроме трёх невлитых и `main`) | низкий; ветки в origin остаются | `git branch \| wc -l` ≈ 4 |
| 10 | Вынести общий клиент приёма (`post_document`: коды, отступление на 429, разбор 409), перевести на него `tg_ingest` и `ingest_medical`; загрузчику в `deploy/offline` оставить свою копию — он сознательно standalone | средний: трогает живой фидер | `tests/test_scripts/test_tg_ingest*`, плюс живой прогон одного раунда sync |

## Чего в плане нет

`deploy/offline/loadtest/er_d1/` (2 МБ) — решение за владельцем бэклога:
данные исследования, а не код. Стэш `feature/redis-llm-cache` не трогаем
по стоящему правилу. Живые таблицы `bot_user`, `bot_request`,
`risk_snapshot` и узлы `:Alert` на стендах — операторская чистка, не
кодовая; записана в `docs/runbook/watch.md` и `docs/BACKLOG.md`.
