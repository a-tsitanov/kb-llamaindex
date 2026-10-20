# Hermes Agent integration runbook

Подключение `kb-llamaindex` к [Hermes Agent](https://hermes-agent.nousresearch.com)
(Nous Research) — персистентному серверному агенту. RAG выступает источником
инструментов через MCP по SSE; память, цикл диалога и обучаемость — на стороне
Hermes. Интеграция **аддитивна**: поведение MCP-серверов не меняется.

Связанные runbook'и: [`mcp.md`](mcp.md) (сами MCP-серверы; §3 про контракт
`kb_search` частично устарел — см. баннер в начале того файла),
[`search-usage.md`](search-usage.md).

## 1. Поднять SSE-сервисы

Рядом с Temporal worker (тот же стек: Milvus, NebulaGraph, Postgres, LiteLLM):

```bash
# Атомарные тулы (основная поверхность для интерактивного цикла)
# Streamable HTTP (эндпоинт /mcp)
uv run python -m src.mcp.tools_server  --transport http --host 0.0.0.0 --port 9002

# Оркестрованный поиск: kb_search (local) + kb_global_search +
# kb_drift_search + kb_auto_search — тяжёлые escape-hatch'и
uv run python -m src.mcp.search_server --transport sse --host 0.0.0.0 --port 9001
```

**Авторизация:** при `KB_MCP_REQUIRE_AUTH=true` (по умолчанию) сервер требует
заголовок `Authorization: Bearer <key>`; ключ проверяется по реестру API-ключей
(`public.api_keys`, sha256-хэш; фолбэк — env `API_KEYS`). Без env `API_KEYS`
сервер не стартует (`assert_api_key_env_set`). Для локального stdio-режима
desktop-клиентов auth отключается через `KB_MCP_REQUIRE_AUTH=false`.

**Граф:** каждый вызов тула привязан ровно к одному графу, и выбирает его
заголовок `X-Graph: <id>`. Без заголовка берётся единственный граф ключа,
если ключ сужен до одного (`api_keys.graph_ids` — так выписывают фидерные
ключи), иначе `KB_MCP_GRAPH` (по умолчанию `default`) — поэтому env-ключи из
`API_KEYS` работают без дополнительных заголовков. Сужение до ДВУХ и более
графов подстановки не даёт и остаётся чистым ограничением: граф вне списка
даёт отказ, а не подстановку. Подробно — [`mcp.md` §6](mcp.md#6-auth).

> **⚠️ Про `RegistryTokenVerifier`.** Auth реализован собственным FastMCP
> `TokenVerifier` — `RegistryTokenVerifier` (`src/mcp/_shared.py`): Bearer-токен
> = API-ключ, он ищется в реестре ключей (`ApiKeyStore`, кэш 30 с), а арендатор
> и права ключа кладутся в claims токена. Права (`scopes`) есть и проверяются
> на каждом вызове тула (`AUTHZ_MODE`, см. [`mcp.md` §6.2](mcp.md#62-авторизация-проверка-на-каждый-вызов-инструмента)),
> срока жизни у токена по-прежнему нет. Поэтому: (1) держите SSE-порты во
> внутренней сети, не публикуйте наружу; (2) при выставлении наружу —
> закрывайте reverse-proxy с TLS; (3) ротация env-ключа = смена `API_KEYS` +
> рестарт сервиса; (4) выписка и отзыв ключей в `public.api_keys` — только CLI
> `scripts/tenant_admin.py` (`key` / `revoke`), HTTP-маршрута для этого нет и
> не планируется.

## 2. Зарегистрировать в Hermes

Скопировать блок из [`integrations/hermes/config.example.yaml`](../../integrations/hermes/config.example.yaml)
в `~/.hermes/config.yaml`, заменив `<kb-host>` и выставив `KB_API_KEY` в окружении
процесса Hermes. При старте Hermes сам дискаверит тулы и покажет чек-лист; имена
в агенте получают префикс `mcp_kbtools_*` (8 атомарных) и `mcp_kbsearch_*`
(`kb_search`, `kb_global_search`, `kb_drift_search`, `kb_auto_search`).

## 3. Установить скилл

Скилл [`integrations/hermes/knowledge-base/SKILL.md`](../../integrations/hermes/knowledge-base/SKILL.md)
кладётся в `~/.hermes/skills/knowledge-base/SKILL.md` (или публикуется через Skills
Hub). Он учит Hermes выбирать тул под тип задачи, форматировать ответы с
цитатами, пользоваться памятью и резолвить follow-up-реплики в самодостаточные
запросы.

## 4. Smoke-проверка

1. Hermes стартует без ошибок и в списке тулов видны 8 `mcp_kbtools_*` +
   4 `mcp_kbsearch_*`.
2. Запрос с точным идентификатором (телефон/ИНН) → Hermes зовёт
   `find_entity_by_id` и возвращает досье.
3. Неверный/отсутствующий `KB_API_KEY` → запрос к SSE отклоняется (401).

## 5. Приёмочные сценарии

См. `tests/eval/hermes_scenarios.py` — золотой набор интерактивных сценариев
(по одному на ветку дерева выбора тула + многоходовый follow-up + досье). Прогон
end-to-end через живой Hermes — ручной; критерии: верный тул, применён шаблон,
сработала реформулировка.
