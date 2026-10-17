# Offline-развёртывание на srv01/02/03 — журнал этапов

Серверы: srv01 10.10.113.11 · srv02 10.10.113.12 · srv03 10.10.113.13 (user `pitcher`, без sudo, без интернета)
Папка на серверах: `~/offline/{debs,images,models,stack}`
Статусы: ✅ сделано · 🔄 в работе · ⏳ ожидает · ❌ ошибка

## Этап 1 — копирование (Claude, без sudo)

| # | Шаг | Статус | Детали |
|---|-----|--------|--------|
| 1.0 | Подготовка: чистка build cache мака, папки на серверах, проверка srv01→srv02/03 по ssh | ✅ | освобождено 39.2 ГБ; fan-out srv01→02/03 работает (ssh -A) |
| 1.1 | .deb пакеты (docker-ce 29.8.2, containerd 2.3.6, compose 5.6.0, pigz, chrony, rdma-core/opensm, ipmitool) | ✅ | 28 пакетов (102 МБ) в ~/offline/debs на srv01; 11 обновлений уже установленного — в optional-upgrades/ (ставить не обязательно) |
| 1.2 | Docker-образы инфраструктуры (amd64) | ✅ | 15/15 в ~/offline-kb-stage/images (~1.9 ГБ zstd); MinIO — локальный amd64 |
| 1.3 | Docker-образы приложения (linux/amd64) | ✅ | kb-app:offline 1.0 ГБ, kb-app-rerank:offline 4.4 ГБ + офлайн-слой (NLTK stopwords/punkt_tab, HF_HUB_OFFLINE). Проверено в `--network none`: импорты всех ролей, reranker bge-v2-m3 считает |
| 1.4 | Модели GGUF | ✅ | gemma-4-E4B Q4_K_M 5.0 ГБ, Qwen3-30B-A3B Q4_K_M 18.6 ГБ, bge-m3 FP16 1.2 ГБ, nomic f16 0.3 ГБ — sha256 совпали с HF |
| 1.5 | Стек: исходники, compose по серверам, litellm config, .env шаблон | ✅ | deploy/offline/stack/: docker-compose.srv0{1,2,3}.yml (override к prod, `compose config` валиден), litellm_config.offline.yaml, .env.offline.example; deploy/offline/sudo-setup.sh |
| 1.6 | Заливка мак→srv01 → раздача srv01→srv02/03 + SHA256SUMS | ✅ | 28 ГБ на каждом сервере в ~/offline, sha256 сошлись везде (images/models/debs/stack); `apt-get -s` на srv02: 28 пакетов из локальных .deb, удаляется только systemd-timesyncd |

## Этап 2 — команды с sudo (пользователь)

| # | Шаг | Статус |
|---|-----|--------|
| 2.0 | Запустить sudo-setup.sh на каждом сервере | ✅ | 1-я попытка на srv01 упала (apt offline: «Pathname not absolute»), скрипт переделан на dpkg -i; затем прошёл на всех трёх |
| 2.1 | hostname srv02 → ext22-srv02 | ✅ | srv02 теперь ext22-srv02 |
| 2.2 | маска /23 на srv03 — проверить netplan | ⚠ | маска /23 на srv03 осталась — согласовать с сетевиками (скрипт не менял) |
| 2.3 | NTP: chrony-сервер на srv01, клиенты srv02/03 | ✅ | srv01 = stratum 8 (local), srv02/03 синхронизированы с ним, смещение < 1 мкс…100 мкс |
| 2.4 | установка .deb, pitcher в группу docker | ✅ | 28 пакетов, dpkg --audit чистый, pitcher в группе docker |
| 2.5 | /etc/docker/daemon.json, sysctl, limits | ✅ | daemon.json, sysctl применены |
| 2.6 | (опц.) opensm, storcli | ✅/⏳ | opensm активен (IB State Active, 100 Гбит/с, IPoIB не настроен); storcli нет — диски за RAID неизвестны |

## Этап 3 — запуск (Claude)

| # | Шаг | Статус |
|---|-----|--------|
| 3.1 | docker load на всех серверах | ✅ | 17 образов на каждом |
| 3.2 | запуск стека по раскладке, smoke-тест | ✅ | все сервисы Up/healthy на 3 серверах; small/large/bge-m3 отвечают через litellm; тестовый документ: ingest 3 мин (10 сущностей, 7 связей), поиск local 15 с — ответ верный со ссылкой |

