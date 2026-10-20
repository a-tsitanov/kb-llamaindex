# Контур приёма (intake) — план реализации

Дата: 2026-10-19. Статус: на утверждение, код не писался.
Спека: [`2026-10-19-intake-contour-design.md`](../specs/2026-10-19-intake-contour-design.md). База: ветка `a-tsitanov/tenancy-authz`.

Прогон `code-plan`: разведка → план → критик → ревизия. Одиннадцать возражений, из них два блокирующих; разбор в §5.

---

## 1. Сводка ревизии

Ревизия плана реализации docs/superpowers/specs/2026-10-19-intake-contour-design.md на ветке a-tsitanov/tenancy-authz. 12 шагов TDD в прежнем порядке: аддитивная схема → одноразовая миграция intake_split_v1 по каждой схеме графа → чистые переносы модулей под защитой test_route_actions.py → arch-тест границ → расщепление записи статуса → отказ классификатора как intake_status='rejected' → дедуп по sha256 → расширенный GET /ingest/{job_id} → ops-скрипты.

ЧТО ИЗМЕНИЛОСЬ ПО ШЕСТИ ВОЗРАЖЕНИЯМ (все шесть проверены в коде, ни одно не принято «как есть»):

1. БЛОКЕР «прод-консьюмер стартует по старому пути модуля» — ПОДТВЕРЖДЁН и исправлен. `grep -rn 'ingest_queue' . --exclude-dir=.git` по всему репозиторию даёт ровно один исполняемый hit вне Python: docker-compose.prod.yml:189 `command: ["python", "-m", "src.ingest_queue.consumer"]` (плюс README.md:172 — дерево каталогов). Под deploy/ ссылки нет вовсе, то есть старая формулировка S4 «проверить deploy/ отдельным grep'ом» искала не там. docker-compose.prod.yml и README.md добавлены в allowed_files и правятся ТЕМ ЖЕ коммитом, что и перенос; предпроверка S4 расширена до grep по всему репозиторию с явным списком исключений (docs/superpowers/plans/* и docs/superpowers/specs/2026-07-01-* — исторические документы, их не трогаем).

2. БЛОКЕР «пропущен инжектор AsyncPostgres в ChunkRepository» — ПОДТВЕРЖДЁН и исправлен. Инжекторов два: src/mcp/tools_server.py:144 и src/workflow/_search_deps.py:127, оба `ChunkRepository(graph=graph, pg=AsyncPostgres(graph=graph))`, а chunk_repository.py:162 зовёт `self._pg.get(...)`. Решение НЕ «подставить IntakeRepository в обоих местах»: во втором это поставило бы прямой импорт src.intake в src/workflow и потребовало третьего исключения в arch-тесте. Вместо этого оба вызова теряют аргумент `pg=` вовсе, а ChunkRepository строит `IntakeRepository(graph=graph)` сам по умолчанию — конструкция побайтово эквивалентна прежней, а импорт остаётся внутри src/storage, где он уже разрешён. Аннотация параметра меняется на `IntakeRepository | None`; поскольку mypy/pyright в проекте НЕТ (в pyproject только ruff), аннотация одна защитить не может — добавлено правило 3 в arch-тест: ни один модуль под src/ не передаёт `pg=AsyncPostgres(...)` в ChunkRepository. Третья затронутая точка — tests/test_retrieval/test_graph_rank.py:294 `lambda *, graph, pg`: без правки TypeError; файл добавлен в S5 и в allowed_files.

3. КРУПНОЕ «intake_split_v1 воскрешает отклонённые документы при повторном прогоне» — ПОДТВЕРЖДЕНО и исправлено в корне. После S8 documents.status у новых строк навсегда остаётся 'pending' (колонка с DEFAULT, в неё не пишут), а S9 удаляет строку doc_processing — значит предикат `WHERE status <> 'skipped'` при повторе вставил бы отклонённым документам строку обработки 'pending'. Предикат ужесточён до трёх условий: `status <> 'skipped' AND intake_status <> 'rejected' AND NOT EXISTS (SELECT 1 FROM doc_processing p WHERE p.doc_id = d.id)`. Теперь оператор идемпотентен по существу, а не по маркеру, и маркер становится дешёвой оптимизацией, а не единственной защитой. Попутно исправлен САМ ТЕКСТ отката: прежняя инструкция «TRUNCATE doc_processing CASCADE и проиграть миграцию заново» после S8 уничтожала бы статусы ВСЕХ послерасщеплённых документов (их pre-split значения в documents.status нет — там 'pending'); в новом rollback это прямо запрещено.

4. КРУПНОЕ «on_duplicate=reject по умолчанию глушит документированный переингест» — ПОДТВЕРЖДЕНО и исправлено разделением политики по вызывающему. Проверено: scripts/tg_ingest.py:161 reingest_channels → post_ingest (:98) шлёт только priority=PRIO_BACKFILL, никакого on_duplicate; src/api/routes/ingest.py:84 backfill задокументирован как «Re-ingest of already-known material»; deploy/offline/loadtest/loader.py:76 шлёт backfill=true. Решение: поле формы становится `on_duplicate: str | None = Form(default=None)`, эффективная политика = явное значение, иначе 'version' при backfill=true, иначе 'reject'. tg_ingest в режиме reingest шлёт on_duplicate=version явно (post_ingest получает новый параметр), режимы sync и legacy --channels остаются на reject и считают 409 отдельным счётчиком дубликатов. Сегодняшнее поведение переингеста (новый doc_id, новый комплект чанков) сохраняется дословно — version делает ровно это, добавляя лишь ссылку duplicate_of.

5. КРУПНОЕ «on_duplicate=replace ничего наблюдаемого не делает» — ПОДТВЕРЖДЕНО и политика ОТЛОЖЕНА (сознательное отклонение от I4 спеки, см. risks). Проверено: в src/retrieval/ слово documents встречается только в комментариях (llm_pool.py:4-5, vector_index.py:88), ни одного запроса; chunk_repository читает documents только ради .path; фильтра по intake_status в путях чтения нет нигде. Значит после replace обе копии остаются одинаково находимыми и цитируемыми, тогда как Postgres объявляет одну дубликатом. Честная реализация требует удаления чанков старого документа из коллекции Milvus и его узлов/рёбер из графа, а сущности мёржатся МЕЖДУ документами (src/workflow/activities/merge_and_resolve.py → merge_kg_extraction), то есть поштучная чистка графа — отдельная задача со своим дизайном. В этом плане ON_DUPLICATE = ('reject','version'); 'replace' отвечает 422 с перечислением допустимых значений. Значение 'duplicate' в CHECK колонки intake_status сохраняется (его никто не пишет), чтобы будущий шаг не требовал миграции схемы.

6. КРУПНОЕ «S4 пропускает второго импортёра ingest_submit» — ПОДТВЕРЖДЕНО. Полный grep даёт для ingest_submit три файла помимо самого модуля: src/api/routes/ingest.py, tests/test_workflow/test_ingest_submit.py и tests/test_workflow/test_scheduler_isolation.py:55; для ingest_queue — дополнительно tests/test_api/test_ingest_priority.py:78. Оба теста добавлены в S4 и в allowed_files, а сам шаг теперь НАЧИНАЕТСЯ с полного grep'а по репозиторию, а не со списка радиуса поражения.

Сохранены три прежние поправки к спеке (предикат частичного уникального индекса включает duplicate_of IS NULL; запрос in-flight документов остаётся в ядре, меняется лишь таблица на doc_processing; исключений из правила импорта два, а не одно) и два прежних решения (timeline_counts не требует join; отчётный словарь статусов с ключом 'skipped' сохраняется целиком).

---

## 1a. Дополнение к ревизии (возражения 7, 9, 10, 11)

Фаза ревизии свернула в шаги шесть возражений — оба блокирующих и четыре
крупных. Четыре мелких остались записью в §5 и в шаги не попали. Они
конкретные и дешёвые, поэтому вносятся здесь; при расхождении текста шага с
этим разделом **верен этот раздел**.

**A. Возражение 9 — внешний ключ `duplicate_of` без `ON DELETE`.** В S1
объявлять `duplicate_of UUID REFERENCES documents(id) ON DELETE SET NULL`.
Сейчас в плане действие не указано, то есть `NO ACTION`: удаление документа, на
который кто-то ссылается как на оригинал, упирается в нарушение внешнего ключа —
включая живые тесты, которые прибирают за собой, и любую будущую чистку по сроку
хранения. Асимметрия с `doc_processing.doc_id ON DELETE CASCADE` намеренная и
должна быть объяснена комментарием в DDL: удаление документа уносит его
обработку, но не должно ни блокировать удаление оригинала, ни утаскивать за ним
версии — осиротевшая версия становится канонической.

**A′ (правка по ревью).** `ON DELETE SET NULL` сам по себе возражение 9 НЕ
закрывает: с предикатом индекса `… AND duplicate_of IS NULL` (см. S1 и
митигацию в рисках) удаление канонического документа, у которого ДВЕ и более
версии, падает нарушением уникальности — FK обнуляет ссылки одним `UPDATE`'ом,
и все версии одновременно входят в индекс с одинаковым хешем, то есть
возражение возвращается в другом виде. Итоговое решение: членство в индексе не
зависит от `duplicate_of` вовсе. Предикат — ровно `WHERE content_sha256 IS NOT
NULL` (как в §1.1 спеки), а версия пишется с `content_sha256 = NULL`
(`IntakeRepository.accept_document`, единственная точка записи); провенанс тела
у версии читается через `duplicate_of`. Осиротевшая версия, соответственно, НЕ
становится канонической: владельца тела у неё не остаётся — и это ровно то, что
нужно, потому что хеша она не несёт.

**B. Возражение 7 — гонка под `version` отдаёт 500.** Шаг S10 говорит, что
`accept_document` ловит `UniqueViolation` и «при version пробрасывает». Но под
`version`, если `find_by_sha` ничего не нашёл, INSERT идёт с
`duplicate_of=NULL` и попадает ровно в тот же частичный уникальный индекс при
одновременной первой заливке того же тела. Обработчика нет, значит FastAPI
ответит 500 на случай, ради которого индекс и заводился. Правильное поведение:
на `UniqueViolation` перечитать победителя и **повторить один раз** с
`duplicate_of = <id победителя>`; второй `UniqueViolation` — уже 500, это
настоящая аномалия. Тест (10) расширяется на `version`, а не только на `reject`.

**C. Возражение 10 — отказ по гонке оставляет мусор в MinIO.** Хеш считается до
заливки, поэтому обычный дубль до хранилища не доходит. Но ветка
`UniqueViolation` срабатывает уже **после** `put_object`: тело и необязательный
`original` записаны, а строки не будет никогда. Эти объекты лежат под префиксом
`doc_id`, на который не ссылается ни одна строка, и видимы только для
`delete_prefix` при удалении всего графа. В ветке `UniqueViolation` под `reject`
удалить только что записанные объекты до ответа 409 — best-effort, с записью в
журнал при неудаче, без превращения 409 в 500. Зафиксировать в тесте (10),
иначе уборку потеряют при первой же правке.

**D. Возражение 11 — неканонические строки раздувают отчётность.** После
появления `version` каждая версия — отдельная строка `documents`, и
`status_counts_by.total` считает её как ещё один документ, а `timeline_counts`
— как ещё одно сообщение. Инвариант «три поверхности показывают одинаковые
числа» при этом формально держится, но сами числа перестают означать
«документов принято». В обе агрегации добавить `WHERE d.duplicate_of IS NULL`.
Форма ответа не меняется, и инвариант «числа после миграции совпадают с
дорасщеплёнными» остаётся буквально верным: у всех строк, существовавших до
миграции, `duplicate_of IS NULL`. Предикат покрывается тестами репозитория в S8.

**D′ (правка по ревью).** Предикат в `WHERE` прячет не только лишнюю строку, но
и её ИСХОД: версия идёт в пайплайн, получает чанки и узлы и может упасть, а
оператор, который реингестил канал именно затем, чтобы что-то починить, не
видит её `failed` ни в одной из трёх поверхностей. Итоговое решение:
`timeline_counts` оставляет предикат (статуса лента не показывает вовсе), а
`status_counts_by` считает каноничность в SELECT/GROUP BY и отдаёт исход
неканонических строк ДОБАВОЧНЫМ полем `versions` — `{статус: сколько}` без
нулей. `total` и разбивка по статусам по-прежнему только канонические, то есть
инвариант «числа совпадают с дорасщеплёнными» держится, а форма расширяется
обратно совместимо (как `JobProgressResponse.intake_status`).

---

## 2. Шаги

### S1 — Схема приёма и обработки появляется в GRAPH_DDL; новая таблица автоматически попадает в гейт готовности графа. Поведение не меняется — шаг чисто аддитивный.
**Файлы:** `src/storage/pg_schema.py`, `scripts/setup_db.py`, `tests/test_storage/test_pg_schema.py`, `tests/test_scripts/test_setup_db_graph_schema.py`

**Изменение**

В `_DOCUMENTS_DDL` добавить колонки приёма — и во встроенный CREATE TABLE (строки 15-31), и идемпотентными ALTER'ами ниже (повторяя приём строк 35-40): content_sha256 TEXT; intake_status TEXT NOT NULL DEFAULT 'accepted'; intake_reason TEXT NOT NULL DEFAULT ''; duplicate_of UUID REFERENCES documents(id); source_kind TEXT NOT NULL DEFAULT 'upload'. Там же DROP/ADD CONSTRAINT documents_intake_status_check CHECK (intake_status IN ('accepted','duplicate','rejected')) — тем же идемпотентным шаблоном, что documents_status_check на строках 45-48. Значение 'duplicate' остаётся в домене ЗАРЕЗЕРВИРОВАННЫМ: политика replace в этом плане не реализуется (см. S10 и risks), никто его не пишет — комментарий об этом рядом, чтобы будущий шаг не требовал миграции схемы. Индексы: CREATE UNIQUE INDEX IF NOT EXISTS documents_sha_idx ON documents (content_sha256) WHERE content_sha256 IS NOT NULL AND duplicate_of IS NULL — предикат отличается от §1.1 спеки, рядом комментарий: «ровно одна каноническая строка на хеш; дочерние версии (duplicate_of IS NOT NULL) вне индекса, иначе политика version физически невозможна; предикат по duplicate_of, а не по intake_status, потому что отклонённый классификатором документ обязан остаться в индексе — 409 отдаёт его intake_status»; и CREATE INDEX IF NOT EXISTS documents_intake_status_idx ON documents (intake_status). Новая константа `_DOC_PROCESSING_DDL` ровно по §1.2 спеки (doc_id UUID PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE; status TEXT NOT NULL DEFAULT 'pending' CHECK IN ('pending','processing','completed','vector_only','failed') — без 'skipped'; error TEXT DEFAULT ''; summary TEXT DEFAULT ''; updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(); индекс по status) — вставить в список GRAPH_DDL (строки 370-386) СРАЗУ ПОСЛЕ `_DOCUMENTS_DDL`: внешний ключ требует порядка. `documents.status` и его CHECK не трогать (I8). В scripts/setup_db.py добавить `_DOC_PROCESSING_DDL` в блок re-export `# noqa: F401`.

**Тесты**

