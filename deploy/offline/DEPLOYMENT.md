# Офлайн-кластер базы знаний — отчёт о развёртывании

**Состояние на:** 2026-10-06
**Серверы:** ext22-srv01 / srv02 / srv03 (10.10.113.11–13)
**Код развёртывания:** `deploy/offline/` (локальный `main`, коммит `4003f86`)
**Журнал этапов (хронология):** [`PROGRESS.md`](PROGRESS.md)
**Схема:** [`architecture.svg`](architecture.svg) (исходник [`architecture.d2`](architecture.d2))

---

## 0. Коротко

- Полный стек базы знаний (ingest → граф + векторы → поиск → MCP) развёрнут на **трёх серверах без GPU и без доступа в интернет**.
- Всё работает в Docker, единый compose-проект `kb` поверх `docker-compose.prod.yml`, для каждого сервера свой override.
- **LLM:** основная модель — `deepseek-v4-flash` на внешнем GPU-узле `10.10.151.15` (vLLM). Через LiteLLM к ней идут оба алиаса приложения:
  - `small` — без размышлений;
  - `large` — с размышлениями.
- **Запасной путь LLM:** CPU-модели Qwen3-30B-A3B (llama.cpp) на srv02 и srv03, включаются автоматически, если GPU недоступен.
- **Embeddings:** `bge-m3` (размерность 1024) на CPU srv01.
- **Интерфейсы:**
  - веб-форма загрузки и поиска — `http://10.10.113.12:8090`;
  - агент DeepSeek Harness с инструментами базы знаний — `http://10.10.113.11:3080`;
  - MCP-серверы — `10.10.113.12:9001–9003`.
- **Данные на 2026-10-06:** 14 документов (`completed`), 265 чанков в Milvus, 1327 канонических сущностей в индексе ER.

---

## 1. Железо и ОС

Три одинаковых блейд-сервера.

| Параметр | Значение |
|---|---|
| Платформа | Supermicro SuperBlade SBI-4129P-C2N, плата B11DPT, BIOS AMI 4.2 (27.12.2023) |
| CPU | 2× Intel Xeon Gold 5218R (20C/40T, 2.1/4.0 ГГц): 40 ядер / 80 потоков, 2 NUMA-узла |
| Инструкции | AVX-512, AVX512-VNNI (нет BF16 и AMX) |
| RAM | 256 ГБ = 16× 16 ГБ DDR4, по 125 ГБ на сокет |
| Диск | RAID LSI MegaRAID SAS-3 3108, виден один том 223 ГБ (LVM `/` 217 ГБ). Физические диски за RAID неизвестны: нет `storcli` |
| Сеть | Intel X722 2×10G (`eno1np0` up 10G, `eno2np1` down); Mellanox ConnectX-4 InfiniBand 100G EDR |
| GPU | нет |
| ОС | Ubuntu 24.04.2 LTS, ядро 6.8.0-146-generic |
| Интернет | нет (пакеты и образы привозились с мака) |

**Загрузка на 2026-10-06:**

| Сервер | Диск `/` | RAM |
|---|---|---|
| srv01 | 88 / 217 ГБ (43%) | 10 / 250 ГБ |
| srv02 | 94 / 217 ГБ (46%) | 38 / 250 ГБ |
| srv03 | 84 / 217 ГБ (41%) | 55 / 250 ГБ |

---

## 2. Сеть и доступ

### Адреса