## Лог
- 2026-10-03 — старт этапа 1. Решения: без Wikibase; NTP-сервер поднимаем на srv01; build cache мака почищен.
- 2026-10-03 08:43 — обрыв VPN до 10.10.113.x (ssh timeout) посреди прямой заливки; на srv01 успели .deb. Заливка прервана.
- 2026-10-03 21:25 — схема изменена: всё сначала качается на мак в `~/offline-kb-stage/` (debs/images/models), потом `rsync -P` (докачка после обрыва) на srv01 и раздача srv01→srv02/03. Серверы пока недоступны (VPN).
- 2026-10-03 21:41 — MinIO больше не публикует образы (docker.io и quay.io: access denied). Взят локальный amd64 `minio/minio:latest` (2025-09-07) с мака. Инфраструктурные образы: 14/15 готово, остались litellm + llama.cpp.
- 2026-10-03 21:45 — VPN снова поднят, запущена заливка на srv01 (rsync --partial, 60 попыток).
- ⚠ Прод-конфиг litellm использует облачные модели (gemma4:31b-cloud, deepseek-v4-flash:cloud) — офлайн недоступны. Офлайн: small=gemma-4-E4B (srv03), large=Qwen3-30B-A3B (srv02). Риск: отчёт по корневому сообществу (~390k токенов) не влезет в контекст локальных моделей.
- 2026-10-04 10:15 — модели и образы на маке готовы. Заливка на srv01 перезапущена (openrsync без --append-verify). Сборка приложения перезапущена.
- 2026-10-04 10:55 — Этап 1 завершён. Найдено и исправлено: llama-index тянет NLTK из интернета при старте → докачано в образ (deploy/offline/Dockerfile.offline). apt в офлайне лез в репозиторий → sudo-setup ставит с отключёнными источниками. Часы серверов совпадают с маком (<1 с).
- 2026-10-04 11:45 — Этап 2 завершён на всех трёх серверах; NTP синхронизирован, образы загружены (17/17).
- 2026-10-04 12:05 — Этап 3 завершён. Исправлено по ходу: llama.cpp `--no-mmap` → `--load-mode none` (новая сборка); `--reasoning off` для gemma; API preflight требовал NEO4J_PASSWORD (Neo4j не используется) → случайный секрет в .env.offline; Grafana падала на macOS `._*` файлах из tar → удалены. Пароли сгенерированы на srv01 (`openssl rand`), .env.offline 600 на всех трёх.
- Известное: при первом ingest поиск один раз попал в `entity_er_vec` до её загрузки (Milvus «collection not loaded») — разовая гонка, коллекция загружена.

## Как управлять
- Каталог: `~/offline/stack` на каждом сервере; проект compose `-p kb`.
- `C="docker compose -p kb -f docker-compose.prod.yml -f deploy/offline/stack/docker-compose.srvNN.yml --env-file deploy/offline/stack/.env.offline"` → `$C ps`, `$C logs -f <svc>`, `$C restart <svc>`.
- Порядок старта после перезагрузки: srv01 → srv02 → srv03 (restart: unless-stopped поднимет сам, но app на srv02 ждёт srv01).
- Точки входа (srv02): API :8000 (X-API-Key = API_KEYS), MCP :9001/:9002/:9003, litellm :4000, Temporal UI :8080, Grafana :3001, Prometheus :9092. srv01: RabbitMQ UI :15672, MinIO console :9101.
- 2026-10-04 12:30 — По решению пользователя `small` переключён с gemma-4-E4B на **Qwen3-30B-A3B** (srv03, 2 инстанса × 6 слотов). Теперь small и large — одна модель. gemma GGUF остаётся в /opt/models.
- 2026-10-04 13:50 — Бенчмарк Qwen3-30B-A3B Q4_K_M на srv03 (llama.cpp CPU, 20 потоков/сокет):
  - короткий промпт: 1 поток 25 ток/с генерации; 6 параллельно на инстанс 52 ток/с суммарно; 12 на 2 инстанса 102 ток/с суммарно.
  - промпт 5.7k без кэша: префилл 81 ток/с (~70 с), генерация 13.6 ток/с; 12 параллельно — 563 с, упор в префилл (~120 ток/с суммарно).
  - ingest-подобный (общий префикс 4.7k в кэше + 825 новых токенов): 1 поток 28.6 с на вызов (префилл 825 ток ~13 с + 256 ток генерации); 12 параллельно 169 с (≈14 с srv03-времени на вызов).
  - ⚠ слот = 8192 токена (49152/6): префикс 4.7k + чанк 0.8k оставляют ~2.7k на ответ.
