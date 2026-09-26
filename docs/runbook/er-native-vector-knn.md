# ER vector kNN через Milvus (снятие окна 5000)

## Зачем
Инкрементальный entity-resolution при каждом инжесте сравнивает новые
сущности с уже сохранёнными. Исходный путь грузил окно из
`incremental_window` (5000) канонических сущностей, отсортированных по
`mention_count`. На большом графе это потолок: замерено на синтетике —
при **200k** канонических окно 5000 «видит» лишь **~2%** истинных
ближайших матчей, остальное фрагментируется в дубли.

Режим vector kNN заменяет загрузку окна на **kNN по Milvus-коллекции
`entity_er_vec`** (шов `EntityVectorStore` → `MilvusEntityVectorStore`):
для каждой новой сущности ищутся ближайшие канонические по **всему графу**
(без окна). Бенч: recall ~96% (`tests/eval/scale/bench_er_native`).

## Состояние по умолчанию
Включено: `AGENT_ER_USE_NATIVE_VECTOR_KNN=true` (префикс `AGENT_` —
`AgentSettings`). Ingest-активности `merge_and_resolve` всегда передают
`vector_store=build_entity_vector_store(...)`, поэтому kNN идёт в Milvus, а
разрешённые канонические сущности upsert'ятся обратно в `entity_er_vec`
в конце ER — коллекция наполняется по мере инжеста.

```bash
AGENT_ER_USE_NATIVE_VECTOR_KNN=true
AGENT_ER_VECTOR_KNN_K=20   # соседей на новую сущность (по умолчанию 20)
```

Отдельного бэкфилла нет: сущности, записанные в граф до появления коллекции,
находятся kNN только после ре-инжеста их документов.

## Откат
`AGENT_ER_USE_NATIVE_VECTOR_KNN=false` + перезапуск ingest-воркера вернёт
легаси-загрузку окна (`_load_existing_canonicals`). **Внимание:** это
параметризованный Cypher, который хранилище NebulaGraph не выполняет — на
Nebula откат означает ER только внутри батча (без кросс-документного
дедупа). Используйте только как аварийный выключатель Milvus-зависимости.

## Проверка
- Размер коллекции растёт по мере инжеста:
  ```bash
  uv run python -c "
  from pymilvus import MilvusClient
  from src.config import settings
  c = MilvusClient(uri=settings.milvus.uri)
  print(c.get_collection_stats('entity_er_vec'))
  "
  ```
- В логах merge/resolve нет `ER vector-store kNN failed`; склейки растут
  (меньше дублей в графе).

## Требования
Milvus (тот же, что для чанков). Размерность вектора берётся из `MILVUS_DIM`
(`settings.milvus.dim`, по умолчанию 768).