tests/test_storage/test_pg_schema.py: (а) в test_graph_tables_cover_core_tables добавить 'doc_processing' — это и есть гард §5 «новый граф не встанет в ready без неё» (спека просит отдельный файл test_graph_tables.py; кладём в существующий, где уже живут graph_tables/missing_graph_tables — отклонение осознанное); (б) новый test_missing_graph_tables_reports_doc_processing: _Cur(existing=[все таблицы кроме 'doc_processing']) → missing == ['doc_processing']; (в) новый test_documents_ddl_declares_intake_columns: в тексте pg_schema._DOCUMENTS_DDL есть все пять колонок, documents_intake_status_check и подстрока 'duplicate_of IS NULL' в определении documents_sha_idx; (г) новый test_doc_processing_status_domain_excludes_skipped: 'skipped' не встречается в _DOC_PROCESSING_DDL; (д) в test_setup_db_reexports_moved_names добавить `setup_db._DOC_PROCESSING_DDL is pg_schema._DOC_PROCESSING_DDL`. tests/test_scripts/test_setup_db_graph_schema.py: в test_graph_ddl_contains_every_graph_table_and_no_global_one добавить 'doc_processing'; test_migrate_new_graph_creates_schema_and_scopes_ddl (срез cur.sql[2:2+len(GRAPH_DDL)]) обязан остаться зелёным без правок.

### S2 — Исторические строки расщеплены по двум таблицам одноразовым шагом, идемпотентным ПО СУЩЕСТВУ (а не только по маркеру) и выполняемым ПО КАЖДОЙ схеме графа.
**Файлы:** `src/storage/pg_schema.py`, `tests/test_storage/test_pg_schema.py`, `tests/test_storage/test_intake_migration.py`, `tests/test_scripts/test_setup_db_graph_schema.py`

**Изменение**

В src/storage/pg_schema.py добавить `_INTAKE_SPLIT_MARKER = 'intake_split_v1'` и функцию `_intake_split(cur, graph)`, вызываемую из `migrate_graph_schema` (строки 389-400) ПОСЛЕ цикла по GRAPH_DDL и ДО `RESET search_path`. Маркер ПОСХЕМНЫЙ: `f'{_INTAKE_SPLIT_MARKER}:{graph.pg_schema}'` — public.schema_migration.name один глобальный PRIMARY KEY, голое имя отработало бы только на первом графе (_ready_graphs всегда ставит default первым) и молча пропустило бы остальные; прецедент authz_grandfather_v1 глобален и НЕ обобщается, написать это комментарием. Тело: SELECT 1 FROM public.schema_migration WHERE name=%s (префикс public. обязателен — search_path указывает на схему графа, public в нём нет); если строка есть — выход; иначе два оператора и ТОЛЬКО ПОТОМ INSERT маркера с ON CONFLICT (name) DO NOTHING.

ПЕРВЫЙ ОПЕРАТОР — с ужесточённым против §1.3 спеки предикатом (возражение 3):
INSERT INTO doc_processing (doc_id, status, error, summary, updated_at)
SELECT d.id, d.status, d.error, d.summary, d.updated_at FROM documents d
WHERE d.status <> 'skipped'
  AND d.intake_status <> 'rejected'
  AND NOT EXISTS (SELECT 1 FROM doc_processing p WHERE p.doc_id = d.id)
ON CONFLICT (doc_id) DO NOTHING;
Два добавленных условия — не украшение: после S8 новые строки documents навсегда остаются со status='pending' (колонка с DEFAULT, в неё не пишут), а S9 УДАЛЯЕТ строку обработки у отклонённого документа. Голый предикат спеки при повторном прогоне вставил бы таким документам строку 'pending' и перевернул бы их статус во всех четырёх поверхностях отчётности. Комментарий с этим обоснованием — рядом с запросом.

ВТОРОЙ: UPDATE documents SET intake_status='rejected', intake_reason='classifier (pre-split)' WHERE status='skipped' AND intake_status <> 'rejected';

Порядок «маркер последним» важен: соединение в autocommit, атомарности нет, оба оператора идемпотентны — падение посередине чинится повтором, а маркер, записанный первым, навсегда заблокировал бы недоделанную миграцию.

**Тесты**

Новый tests/test_storage/test_intake_migration.py с расширенным фейком курсора (execute пишет (sql, params); fetchall/fetchone отвечают по сценарию): (а) test_runs_when_marker_absent — ровно три оператора после GRAPH_DDL в порядке INSERT INTO doc_processing / UPDATE documents / INSERT INTO public.schema_migration, параметр маркера == 'intake_split_v1:g_acme'; (б) test_skips_when_marker_present — ни одного из трёх; (в) test_marker_is_per_schema — для default_graph_context() маркер 'intake_split_v1:public', для g_acme — 'intake_split_v1:g_acme', один не глушит другой; (г) test_marker_written_last — индекс INSERT'а маркера больше индексов обоих операторов данных; (д) test_backfill_predicate_cannot_resurrect_a_rejected_row — в тексте INSERT'а присутствуют ВСЕ ТРИ условия: `status <> 'skipped'`, `intake_status <> 'rejected'` и `NOT EXISTS`; (е) test_update_marks_pre_split_skipped_as_rejected — в UPDATE есть intake_status='rejected' и защита `AND intake_status <> 'rejected'`. Параллельно расширить ОБА существующих фейка, иначе шаг не стартует: tests/test_storage/test_pg_schema.py::_Cur.fetchall сегодня возвращает кортежи имён таблиц, то есть гард маркера прочитался бы как «уже применено» (зелёный тест при неработающем коде) — добавить режим «маркера нет» и параметризовать счётчик len(GRAPH_DDL)+3+N (N=1 при наличии маркера, 4 при отсутствии); tests/test_scripts/test_setup_db_graph_schema.py::_Cur вообще не имеет fetchone/fetchall (AttributeError) — добавить их; срез cur.sql[2:2+len(GRAPH_DDL)] и `cur.sql[-1] == 'RESET search_path'` обязаны остаться зелёными.

### S3 — Классификатор живёт в контуре приёма; воркер по-прежнему его исполняет (I6).
**Файлы:** `src/intake/__init__.py`, `src/intake/classifier.py`, `src/ingestion/classifier.py`, `src/workflow/activities/classify_document.py`, `tests/test_intake/__init__.py`, `tests/test_intake/test_classifier.py`, `tests/test_ingestion/test_classifier.py`, `tests/eval/classifier_scenarios.py`

**Изменение**

Создать пакет src/intake/ (пустой __init__.py с одной строкой назначения в докстринге). `git mv src/ingestion/classifier.py src/intake/classifier.py` — содержимое байт в байт; модуль не импортирует ничего из src.*, перенос безрисковый. Поправить единственный импорт: src/workflow/activities/classify_document.py:16 → `from src.intake.classifier import apply_rules, classify_with_llm, read_preview`, рядом комментарий «объявленное исключение §3.2: LLM-гейт нельзя держать синхронно в HTTP-запросе (I6)». tests/eval/classifier_scenarios.py:14 → тот же новый путь. Логика `force` (classify_document.py:23-25) не меняется ни на символ.

**Тесты**

`git mv tests/test_ingestion/test_classifier.py tests/test_intake/test_classifier.py` + создать tests/test_intake/__init__.py; импорты внутри переведены на src.intake.classifier, утверждения не трогать — их зелёность и есть доказательство чистоты переноса. Добавить test_old_module_is_gone: `pytest.raises(ModuleNotFoundError)` на `import src.ingestion.classifier` (чтобы старый путь не воскрес копипастой).

### S4 — Очередь приёма и producer-side диспетчер переезжают в контур; src.config перестаёт быть корнем, тянущим intake; ни одна точка запуска не остаётся на старом пути модуля.
**Файлы:** `src/intake/queue/__init__.py`, `src/intake/queue/priorities.py`, `src/intake/queue/topology.py`, `src/intake/queue/publisher.py`, `src/intake/queue/consumer.py`, `src/intake/submit.py`, `src/ingest_queue/__init__.py`, `src/ingest_queue/priorities.py`, `src/ingest_queue/topology.py`, `src/ingest_queue/publisher.py`, `src/ingest_queue/consumer.py`, `src/workflow/ingest_submit.py`, `src/config.py`, `src/api/routes/ingest.py`, `scripts/tg_ingest.py`, `docker-compose.prod.yml`, `README.md`, `tests/test_intake/test_queue_topology.py`, `tests/test_intake/test_queue_publisher.py`, `tests/test_intake/test_queue_consumer.py`, `tests/test_intake/test_queue_consumer_graph.py`, `tests/test_intake/test_submit.py`, `tests/test_ingest_queue/test_topology.py`, `tests/test_ingest_queue/test_publisher.py`, `tests/test_ingest_queue/test_consumer.py`, `tests/test_ingest_queue/test_consumer_graph.py`, `tests/test_workflow/test_ingest_submit.py`, `tests/test_workflow/test_scheduler_isolation.py`, `tests/test_api/test_ingest_priority.py`, `tests/test_config/test_ingest_priorities.py`

**Изменение**