- 2026-10-04 14:05 — srv03: по решению пользователя 2 инстанса Qwen × **1 слот**, ctx 32768 (нет обрезки ответа); worker-llm LLM_POOL_N=2.

## Этап 4 — docs2md + веб-интерфейс

| # | Шаг | Статус | Детали |
|---|-----|--------|--------|
| 4.1 | Образ doc2md (из ~/projects/docs2md, linux/amd64) | ✅ | 392 МБ; проверен в `--network none`: docx/xlsx/pptx/pdf-текст ок, скан → 503 |
| 4.2 | docs2md на srv01 (сокет 1), `:8070`, OCR выключен | ✅ | решение 2026-10-04: без OCR |
| 4.3 | Веб-интерфейс на srv02 `:8090` (deploy/offline/webui, образ kb-app:offline) | ✅ | вкладки «Загрузка» и «Поиск»; без логина в LAN; API-ключ на сервере |
| 4.4 | E2E: sample.docx → md → ingest → поиск | ✅ | конвертация мгновенно, ingest ~3 мин, поиск 14 с, ответ верный |

- Перед ingest из md вырезаются ссылки на картинки `assets/img_N` (файлов в базе нет), подпись остаётся.
- 2026-10-04 15:30 — Документ `6.md` (29 чанков) висел в extract_kg 25+ мин: **все вызовы LLM падали по таймауту клиента 60 с** (LITELLM_TIMEOUT_S по умолчанию), а генерация одного ответа на CPU 60–100 с (860–1364 ток при ~14 ток/с) → 16 таймаутов, 0 успешных, бесконечные повторы. Исправлено: LITELLM_TIMEOUT_S=900, LITELLM_MAX_RETRIES=1 (srv02 app + srv03 worker-llm), воркеры пересозданы.
- 2026-10-05 — Проверка качества извлечения на `7.md` (обвинительное заключение, 29 чанков, 44 мин, 0 таймаутов): полнота ключевых фактов высокая (7/7 лиц, 5/5 карт, 4/4 суммы, 3/3 эпизода кражи с интервалами, номер дела, статья, авто); проблемы — дубли лиц (12 узлов на 7 человек, ошибки рода «Кузнецов/Хасанов»), обрезанная закрывающая «» (баг `lightrag_parse.py:39` strip("«»")), утечка примера из промпта («ООО Ромашка»), водитель Омармагомедов ошибочно PARTICIPATED_IN в краже, развёрнутые связи, 78 мелких событий, даты в двух форматах.
- 2026-10-05 — Исправления качества извлечения (TDD, код в ветке a-tsitanov/bik, НЕ закоммичено):
  1. `src/graph/lightrag_parse.py` `_clean_raw_name`: снимаются только кавычки, обрамляющие ВСЁ имя («ПАО «Детский мир»» больше не теряет закрывающую »).
  2. Новый фильтр `drop_prompt_example_entities` + `prompt_example_entity_names`: сущности из few-shot примеров промпта, которых нет в тексте чанка («ООО «Ромашка»»), отбрасываются вместе со связями; подключён в `lightrag_extract.py` (шаг 2c).
  - Тесты: +13 новых; полный прогон — 53 падения, идентичны чистому HEAD (инфраструктурные/wikibase-flake), регрессий нет.
