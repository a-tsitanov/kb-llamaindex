## Контуры

Проект разделён на контуры; граница — пакет, не репозиторий.

| Контур | Где | Отвечает за |
|---|---|---|
| Приём | `src/intake/` | входная группа: классификатор, дедуп по телу, реестр приёма (`documents`), очередь, маршруты `/ingest` и выдача оригинала |
| Ядро | `src/workflow/`, `src/graph/`, `src/retrieval/`, `src/analytics/` | документы в граф и чтение графа; статус обработки — `doc_processing` |
| Наблюдение | `src/watch/` | подписки на сущности, детекторы событий, доставка |
| Доступ | `src/tenancy/`, `src/api/graph_dep.py`, `src/mcp/_shared.py` | арендаторы, права ключа, выбор графа; шва три, других нет |
| Инфраструктура | `src/storage/` | Postgres, MinIO, схема графа — НИЖЕ контуров, импортировать её можно всем |

Правила границы (исполняются тестом `tests/test_intake/test_boundaries.py`):

- `src/graph`, `src/retrieval`, `src/workflow` не импортируют `src.intake`,
  кроме объявленных воркерных адаптеров;
- `src/intake` не импортирует `src.graph`;
- `ChunkRepository` не получает `pg=AsyncPostgres(...)` ни из одного модуля;
- ядро не импортирует `src.watch`, кроме трёх объявленных адаптеров
  (воркер, запись журналов на ингесте, переписывание vid при слиянии);
- `src/watch` не импортирует приём мимо `IntakeRepository` (`tests/test_watch/test_boundaries.py`).

Карта контуров и порядок работ — `docs/superpowers/plans/2026-10-17-project-boundaries.md`.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
