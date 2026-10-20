# kb-tools MCP — the surface Lens relies on

Lens (`~/projects/lens`, extracted 2026-10-08) talks to the knowledge base only through the
kb-tools / kb-stats MCP servers. This page lists what it depends on; changing any of it is a
contract change: update Lens (`tests/fixtures/lens_eval` pins recorded payloads) together.

## Row shapes

Lens finds rows generically (`rows.py` в проекте `lens` — он выехал из этого репозитория, здесь остался только контракт):
- **entity row** — a dict with `entity_name` (or `id` / `name`), optional `entity_type`,
  `description`, `relevance` (cross-encoder sigmoid 0..1), `match` (`strong|weak|none`);
- **relation row** — a dict with `src_id` and `tgt_id` (entity names) and `label` (the KB
  relation type, e.g. `DIPLOMACY`, `PARTICIPATED_IN`).

## Meta fields on graph tools

| field | tool | meaning |
|---|---|---|
| `resolution` | every name-taking tool | `{query, status: ok\|ambiguous\|not_found, chosen{name, label, matched_via, matched_text, score}, alternatives[], ambiguous, verified?}` |
| `centre_found`, `closest`, `centre_note` | `find_neighbours` | whether the asked entity is in the result |
| `ranked`, `best_relevance`, `relevance_note`, `rank_timeout` | `graph_search`, `find_neighbours` | ranking outcome; `relevance_note` = nothing relevant, `rank_timeout` = store order |
| `order: edges_to_centre` | `find_neighbours` | vague question / timeout: ordered by edges to the centre |
| `types`, `types_inferred` | `find_neighbours` | type filter (given or inferred from «люди / кто») |
| `depth_note` | `graph_search`, `find_neighbours` | depth/hops cut to `MCP_TOOLS_MAX_DEPTH` |
| `unresolved` | `graph_shortest_path`, `graph_personalized_pagerank`, `relations_between` | names that did not resolve |

`matched_via` values Lens reads: `exact`, `casefold`, `alias`, `translit`, with optional
`legal_form+` / `stem+` prefixes (exact-level → a board object is redirected to the
canonical key); `word`, `tword`, `prefix`, `trigram` are guesses (no redirect).

## Helper tools (hidden from the model, called by Lens itself)

- `resolve_names(text) -> {names: [{span, name, label, matched_via, score}]}` — request
  names that resolve at an exact level, named types only; Lens puts them into the prompt
  (`McpEntry.resolve_tool`).
- `relations_between(a, b) -> {relations: [{src_id, tgt_id, label, polarity}], resolution,
  unresolved?}` — live RELATED edges between two strictly-resolved entities; Lens uses it to
  confirm a relation the model draws (`McpEntry.relation_tool`).

## Board-key normalization

`src/utils/names.norm_name` here and `lens_common/names.norm_name` in the `lens` project are the same
function; both are pinned by the same case list (`tests/test_utils/test_names.py` here,
`tests/test_lens_common/test_names.py` there).