- 2026-10-05 — **Применено переключение на GPU vLLM** (10.10.151.15:8000, deepseek-v4-flash, thinking off): small и large → GPU, Qwen3-30B-A3B CPU остались fallback (small-cpu srv03, large-cpu srv02). litellm перезапущен, worker-llm пересоздан (LLM_POOL_N=8). Проверено: заголовок x-litellm-model-api-base = GPU для small/large, 150 токенов за 0.7–0.8 с, поиск 9.8 с (было 15 с). VPN с мака видит только srv01, srv02/03 — через ssh -J srv01.
- 2026-10-05 — Для `large` (только роль synthesis = финальный ответ) включены размышления (thinking=true); `small` без размышлений. vLLM отдаёт мысли в reasoning_content, content чистый. Поиск: ответ полный, 13.1 с (без размышлений было 9.8 с).
- 2026-10-05 18:06–18:23 UTC — первая пачка на GPU: 13 .md, все completed, 0 failed, 16 мин 39 с на всю пачку (K=4); ~250 чанков, ~2.5k сущностей, ~3.6k связей. 3.md шёл дольше всех (16.6 мин): фаза ER 15 мин без логов — НЕ зависание, закончилась сама; перезапуск kb-worker-1 в 18:29 был лишним (вреда нет). Известное: ER не подгружает канонические сущности из прошлых документов (nebula structured_query без параметров).
- 2026-10-05 18:36 UTC — **Инкрементальный ER починен**: AGENT_ER_USE_NATIVE_VECTOR_KNN=true в .env.offline (prod compose по умолчанию ставил false → ER шёл в Cypher-окно, которое на Nebula падает). База полностью очищена (scripts/wipe_db.py --keep-wiki). Тест: док B (варианты имён) слил 5/5 сущностей с уже записанными из дока A (Ковалева А.А., ООО «ДИАМАНД», МУ МВД, Северные Сети, Петров И.С.); entity_er_vec заполняется. В базе сейчас только 2 тестовых документа.
- 2026-10-05 18:45 UTC — 2 тестовых документа удалены (повторный wipe). База пустая, готова к загрузке пользователем.
- 2026-10-05 — Ваши 13 документов: completed 13/13 (18:46–18:56 UTC, ~10 мин), ER между документами работает (~50 слияний с уже записанными, 0 ошибок).
- 2026-10-05 — **DeepSeek Harness (dsh 0.2.0-rc.2) web на srv01**: образ dsh-web:offline (deploy/offline/dsh/: Dockerfile, entrypoint.sh, cordis.patch.yml), сервис dsh-web в docker-compose.srv01.yml. Модели: провайдер kb-litellm → litellm srv02 (large = deepseek-v4-flash с размышлениями, по умолчанию; small — без), облачные DeepSeek-маршруты отключены. MCP: kb_search/kb_tools/kb_stats (srv02 :9001-9003, Bearer KB_MCP_TOKEN). network_mode: host, слушает ТОЛЬКО 127.0.0.1:3080 (dsh запрещает 0.0.0.0: нет защиты от RCE, у агента bash). Вход: ssh -N -L 3080:127.0.0.1:3080 pitcher@10.10.113.11 + ссылка с token из docker logs kb-dsh-web-1. Телеметрия отключена (DSH_TELEMETRY_DISABLED=1).
- 2026-10-05 — **Плагин dsh-kb-ingest** (deploy/offline/dsh/plugin-kb-ingest, чистый JS): /kb-ingest [ГГГГ-ММ-ДД] с вложениями, /kb-status [job_id…], инструменты агента kb_ingest_file/kb_ingest_status; ходит в webui srv02 /api/convert → /api/ingest. Ставится entrypoint'ом в node_modules профиля web (загрузчик dsh резолвит только свои deps + объявленные deps профиля). Проверено в контейнере на srv01: плагин активируется, конвертация 200, неизвестный job → 404 с текстом, картинка → 503 ocr_unavailable. Реальный ingest через UI — за пользователем (тестовый документ в боевую базу не грузили).
- 2026-10-05 — dsh: отключить вход штатно нельзя (каждый RPC требует подписанный cookie). Сделано: cookieMaxAgeDays=365 (patch на запись connection). Проверено: cookie переживает перезапуск контейнера (секрет в /data/dsh/.credentials.yaml): со старым cookie 200, без cookie 401. Ссылка с токеном нужна один раз на браузер в год.
- 2026-10-06 — dsh доступен по LAN: http://10.10.113.11:3080 через lan-proxy (L4-прокси в контейнере, белый список LAN_ALLOW=10.10.0.0/16, переопределяется DSH_LAN_ALLOW в .env.offline); сам dsh по-прежнему на 127.0.0.1, авторизация токен/cookie сохранена (--trusted-host 10.10.113.11:3080). Проверено с мака: токен 303, cookie 200, без cookie 401. Туннель больше не нужен.
- 2026-10-08 — **.31 как постоянный шлюз в кластер:** VPN BIBB на .31 (deploy/offline/remote-access/setup-bibb-vpn.sh, split-tunnel). Через VPN отвечает только srv01 → добавлен сервис llm-proxy на srv01 (10.10.113.11:4000 → srv02:4000, белый список 10.10.0.0/16). Стек agent_v2 на .31 переведён на модели кластера (litellm_config.cluster.yaml), Ollama на .31 больше не нужен; эмбеддинги совпадают (cos=1.0). ⚠ одна VPN-учётка: пока .31 подключён, мак без доступа к кластеру.
- 2026-10-14 — **Ребрендинг веб-агента: dsh-web → agent-web** (раскатано на srv01 2026-10-14: kb-agent-web-1, тома kb_dsh_* сохранены): каталог deploy/offline/dsh → deploy/offline/agent-web (git mv), образ `agent-web:offline`, сервис `agent-web` (контейнер kb-agent-web-1), env AGENT_TRUSTED_HOST / AGENT_LAN_ALLOW (старые DSH_* тоже читаются). Бренд — build-arg BRAND_NAME (по умолч. «KB Ассистент») / BRAND_SHORT («KB»): `brand/rebrand.mjs` при сборке правит title, manifest, favicon, строки UI («DeepSeek Harness», «DSH»), идентичность в системном промпте, префикс лога («agent web: …?token=»); guard в Dockerfile валит сборку, если «DeepSeek Harness» остался. Сайдбар (знак+имя) и знак на пустом чате — плагин `kb-brand` (plugin-brand/), `ui-brand-official` отключён в cordis.patch.yml. Тома остаются `kb_dsh_data` / `kb_dsh_workspace` (явные `name:` в compose) — сессии, workspace и .credentials.yaml (cookie) сохраняются. llm-proxy переведён на образ agent-web и берёт /opt/dsh/lan-proxy.mjs из образа (bind-mount убран). Внутренние id (__DSH_*__, cookie dsh-auth-*, @deepseek-ai/*, DSH_HOME) не трогаются. Остались строки про «DeepSeek»-аккаунт (провайдер отключён) и слоган пустого чата «Into the Unknown».
- 2026-10-14 — **GPU-узел .15 выведен из LiteLLM** (сервер отключают): удалены small-gpu15/large-gpu15, fallbacks small→small-cpu, large→large-cpu→small-cpu, context_window_fallbacks убраны. vLLM на .14 поднят до 131k контекста (MAX_LEN в vllm.service), веб-агент показывает модели как Qwen3.6-35B-A3B (contextWindow 131072). Бэкап конфига на srv02: litellm_config.offline.yaml.bak-20261014.
- 2026-10-14 — **Русификация интерфейса agent-web**: плагин `kb-locale-ru` (deploy/offline/agent-web/plugin-locale-ru): регистрирует язык ru (запасной — en) и ru-словари для 52 пространств имён UI (2113 ключей, выгружены из рантайма, переведены, плейсхолдеры {…} сверены). Русский — язык по умолчанию, явный выбор пользователя в настройках сохраняется и имеет приоритет. Проверено в собранном образе: lang=ru, сайдбар, пустой чат, экран «Предварительная версия», настройки — на русском. Не переведено: пространства имён, которые в web не грузятся (settings.account, schedule, браузер боковой панели, экспериментальные), и строки, зашитые в код вне системы локалей.
- 2026-10-14 — **Хранение и скачивание оригинала** раскатано на srv02: новый kb-app:offline (api; откат — kb-app:rollback-20261014), setup_db добавил documents.original_path, webui (app.py/index.html, бэкапы *.bak-20261014) пересоздан. Проверено вживую: 1.docx через webui → original_path s3://kb-uploads/<id>/original/1.docx; GET /api/documents/<id> отдаёт тот же .docx (sha256 совпал, верный content-type), ?variant=text — .md; у старых документов по умолчанию .md, variant=original → 404. Воркер, consumer, MCP не пересоздавались.
- 2026-10-15 — **Наблюдение за сущностями** раскатано: kb-app/kb-app-rerank на srv02 и kb-app на srv03 собраны патчем поверх прежних образов (откат — `:rollback-20261015`), setup_db создал 7 таблиц (`watch`, `entity_mention`, `edge_new`, `watch_event`, `watch_seen`, `monitor_cursor`, `risk_snapshot`), `MONITOR_ENABLED=true`, sweep каждые 5 мин. Заодно исправлен сброс `watched`/риска/вики при повторном упоминании сущности. Проверено вживую: подписка на «Блинов Андрей Степанович» → тестовый документ → через ≤6 мин в `kb_watch_feed` карточка: new_mention, new_connection (Кравцов О.И., ломбард, цепочка), new_identifier (+79035551234), new_event ×2.