| Сервер | IP | Hostname | Роль |
|---|---|---|---|
| srv01 | 10.10.113.11/24 | ext22-srv01 | данные + embeddings + docs2md + dsh |
| srv02 | 10.10.113.12/24 | ext22-srv02 | приложение + поиск + LiteLLM + webui |
| srv03 | 10.10.113.13/**23** | ext22-srv03 | LLM для ingest (worker-llm + CPU-резерв) |
| GPU-узел | 10.10.151.15 | — | vLLM `deepseek-v4-flash` (развёрнут отдельно) |

- Шлюз — `10.10.113.1`, DNS — `10.10.113.1`.
- ⚠ Маска `/23` на srv03 отличается от остальных. Скрипт её не трогал, нужно согласовать с сетевиками.

### SSH

- Пользователь `pitcher`, вход по ключу. Sudo с паролем, его выполняет владелец.
- Доступ снаружи через VPN (`ppp0`, клиентский адрес `10.10.240.x`).
- **Известная проблема:** VPN периодически пропускает не все три сервера. Обходной путь — промежуточный хост:
  `ssh -J pitcher@10.10.113.11 pitcher@10.10.113.12`.
  Пакеты до серверов доходят, а ответы от части серверов теряются после шлюза `10.10.113.1`. Это вопрос к сетевикам: на самих серверах ограничений нет.

### Время (NTP)

- Внутреннего NTP-сервера в сети нет.
- **chrony** на srv01 раздаёт время по своим часам (`local stratum 8`, `allow 10.10.112.0/23`).
- srv02 и srv03 синхронизируются с srv01, расхождение меньше 100 мкс.
- `systemd-timesyncd` удалён, его заменил chrony.

### InfiniBand

- На srv01 включён subnet manager `opensm`. Порты ConnectX-4 в состоянии `Active`, 100 Гбит/с.
- Адреса IPoIB (`ibp59s0`) не назначены: в текущей схеме InfiniBand не используется. Это резерв для будущего шардинга Milvus и Nebula.

### Точки входа

| Что | Адрес | Авторизация |
|---|---|---|
| Веб-форма загрузки и поиска | http://10.10.113.12:8090 | нет (ключ API хранится в webui) |
| DeepSeek Harness (агент) | http://10.10.113.11:3080 | ссылка с токеном → cookie на 365 дней; белый список `10.10.0.0/16` |
| KB API | http://10.10.113.12:8000 | `X-API-Key` (значение `API_KEYS`) |
| MCP search / tools / stats | http://10.10.113.12:9001/mcp, :9002/mcp, :9003/mcp | `Authorization: Bearer <API_KEYS>` |
| LiteLLM (OpenAI-совместимый) | http://10.10.113.12:4000/v1 | `Bearer <LITELLM_API_KEY>` |
| Админка LiteLLM | http://10.10.113.12:4000/ui | `admin` / `LITELLM_UI_PASSWORD` |
| Temporal UI | http://10.10.113.12:8080 | нет |
| Grafana / Prometheus | http://10.10.113.12:3001 / :9092 | Grafana: `admin` / `GRAFANA_ADMIN_PASSWORD` |
| RabbitMQ UI | http://10.10.113.11:15672 | `RABBITMQ_USER` / `RABBITMQ_PASSWORD` |
| Консоль MinIO | http://10.10.113.11:9101 | `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` |

Все пароли и ключи лежат в `~/offline/stack/deploy/offline/stack/.env.offline` на любом сервере: права `600`, файл одинаковый на всех трёх. В репозитории есть только шаблон `.env.offline.example`.

---

## 3. Раскладка по серверам

Принципы:
- **Данные отдельно от LLM.** Инференс на CPU забирает всю пропускную способность памяти, и векторный и графовый поиск рядом с ним начинает тормозить.
- **LLM для поиска отдельно от LLM для ingest,** чтобы пользователь не ждал в общей очереди.
- **Внутри сервера тяжёлые процессы привязаны к сокету** через `cpuset`:
  - сокет 0 — ядра `0-19,40-59`;
  - сокет 1 — ядра `20-39,60-79`.

### srv01 — данные (10.10.113.11)

| Контейнер | Образ | Порт(ы) | Сокет | Назначение |
|---|---|---|---|---|
| kb-postgres-1 | postgres:16-alpine | 5432 | 0 | БД `kb_llamaindex` (документы, метрики), `temporal`, `temporal_visibility`, `litellm` |
| kb-milvus-1 | milvusdb/milvus:v2.4.17 | 19530, 9091 | 0 | коллекции `kb_llamaindex` (чанки) и `entity_er_vec` (ER) |
| kb-etcd-1 | quay.io/coreos/etcd:v3.5.16 | — | 0 | метаданные Milvus |
| kb-minio-1 | minio/minio:latest (amd64 от 2025-09-07) | 9000, 9101 | 0 | бакеты `kb-uploads`, `kb-staging`, сегменты Milvus |
| kb-nebula-metad/storaged/graphd-1 | vesoft/nebula-*:v3.8.0 | 9669 (graphd) | 0 | граф знаний, space `kb` |
| kb-redis-1 | redis:7-alpine | 6379 | 0 | кэш |
| kb-rabbitmq-1 | rabbitmq:3-management | 5672, 15672 | 0 | очереди `ingest.pending`, `ingest.dlq` |
| kb-embed-1 | ghcr.io/ggml-org/llama.cpp:server | 8081 | 1 | embeddings `bge-m3` FP16, 1024, пулинг CLS |
| kb-docs2md-1 | doc2md:offline | 8070 | 1 | конвертация документов в Markdown, OCR выключен |
| kb-dsh-web-1 | dsh-web:offline | 127.0.0.1:3080 + LAN 10.10.113.11:3080 | 1 | DeepSeek Harness, см. раздел 7 |

На хосте также работают chrony (NTP-сервер) и opensm (InfiniBand).
Тома: `kb_pg_data`, `kb_milvus_data`, `kb_etcd_data`, `kb_minio_data`, `kb_nebula_meta`, `kb_nebula_storage`, `kb_redis_data`, `kb_rabbitmq_data`, `kb_dsh_data`, `kb_dsh_workspace`.

### srv02 — приложение и поиск (10.10.113.12)

| Контейнер | Образ | Порт(ы) | Сокет | Назначение |
|---|---|---|---|---|
| kb-api-1 | kb-app:offline | 8000 | 0 | REST API (ingest, search, documents) |
| kb-worker-1 | kb-app-rerank:offline | — | 0 | пулы Temporal: `main, merge, search, large, graph_build, wiki, scheduler, monitor` + reranker bge-reranker-v2-m3 |
| kb-ingest-consumer-1 | kb-app:offline | — | 0 | читает RabbitMQ, запускает `DocumentIngestWorkflow` (K=4 одновременно) |
| kb-mcp-search/tools/stats-1 | kb-app:offline | 9001/9002/9003 | 0 | MCP-серверы базы знаний (Streamable HTTP) |
| kb-temporal-1 / kb-temporal-ui-1 | temporalio/auto-setup:1.25.2 / ui:2.31.2 | 7233 / 8080 | 0 | оркестрация, БД в Postgres на srv01 |
| kb-litellm-1 | ghcr.io/berriai/litellm:main-stable | 4000 | 0 | маршрутизация моделей, раздел 5 |
| kb-webui-1 | kb-app:offline (код `deploy/offline/webui`) | 8090 | 0 | форма загрузки (docs2md → ingest) и поиск |
| kb-prometheus-1 / kb-grafana-1 | prom/prometheus:v2.55.0 / grafana:11.3.0 | 9092 / 3001 | 0 | мониторинг |
| kb-llm-search-1 | llama.cpp:server | 8085 | 1 | Qwen3-30B-A3B Q4_K_M, резерв `large-cpu`, контекст 64k, 2 слота |

Сервисы приложения обращаются к хранилищам на srv01 по IP. Зависимости `depends_on` между серверами сброшены через `!reset`, порядок старта обеспечивают `restart: unless-stopped` и повторные попытки.

### srv03 — LLM для ingest (10.10.113.13)

| Контейнер | Образ | Порт | Сокет | Назначение |
|---|---|---|---|---|
| kb-llm-ingest-0-1 | llama.cpp:server | 8082 | 0 | Qwen3-30B-A3B Q4_K_M, резерв `small-cpu`, 1 слот, контекст 32k |
| kb-llm-ingest-1-1 | llama.cpp:server | 8083 | 1 | то же |
| kb-worker-llm-1 | kb-app:offline | — | 0 | пул Temporal `llm` (extract_kg), `LLM_POOL_N=8`, Temporal на srv02 |

### Модели на дисках (`/opt/models` на всех серверах)

| Файл | Размер | Используется |
|---|---|---|
| Qwen3-30B-A3B-Instruct-2507-Q4_K_M.gguf | 18.6 ГБ | да, CPU-резерв на srv02 и srv03 |
| bge-m3-FP16.gguf | 1.2 ГБ | да, embeddings на srv01 |
| gemma-4-E4B-it-Q4_K_M.gguf | 5.0 ГБ | нет, раньше был `small` |
| nomic-embed-text-v1.5.f16.gguf | 0.3 ГБ | нет |

Контрольные суммы сверены с Hugging Face (`~/offline/models/SHA256SUMS`).

---

## 4. Базовая настройка серверов (sudo, однократно)

Скрипт `deploy/offline/sudo-setup.sh <srv01|srv02|srv03>` можно запускать повторно. Что он делает:

1. **hostname** и `/etc/hosts`. На srv02 исправлен hostname: был `ext22-srv01`, стал `ext22-srv02`.
2. **Проверяет контрольные суммы** офлайн-пакета.
3. **Ставит 28 пакетов через `dpkg -i` из `~/offline/debs`:** docker-ce 29.8.2, containerd 2.3.6, compose 5.6.0, buildx, chrony, pigz, rdma-core, opensm, infiniband-diags, ipmitool и зависимости. `systemd-timesyncd` удаляется. Почему не `apt`: офлайн он пытается качать из репозитория.
4. **Docker:** `/etc/docker/daemon.json`:
   - логи 50 МБ × 3;
   - `live-restore`;
   - подсети `172.30.0.0/16`;
   - `nofile` 1048576.

   `pitcher` добавлен в группу `docker`, data-root — `/var/lib/docker`.
5. **sysctl:** `vm.max_map_count=262144`, `vm.swappiness=10`, `fs.file-max`, `inotify`, `somaxconn=4096`, `tcp_keepalive_time=300`.
6. **chrony:** сервер на srv01, клиенты на srv02 и srv03.
7. **Модели** копируются в `/opt/models`.
8. **ufw:** если включён, разрешается подсеть 10.10.112.0/23. На всех трёх серверах он был неактивен.
9. **opensm** включается на srv01.
10. **Отчёт по сети** выводится без изменений.

Офлайн-пакет лежит на каждом сервере в `~/offline/`: `debs/`, `images/` (17 образов в `.tar.zst`), `models/`, `stack/`. У каждой папки свой `SHA256SUMS`.

---

## 5. Модели и маршрутизация (LiteLLM)

Конфиг: `deploy/offline/stack/litellm_config.offline.yaml`. Приложение запрашивает только три алиаса.

| Алиас | Основной путь | Резерв | Где используется в приложении |
|---|---|---|---|
| `small` | GPU vLLM `deepseek-v4-flash`, `thinking: false` | `small-cpu` → Qwen srv03 :8082 / :8083 | извлечение сущностей, judge, планирование, роутинг, ER-верификация |
| `large` | GPU vLLM `deepseek-v4-flash`, `thinking: true` | `large-cpu` (Qwen srv02 :8085), затем `small-cpu` | только роль `synthesis`, то есть финальный ответ пользователю |
| `bge-m3` | llama.cpp srv01 :8081 | — | embeddings (размерность 1024 = `MILVUS_DIM`) |

**Параметры:**
- Маршрутизатор: `least-busy`, 2 повтора, общий таймаут 900 с, таймаут вызова GPU 180 с.
- Кулдаун после 3 ошибок — 60 с.
- Размышления vLLM возвращает в отдельном поле `reasoning_content`, в `content` они не попадают.
- Хранилище админки: БД `litellm` в Postgres на srv01. Модели в БД не хранятся, источник истины — файл конфига.
- `LITELLM_LOCAL_MODEL_COST_MAP=True`: без интернета litellm не пытается скачивать таблицу цен.
- Какую роль обслуживает какой алиас, задаёт `src/config.py` (`_DEFAULT_ROLE_TIERS`). Переопределить можно без кода: `LITELLM_ROLE_TIERS='{"plan":"large"}'`.

**Проверка маршрута:** заголовок ответа `x-litellm-model-api-base` у `small` и `large` равен `http://10.10.151.15:8000/v1`.

---

## 6. Потоки данных

### Ingest (загрузка документа)

```
браузер → webui :8090 ──/api/convert──► docs2md :8070 (srv01) → Markdown
          (или dsh /kb-ingest)  └─/api/ingest──► API :8000 → MinIO kb-uploads + Postgres documents
                                              → RabbitMQ ingest.pending (srv01)
ingest-consumer (prefetch K=4) → Temporal DocumentIngestWorkflow
   ├─ main (srv02):  parse → chunk → embeddings (bge-m3) → Milvus kb_llamaindex
   ├─ llm  (srv03):  extract_kg — small → GPU deepseek-v4-flash
   ├─ merge (srv02): merge_and_resolve (ER: kNN по Milvus entity_er_vec + LLM-проверка)
   ├─ graph_build:   запись в NebulaGraph space kb
   └─ finalize:      status=completed, ingest_metrics
```

- **Форматы:** webui всегда передаёт в API Markdown. docs2md понимает форматы с текстовым слоем: DOCX, PDF с текстом, TXT, HTML и т.д. **Сканы и картинки не поддерживаются:** OCR выключен, ответ `503 ocr_unavailable`.
- **Дедупликация между документами (ER)** включена флагом `AGENT_ER_USE_NATIVE_VECTOR_KNN=true`. Для каждой новой сущности берутся 20 ближайших из всего графа. Флаг теперь `true` по умолчанию и в `docker-compose.prod.yml`, коммит `39d4d79`.
- **Параллельность:** 4 документа одновременно (`INGEST_ADMISSION_MAX_INFLIGHT=4`). Пул LLM: 12 вызовов на srv02 и 8 на srv03.

### Поиск

```
webui / API /api/v1/search/{local,global,drift,auto} / MCP kb_search
 → Temporal SearchOrchestratorWorkflow (worker srv02, пул search)
 → гибрид: Milvus (векторы) + Nebula (граф) + BM25 → reranker bge-reranker-v2-m3 (CPU, top 20)
 → синтез ответа: large → GPU deepseek-v4-flash (с размышлениями)
```

### MCP

- Три сервера (`kb-llamaindex-search`, `-tools`, `-stats`) на srv02, транспорт Streamable HTTP, endpoint `/mcp`, авторизация `Bearer <одно из API_KEYS>`.
- Подключены к DeepSeek Harness. Любой MCP-клиент в сети может подключиться с тем же ключом.

---

## 7. DeepSeek Harness (агент) на srv01

| Параметр | Значение |
|---|---|
| Версия | `@deepseek-ai/dsh` 0.2.0-rc.2 (зафиксирована в образе) |
| Образ | `dsh-web:offline`: node:22-slim + dsh + ripgrep/git/python3, собран заранее, интернет при запуске не нужен |
| Файлы | `deploy/offline/dsh/`: `Dockerfile`, `entrypoint.sh`, `cordis.patch.yml`, `lan-proxy.mjs`, `plugin-kb-ingest/` |
| Сеть | `network_mode: host`. Сам dsh слушает только `127.0.0.1:3080` (адрес `0.0.0.0` dsh запрещает сам) |
| LAN-доступ | L4-прокси `lan-proxy.mjs` на `10.10.113.11:3080` → `127.0.0.1:3080`. Белый список клиентов `LAN_ALLOW=10.10.0.0/16`, меняется через `DSH_LAN_ALLOW` |
| Авторизация | токен в ссылке (новый при каждом перезапуске) → подписанный cookie на 365 дней. Секрет подписи хранится в `/data/dsh/.credentials.yaml` (том `kb_dsh_data`), поэтому cookie переживает перезапуски |
| Модели | провайдер `kb-litellm` → LiteLLM srv02. По умолчанию `large`, есть и `small`. Облачные маршруты DeepSeek отключены |
| MCP | `kb_search`, `kb_tools`, `kb_stats` → srv02 :9001–9003, токен `KB_MCP_TOKEN`, таймаут вызова 5 мин |
| Телеметрия | отключена (`DSH_TELEMETRY_DISABLED=1`) |

**Плагин `dsh-kb-ingest`** (чистый JS, около 200 строк):

| Что | Как пользоваться |
|---|---|
| `/kb-ingest [ГГГГ-ММ-ДД]` | прикрепить файлы в чате и отправить команду: загрузка напрямую, без вызова модели |
| `/kb-status [job_id …]` | статус загрузок текущего сеанса или указанных job |
| `kb_ingest_file(path, document_date?)` | инструмент агента: загрузить файл по пути (прикреплённые файлы агент видит по пути) |
| `kb_ingest_status(job_id)` | инструмент агента: статус |

- Плагин отправляет файлы в webui srv02: `/api/convert` → `/api/ingest`. Ключ API хранится в webui, в dsh его нет.
- Загрузчик dsh находит только свои пакеты и пакеты, объявленные в профиле. Поэтому `entrypoint.sh` при каждом старте копирует плагин в `$DSH_HOME/profiles/web/node_modules` и прописывает зависимость в `package.json` профиля.

**Получить ссылку для входа:**
```bash
ssh pitcher@10.10.113.11 'docker logs kb-dsh-web-1 2>&1 | grep -oE "http://127.0.0.1:3080/\?token=[^ ]+" | tail -1'
# в ссылке заменить 127.0.0.1 на 10.10.113.11
```

**Отозвать все входы:**
```bash
docker exec kb-dsh-web-1 rm /data/dsh/.credentials.yaml && docker restart kb-dsh-web-1
```

---

## 8. Безопасность — сводка

- ⚠ **dsh:** у агента есть bash. Контейнер работает в сети хоста, поэтому агент может обращаться ко всем сервисам локальной сети. Пользователей dsh не различает: все, кто вошёл, видят общие сессии. Соединение — HTTP без TLS.
  Ограничения:
  - белый список `10.10.0.0/16`;
  - вход по токену и cookie;
  - нет доступа к Docker-сокету и файловой системе хоста.

  Ссылку с токеном и cookie никому не передавать.
- **webui :8090 без авторизации:** любой в сети может загружать документы и искать. Ключ API хранится в webui.
- **Temporal UI, Prometheus:** без авторизации.
- **Секреты** только в `.env.offline` (`600`) на серверах. Пароли сгенерированы `openssl rand`.
- **ufw выключен** на всех серверах.
- Docker-сети `172.17.0.0/16` и `172.30.0.0/16` не пересекаются с офисными и VPN-подсетями.

---

## 9. Конфигурация

### Файлы в репозитории (`deploy/offline/`)

| Файл | Что |
|---|---|
| `stack/docker-compose.srv01.yml`, `.srv02.yml`, `.srv03.yml` | override для каждого сервера к `docker-compose.prod.yml`: сервисы, IP, `cpuset`, порты, `!reset` зависимостей |
| `stack/litellm_config.offline.yaml` | алиасы моделей, GPU и CPU-резервы, размышления |
| `stack/.env.offline.example` | шаблон переменных и секретов |
| `sudo-setup.sh` | базовая настройка серверов (раздел 4) |
| `Dockerfile.offline` | слой поверх образов приложения: NLTK stopwords и punkt_tab, `HF_HUB_OFFLINE=1` |
| `webui/` | веб-форма (FastAPI + HTML) |
| `dsh/` | DeepSeek Harness (раздел 7) |
| `PROGRESS.md`, `DEPLOYMENT.md`, `architecture.d2/.svg` | журнал, этот отчёт, схема |

### Ключевые переменные `.env.offline` (без значений)

| Группа | Переменные |
|---|---|
| Секреты | `POSTGRES_PASSWORD`, `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY`, `NEBULA_PASSWORD`, `RABBITMQ_USER` / `RABBITMQ_PASSWORD`, `LITELLM_API_KEY`, `LITELLM_UI_PASSWORD`, `API_KEYS`, `KB_MCP_TOKEN`, `GRAFANA_ADMIN_PASSWORD`, `NEO4J_PASSWORD` (не используется, но preflight API требует не-дефолтное значение) |
| Адреса | `LITELLM_BASE_URL=http://10.10.113.12:4000`, `API_CORS_ORIGINS`, `TEMPORAL_UI_CORS` |
| Модели | `LITELLM_MODEL_SMALL=small`, `LITELLM_MODEL_LARGE=large`, `LITELLM_EMBEDDING_MODEL=bge-m3`, `MILVUS_DIM=1024` |
| Параллельность | `LLM_POOL_N=12` (srv02; на srv03 переопределено на 8), `INGEST_ADMISSION_MAX_INFLIGHT=4`, `TEMPORAL_LLM/MERGE_ACTIVITY_CONCURRENCY=14`, `INGEST_QUEUE_BACKEND=rabbitmq` |
| Граф и ER | `GRAPH_BACKEND=nebula`, `TEMPORAL_COMMUNITY_BACKEND=leidenalg`, `EVENTS_FIRST_SEEN_ENABLED=true`, `AGENT_ER_USE_NATIVE_VECTOR_KNN=true` |

### Параметры llama.cpp

| Сервис | Ключевые флаги |
|---|---|
| embed (srv01) | `--embedding --pooling cls --ctx-size 32768 --batch/ubatch 8192 --parallel 4 --threads 20` |
| llm-search (srv02) | `--ctx-size 65536 --parallel 2 --threads 20 --load-mode none --jinja --cache-reuse 256` |
| llm-ingest-0/1 (srv03) | `--ctx-size 32768 --parallel 1 --threads 20 --load-mode none --jinja --reasoning off --cache-reuse 256` |

`--threads 20` — это физические ядра одного сокета. `--load-mode none` загружает модель в RAM своего NUMA-узла: в новой сборке llama.cpp это замена `--no-mmap`.

---

## 10. Производительность (замеры)

| Что | Результат |
|---|---|
| GPU `deepseek-v4-flash` через LiteLLM, 150 токенов | 0.7–0.8 с |
| Поиск `/search/local` целиком | 9.8 с без размышлений у `large`, 13.1 с с размышлениями |
| Embeddings bge-m3, короткий текст | ~70 мс |
| Пачка из 13 документов `.docx` (GPU, K=4) | 1-я пачка — 16 мин 39 с; 2-я — около 10 мин; 0 сбоев |
| Один документ | 2–9 мин, включая очередь. Самый долгий этап — ER (до 15 мин на документ с 233 сущностями); в это время GPU простаивает |
| CPU Qwen3-30B-A3B (резерв), 1 поток | генерация 25 ток/с, обработка промпта 70–80 ток/с |
| CPU Qwen3-30B-A3B, 2 сервера × 6 слотов, короткие промпты | суммарно 102 ток/с |
| CPU, промпт 5.7k без кэша | ~70 с только на обработку промпта; при 12 параллельных запросах генерация почти стоит |
| Тот же ingest на CPU до перехода на GPU | 44 мин и 1 ч 42 мин на документ |

Вывод: на CPU-резерве ingest рабочий, но медленный, в 20–40 раз медленнее GPU. Узкое место — обработка промпта.

---

## 11. Эксплуатация

### Базовая команда

На любом сервере, где `NN` — номер сервера:
```bash
cd ~/offline/stack
C="docker compose -p kb -f docker-compose.prod.yml -f deploy/offline/stack/docker-compose.srvNN.yml --env-file deploy/offline/stack/.env.offline"
$C ps                # состояние
$C logs -f <svc>     # логи
$C restart <svc>     # перезапуск
$C up -d <svc>       # пересоздать после изменения env/compose
```
Перезапуска (`restart`) недостаточно, если изменились переменные окружения: тогда нужно `up -d` (пересоздание контейнера).

### Порядок запуска с нуля / после перезагрузки

Контейнеры с `restart: unless-stopped` поднимаются сами. Если поднимать вручную:

1. **srv01:** `postgres etcd minio milvus nebula-metad nebula-storaged nebula-graphd redis rabbitmq embed docs2md dsh-web`
2. **srv02:** `temporal temporal-ui litellm llm-search` → (однократно, на чистой базе) `init` → `api worker ingest-consumer mcp-search mcp-tools mcp-stats webui prometheus grafana`
3. **srv03:** `llm-ingest-0 llm-ingest-1 worker-llm`

### Частые операции

| Задача | Как |
|---|---|
| Статус ingest | webui; `/kb-status` в dsh; SQL `select status,count(*) from documents group by 1` в Postgres srv01 |
| Очередь | `docker exec kb-rabbitmq-1 rabbitmqctl list_queues name messages_ready messages_unacknowledged` |
| Сменить модель | править `litellm_config.offline.yaml` на srv02 → `docker restart kb-litellm-1` (приложение не трогать) |
| Полная очистка данных | остановить `worker`, `ingest-consumer` (srv02) и `worker-llm` (srv03), затем `$C run --rm --no-deps init python -m scripts.wipe_db --yes --keep-wiki` (srv02), затем запустить их обратно |
| Ссылка входа в dsh | раздел 7 |
| Обновить образ приложения | на маке: `docker buildx build --platform linux/amd64 …` + слой `Dockerfile.offline` → `docker save \| zstd \| ssh … 'zstd -dc \| docker load'` → `$C up -d <svc>` |
| Поставить пакет на сервер | скачать `.deb` с зависимостями в контейнере `ubuntu:24.04 --platform linux/amd64` (`apt-get install --download-only`), перенести, `sudo dpkg -i` |

### Мониторинг зависаний

- Длинная фаза ER может молчать в логах **минутами**. Это не зависание, если у активности `merge_and_resolve` свежий heartbeat в Temporal.
- Проверка:
  ```bash
  tctl --address <temporal-ip>:7233 wf desc -w graph-<doc_id>
  ```
- Heartbeat-таймаут у merge — 15 мин.

---

## 12. Известные проблемы и ограничения

| Проблема | Влияние | Что делать |
|---|---|---|
| VPN нестабилен: виден не каждый сервер | доступ с мака к части серверов пропадает | `ssh -J` через доступный сервер; разобраться на стороне сети (ACL на шлюзе `10.10.113.1` или VPN-концентраторе) |
| Маска `/23` на srv03 | возможны проблемы с маршрутизацией | согласовать с сетевиками |
| Нет OCR | сканы и картинки не загружаются | включить OCR в docs2md, когда появится GPU, или ставить OCR на CPU |
| Свободно ~120–130 ГБ на каждом сервере, физические диски за RAID неизвестны | рост данных 0.7–3.6 ГБ в сутки, место кончится примерно через несколько месяцев | `storcli` → проверить свободные диски, перенести тома данных |
| Длинный контекст | отчёт по корневому сообществу (~390k токенов) больше контекста `deepseek-v4-flash` (262k) | следить при построении сообществ |
| ER — самый долгий этап ingest | пачки упираются в ER, а не в LLM | отдельная задача на оптимизацию |
| dsh 0.2.0-rc.2 (rc-версия) | плагин использует внутренние API, при обновлении dsh может сломаться | версия зафиксирована; обновлять осознанно с проверкой |
| `kb-webui-1` запущен на предыдущем образе `kb-app` (сейчас помечен `kb-app:prev`) | работает; при пересоздании возьмёт новый `kb-app:offline` | при следующем `up -d webui` проверить |
| В `main` в `docker-compose.prod.yml` появился `lens-agent` с обязательной `LENS_API_KEYS` | если развернуть `main`, compose не стартует без этой переменной | добавить `LENS_API_KEYS` в `.env.offline` перед переходом на `main` |
| MinIO больше не публикует образы | обновить MinIO из registry нельзя | используется локальная amd64-копия от 2025-09-07 |

---

## 13. Ключевые решения и находки (хронология — в `PROGRESS.md`)

1. **Без интернета:** всё скачивается на мак в `~/offline-kb-stage/`, затем `rsync --partial` на srv01 и раздача srv01 → srv02/03. Прямая загрузка с мака на серверы рвалась при обрывах VPN.
2. **apt офлайн не работает** (лезет в репозиторий, а при скрытых источниках падает с «Pathname not absolute»), поэтому установка через `dpkg -i`. Пакеты собраны в контейнере Ubuntu 24.04, отфильтрованы до недостающих на серверах.
3. **llama-index при старте скачивает данные NLTK.** Без интернета это падает, поэтому они добавлены в образ отдельным слоем. Проверено запуском с `--network none`.
4. **Embeddings в проде — bge-m3 (1024), а не nomic,** поэтому везём bge-m3 в GGUF.
5. **Модели:** сначала `small` = gemma-4-E4B на CPU, потом Qwen3-30B-A3B на CPU, затем (2026-10-05) обе роли переведены на GPU vLLM `deepseek-v4-flash`, CPU-модели оставлены резервом. Для `large` включены размышления.
6. **Межд документная дедупликация (ER) не работала под Nebula:** prod-compose принудительно выключал kNN-путь, а старый Cypher-путь на Nebula падает. Флаг включён, база очищена и загружена заново. Проверено: 5/5 слияний на тесте и около 50 слияний между документами в реальной пачке.
7. **dsh** запрещает слушать сетевой адрес. Сделано так: `network_mode: host` + `127.0.0.1` + L4-прокси с белым списком, авторизация dsh сохранена.
8. **Ошибочная диагностика 2026-10-05:** долгую «тихую» фазу ER на документе 3.md я принял за взаимоблокировку пула LLM и перезапустил worker. На самом деле документ закончился сам. Вывод: смотреть на heartbeat в Temporal, а не на тишину в логах.

---

## 14. Что дальше

- [ ] Разобраться с сетью: VPN-доступ ко всем трём серверам и маска `/23` на srv03.
- [ ] Установить `storcli` и выяснить, какие физические диски стоят за RAID; спланировать место под данные.
- [ ] OCR для сканов (docs2md).
- [ ] Ускорить ER на больших документах.
- [ ] Добавить `LENS_API_KEYS` в `.env.offline` перед переходом серверов на актуальный `main`.
- [ ] (по желанию) HTTPS и нормальная авторизация перед dsh и webui, если доступ понадобится шире одного пользователя.
- [ ] Нагрузочный замер ingest на GPU (реальная пропускная способность в документах в сутки).