ШАГ НОЛЬ, до любой правки: `grep -rn 'ingest_queue\|ingest_submit' . --exclude-dir=.git --exclude-dir=.venv --exclude-dir=__pycache__` по ВСЕМУ репозиторию, не по deploy/. Он даёт ровно то, чего список радиуса поражения не видел (возражение 1 и 6): docker-compose.prod.yml:189 `command: ["python", "-m", "src.ingest_queue.consumer"]` — прод-контейнер ingest-consumer, который после переноса ушёл бы в crash-loop с ModuleNotFoundError на rabbitmq-бэкенде; README.md:172 — строка дерева каталогов; tests/test_workflow/test_scheduler_isolation.py:55 `from src.workflow.ingest_submit import _submit_to_scheduler`; tests/test_api/test_ingest_priority.py:78 `from src.ingest_queue.priorities import PRIO_LIVE`. Исторические docs/superpowers/plans/* и docs/superpowers/specs/2026-07-01-* не правим — это записи о прошлом.

Сам перенос: `git mv src/ingest_queue/{topology,publisher,consumer,priorities}.py src/intake/queue/`, создать src/intake/queue/__init__.py, удалить src/ingest_queue/. Внутренние импорты модулей очереди — на src.intake.queue.*. Строку запуска в докстринге consumer.py (`python -m src.ingest_queue.consumer`) и docker-compose.prod.yml:189 обновить на `src.intake.queue.consumer` ТЕМ ЖЕ коммитом, что и git mv. README.md:172 — переименовать запись дерева на `intake/` с пометкой «приём: классификатор, очередь, submit, репозиторий, маршруты».

ДОПОЛНЕНИЕ К СПЕКЕ: `git mv src/workflow/ingest_submit.py src/intake/submit.py` — §3.1 его не называет, но §3.2 вынуждает: ingest_submit импортирует и priorities, и publisher, то есть остался бы единственным ядровым модулем, тянущим intake. Он импортирует src.workflow.ingest_scheduler и src.workflow.contracts — направление intake → workflow правилом разрешено.

Снять последнюю ядровую зависимость: убрать `from src.ingest_queue.priorities import PRIO_LIVE` из src/config.py:21, заменить `ge=PRIO_LIVE` на `ge=5` с комментарием, называющим PRIO_LIVE и ссылающимся на новый гард-тест (src.config импортируют все, импорт intake из него сделал бы arch-тест S6/S7 бессмысленным: AST видит только прямые импорты). scripts/tg_ingest.py:56 и src/api/routes/ingest.py:27 — на новый путь.

**Тесты**

Сначала новый tests/test_config/test_ingest_priorities.py::test_max_priority_floor_matches_prio_live — `from src.intake.queue.priorities import PRIO_LIVE`; RabbitMQSettings(max_priority=PRIO_LIVE) строится, RabbitMQSettings(max_priority=PRIO_LIVE-1) бросает ValidationError (гард дрейфа взамен снятого импорта, тот же приём, что tests/test_scripts/test_setup_db_authz.py). Затем `git mv` четырёх файлов tests/test_ingest_queue/* в tests/test_intake/test_queue_*.py и tests/test_workflow/test_ingest_submit.py → tests/test_intake/test_submit.py, с правкой импортов и monkeypatch.setitem(sys.modules, 'src.intake.queue.publisher', …). Отдельно одна строка импорта в tests/test_workflow/test_scheduler_isolation.py:55 и одна в tests/test_api/test_ingest_priority.py:78 — без них шаг заканчивается ImportError'ом, который выглядит как регрессия базового фона. Новый tests/test_intake/test_queue_consumer.py::test_compose_command_matches_module_path — читает docker-compose.prod.yml как текст и требует, чтобы подстрока 'src.ingest_queue' в нём отсутствовала, а 'python -m src.intake.queue.consumer' присутствовала (гард ровно против того, что этот шаг чуть не сломал). Утверждения перенесённых тестов не трогать.

### S5 — SQL по `documents` целиком переезжает в репозиторий приёма. Чистый перенос: ни одного запроса не переписываем, и ни один инжектор не остаётся с классом, у которого метода больше нет.
**Файлы:** `src/intake/repository.py`, `src/storage/postgres.py`, `src/storage/chunk_repository.py`, `src/workflow/_search_deps.py`, `src/mcp/tools_server.py`, `src/api/routes/stats.py`, `src/api/routes/ingest.py`, `src/api/routes/documents.py`, `scripts/message_stats.py`, `scripts/backfill_doc_id.py`, `tests/test_intake/test_repository.py`, `tests/test_storage/test_chunk_repository.py`, `tests/test_storage/test_document_original_path.py`, `tests/test_storage/test_insert_pending_source.py`, `tests/test_storage/test_message_stats_queries.py`, `tests/test_retrieval/test_graph_rank.py`, `tests/test_tenancy/test_storage_names.py`, `tests/test_api/test_stats_routes.py`, `tests/test_api/test_graph_binding.py`, `tests/test_api/test_graph_dep_authz.py`, `tests/test_api/test_documents.py`, `tests/test_api/test_ingest.py`, `tests/test_api/test_ingest_backfill.py`, `tests/test_api/test_ingest_group.py`, `tests/test_api/test_ingest_original.py`, `tests/test_api/test_ingest_priority.py`, `tests/test_api/test_ingest_source_channel.py`, `tests/test_mcp/test_tools_server.py`, `tests/test_mcp/test_current_graph.py`, `tests/test_scripts/test_message_stats_cli.py`

**Изменение**

Новый src/intake/repository.py: класс `IntakeRepository` с тем же конструктором (dsn, *, graph) и тем же `_conn()` через src.storage.pg_scope.graph_connection, плюс перенесённые БЕЗ ИЗМЕНЕНИЯ ТЕКСТА SQL методы insert_pending, list_id_path, get, status_counts_by, timeline_counts и символы DocumentRow, DOC_STATUSES, GROUP_BY_COLUMN, _DIMENSIONS, _DATE_FIELDS. В src/storage/postgres.py остаются AsyncPostgres.update_status и record_fact_conflicts (fact_supersede к приёму отношения не имеет); DOC_STATUSES/GROUP_BY_COLUMN оттуда удаляются.

Потребители прямых вызовов — на IntakeRepository: src/api/routes/stats.py:65/87, src/api/routes/ingest.py:88/280, src/api/routes/documents.py:44, src/mcp/tools_server.py:676/700, scripts/message_stats.py:48, scripts/backfill_doc_id.py:76.

ИНЖЕКТОРЫ (возражение 2 — блокер, подтверждён): ChunkRepository.aget_document_path (:162) зовёт `self._pg.get(...)`, а строят его ДВА места, оба с явным `pg=AsyncPostgres(graph=graph)`: src/mcp/tools_server.py:144 и src/workflow/_search_deps.py:127. Второе — модуль ядра, и подстановка туда IntakeRepository потребовала бы третьего исключения в arch-тесте. Поэтому: из ОБОИХ вызовов аргумент `pg=` убирается вовсе (`ChunkRepository(graph=graph)`), а chunk_repository.py:72 строит умолчание сам — `self._pg = pg or IntakeRepository(graph=graph)`; аннотация параметра `pg: IntakeRepository | None`. Конструкция эквивалентна прежней (оба класса берут только graph и не открывают соединение в __init__), импорт src.intake остаётся внутри src/storage. Докстринг chunk_repository.py:8-9 («Postgres — the document-status table») поправить на «реестр приёма (documents) контура intake». Комментарий tools_server.py:649-657 про «те же методы агрегации» — на новое имя класса.

ОСОЗНАННОЕ РЕШЕНИЕ: src/storage импортирует src.intake. §3.2 перечисляет ядром src/graph, src/retrieval, src/workflow и src/storage туда не относит; src/storage — общая инфраструктура НИЖЕ обоих контуров (сам intake импортирует src.storage.pg_scope). Зафиксировать комментарием в arch-тесте S7.

**Тесты**

Сначала новый tests/test_intake/test_repository.py на фейковом курсоре: для каждого метода проверяется текст эмитируемого SQL и параметры (insert_pending называет только переданные колонки; list_id_path; get = SELECT по documents; status_counts_by отвергает плохое dimension ValueError'ом и возвращает словарь с ключом на каждый DOC_STATUSES плюс total; timeline_counts отвергает плохие date_field/group_by). Новый tests/test_storage/test_chunk_repository.py::test_default_pg_is_intake_repository — ChunkRepository(graph=…, milvus_client=<stub>) без pg → isinstance(repo._pg, IntakeRepository) (руками сделанный фейк с методом get в остальных тестах файла оставить как есть). tests/test_retrieval/test_graph_rank.py:294 — `lambda *, graph, pg` превращается в `lambda *, graph`, строка 295 с патчем pg.AsyncPostgres удаляется; без этой правки тест падает TypeError'ом. tests/test_tenancy/test_storage_names.py:36 (pg=object()) остаётся зелёным без изменений — проверить. Далее механическая правка целей патчей: `src.storage.postgres.AsyncPostgres.get` → `src.intake.repository.IntakeRepository.get`, `patch.object(AsyncPostgres, 'insert_pending')` → `patch.object(IntakeRepository, 'insert_pending')`, то же для status_counts_by/timeline_counts в test_graph_binding.py:259, test_graph_dep_authz.py:97, test_current_graph.py:228, test_tools_server.py:149/180, test_stats_routes.py:25-26/72. Утверждения о телах ответов НЕ менять — это и есть доказательство чистоты переноса. Живые tests/test_storage/test_insert_pending_source.py, test_document_original_path.py, test_message_stats_queries.py: только импорт класса (без стека они скипаются/падают — базовый фон).

### S6 — Маршруты приёма и выдачи оригинала живут в контуре, публичные пути и права не меняются (I7).
**Файлы:** `src/intake/api/__init__.py`, `src/intake/api/ingest.py`, `src/intake/api/documents.py`, `src/api/routes/ingest.py`, `src/api/routes/documents.py`, `src/api/main.py`, `tests/test_api/test_ingest.py`, `tests/test_api/test_ingest_backfill.py`, `tests/test_api/test_ingest_group.py`, `tests/test_api/test_ingest_original.py`, `tests/test_api/test_ingest_priority.py`, `tests/test_api/test_ingest_source_channel.py`, `tests/test_api/test_documents.py`

**Изменение**

`git mv src/api/routes/ingest.py src/intake/api/ingest.py` и `git mv src/api/routes/documents.py src/intake/api/documents.py`, создать src/intake/api/__init__.py. Код внутри не меняется: те же APIRouter без prefix, те же зависимости Depends(resolve_graph_write) / Depends(resolve_graph) / Depends(resolve_graph_download) — правило авторизации из спеки арендаторов трогать запрещено. В src/api/main.py убрать ingest и documents из блока `from src.api.routes import (...)`, добавить `from src.intake.api import documents as intake_documents, ingest as intake_ingest`, заменить две строки include_router, СОХРАНИВ `prefix='/api/v1'` и порядок регистрации.

**Тесты**

tests/test_api/test_route_actions.py НЕ меняется ни на строку и обязан остаться зелёным — он обходит src.api.main.app и сверяет матрицу (метод, путь) → действие, то есть доказывает и I7, и сохранность прав write/read/download_original. То же про матрицу 403 в tests/test_api/test_graph_binding.py:230-249. Механически перенацелить строковые патчи в шести test_ingest*.py: 'src.api.routes.ingest.build_minio_storage' → 'src.intake.api.ingest.build_minio_storage', '…get_temporal_client' → 'src.intake.api.ingest.get_temporal_client'; в test_documents.py — 'src.api.routes.documents.build_minio_storage' → 'src.intake.api.documents.build_minio_storage'. Утверждения не трогать.

### S7 — Граница контуров закреплена исполняемым тестом, а не договорённостью — включая запрет на возврат инжекции AsyncPostgres, которую не поймает ни один тайпчекер (в проекте только ruff).
**Файлы:** `tests/test_intake/test_boundaries.py`

**Изменение**

Новый arch-тест по образцу tests/test_no_neo4j.py, но разбирающий AST, а не регулярку: обойти *.py под src/, для каждого файла собрать модули из ast.Import/ast.ImportFrom, включая импорты внутри функций (ленивые импорты здесь обычны — tools_server.py:666, _search_deps.py:125-127). ПРАВИЛО 1: ни один модуль под src/graph, src/retrieval, src/workflow не импортирует src.intake, кроме allowlist `_INTAKE_WORKER_ADAPTERS = {'src/workflow/activities/classify_document.py', 'src/workflow/activities/mark_skipped.py'}` (второй файл появляется в S9; до него в allowlist только первый). ПРАВИЛО 2: ни один модуль под src/intake не импортирует src.graph. ПРАВИЛО 3 (новое, возражение 2): ни один модуль под src/ не передаёт `pg=AsyncPostgres(...)` в конструктор ChunkRepository — по AST ищем Call с func.id/attr == 'ChunkRepository' и keyword 'pg', значение которого Call к AsyncPostgres. Это единственная исполняемая защита: у ChunkRepository умолчание теперь IntakeRepository, метода `get` у AsyncPostgres больше нет, а mypy/pyright в проекте отсутствует, так что возврат инжекции иначе всплыл бы только AttributeError'ом в проде на read_full_document. Падение любого правила — со списком нарушителей «файл:строка → модуль/вызов». В докстринге зафиксировать три решения: (а) почему исключений два, а не одно, как в §3.2 — вердикт классификатора пишет активность mark_skipped, она такая же воркер-сторона приёма, что и classify_document (I6); (б) почему src/storage в правилах 1-2 не фигурирует — общая инфраструктура ниже обоих контуров, intake сам импортирует src.storage.pg_scope; (в) почему правило 3 вообще нужно — транзитивный путь src/workflow → src/storage/chunk_repository → src/intake допустим, а прямая инжекция ядрового класса в чужой контур — нет.

**Тесты**

Сам тест и есть проверка. Дополнительно test_allowlist_entries_exist — каждый путь из _INTAKE_WORKER_ADAPTERS существует на диске и реально импортирует src.intake (устаревшее исключение тихо расширяет правило); test_allowlist_is_minimal — ни один файл из allowlist не импортирует src.intake.api (адаптеру положены только классификатор и репозиторий приёма); test_rule3_catches_synthetic_violation — правило 3 прогоняется на строке-образце с `ChunkRepository(graph=g, pg=AsyncPostgres(graph=g))` и обязано её поймать (иначе правило может оказаться вечнозелёным из-за опечатки в обходе AST).

### S8 — Статус обработки пишется в doc_processing, запись в documents.status прекращается, читатели переведены — одним изменением, иначе два источника истины разойдутся (§7).
**Файлы:** `src/intake/repository.py`, `src/storage/postgres.py`, `src/workflow/graph_lifecycle/activities.py`, `tests/test_intake/test_repository.py`, `tests/test_workflow/test_fetch_source.py`, `tests/test_workflow/test_finalize.py`, `tests/test_workflow/test_graph_lifecycle_activities.py`, `tests/test_api/test_stats_routes.py`, `tests/test_scripts/test_message_stats_cli.py`, `tests/test_storage/test_insert_pending_source.py`, `tests/test_storage/test_message_stats_queries.py`, `tests/test_workflow/test_workflow_local.py`

**Изменение**

(1) IntakeRepository.insert_pending → `accept_document`, атомарный: в ОДНОЙ транзакции INSERT в documents (колонку status не называем — остаётся NOT NULL DEFAULT 'pending', I8) + INSERT INTO doc_processing (doc_id) VALUES (%s). Комментарий с обоснованием: внешний ключ делает две строки одним актом приёма, а две отдельные транзакции оставили бы при падении документ без строки обработки, визуально неотличимый от отклонённого — и именно на эту неотличимость опирается предикат миграции S2. (2) AsyncPostgres.update_status: UPDATE doc_processing SET status/error/summary (тот же COALESCE(NULLIF(%s,''), summary))/updated_at WHERE doc_id=%s. Именно UPDATE, не UPSERT: после отказа классификатора строки нет, и запоздалая активность не должна её воскрешать. Имя и сигнатуру метода не менять — fetch_source.py:33 и finalize.py:49/214 остаются как есть. (3) IntakeRepository.get: SELECT d.*, p.status AS proc_status, p.error AS proc_error, p.summary AS proc_summary FROM documents d LEFT JOIN doc_processing p ON p.doc_id = d.id WHERE d.id=%s — псевдонимы обязательны, иначе dict_row схлопнет одноимённые status/error/summary. DocumentRow.from_dict считает эффективный статус: proc_status, иначе 'skipped' при intake_status='rejected', иначе row['status']; error = proc_error или intake_reason; summary = proc_summary или ''. В DocumentRow добавить поля intake_status и intake_reason. (4) status_counts_by: LEFT JOIN doc_processing и группировка по тому же выражению COALESCE(p.status, CASE WHEN d.intake_status='rejected' THEN 'skipped' ELSE d.status END) — отчётный словарь DOC_STATUSES остаётся сегодняшним, включая 'skipped' (StatRow требует этот ключ, иначе 500 на валидации ответа; те же колонки у message_stats и схемы MCP). timeline_counts НЕ трогать: все её колонки в documents. (5) src/workflow/graph_lifecycle/activities.py:152-166 — и зонд `SELECT to_regclass('doc_processing')`, и запрос `SELECT doc_id::text FROM doc_processing WHERE status IN ('pending','processing')`: doc_processing — таблица ЯДРА, импорта src.intake здесь не возникает, противоречия §3.1 с §3.2 нет.

**Тесты**

Сначала тесты. tests/test_intake/test_repository.py: test_accept_writes_both_tables_in_one_transaction (два INSERT'а на одном соединении, один commit, в INSERT documents нет слова status); test_get_joins_processing (LEFT JOIN doc_processing и псевдонимы proc_*); test_get_of_rejected_doc (строка без proc_* и с intake_status='rejected' → DocumentRow.status == 'skipped', error == intake_reason); test_get_of_pending_doc (proc_status='pending' → status == 'pending'); test_status_counts_keeps_skipped_key; test_timeline_counts_sql_touches_only_documents (в SQL нет 'doc_processing'); test_update_status_targets_doc_processing (есть 'UPDATE doc_processing', нет 'UPDATE documents'). tests/test_workflow/test_fetch_source.py:35/58/66/96 и test_finalize.py:25-143 — утверждения `update_status(..., status=…)` остаются дословно. tests/test_workflow/test_graph_lifecycle_activities.py: _PgCur ключуется на литерал 'FROM documents' и fetchone отдаёт ('documents',) — перевести на 'FROM doc_processing' / ('doc_processing',), параметризованный test_inflight_doc_ids_tolerates_missing_schema сохранить. tests/test_api/test_stats_routes.py и tests/test_scripts/test_message_stats_cli.py — фикстуры со "skipped": 0 НЕ менять: их зелёность и есть инвариант формы ответа. Живые test_insert_pending_source.py, test_message_stats_queries.py, test_workflow_local.py — прямые INSERT'ы в documents дополнить строкой doc_processing.

### S9 — Отказ классификатора — решение приёма: intake_status='rejected' плюс УДАЛЕНИЕ строки обработки, чтобы таблица обработки не врала.
**Файлы:** `src/workflow/activities/mark_skipped.py`, `src/workflow/activities/finalize.py`, `src/workflow/activities/__init__.py`, `src/intake/repository.py`, `tests/test_intake/test_boundaries.py`, `tests/test_workflow/test_mark_skipped.py`, `tests/test_workflow/test_finalize.py`, `tests/test_workflow/test_activity_graph_resolution.py`, `tests/test_workflow/test_document_ingest_workflow.py`, `tests/test_intake/test_repository.py`

**Изменение**

IntakeRepository.reject(doc_id, reason): в одной транзакции UPDATE documents SET intake_status='rejected', intake_reason=%s, updated_at=NOW() WHERE id=%s и DELETE FROM doc_processing WHERE doc_id=%s. Рядом комментарий-перекрёстная ссылка на предикат S2: удаление намеренное, поэтому backfill обязан проверять intake_status и NOT EXISTS, иначе повторный прогон воскресит строку. Вынести активность mark_skipped из src/workflow/activities/finalize.py:170-201 в новый src/workflow/activities/mark_skipped.py (соглашение репозитория — одна активность на модуль: fetch_source.py, classify_document.py, merge_and_resolve.py; finalize.py с тремя активностями здесь выброс). Декоратор @activity.defn без аргумента — ИМЯ активности остаётся 'mark_skipped', строка в document_ingest.py:165 не меняется, реплей незавершённых историй цел. Тело: resolve_graph_for_activity (воркер не трогаем), затем IntakeRepository(graph=graph).reject(...) вместо update_status('skipped'), затем прежняя очистка staging/локальной папки; IngestResult.graph_status остаётся 'skipped' — это контракт воркфлоу, не колонка БД. Поправить реэкспорты в src/workflow/activities/__init__.py:33/71/105. В allowlist arch-теста S7 добавить второй файл.

**Тесты**

Новый tests/test_workflow/test_mark_skipped.py (кейс 'skipped' переезжает из test_finalize.py:25-143): ActivityEnvironment прогоняет mark_skipped, фейковый репозиторий получает reject(doc_id, reason) ровно один раз, update_status НЕ вызывается, staging.delete_prefix вызван, возвращается IngestResult с graph_status='skipped'. tests/test_intake/test_repository.py::test_reject_updates_intake_and_deletes_processing — два оператора на одном соединении, один commit, порядок UPDATE documents → DELETE FROM doc_processing. tests/test_workflow/test_finalize.py — кейс skipped удалить, три остальных (completed / vector_only / failed) оставить дословно. tests/test_workflow/test_activity_graph_resolution.py — реестр активностей, трогающих хранилище (SkipIn # mark_skipped), обязан остаться зелёным; при необходимости поправить путь модуля, не состав. tests/test_workflow/test_document_ingest_workflow.py:183/216 — не менять.

### S10 — Повторная заливка того же тела в тот же граф не доходит до MinIO и не порождает работы — головная цель спеки; при этом документированные режимы переингеста продолжают реально переингестить.
**Файлы:** `src/intake/api/ingest.py`, `src/intake/repository.py`, `tests/test_intake/test_dedup.py`, `tests/test_api/test_ingest.py`, `tests/test_api/test_ingest_backfill.py`

**Изменение**

ПОЛИТИКИ: `ON_DUPLICATE = ('reject','version')` в src/intake/repository.py. Политика `replace` из §2.2/I4 в этом плане НЕ реализуется (возражение 5; обоснование в risks и в out_of_scope): проверено, что ни один путь чтения не смотрит в documents (в src/retrieval упоминания только в комментариях llm_pool.py:4-5 и vector_index.py:88; chunk_repository берёт оттуда лишь .path), поэтому три Postgres-оператора replace не убрали бы ни одного чанка из Milvus и ни одного узла из графа — обе копии остались бы одинаково находимыми, а Postgres объявлял бы одну дубликатом. Значение 'replace' отвечает 422 вместе с прочими неизвестными.

ВЫБОР ПОЛИТИКИ ПО ВЫЗЫВАЮЩЕМУ (возражение 4): поле формы `on_duplicate: str | None = Form(default=None)`; эффективная политика = явное значение, иначе 'version' при backfill=true, иначе 'reject'. Обоснование комментарием у поля: backfill задокументирован на ingest.py:82-84 как «Re-ingest of already-known material» (его шлёт deploy/offline/loadtest/loader.py:76 и, по DEPLOYMENT.md:252, операторские перезаливки) — с умолчанием reject этот флаг стал бы no-op'ом. Явное значение всегда перекрывает умолчание. Отдельной строкой в том же комментарии: устаревшее отображение force=true → on_duplicate=version из docs/superpowers/plans/2026-10-17-project-boundaries.md §4 шаг 1.2 НЕ реализуется (I4: force — переключатель только классификатора); backfill — другой флаг с другой документированной семантикой, и это не та же поблажка.

ПОТОК В МАРШРУТЕ: валидация явного on_duplicate вместе с остальными ранними 422 (рядом с queue/group/priority/document_date), до чтения тела. Сразу после `contents = await file.read()` (ingest.py:147) считать `content_sha256 = hashlib.sha256(contents).hexdigest()` и ДО `build_minio_storage()` (и, разумеется, до опциональной заливки original) выполнить IntakeRepository.find_by_sha(content_sha256) → SELECT id, intake_status FROM documents WHERE content_sha256=%s AND duplicate_of IS NULL. При политике reject и найденном совпадении — HTTPException 409 с detail {'message':'duplicate','doc_id':str(first_id),'intake_status':first_status}; MinIO и очередь не трогаются. При version работа продолжается, accept_document получает content_sha256, source_kind='upload', duplicate_of=<id первого> и intake_status='accepted' (строка вне частичного уникального индекса, конфликта нет). Гонка двух одновременных POST закрывается индексом, а не чтением: accept_document ловит psycopg.errors.UniqueViolation и при reject отдаёт тот же 409, перечитав победителя; при version пробрасывает. Удалить мёртвый `except WorkflowAlreadyStartedError` (ingest.py:245-260): submit_document на temporal-ветке стартует id='ingest-scheduler' с WorkflowIDConflictPolicy.USE_EXISTING и не бросает, rabbitmq-ветка просто публикует, per-doc id куётся в воркере (ingest_scheduler.py:146, consumer.py:67) — переиспользовать этот обработчик под дедуп было бы ложью о причине.

**Тесты**

Новый tests/test_intake/test_dedup.py (стиль tests/test_api/test_ingest.py — ASGITransport + патчи на src.intake.api.ingest.*): (1) test_same_body_rejected_without_upload — второй POST того же тела даёт 409, тело содержит doc_id первого и его intake_status, stub_storage.put_object НЕ вызван, submit_document НЕ вызван; (2) test_different_body_passes — 202; (3) test_on_duplicate_version_creates_second_row — 202, accept_document получил duplicate_of = id первого, документ ушёл в пайплайн; (4) test_replace_is_rejected_for_now — on_duplicate=replace даёт 422 со списком ('reject','version'), фиксируя осознанную отсрочку; (5) test_unknown_on_duplicate_422 — то же для мусорного значения, тело файла не читалось; (6) test_backfill_true_defaults_to_version — backfill=true без on_duplicate на дубль даёт 202 и duplicate_of, а не 409 (запись решения из возражения 4); (7) test_explicit_on_duplicate_overrides_backfill — backfill=true + on_duplicate=reject даёт 409; (8) test_force_does_not_affect_dedup — force=true на дубль всё равно 409, а на уникальном теле прокидывается в IngestParams.force=True; (9) test_hash_computed_before_put_object — при найденном дубле build_minio_storage не вызывался вовсе; (10) test_concurrent_insert_loses_on_unique_violation — accept_document бросает UniqueViolation → 409, не 500; (11) test_rejected_first_doc_still_blocks — первый документ с intake_status='rejected' даёт 409 с intake_status='rejected' в теле (обоснование предиката индекса по duplicate_of). В tests/test_api/test_ingest.py добавить test_no_workflow_already_started_handler — исходник маршрута больше не упоминает WorkflowAlreadyStartedError. tests/test_api/test_ingest_backfill.py — оба существующих теста (forwards_backfill / defaults_to_false) остаются зелёными: они не шлют дубликатов.

### S11 — GET /ingest/{job_id} отвечает и о приёме: отклонённый классификатором документ перестаёт выглядеть пропавшим.
**Файлы:** `src/intake/api/ingest.py`, `tests/test_api/test_ingest_status.py`

**Изменение**

JobProgressResponse получает два ДОБАВОЧНЫХ поля: intake_status: str и intake_reason: str = ''. Существующие семь полей и их значения не меняются — обработчик уже читает объединённую строку из S8, поэтому для отклонённого документа status='skipped' и error=<причина отказа> ровно как до расщепления, а два новых поля объясняют почему. Добавление обратно совместимо: deploy/offline/webui/index.html:203-216 читает только b.status и b.error, плагин agent-web — только job_id/status.

**Тесты**

Новый tests/test_api/test_ingest_status.py: (1) test_pending_document — status='pending', intake_status='accepted'; (2) test_rejected_document_is_visible — документ с intake_status='rejected' и без строки обработки отдаёт 200 (не 404), status='skipped', error=<причина>, intake_status='rejected', intake_reason=<причина>; (3) test_completed_document; (4) test_unknown_job_404; (5) test_legacy_fields_unchanged — набор ключей ответа = прежние семь плюс ровно два новых.

### S12 — Ops-инструменты не ломаются и не врут после расщепления и после включения дедупа.
**Файлы:** `scripts/wipe_db.py`, `scripts/check_ingestion.py`, `scripts/tg_ingest.py`, `deploy/offline/loadtest/monitor.sh`, `tests/test_scripts/test_wipe_db.py`, `tests/test_scripts/test_tg_ingest.py`

**Изменение**

scripts/wipe_db.py: внешний ключ doc_processing.doc_id → documents(id) делает `TRUNCATE TABLE documents` (строка 108) ошибкой FeatureNotSupported, а цикл :106-112 ловит только UndefinedTable — wipe падает. Починка: добавить 'doc_processing' в _PG_TABLES (строка 91) ПЕРЕД 'documents' И поменять оператор на `TRUNCATE TABLE {table} CASCADE`: одной очистки дочерней таблицы недостаточно, Postgres отказывает по самому НАЛИЧИЮ ссылки, а не строк. CASCADE безопасен — входящих внешних ключей нет ни у одной другой таблицы списка (stat_observation.source_doc_id и entity_mention.doc_id намеренно без FK).

scripts/check_ingestion.py:36-44 `SELECT status, COUNT(*) FROM documents GROUP BY status` после расщепления всегда показывал бы 'pending' — перевести на выражение эффективного статуса с LEFT JOIN doc_processing (то же, что в status_counts_by S8). deploy/offline/loadtest/monitor.sh:10-17 — те же `count(*) filter (where status=…)` на join; состав колонок CSV сохранить.

scripts/tg_ingest.py (возражение 4): post_ingest (:98-128) получает параметр `on_duplicate: str = ''`, кладёт его в data только когда непусто, и перестаёт считать любой не-2xx провалом — 409 возвращается отдельным исходом («уже известный документ») и попадает в свой счётчик tally['duplicate'], не в 'failed'. reingest_channels (:161-208) передаёт on_duplicate='version': этот режим существует ровно затем, чтобы перечитать и переотправить свежие N сообщений канала, и с умолчанием reject он стал бы молчаливым no-op'ом; version воспроизводит сегодняшнее поведение дословно (новый doc_id, новый комплект чанков) плюс ссылка duplicate_of. Режимы continuous sync и legacy --channels остаются на умолчании reject: повторный проход по тому же окну и ДОЛЖЕН быть идемпотентным, 409 там — успех, а не ошибка. Существующий tally['skipped'] — счётчик самого скрипта (сообщение не стало документом), к статусам БД отношения не имеет, его не трогать.

**Тесты**

tests/test_scripts/test_wipe_db.py: test_truncates_doc_processing_and_cascades — в перехваченных операторах есть TRUNCATE для doc_processing, он идёт раньше documents, и у каждого есть CASCADE. tests/test_scripts/test_tg_ingest.py: test_post_ingest_counts_409_as_duplicate (409 не попадает в счётчик ошибок и помечен дубликатом), test_post_ingest_still_fails_on_500 (500 по-прежнему провал), test_reingest_sends_on_duplicate_version (перехваченный POST режима reingest содержит on_duplicate='version'), test_sync_sends_no_on_duplicate (обычный проход поле не шлёт). check_ingestion.py и monitor.sh тестами не покрыты (их нет и сегодня) — проверяются чтением SQL глазами на ревью; указать это явно в описании коммита.

---

## 3. Инварианты

- Публичные пути маршрутов неизменны: POST /api/v1/ingest, GET /api/v1/ingest/{job_id}, GET /api/v1/documents/{doc_id} (I7). Гард — tests/test_api/test_route_actions.py, который обходит src.api.main.app; этот файл за весь план не правится ни на строку.
- Действия авторизации неизменны: POST /ingest = write (resolve_graph_write), GET /ingest/{job_id} = read, GET /documents/{doc_id} = download_original. Гарды — test_route_actions.py::EXPECTED и матрица 403 в tests/test_api/test_graph_binding.py:230-249.
- src/tenancy/activity.py::resolve_graph_for_activity и способ его вызова из активностей не меняются (прямой запрет задачи).
- Имена активностей Temporal неизменны: 'mark_skipped', 'classify_document', 'fetch_source', 'finalize', 'mark_failed'. Перенос mark_skipped в собственный модуль меняет расположение функции, но не строку, которой её зовёт src/workflow/document_ingest.py:165 — иначе реплей незавершённых историй ломается.
- Детерминизм воркфлоу: никакой новый флаг приёма не читается внутри @workflow.run; всё снимается в маршруте и едет через IngestParams, как classifier_enabled и wiki_enabled сегодня.
- Форма ответа GET /api/v1/stats/messages неизменна: StatRow сохраняет все семь ключей, включая обязательный skipped. Числа по существующим данным после миграции совпадают с дорасщеплёнными.
- Набор колонок scripts/message_stats.py (_COLS = key, total, *DOC_STATUSES) и форма выдачи MCP-инструментов tools_server.py:676/700 не меняются — три поверхности отчётности показывают одинаковые числа.
- Тело успешного ответа приёма остаётся {"job_id": "<uuid>"} с кодом 202; семь существующих полей JobProgressResponse сохраняют имена и значения.
- `force` остаётся переключателем ТОЛЬКО классификатора и никак не влияет на дедуп (I4). Отображение force=true → on_duplicate=version из docs/superpowers/plans/2026-10-17-project-boundaries.md §4 шаг 1.2 не реализуется.
- Контейнер ingest-consumer запускается тем путём модуля, который реально существует: docker-compose.prod.yml:189 и расположение consumer.py меняются одним коммитом, гард — чтение compose-файла тестом в S4.
- read_full_document / поиск пути документа по doc_id продолжают работать из обеих точек сборки ChunkRepository (src/mcp/tools_server.py:144 и src/workflow/_search_deps.py:127): умолчание конструктора — IntakeRepository, прямая инжекция AsyncPostgres запрещена правилом 3 arch-теста.
- Документированные режимы переингеста остаются рабочими: `scripts/tg_ingest.py --reingest` и POST с backfill=true после включения дедупа по-прежнему создают документ и запускают пайплайн (политика version), а не возвращают 409.
- intake_split_v1 безопасна при повторном прогоне в любой момент жизни системы: предикат отбора исключает отклонённые документы и любые строки, у которых doc_processing уже есть. Маркер — оптимизация, а не единственная защита.
- Колонка documents.status и её CHECK сохраняются в схеме (I8); меняется только то, что в неё перестают писать. Удаление — отдельный шаг после выката.
- Уникальность хеша действует строго в пределах схемы графа; глобального индекса по content_sha256 не появляется (утечка между арендаторами).
- Список таблиц гейта готовности графа по-прежнему выводится регуляркой pg_schema.graph_tables() из GRAPH_DDL — руками поддерживаемого списка не заводим.
- Базовый фон прогона: 13 падений сюиты (нужен живой RabbitMQ; корневой .env перекрывает дефолты настроек). Любое 14-е падение — регрессия; сравнение делать по именам тестов, а не по числу.

---

## 4. Риски

- **БЛОКЕР (возражение 1, подтверждён в коде): docker-compose.prod.yml:189 запускает прод-контейнер ingest-consumer командой `python -m src.ingest_queue.consumer`. Перенос пакета без правки этого файла = crash-loop на rabbitmq-бэкенде, то есть полная остановка приёма на умолчательном пути. Прежняя формулировка шага искала ссылку под deploy/, где её нет.**  
  _вероятность high, ущерб high_  
  Митигация: docker-compose.prod.yml и README.md добавлены в allowed_files; S4 начинается с grep по ВСЕМУ репозиторию (--exclude-dir=.git), compose правится тем же коммитом, что git mv, и закрепляется тестом, читающим compose-файл: подстроки 'src.ingest_queue' в нём быть не должно, 'python -m src.intake.queue.consumer' — должна.
- **БЛОКЕР (возражение 2, подтверждён в коде): src/workflow/_search_deps.py:127 и src/mcp/tools_server.py:144 инжектируют AsyncPostgres в ChunkRepository, а chunk_repository.py:162 зовёт self._pg.get(). Снятие `get` с AsyncPostgres ломает read_full_document и поиск пути документа в рантайме, и ни один юнит-тест этого не ловит: tests/test_storage/test_chunk_repository.py подсовывает собственный фейк с методом get.**  
  _вероятность high, ущерб high_  
  Митигация: Аргумент `pg=` убран из обоих вызовов; умолчание конструктора ChunkRepository — IntakeRepository (импорт остаётся внутри src/storage, так что src/workflow не получает прямой зависимости от intake и третьего исключения в arch-тесте не нужно). Аннотация сменена на IntakeRepository | None, но тайпчекера в проекте нет (pyproject знает только ruff), поэтому защита исполняемая: правило 3 arch-теста ловит `pg=AsyncPostgres(...)` по AST, плюс test_default_pg_is_intake_repository. Третья затронутая точка — tests/test_retrieval/test_graph_rank.py:294 (`lambda *, graph, pg`) — в allowed_files.
- **КРУПНОЕ (возражение 3, подтверждено): после S8 отклонённый документ имеет documents.status='pending' (колонка с DEFAULT, в неё не пишут) и, после S9, не имеет строки doc_processing. Миграция с предикатом только `status <> 'skipped'` при повторном прогоне вставила бы ему строку 'pending', и документ перевернулся бы из 'skipped' в 'pending' в GET /ingest/{job_id}, /stats/messages, MCP-инструменте и CLI. Прежний текст отката прямо предписывал такой повтор.**  
  _вероятность high, ущерб high_  
  Митигация: Предикат ужесточён до трёх условий (status <> 'skipped' AND intake_status <> 'rejected' AND NOT EXISTS по doc_processing) — оператор стал идемпотентным по существу, маркер превратился в оптимизацию. Тест test_backfill_predicate_cannot_resurrect_a_rejected_row требует присутствия всех трёх условий. Текст отката переписан: повторный прогон миграции безопасен, а TRUNCATE doc_processing после S8 — запрещён (см. rollback).
- **КРУПНОЕ (возражение 4, подтверждено): умолчание on_duplicate=reject превращает документированные режимы переингеста в no-op. scripts/tg_ingest.py:161 reingest_channels существует, чтобы перечитать новейшие N сообщений канала, а src/api/routes/ingest.py:82-84 описывает backfill как «Re-ingest of already-known material» (его шлёт deploy/offline/loadtest/loader.py:76 и операторские перезаливки по DEPLOYMENT.md:252). Подсчёт 409 как «уже известного документа» без смены политики = рапорт об успехе при нулевой работе.**  
  _вероятность high, ущерб medium_  
  Митигация: Политика выбирается по вызывающему: on_duplicate стал необязательным (None), эффективное значение = явное, иначе 'version' при backfill=true, иначе 'reject'; tg_ingest в режиме reingest шлёт version явно. Сегодняшнее поведение переингеста (новый doc_id, новый комплект чанков) при version воспроизводится дословно. Счётчик 409-как-дубликат остаётся только для continuous sync и legacy --channels, где повтор и должен быть идемпотентным. Решения записаны тестами (6)(7) в test_dedup.py и test_reingest_sends_on_duplicate_version.
- **КРУПНОЕ (возражение 5, подтверждено): on_duplicate=replace не даёт наблюдаемого эффекта. В src/retrieval слово documents встречается только в комментариях, фильтра по intake_status нет нигде, chunk_repository берёт из documents лишь .path — значит после replace обе копии остаются находимыми и цитируемыми, а Postgres объявляет одну дубликатом. Это ровно та политика, к которой пользователь потянется, чтобы избавиться от старой копии.**  
  _вероятность high, ущерб medium_  
  Митигация: ПРИНЯТОЕ ОТКЛОНЕНИЕ ОТ I4: replace отложен, ON_DUPLICATE = ('reject','version'), значение 'replace' отвечает 422 вместе с прочими неизвестными (тест (4) фиксирует это как решение, а не упущение). Честная реализация требует удаления чанков старого документа из Milvus и его узлов/рёбер из графа, а сущности мёржатся МЕЖДУ документами (merge_and_resolve → merge_kg_extraction), поэтому поштучная чистка графа — отдельная задача со своим дизайном (вынесена в out_of_scope). Значение 'duplicate' остаётся в CHECK колонки intake_status, так что будущий шаг не потребует миграции схемы. Альтернатива — выпустить replace с честной оговоркой «только бухгалтерия в Postgres» — отклонена: поведение, невидимое снаружи, хуже отсутствующего.
- **КРУПНОЕ (возражение 6, подтверждено): перенос src/workflow/ingest_submit.py ломает tests/test_workflow/test_scheduler_isolation.py:55, а перенос очереди — tests/test_api/test_ingest_priority.py:78; оба файла отсутствовали и в шаге, и в allowed_files, то есть шаг завершился бы ImportError'ом, неотличимым от регрессии базового фона.**  
  _вероятность high, ущерб medium_  
  Митигация: Оба файла в S4 и в allowed_files (по одной строке импорта каждый). Сам шаг теперь начинается с полного grep'а 'ingest_queue\|ingest_submit' по репозиторию, а не со списка радиуса поражения; тот же приём (grep вместо памяти) предписан для S3, S5 и S6.
- **Частичный уникальный индекс из §1.1 спеки (WHERE content_sha256 IS NOT NULL) делает политику version физически невыполнимой: она создаёт вторую строку с тем же хешем.**  
  _вероятность high, ущерб high_  
  Митигация (в редакции правки A′): предикат остаётся `WHERE content_sha256 IS NOT NULL`, а из индекса версию выводит ОТСУТСТВИЕ хеша — `accept_document` пишет неканонической строке `content_sha256 = NULL`. Расширять предикат до `AND duplicate_of IS NULL` НЕЛЬЗЯ: это несовместимо с `ON DELETE SET NULL` у `duplicate_of` (удаление канона с двумя версиями падает нарушением уникальности, см. A′). Предикат не смотрит и на intake_status: отклонённый документ обязан остаться в индексе — 409 отдаёт его intake_status. Тесты (3) и (11) в tests/test_intake/test_dedup.py закрепляют обе стороны, схему — tests/test_storage/test_pg_schema.py::test_sha_index_predicate_does_not_mention_duplicate_of, инвариант записи — tests/test_intake/test_repository.py::test_accept_nulls_sha_on_version_row.
- **Маркер public.schema_migration.name — один глобальный PRIMARY KEY, а intake_split_v1 должен отработать по каждой схеме графа. Голое имя мигрировало бы первый граф (_ready_graphs всегда ставит default первым) и молча пропустило остальные.**  
  _вероятность high, ущерб high_  
  Митигация: Маркер посхемный: 'intake_split_v1:<pg_schema>' (S2), тест test_marker_is_per_schema. Прецедент authz_grandfather_v1 глобален и помечен комментарием как необобщаемый. Дополнительная страховка — сам предикат теперь идемпотентен, так что пропуск маркера не портит данные, а лишь стоит одного индексного сканирования.
- **Два фейковых курсора несовместимы с добавлением чего-либо в migrate_graph_schema и ломаются по-разному: test_pg_schema._Cur.fetchall возвращает кортежи имён таблиц (гард маркера прочитается как «уже применено» — зелёный тест при неработающем коде), а test_setup_db_graph_schema._Cur вообще не имеет fetchone/fetchall (AttributeError).**  
  _вероятность high, ущерб medium_  
  Митигация: Оба фейка расширяются в S2 ДО написания кода миграции; в test_intake_migration.py заведён отдельный курсор со сценарием «маркера нет», где проверяется, что три оператора реально эмитируются. Счётчик len(GRAPH_DDL)+3 параметризуется по наличию маркера.
- **Выбрасывание 'skipped' из DOC_STATUSES уронило бы GET /api/v1/stats/messages: StatRow (src/api/routes/stats.py:30-38) требует этот ключ, его отсутствие — ValidationError на валидации ответа, то есть 500. Та же выдача без схемы уходит в MCP-инструмент и в колонки CLI.**  
  _вероятность medium, ущерб high_  
  Митигация: Отчётный словарь DOC_STATUSES сохраняется целиком, 'skipped' вычисляется из intake_status='rejected' выражением эффективного статуса (S8). Из домена уходит только CHECK таблицы doc_processing. Фикстуры с "skipped": 0 в tests/test_api/test_stats_routes.py и tests/test_scripts/test_message_stats_cli.py намеренно не правятся — их зелёность и есть гард.
- **DocumentRow.from_dict читает row['status'], row['error'], row['summary'] жёстким ключом, а у отклонённого документа строки обработки нет по замыслу (§1.4). Наивный LEFT JOIN даст None или KeyError ровно на тех строках, которые спека хочет сделать видимыми.**  
  _вероятность high, ущерб medium_  
  Митигация: Форма объединённой строки выбрана явно: псевдонимы proc_status/proc_error/proc_summary (без них dict_row схлопнет одноимённые колонки) плюс правило эффективного статуса. Тесты test_get_of_rejected_doc и test_get_of_pending_doc закрепляют обе ветки.
- **scripts/wipe_db.py перестаёт работать: внешний ключ doc_processing → documents делает TRUNCATE documents ошибкой FeatureNotSupported, а цикл :106-112 ловит только UndefinedTable. Падение на первой же очистке стенда.**  
  _вероятность high, ущерб medium_  
  Митигация: S12: 'doc_processing' добавлен в _PG_TABLES перед 'documents' И оператор переведён на TRUNCATE … CASCADE (очистки дочерней таблицы мало — Postgres отказывает по наличию ссылки, не строк). Входящих внешних ключей у остальных таблиц списка нет, CASCADE для них no-op. Тест test_truncates_doc_processing_and_cascades.
- **Читатели documents вне списка §3.3: src/storage/watch.py:95/250 (LEFT JOIN documents ради d.path), scripts/check_ingestion.py:37 и deploy/offline/loadtest/monitor.sh:14-17 (агрегация documents.status напрямую).**  
  _вероятность medium, ущерб low_  
  Митигация: watch.py берёт только path — колонка остаётся в documents, запрос переживает расщепление без правки; импортная граница зафиксирована в докстринге arch-теста (src/storage — инфраструктура ниже обоих контуров). check_ingestion.py и monitor.sh переведены на join в S12, иначе вечно показывали бы всё как 'pending'.
- **Перенос модулей ломает тесты по цели патча, а не по поведению: шесть tests/test_api/test_ingest*.py патчат литерал 'src.api.routes.ingest.build_minio_storage', около пятнадцати файлов патчат методы на AsyncPostgres по имени атрибута. Легко получить «зелёный» прогон, где патч не применился и тест проверяет чужой код.**  
  _вероятность medium, ущерб medium_  
  Митигация: Переносы (S3–S6) отделены от изменений поведения отдельными шагами, где утверждения тестов не меняются вовсе — расходится только строка патча. После каждого такого шага прогон сравнивается с базовым списком падений по ИМЕНАМ тестов. Патчи через patch.object(Class, 'method') вместо строки там, где возможно: AttributeError при опечатке вместо тихого промаха.
- **src/config.py:21 импортирует src.ingest_queue.priorities. После переезда очереди это поставило бы контур приёма в корень графа импортов ядра и обесценило бы arch-тест: AST видит только прямые импорты, транзитивный src.graph → src.config → src.intake остался бы незамеченным.**  
  _вероятность high, ущерб medium_  
  Митигация: S4 снимает импорт (ge=PRIO_LIVE → ge=5 с комментарием), дрейф закрывается новым tests/test_config/test_ingest_priorities.py — тот же приём, что tests/test_scripts/test_setup_db_authz.py для _FULL_SCOPES_SQL. Заодно src/workflow/ingest_submit.py переезжает в src/intake/submit.py как второй и последний ядровый импортёр очереди.
- **Зонд to_regclass в graph_lifecycle/activities.py переводится на doc_processing. На полумигрированной схеме (documents есть, doc_processing нет) зонд вернёт NULL, функция отдаст пустой список, и удаление графа пойдёт при живых документах в полёте.**  
  _вероятность low, ущерб medium_  
  Митигация: Окно существует только между S1 и прогоном setup_db/провижининга, который создаёт таблицу в том же вызове migrate_graph_schema, что и остальной DDL. Это ровно та же толерантность к отсутствующей схеме, что заложена сегодня. Параметризованный test_inflight_doc_ids_tolerates_missing_schema сохраняется на новой таблице.
- **MinIO не транзакционен с Postgres: при reject не должно записываться вообще ничего — но это верно, только если sha256 считается и проверяется строго до put_object, включая опциональную заливку original.**  
  _вероятность low, ущерб medium_  
  Митигация: S10 ставит проверку между file.read() (ingest.py:147) и build_minio_storage(); тест (9) проверяет, что при найденном дубле build_minio_storage не вызывался вовсе, а не только put_object.
- **Повторные прогоны инструментов по одному и тому же корпусу теперь видят 409: deploy/offline/loadtest/loader.py без --backfill пишет HTTP-код в rec['ingest_status'] и покажет прогон как сломанный; deploy/offline/webui при повторной заливке того же файла покажет оператору ошибку.**  
  _вероятность medium, ущерб low_  
  Митигация: ПРИНЯТО. С --backfill (документированный способ перезаливки, DEPLOYMENT.md:252) loader попадает на политику version и работает как раньше; без него 409 — это и есть заявленная функция. loader.py и webui не правим (out_of_scope), факт фиксируется в CHANGELOG при реализации, чтобы операторы не приняли его за поломку.
- **Прод-данные в этой сессии не читались: mongodb MCP не подключён, kb-search и kb-tools отвалились с ECONNREFUSED. Сколько строк в documents, сколько из них status='skipped' и сколько существует схем g_<id> — неизвестно, цена intake_split_v1 на боевой базе не оценена.**  
  _вероятность medium, ущерб medium_  
  Митигация: Миграция — один INSERT … SELECT плюс один UPDATE на схему, оба по индексируемому documents_status_idx; на пустых графах бесплатны. Добавленный NOT EXISTS — антиджойн по первичному ключу doc_processing, не меняет порядок стоимости. Перед выкатом снять три числа живым psql (count(*) FROM documents; разбивка по status; количество схем g_%) — отдельным явным разрешением пользователя.
- **Исключений из правила импорта будет два, а не одно, как требует §3.2: вердикт классификатора пишет активность mark_skipped, и она тоже принадлежит приёму.**  
  _вероятность high, ущерб low_  
  Митигация: Оба исключения объявлены одним явным allowlist в tests/test_intake/test_boundaries.py с обоснованием в докстринге; test_allowlist_is_minimal запрещает этим файлам импортировать src.intake.api. Вынос mark_skipped в собственный модуль заодно выравнивает finalize.py по соглашению «одна активность — один модуль».

---

## 5. Возражения критика

### 1. BLOCKER

**Проблема.** S4 deletes `src/ingest_queue/` but the production RabbitMQ consumer container is started by module path from a file the plan cannot touch. `docker-compose.prod.yml:189` is `command: ["python", "-m", "src.ingest_queue.consumer"]`. After the move that container crash-loops with ModuleNotFoundError on the rabbitmq backend. S4 only says «проверить deploy/ на эту команду отдельным grep'ом» — the reference is NOT under deploy/, it is at the repo root, and `docker-compose.prod.yml` is absent from `allowed_files`, so the plan as written is unable to fix what it breaks.

**Доказательство.** docker-compose.prod.yml:189 — `command: ["python", "-m", "src.ingest_queue.consumer"]`; grep over deploy/ docker-compose*.yml Makefile returns this single hit; `allowed_files` contains no compose file.

**Предложенная починка.** Add `docker-compose.prod.yml` to allowed_files and update the command to `src.intake.queue.consumer` in the same commit as the move; widen S4's pre-move grep from `deploy/` to the whole repo (`grep -rn ingest_queue . --exclude-dir=.git`).

### 2. BLOCKER

**Проблема.** S5 moves `get()` off `AsyncPostgres` onto `IntakeRepository` and re-points `ChunkRepository` at the new class, but misses a caller that INJECTS an `AsyncPostgres` into `ChunkRepository`. `src/workflow/_search_deps.py:127` builds `ChunkRepository(graph=graph, pg=AsyncPostgres(graph=graph))`; `ChunkRepository.aget_document_path` then calls `self._pg.get(...)`. With `get` removed from `AsyncPostgres`, every `read_full_document` / document-path lookup in the search path raises AttributeError at runtime — and no unit test catches it, because `tests/test_storage/test_chunk_repository.py` passes a hand-rolled fake with a `get` method.

**Доказательство.** src/workflow/_search_deps.py:127 `return ChunkRepository(graph=graph, pg=AsyncPostgres(graph=graph))`; src/storage/chunk_repository.py:72 `self._pg = pg or AsyncPostgres(graph=graph)`; :162 `row = await self._pg.get(uuid.UUID(doc_id))`. `src/workflow/_search_deps.py` appears in neither S5's `files` nor `allowed_files` (only `src/mcp/tools_server.py:144`, the other injection site, is listed).

**Предложенная починка.** Add `src/workflow/_search_deps.py` to S5 and swap the injected class there too; also change the `pg:` parameter annotation in `chunk_repository.py` from `AsyncPostgres | None` to `IntakeRepository | None` so mypy/pyright flags any remaining injection site instead of letting it fail at runtime.

### 3. MAJOR

**Проблема.** The one-off `intake_split_v1` is not idempotent once S9 is live, and the plan's own documented rollback procedure replays it. After S8 nothing writes `documents.status`, so a classifier-rejected document keeps `status='pending'` (the column DEFAULT) while S9's `reject()` DELETEs its `doc_processing` row. Re-running the migration — exactly what the rollback section tells an operator to do — matches those rows on `WHERE status <> 'skipped'`, re-inserts a `doc_processing` row with `status='pending'`, and every rejected document silently flips from 'skipped' back to 'pending' in `GET /ingest/{job_id}`, `/stats/messages`, the MCP tool and the CLI.

**Доказательство.** Plan S2 change: `INSERT INTO doc_processing … SELECT … FROM documents WHERE status <> 'skipped' ON CONFLICT (doc_id) DO NOTHING`; plan S8(1): «колонку status не называем — остаётся NOT NULL DEFAULT 'pending'»; plan S9: `DELETE FROM doc_processing WHERE doc_id=%s`; plan rollback: «удалить строки public.schema_migration WHERE name LIKE 'intake_split_v1:%' и TRUNCATE doc_processing CASCADE … следующий прогон setup_db проиграет миграцию заново (оба оператора идемпотентны)».

**Предложенная починка.** Tighten the backfill predicate so it cannot resurrect a deliberate deletion: `WHERE status <> 'skipped' AND intake_status <> 'rejected'` (or `AND NOT EXISTS (SELECT 1 FROM doc_processing p WHERE p.doc_id = documents.id)` plus the intake_status guard). Add a test that runs the migration SQL against a corpus containing a rejected row and asserts no processing row appears. Then the statement really is idempotent and the per-schema marker becomes a cheap extra guard rather than the only thing standing between prod and corruption.

### 4. MAJOR

**Проблема.** `on_duplicate` defaulting to `reject` silently disables the repository's documented re-ingest paths, and S12 codifies the breakage instead of fixing it. `scripts/tg_ingest.py --reingest` exists specifically to re-read and re-POST the newest N messages of a channel at low priority; with the default policy every unchanged message now returns 409 and the mode becomes a no-op. S12's remedy is to count 409 as «уже известный документ» in a duplicates tally — i.e. the command reports success while ingesting nothing. The API's `backfill` flag has the same problem: its whole documented purpose is «Re-ingest of already-known material».

**Доказательство.** scripts/tg_ingest.py:24 («Reingest (--reingest @a,@b). Manual re-read: newest --reingest-limit …»), :161 `reingest_channels`, :561-606 `_run_reingest`; `post_ingest` (:98-128) sends no `on_duplicate` and returns `200 <= status < 300`; src/api/routes/ingest.py:82-84 comment on `backfill`. Plan S12: «Считать 409 не ошибкой, а уже известным документом».

**Предложенная починка.** Decide the policy per caller rather than globally: have `tg_ingest` reingest mode and any `backfill=true` POST send `on_duplicate=version` explicitly (the plan already forbids the implicit `force→version` mapping, but `backfill` is a different flag and reingest is a different mode), and keep the 409-as-duplicate tally only for the continuous-sync path. Add a dedup test asserting that `backfill=true` + default policy is a deliberate 409, so the decision is recorded rather than discovered in prod.

### 5. MAJOR

**Проблема.** `on_duplicate=replace` changes nothing a user can observe. The three statements touch only Postgres; the replaced document's chunks stay in Milvus and its entities/relations stay in the graph, and nothing in retrieval consults `documents` at all — there is no `intake_status` filter anywhere in the read path. So after a `replace` both copies remain fully searchable and both are cited, while Postgres claims one is a duplicate. The policy's name promises de-duplication the implementation does not deliver, and it is the one policy a user would reach for precisely to get rid of the old copy.

**Доказательство.** Plan S10 replace = three Postgres statements only (INSERT / UPDATE old / UPDATE new); `grep -rn documents src/retrieval/*.py` returns only prose in comments (llm_pool.py:4-5, vector_index.py:88) — no query; src/storage/chunk_repository.py reads `documents` only for `.path` (:162).

**Предложенная починка.** Either scope `replace` honestly in the spec and the form-field docstring («Postgres bookkeeping only; vectors and graph of the superseded document are not removed — see out_of_scope»), or add the deletion to S10: drop the old doc's chunks from the graph's Milvus collection and its nodes/edges from the graph store. If the deletion is out of scope for this plan, drop `replace` from `ON_DUPLICATE` for now and ship `reject`/`version` only — shipping a policy whose effect is invisible is worse than not shipping it.

### 6. MAJOR

**Проблема.** S4 misses a second importer of the module it moves. `tests/test_workflow/test_scheduler_isolation.py:55` does `from src.workflow.ingest_submit import _submit_to_scheduler` to guard the scheduler-queue isolation invariant. S4 lists only `tests/test_workflow/test_ingest_submit.py` for the rename, and `test_scheduler_isolation.py` is in neither the step's `files` nor `allowed_files` — so the step ends with an ImportError the plan is not permitted to fix, and the baseline «13 падений» comparison turns into 14 for a reason that looks like a regression.

**Доказательство.** tests/test_workflow/test_scheduler_isolation.py:55 `from src.workflow.ingest_submit import _submit_to_scheduler`; plan S4 `files` lists `tests/test_workflow/test_ingest_submit.py` only; `allowed_files` has no `test_scheduler_isolation.py`.

**Предложенная починка.** Add `tests/test_workflow/test_scheduler_isolation.py` to S4 (one import line) and to allowed_files. More generally, S4 should start from `grep -rn 'ingest_submit\|ingest_queue' src tests scripts docs *.yml Makefile` rather than from the blast-radius list, which also missed `tests/test_api/test_ingest_priority.py:78`.

### 7. MINOR

**Проблема.** S10's race handling turns a legitimate concurrent upload into a 500 for two of the three policies. «accept_document ловит UniqueViolation и при reject отдаёт тот же 409, при version/replace — пробрасывает». But under `version`, when `find_by_sha` found nothing the INSERT carries `duplicate_of=NULL` and therefore CAN collide with a simultaneous first upload of the same body; the same is true for `replace`. The route has no handler for a re-raised `UniqueViolation`, so FastAPI returns 500 on a case the index was introduced to handle gracefully.

**Доказательство.** Plan S10: «Гонка двух одновременных POST закрывается индексом … при version/replace — пробрасывает»; src/api/routes/ingest.py has no `except psycopg.errors.*` around the insert (the only handler is the S3/transport one at :181 and the dead Temporal one at :245).

**Предложенная починка.** On `UniqueViolation` re-read the winner and retry once with the duplicate branch of the chosen policy (version → set `duplicate_of` to the winner and insert again; replace → run the three-statement sequence against the winner). Cover it with the existing test (8), extended to `version` and `replace`, not just `reject`.

### 8. MINOR

**Проблема.** S2's stated failure mode for the existing fake cursor is backwards, and acting on the stated reasoning produces the wrong fix. `_Cur.fetchall()` returns `[(t,) for t in self._existing]`, and `test_migrate_creates_schema_then_runs_graph_ddl` constructs `_Cur()` with no `existing` — so it returns `[]`, the marker guard reads «never applied», and the migration DOES execute under test. The failure is a loud count mismatch (`len(GRAPH_DDL)+3` vs the actual +7), not the «зелёный тест при нерабочем коде» the risk register describes. Separately, `_Cur` has no `fetchone`, so `_intake_split` must probe with `fetchall()` (the `_grandfather_scopes` pattern) or that test errors.

**Доказательство.** tests/test_storage/test_pg_schema.py:14-15 `def fetchall(self): return [(t,) for t in self._existing]`; :39-40 `cur = _Cur()` then `:46 assert len(stmts) == len(pg_schema.GRAPH_DDL) + 3`; scripts/setup_db.py:236 `if cur.fetchall():  # at most one row; empty means "never ran"`.

**Предложенная починка.** State the real arithmetic in S2: marker absent → +4 statements (guard SELECT, two data statements, marker INSERT), marker present → +1, so the assertion becomes `len(GRAPH_DDL) + 3 + N`. Mirror `_grandfather_scopes` exactly (`cur.fetchall()`), and add `fetchone` to `tests/test_scripts/test_setup_db_graph_schema.py::_Cur` only if the implementation actually needs it.

### 9. MINOR

**Проблема.** `duplicate_of UUID REFERENCES documents(id)` is declared with no `ON DELETE` action, i.e. NO ACTION. Any `DELETE FROM documents` that removes a row another row points at now fails with a foreign-key violation — including two live tests that clean up after themselves, and any future retention job (the `doc_processing` FK was given `ON DELETE CASCADE`, so the asymmetry is clearly unintentional).

**Доказательство.** Plan S1: «duplicate_of UUID REFERENCES documents(id)» (no ON DELETE), against «doc_id UUID PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE»; tests/test_storage/test_message_stats_queries.py:67 `cur.execute("DELETE FROM documents WHERE path LIKE %s", …)`; tests/test_storage/test_insert_pending_source.py:60 `DELETE FROM documents WHERE id = %s`.

**Предложенная починка.** Declare `duplicate_of UUID REFERENCES documents(id) ON DELETE SET NULL` — a deleted canonical row should leave its versions standing as canonical rather than block the delete. Note in S1 why the two FKs differ.

### 10. MINOR

**Проблема.** The `reject` path can orphan a MinIO object. The plan is careful to compute sha256 before `build_minio_storage()`, but the UniqueViolation fallback fires AFTER the upload: `put_object` runs at ingest.py:157-165 and the insert only at :191. A concurrent duplicate therefore uploads its body (and its optional `original`) and then answers 409, leaving two objects under a `doc_id` prefix that no `documents` row will ever reference — invisible to `delete_prefix`-based graph teardown, which walks `graph.minio_prefix` but is only triggered on graph deletion.

**Доказательство.** src/api/routes/ingest.py:147 `contents = await file.read()`, :158-165 `storage.put_object(...)`, :171-180 optional original upload, :191 `await pg.insert_pending(...)`; plan S10 «accept_document ловит psycopg.errors.UniqueViolation и при reject отдаёт тот же 409».

**Предложенная починка.** Delete the just-written object(s) in the UniqueViolation branch before answering 409 (best-effort, log on failure), and say so in test (8) so the cleanup does not get dropped later.

### 11. MINOR

**Проблема.** `version` and `replace` inflate every reporting surface, and the plan explicitly decides not to join `timeline_counts` to the processing table — so duplicate rows are counted as separate messages. `status_counts_by.total` is deliberately the unconditional per-key row count, and `StatRow` has no bucket for `intake_status='duplicate'`, so a replaced document is counted once as 'completed' (old row, processing row kept) and again under the new row. Three surfaces that the plan's own invariant promises will «показывать одинаковые числа» now show numbers that no longer mean «documents ingested».

**Доказательство.** src/storage/postgres.py:222-229 («`total` is deliberately the count of ALL rows for the key»); src/api/routes/stats.py:30-38 `StatRow` (key,total,pending,processing,completed,vector_only,failed,skipped — no duplicate); plan S8(4) «timeline_counts НЕ трогать: все её колонки в documents, join не нужен».

**Предложенная починка.** Exclude non-canonical rows from both aggregations — `WHERE duplicate_of IS NULL` in `status_counts_by` and `timeline_counts` — which keeps the response shape and the invariant «числа после миграции совпадают с дорасщеплёнными» literally true, since every pre-migration row has `duplicate_of IS NULL`. Add that predicate to the S8 repository tests.

---

## 6. Откат

"Шаги независимы и ревертятся по одному: `git revert` коммита шага. Два коммита атомарны по составу и ревертятся целиком: S4 (перенос очереди ВМЕСТЕ с docker-compose.prod.yml:189 — откатывать код без compose или наоборот значит получить crash-loop ingest-consumer) и S5 (снятие `get` с AsyncPostgres ВМЕСТЕ с обоими местами сборки ChunkRepository).\n\nСхема аддитивна (новые колонки, новая таблица, новые индексы) — откат кода на любой предыдущий коммит работает, пока documents.status не удалён (I8). После S8 записи нового кода в doc_processing в documents.status не отражаются, и откаченный старый код покажет такие документы как 'pending'. Это принятая цена (§7 спеки), и она же определяет правило ниже.\n\nДАННЫЕ. Повторный прогон intake_split_v1 безопасен в любой момент: предикат исключает отклонённые документы (intake_status='rejected') и любые строки, у которых doc_processing уже есть, поэтому оператор ничего не перезаписывает и ничего не воскрешает. Чтобы заставить его проиграться заново, достаточно удалить строки public.schema_migration WHERE name LIKE 'intake_split_v1:%'.\n\nЗАПРЕЩЕНО после того, как S8 попал на стенд: `TRUNCATE doc_processing` (с CASCADE или без) с расчётом «миграция восстановит». Восстановить она может только ДОрасщеплённые строки — их статусы лежат в documents.status; у всех документов, принятых после S8, в documents.status навсегда 'pending', и очистка таблицы обработки уничтожит их реальные статусы без возможности восстановления. Единственный безопасный способ сбросить данные приёма — wipe стенда целиком (scripts/wipe_db.py, уже чинится в S12).\n\nТаблицу doc_processing и колонки приёма физически не удалять: они попадают в graph_tables() и их отсутствие уронит гейт готовности графа.\n\nДля отката ТОЛЬКО дедупа достаточно вернуть S10: схема и индексы остаются, но ни одна новая строка не получает content_sha256, частичный уникальный индекс перестаёт на что-либо влиять, а on_duplicate исчезает из формы (клиенты, уже посылающие поле, получат прежнее поведение — FastAPI игнорирует лишние поля формы)."

---

## 7. Вне объёма

- Политика on_duplicate=replace и всё, что делает её наблюдаемой: удаление чанков вытесненного документа из коллекции Milvus графа и чистка его узлов/рёбер в графовом хранилище. Сущности мёржатся между документами (merge_and_resolve → merge_kg_extraction), поэтому поштучное удаление требует собственного дизайна (что делать с сущностью, подтверждённой и другими документами). Схема к этому готова: значение 'duplicate' уже в CHECK колонки intake_status, миграции шаг не потребует.
- Нечёткий дедуп: тот же документ в другом формате (docx → txt, PDF через другой принтер) даёт другой хеш и проходит как новый (I2).
- Пересчёт content_sha256 для исторических строк — потребовал бы скачать из MinIO весь корпус; они просто не участвуют в дедупе (принятое ограничение §1.3).
- Удаление колонки documents.status и её CHECK (I8) — отдельный шаг после того, как выкат устоится.
- Реестр источников и принципалы фидеров (шаг 1.4 карты контуров).
- GET /intake/stats (шаг 1.5).
- Квоты и честность приёма между арендаторами; колонка graphs.max_inflight остаётся зарезервированной (шаг 1.6).
- Переименование наружного словаря статусов: 'skipped' остаётся отчётным именем для intake_status='rejected'. Введение 'rejected' в StatRow/CLI/MCP — отдельная согласованная задача по трём поверхностям сразу.
- deploy/offline/webui/index.html:203-216 — карта STATUS_RU без записей для vector_only/skipped/rejected (сырая строка показывается как есть, как сегодня); deploy/offline/webui/app.py не трогаем — публичные пути не меняются, 409 пробрасывается как есть.
- deploy/offline/loadtest/loader.py — повторный прогон без --backfill начнёт получать 409; осознанно оставляем как есть (с --backfill он попадает на version и работает по-прежнему).
- docs/bruno/* — ручная коллекция API; новое поле формы on_duplicate в неё не добавляем.
- Исторические документы docs/superpowers/plans/* и docs/superpowers/specs/2026-07-01-* со ссылками на src.ingest_queue — записи о прошлом, не правим.
- Любые git commit / push / restore / clean / stash и make fmt.
- Живые прогоны против стека (RabbitMQ, Postgres, MinIO, Temporal) и чтение боевой БД — только по явному разрешению пользователя.
- Перенос остальных модулей src/ingestion (embeddings, pipeline, run, identifier_transform, translate_transform) — переезжает только classifier.py.
- src/workflow/ingest_scheduler.py и консьюмерская часть исполнения: воркерная механика admission не меняется, переезжает только producer-сторона.

---

## 8. Разрешённые к правке файлы

- `src/intake/__init__.py`
- `src/intake/classifier.py`
- `src/intake/repository.py`
- `src/intake/submit.py`
- `src/intake/api/__init__.py`
- `src/intake/api/ingest.py`
- `src/intake/api/documents.py`
- `src/intake/queue/__init__.py`
- `src/intake/queue/priorities.py`
- `src/intake/queue/topology.py`
- `src/intake/queue/publisher.py`
- `src/intake/queue/consumer.py`
- `src/ingestion/classifier.py`
- `src/ingest_queue/__init__.py`
- `src/ingest_queue/priorities.py`
- `src/ingest_queue/topology.py`
- `src/ingest_queue/publisher.py`
- `src/ingest_queue/consumer.py`
- `src/storage/pg_schema.py`
- `src/storage/postgres.py`
- `src/storage/chunk_repository.py`
- `src/workflow/ingest_submit.py`
- `src/workflow/_search_deps.py`
- `src/workflow/activities/__init__.py`
- `src/workflow/activities/classify_document.py`
- `src/workflow/activities/mark_skipped.py`
- `src/workflow/activities/finalize.py`
- `src/workflow/activities/fetch_source.py`
- `src/workflow/graph_lifecycle/activities.py`
- `src/api/main.py`
- `src/api/routes/ingest.py`
- `src/api/routes/documents.py`
- `src/api/routes/stats.py`
- `src/mcp/tools_server.py`
- `src/config.py`
- `scripts/setup_db.py`
- `scripts/wipe_db.py`
- `scripts/message_stats.py`
- `scripts/backfill_doc_id.py`
- `scripts/check_ingestion.py`
- `scripts/tg_ingest.py`
- `docker-compose.prod.yml`
- `README.md`
- `deploy/offline/loadtest/monitor.sh`
- `docs/superpowers/specs/2026-10-19-intake-contour-design.md`
- `CHANGELOG.md`
- `tests/test_intake/__init__.py`
- `tests/test_intake/test_dedup.py`
- `tests/test_intake/test_repository.py`
- `tests/test_intake/test_boundaries.py`
- `tests/test_intake/test_classifier.py`
- `tests/test_intake/test_submit.py`
- `tests/test_intake/test_queue_topology.py`
- `tests/test_intake/test_queue_publisher.py`
- `tests/test_intake/test_queue_consumer.py`
- `tests/test_intake/test_queue_consumer_graph.py`
- `tests/test_storage/test_pg_schema.py`
- `tests/test_storage/test_intake_migration.py`
- `tests/test_storage/test_chunk_repository.py`
- `tests/test_storage/test_document_original_path.py`
- `tests/test_storage/test_insert_pending_source.py`
- `tests/test_storage/test_message_stats_queries.py`
- `tests/test_scripts/test_setup_db_graph_schema.py`
- `tests/test_scripts/test_setup_db_source_columns.py`
- `tests/test_scripts/test_wipe_db.py`
- `tests/test_scripts/test_message_stats_cli.py`
- `tests/test_scripts/test_tg_ingest.py`
- `tests/test_api/test_ingest.py`
- `tests/test_api/test_ingest_backfill.py`
- `tests/test_api/test_ingest_group.py`
- `tests/test_api/test_ingest_original.py`
- `tests/test_api/test_ingest_priority.py`
- `tests/test_api/test_ingest_source_channel.py`
- `tests/test_api/test_ingest_status.py`
- `tests/test_api/test_documents.py`
- `tests/test_api/test_stats_routes.py`
- `tests/test_api/test_graph_binding.py`
- `tests/test_api/test_graph_dep_authz.py`
- `tests/test_api/test_route_actions.py`
- `tests/test_mcp/test_tools_server.py`
- `tests/test_mcp/test_current_graph.py`
- `tests/test_retrieval/test_graph_rank.py`
- `tests/test_tenancy/test_storage_names.py`
- `tests/test_workflow/test_finalize.py`
- `tests/test_workflow/test_mark_skipped.py`
- `tests/test_workflow/test_fetch_source.py`
- `tests/test_workflow/test_document_ingest_workflow.py`
- `tests/test_workflow/test_graph_lifecycle_activities.py`
- `tests/test_workflow/test_activity_graph_resolution.py`
- `tests/test_workflow/test_ingest_submit.py`
- `tests/test_workflow/test_scheduler_isolation.py`
- `tests/test_workflow/test_workflow_local.py`
- `tests/test_ingestion/test_classifier.py`
- `tests/test_ingest_queue/test_topology.py`
- `tests/test_ingest_queue/test_publisher.py`
- `tests/test_ingest_queue/test_consumer.py`
- `tests/test_ingest_queue/test_consumer_graph.py`
- `tests/test_config/test_ingest_priorities.py`
- `tests/eval/classifier_scenarios.py`

---

## 9. Разведка

### Точки входа

- /Users/a.tsitanov/projects/kb-llamaindex/src/api/routes/ingest.py:138 — `doc_id = uuid.uuid4()` (spec says :139, actual :138). Dedup insertion point is :147 `contents = await file.read()` → sha256 BEFORE :159 `put_object`. Route moves to src/intake/api/ingest.py
- /Users/a.tsitanov/projects/kb-llamaindex/src/api/routes/ingest.py:76 — `force: bool = Form(default=False)`; the new `on_duplicate` Form field goes next to it, validated with the other up-front 422s (:94 queue, :104 group, :118 priority, :131 document_date) so the 422 lands before `file.read()`
- /Users/a.tsitanov/projects/kb-llamaindex/src/api/routes/ingest.py:191 — `await pg.insert_pending(...)`; becomes intake-repo write (hash, intake_status, source_kind) + doc_processing 'pending' row
- /Users/a.tsitanov/projects/kb-llamaindex/src/api/routes/ingest.py:245 — `except WorkflowAlreadyStartedError` → 409. CONFIRMED DEAD: `submit_document` (src/workflow/ingest_submit.py:52) starts id='ingest-scheduler' with `WorkflowIDConflictPolicy.USE_EXISTING`, which never raises; the rabbitmq branch (:45 `publish_ingest`) cannot raise it either. The per-doc id is built in the WORKER (src/workflow/ingest_scheduler.py:146 and src/ingest_queue/consumer.py:67, both `graph_scoped_id("ingest", graph_id, doc_id)`), never in the HTTP path
- /Users/a.tsitanov/projects/kb-llamaindex/src/api/routes/ingest.py:276-291 — `job_status` / `JobProgressResponse` (fields job_id, status, path, department, doc_type, error, summary, declared at :55-64). Must answer about intake + processing
- /Users/a.tsitanov/projects/kb-llamaindex/src/api/routes/documents.py:44-56 — moves to src/intake/api/documents.py; reads `pg.get()` → `row.path`, `row.original_path`
- /Users/a.tsitanov/projects/kb-llamaindex/src/storage/pg_schema.py:14-64 `_DOCUMENTS_DDL` (status CHECK at :21-22 inline and :45-48 idempotent re-add, `documents_status_idx` :50) — intake columns + new `_DOC_PROCESSING_DDL` added to `GRAPH_DDL` (:371-386)
- /Users/a.tsitanov/projects/kb-llamaindex/src/storage/pg_schema.py:389-400 `migrate_graph_schema` — where `intake_split_v1` must run per graph schema
- /Users/a.tsitanov/projects/kb-llamaindex/src/storage/pg_schema.py:403-413 `graph_tables()` regex `CREATE TABLE IF NOT EXISTS\s+([a-z_][a-z0-9_]*)` — picks up `doc_processing` automatically; :416-424 `missing_graph_tables` gates `ready`
- /Users/a.tsitanov/projects/kb-llamaindex/src/storage/postgres.py:22-24 `DOC_STATUSES` tuple (drops 'skipped'), :31-59 `DocumentRow`, :88-111 `insert_pending`, :113-134 `update_status`, :165-173 `list_id_path`, :175-184 `get` (`SELECT *`), :186-232 `status_counts_by`, :234-289 `timeline_counts` — the six `documents` call sites
- /Users/a.tsitanov/projects/kb-llamaindex/src/workflow/activities/fetch_source.py:33 — `update_status('processing')` → doc_processing
- /Users/a.tsitanov/projects/kb-llamaindex/src/workflow/activities/finalize.py:49 (completed/vector_only), :182 (mark_skipped → must write documents.intake_status='rejected' AND DELETE the doc_processing row), :214 (mark_failed)
- /Users/a.tsitanov/projects/kb-llamaindex/src/workflow/graph_lifecycle/activities.py:152-166 `_inflight_doc_ids` — `SELECT to_regclass('documents')` then `SELECT id::text FROM documents WHERE status IN ('pending','processing')`; both the regclass probe and the query must move to `doc_processing`
- /Users/a.tsitanov/projects/kb-llamaindex/src/ingestion/classifier.py → src/intake/classifier.py; sole importer src/workflow/activities/classify_document.py:16 (the one declared arch-test exception); `force` bypass at :23-25
- /Users/a.tsitanov/projects/kb-llamaindex/src/ingest_queue/{topology,publisher,consumer,priorities}.py → src/intake/queue/
- /Users/a.tsitanov/projects/kb-llamaindex/src/api/main.py:17-28 (route imports) and :92-93 (`include_router(ingest…)`, `include_router(documents…)`) — re-point at src.intake.api, keep prefixes
- /Users/a.tsitanov/projects/kb-llamaindex/scripts/setup_db.py:29-46 — the `# noqa: F401 re-exported for tests/ops` import block from pg_schema; a new `_DOC_PROCESSING_DDL` symbol belongs here too (tests/test_storage/test_pg_schema.py:60-65 guards the re-exports)

### Потребители

- src/mcp/tools_server.py:676 `_stats_by` → `status_counts_by`; :700 `_timeline` → `timeline_counts`; :649-657 comment block pins 'the SAME aggregation methods'; :816 tool docstring enumerates 'processing / failed / vector_only / skipped'
- src/api/routes/stats.py:72 `status_counts_by`, :98 `timeline_counts`, and **:30-38 `StatRow` pydantic model with REQUIRED `skipped: int` and `vector_only: int`** — a rows dict without `skipped` 500s at response validation
- scripts/message_stats.py:22 imports `DOC_STATUSES`, :25 `_COLS = ("key","total",*DOC_STATUSES)`, :50/:55 `status_counts_by`, :60 `timeline_counts` — CLI column set is derived from DOC_STATUSES
- scripts/backfill_doc_id.py:77 → `AsyncPostgres.list_id_path()` (doc path map; stays an intake read)
- src/storage/chunk_repository.py:162 `aget_document_path` → `self._pg.get(...)`.path; :72 constructs `AsyncPostgres(graph=graph)`; consumed by src/mcp/tools_server.py:144
- src/storage/watch.py:95 `LEFT JOIN documents d ON d.id = e.doc_id` and :250 `d.path AS doc_path` — **a 7th `documents` reader the task brief does not list**; it joins only `documents.path`, so it survives the split but belongs in the import-boundary decision (src/storage is core, now reading an intake table)
- scripts/check_ingestion.py:36-44 `SELECT status, COUNT(*) FROM documents GROUP BY status` — **not in the brief's list**; breaks silently (always empty) once writes stop
- deploy/offline/loadtest/monitor.sh:10-17 — CSV header + `count(*) filter (where status=…)` over `documents` for all six statuses; breaks the same way
- scripts/wipe_db.py:90-94 `_PG_TABLES = ("documents", …)` with :106-112 `TRUNCATE TABLE <t>` catching ONLY `UndefinedTable` — see traps
- scripts/tg_ingest.py:98-127 `post_ingest` → POST {api_base}/api/v1/ingest (multipart; sends document_date, department, channel, group, priority, queue); :149/:200/:397 tally['skipped'] is its OWN counter, unrelated to doc status. Feeder that will start seeing 409s
- deploy/offline/webui/app.py:78-105 `POST /api/ingest` proxy → /api/v1/ingest; :108-112 `GET /api/ingest/{job_id}` proxy; :126-145 `GET /api/documents/{doc_id}` proxy (streams, passes `variant`)
- deploy/offline/webui/index.html:194 POST /api/ingest (reads `body.job_id`, `errText(body, r.status)` for non-2xx — a 409 body `{message,doc_id,intake_status}` renders through `errText`), :203-216 `STATUS_RU` map + `poll()` reading `b.status` / `b.error`; map has NO entry for `vector_only`/`skipped`/`rejected` → falls through to the raw string
- deploy/offline/agent-web/plugin-kb-ingest/index.js:53 POST {webui}/api/ingest, :61 GET {webui}/api/ingest/{jobId} (agent tools kb_ingest_file / kb_ingest_status)
- deploy/offline/loadtest/loader.py:70-84 POST /api/v1/ingest with department/priority/backfill; records `rec["ingest_status"]` = HTTP code — a 409 wave would look like a load-test failure
- docs/bruno/Ingestion/Upload Document.bru, docs/bruno/Ingestion/Get Job Status.bru, docs/bruno/Documents/Download Source.bru — the hand-run API collection
- src/api/routes/search_v2.py:126 and src/config.py:997 (`MONITOR_DOCUMENT_LINK` default `/api/v1/documents/{doc_id}`) and src/mcp/tools_server.py:537 — all depend on the documents path staying put (I7)
- src/workflow/activity_inputs.py:40,51 lists `SkipIn  # mark_skipped: AsyncPostgres` — the storage-touching-activity registry, guarded by tests/test_workflow/test_activity_graph_resolution.py
- src/workflow/activities/__init__.py:33,71,105 exports `mark_skipped`; src/workflow/document_ingest.py:148-172 is the only caller (short-circuit via `ClassifyIn(ctx, force=params.force)` at :153, `mark_skipped` at :164-172)
- src/workflow/ingest_submit.py:26 and src/config.py:21 and scripts/tg_ingest.py:56 import `src.ingest_queue.priorities` — a package move must keep `PRIO_LIVE`/`PRIO_BACKFILL` importable from src.config, which is imported by everything

### Данные

- Schema of record: all intake/processing tables live in the GRAPH schema (`public` for `default`, `g_<id>` otherwise) — src/storage/pg_schema.py:389-400 + src/storage/pg_scope.py:21-25 `SET search_path TO <schema>, extensions` (deliberately NO `public` on the path, R-P5). Global tables must be addressed as `public.<t>` explicitly.
- `public` holds: graphs, api_keys, tenants, schema_migration, bot_user, bot_request (scripts/setup_db.py:88-207 GLOBAL_DDL at :404-408). Confirmed — nothing else.
- `documents` columns today (src/storage/pg_schema.py:15-31): id, path, department, doc_type, status, error, summary, doc_date, source_channel, source_group, original_path, created_at, updated_at. Indexes: status, department, doc_date, source_channel, source_group.
- `documents.status` CHECK is declared TWICE — inline at :21-22 and as the idempotent DROP/ADD `documents_status_check` at :45-48. Both must change together or an old deployment keeps the stale domain.
- `AsyncPostgres.get` is `SELECT * FROM documents` (src/storage/postgres.py:181) and `DocumentRow.from_dict` (:46-59) indexes `row["status"]`, `row["error"]`, `row["summary"]` by hard key (only `original_path` uses `.get`). After the split those three come from `doc_processing` — a LEFT JOIN whose right side is NULL for a rejected document will KeyError-free but produce `None`, and `row["status"]` on a rejected doc has no value at all. Pick the merged shape deliberately.
- Writers of `documents.status`: src/api/routes/ingest.py:191 (pending, via the literal `'pending'` baked into the INSERT at postgres.py:107-109), fetch_source.py:33 (processing), finalize.py:49 (completed|vector_only), :182 (skipped), :214 (failed). Confirmed complete.
- One-off migration machinery: `public.schema_migration(name PK, applied_at)` created in _TENANTS_DDL (scripts/setup_db.py:153-156); the only existing step is `authz_grandfather_v1` (:219-245), read-then-write with `ON CONFLICT (name) DO NOTHING`, called from `_bootstrap_registry` (:255) — i.e. ONCE, globally, not per graph.
- `migrate_graph_schema` has TWO callers: scripts/setup_db.py:422 (loop over `_ready_graphs`, which always prepends `default` — :426-441) and src/workflow/graph_lifecycle/activities.py:126 `_pg_provision_sync` (brand-new graph, inside the provisioning workflow). Both run on autocommit connections (setup_db.py:415, activities.py:119).
- PROD DATA NOT CHECKED: no mongodb MCP is exposed in this session, and the kb-search / kb-tools MCP servers both failed with ECONNREFUSED. The corpus lives in Postgres, not Mongo, so the relevant shapes (how many rows carry `status='skipped'`, how many graphs exist, whether `g_<id>` schemas have documents) need either a live psql read or the user's go-ahead. Everything above is read from source, not from the database.

### Существующие тесты

- tests/test_storage/test_pg_schema.py::test_migrate_creates_schema_then_runs_graph_ddl — asserts `len(stmts) == len(pg_schema.GRAPH_DDL) + 3` and `stmts[-1] == "RESET search_path"`; its `_Cur.fetchall` (:14-15) returns table-name tuples
- tests/test_storage/test_pg_schema.py::test_graph_tables_cover_core_tables — the natural home for the spec §5 `doc_processing in graph_tables()` guard
- tests/test_storage/test_pg_schema.py::test_missing_graph_tables_reports_absent / ::test_missing_graph_tables_empty_when_complete / ::test_setup_db_reexports_moved_names
- tests/test_scripts/test_setup_db_graph_schema.py::test_migrate_new_graph_creates_schema_and_scopes_ddl — asserts `cur.sql[2:2+len(GRAPH_DDL)] == GRAPH_DDL` and `cur.sql[-1] == "RESET search_path"`; its `_Cur` (:5-10) has NO fetchone/fetchall at all
- tests/test_scripts/test_setup_db_graph_schema.py::test_graph_ddl_contains_every_graph_table_and_no_global_one, ::test_migrate_default_graph_does_not_create_public
- tests/test_scripts/test_setup_db_authz.py (guards `_FULL_SCOPES_SQL` vs `authz.Action` drift — the pattern a new migration marker should copy)
- tests/test_api/test_ingest.py (6 cases: 202 + insert_pending path, 503 on S3Error, auth, etc.), test_ingest_backfill.py, test_ingest_group.py, test_ingest_original.py, test_ingest_priority.py, test_ingest_source_channel.py — ALL patch the literal string "src.api.routes.ingest.build_minio_storage" / "src.api.routes.ingest.get_temporal_client" (e.g. test_ingest.py:46,51), so the module move breaks every one of them by patch target, not by behaviour
- tests/test_api/test_documents.py (6 cases over GET /api/v1/documents/{doc_id}, variants + auth)
- tests/test_api/test_route_actions.py::EXPECTED — the route→action matrix at :25-50 keyed by (method, path); it walks `src.api.main.app`, so it passes unchanged iff paths and dependencies are preserved. This is the guard that POST /ingest stays `write` and GET /documents stays `download_original`
- tests/test_api/test_graph_binding.py:230-249 (403 matrix incl. /api/v1/ingest and /api/v1/documents/…), :259 patches `status_counts_by`
- tests/test_api/test_graph_dep_authz.py:97, tests/test_mcp/test_current_graph.py:228, tests/test_mcp/test_tools_server.py:149,180 — patch `status_counts_by` / `timeline_counts` on AsyncPostgres by attribute name
- tests/test_api/test_stats_routes.py:25-26,72 and tests/test_scripts/test_message_stats_cli.py:13,22 — fixture rows carry explicit `"skipped": 0`; they pin the StatRow shape
- tests/test_workflow/test_finalize.py:25-143 (four cases asserting `pg.update_status.assert_awaited_once_with(...)` for completed / vector_only / skipped / failed)
- tests/test_workflow/test_fetch_source.py:35,58,66,96 — asserts `update_status(..., status="processing")`
- tests/test_workflow/test_document_ingest_workflow.py (classifier short-circuit + vector_only downgrade at :183,:216)
- tests/test_workflow/test_graph_lifecycle_activities.py:174-210 — `_PgCur` keys off the literal `"FROM documents"` in the SQL and `fetchone()` returns `("documents",)`; parametrised test_inflight_doc_ids_tolerates_missing_schema
- tests/test_storage/test_insert_pending_source.py (live PG), tests/test_storage/test_message_stats_queries.py (live PG, INSERT INTO documents at :57), tests/test_scripts/test_setup_db_source_columns.py:55-61 (live PG), tests/test_workflow/test_workflow_local.py:66,118 (live stack, INSERT INTO documents … 'pending')
- tests/test_storage/test_document_original_path.py (DocumentRow.from_dict shape), tests/test_storage/test_chunk_repository.py:64-70 (fake `get` returning a DocumentRow)
- tests/test_ingestion/test_classifier.py:10,55 and tests/eval/classifier_scenarios.py:14 — import `src.ingestion.classifier` directly
- tests/test_ingest_queue/{test_consumer,test_consumer_graph,test_publisher,test_topology}.py — import `src.ingest_queue.*` by path
- tests/test_scripts/test_wipe_db.py, tests/test_scripts/test_tg_ingest*.py (5 files), tests/test_offline_webui/test_webui_app.py:60,90,105
- tests/test_no_neo4j.py — the existing whole-tree arch test; the model for the new tests/test_intake/test_boundaries.py import guard

### Ловушки

- **`public.schema_migration.name` is a single global PRIMARY KEY, but `intake_split_v1` must run per graph schema.** A bare marker named `intake_split_v1` makes the migration run for the FIRST graph only (`_ready_graphs` is ordered `default` first) and silently skip every other schema. The marker must be per schema (e.g. `intake_split_v1:<pg_schema>`), or the table needs a second key column. The existing `authz_grandfather_v1` precedent (scripts/setup_db.py:219-245) is global and does NOT generalise.
- **Two statement-count tests break the moment anything is added to `migrate_graph_schema`.** tests/test_storage/test_pg_schema.py:46 asserts `len(stmts) == len(GRAPH_DDL) + 3`; tests/test_scripts/test_setup_db_graph_schema.py:29-30 asserts the GRAPH_DDL block sits at `cur.sql[2:2+len]` and `RESET search_path` is last. Worse, the two fake cursors disagree: test_pg_schema's `_Cur.fetchall()` returns table-name tuples (so a `SELECT 1 FROM public.schema_migration` guard reads as 'already applied' and the migration never runs under test), and test_setup_db_graph_schema's `_Cur` has no `fetchone`/`fetchall` at all (AttributeError). Both fakes need extending before the migration can be TDD'd.
- **`scripts/wipe_db.py:106-112` will start failing.** `doc_processing.doc_id UUID … REFERENCES documents(id) ON DELETE CASCADE` makes `TRUNCATE TABLE documents` raise `cannot truncate a table referenced in a foreign key constraint` — a `FeatureNotSupported`, while the loop only catches `UndefinedTable`. Fix: add `doc_processing` to `_PG_TABLES` (:90-94) before `documents`, or truncate both in one statement / use CASCADE.
- **`src/api/routes/stats.py:30-38 StatRow` requires `skipped: int`.** Dropping `skipped` from `DOC_STATUSES` (src/storage/postgres.py:22-24) makes `status_counts_by` emit rows without the key → pydantic ValidationError → 500 on `GET /api/v1/stats/messages`. The same dicts feed the MCP tool (tools_server.py:676) which is schema-free and would silently change shape instead, and `scripts/message_stats.py:25` which derives its columns from DOC_STATUSES. Decide the three surfaces together; the spec's §3.3 list omits stats.py entirely.
- **Two readers of `documents` the brief does not list.** `src/storage/watch.py:95,250` LEFT JOINs `documents` for `d.path AS doc_path` (entity-watch feed — a core module reaching into an intake table, which the §3.2 import rule has to rule on explicitly), and `scripts/check_ingestion.py:37` + `deploy/offline/loadtest/monitor.sh:14-17` aggregate `documents.status` directly and will quietly report all-zeros once writes stop.
- **`AsyncPostgres.get` is `SELECT *` and `DocumentRow.from_dict` reads `row["status"]` by hard key** (postgres.py:46-59; only `original_path` uses `.get`). A classifier-rejected document has NO `doc_processing` row by design (spec §1.4), so the merged read must COALESCE to something — otherwise `GET /documents/{id}` and `chunk_repository.aget_document_path` KeyError or return `status=None` for exactly the rows the spec wants to make visible.
- **`insert_pending` hardcodes `'pending'` in the SQL text** (postgres.py:107-109: `INSERT INTO documents (…, status) VALUES (…, 'pending')`), so 'stop writing documents.status' (I8) means editing the INSERT, not just the callers — and the column stays `NOT NULL DEFAULT 'pending'`, so leaving it out is safe but the CHECK still accepts 'skipped' until a later step.
- **The 409 is doubly dead, so there is no existing behaviour to preserve.** ingest.py:245 catches `WorkflowAlreadyStartedError` from `submit_document`, but the temporal branch uses `WorkflowIDConflictPolicy.USE_EXISTING` on the fixed id `ingest-scheduler` (ingest_submit.py:52-66) and the rabbitmq branch just publishes (:45). The per-document id is minted in the worker (ingest_scheduler.py:146, consumer.py:67). Reusing that `except` block for the dedup 409 would be misleading — the duplicate check belongs before `put_object`, and the dead handler should be left alone or removed deliberately.
- **`force` ≠ `on_duplicate`, and the two source documents disagree.** The spec (§2.2, I4) says they are orthogonal and must not be merged; the older plan docs/superpowers/plans/2026-10-17-project-boundaries.md §4 step 1.2 says `force=true` на дубль maps to `on_duplicate=version`. The spec is the newer approved document — follow it, but say so in the plan so the stale plan line is not re-implemented.
- **`graph_lifecycle/activities.py:152-166` probes `to_regclass('documents')` before querying.** Moving the in-flight query to `doc_processing` means the probe must move too, or a half-migrated schema (documents present, doc_processing absent) raises UndefinedTable on every delete retry. The guarding test keys off the literal string `"FROM documents"` (tests/…/test_graph_lifecycle_activities.py:180).
- **Package moves break tests by patch target, not by behaviour.** Every tests/test_api/test_ingest*.py patches the string `"src.api.routes.ingest.build_minio_storage"` / `".get_temporal_client"`. Also `src/config.py:21` imports `src.ingest_queue.priorities` — src.config is imported by essentially everything, so moving that module to src/intake/queue/ puts an intake import at the root of the core import graph and will trip the very arch test the spec asks for (§3.2) unless `priorities` stays put or config stops importing it.
- **Temporal determinism.** `document_ingest.py:148` branches on `params.classifier_enabled`, snapshotted in the route (ingest.py:~205 `classifier_enabled=settings.classifier.enabled`). Any new intake flag must be snapshotted the same way — never read inside `@workflow.run`. And `mark_skipped` is a registered activity name (activities/__init__.py:33,71,105; workflow calls it by the string `"mark_skipped"` at document_ingest.py:165): changing what it writes is fine, renaming it is a replay break for in-flight histories.
- **MinIO is not transactional with Postgres.** On `on_duplicate=replace` the spec keeps the old objects (deliberate). On `reject` nothing is written — which is only true if sha256 is computed and checked strictly before line 159, including before the optional `original` upload at :171.
- **The unique index is partial** (`WHERE content_sha256 IS NOT NULL`), so historical rows never collide — but it also means a concurrent double-POST of the same body can both pass a SELECT-then-INSERT check. The INSERT must rely on the index (catch `UniqueViolation`) rather than a read-then-write, or two simultaneous uploads both get 202.
- **Known-good background, not regression:** 13 suite failures today (need a live RabbitMQ; the root `.env` overrides settings defaults). Several tests in the blast radius are live-PG integration tests (test_insert_pending_source.py, test_message_stats_queries.py, test_setup_db_source_columns.py, test_workflow_local.py) and will SKIP or fail without the stack — do not read that as the migration being wrong.
- **Prod/live data was NOT inspected.** No mongodb MCP in this session; kb-search and kb-tools MCP both ECONNREFUSED. The row counts that decide whether `intake_split_v1` is cheap or long (how many `documents` rows, how many `status='skipped'`, how many `g_<id>` schemas) are unknown and need a live read under the user's standing approval rule.
