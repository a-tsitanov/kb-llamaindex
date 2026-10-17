# KB name resolution and aliases — design and staged plan

Status: draft for approval (2026-09-30). Scope: user items (1) "every kb-tools search tool must handle
name variants and not lose results after ER merges" and (3) "KB quality: different names vs the
canonical entity". Evidence: investigation `inv_resolution.md` (session scratchpad; key facts below).

## 1. Problem (verified on live data)

- The KB identifies an entity by its exact name: VID = blake2b(name) (`src/graph/nebula_store.py:64`).
- ER at ingest picks one canonical per cluster ("Rosatom" — a stored entity always wins,
  `entity_resolution.py:855-877`) and **drops every other name**: the `aliases` list is built
  (`:893`) but not written (`nebula_store.py:186-193`); stored losers are re-pointed and
  `DELETE VERTEX … WITH EDGE` (`er_graph_ops.py:240`); within-batch losers never reach the graph;
  `er_canonical_name` is a self-stamp (0 of ~6 000 sampled vertices point elsewhere).
- Live: "Росатом", "ГК «Росатом", "РОСАТОМ", "Лихачев", "Likhachev", "Alexey Likhachev" do not exist
  as vertices; "Rosatom" (degree 221) and "Алексей Лихачёв" (degree 47) do.
- Leftovers that still remember the old names: the Postgres `entity` mirror (upsert-only; 13% of rows
  are dead vertices, incl. "Росатом", "Лихачев") and `er_verdict` (5.54M LLM verdicts, 227k SAME,
  e.g. `Rosatom≡Росатом`, `Likhachev≡Алексей Лихачёв`; noisy: `Fomc≡ФРС`).
- Every kb-tools tool resolves names its own way and never says what it resolved to:
  `find_neighbours` / `find_entity_by_id` = vector+trigram seeds + subgraph of every seed
  (Росатом → «Российский суд», dead mirror row first); `graph_walk`, `graph_shortest_path`,
  `graph_personalized_pagerank`, `polarity_evolution` need the exact name and return empty /
  `hops:-1` / drop the seed silently; `find_entity_by_name` is prefix-only (no surname, no other
  script, no inflection, no merged-away name).

## 2. Design

### 2.1 One resolver, one normalization
`src/graph/name_resolution.py`:

```python
async def resolve(name: str, *, label: str | None = None, k: int = 5,
                  strict: bool = False, allow_vector: bool = True) -> Resolution
@dataclass
class Candidate:  canonical_name, vid, label, matched_via, matched_text, score, mention_count, degree?
@dataclass
class Resolution: query, chosen: Candidate | None, alternatives: list[Candidate], ambiguous: bool
```

Cascade (cheap → expensive, stop at a confident single hit):

| step | how | matched_via | prior |
|---|---|---|---|
| exact | Nebula `FETCH PROP ON Entity vid(name)` | exact | 1.00 |
| casefold | `entity.name_norm = norm(q)` | casefold | 0.97 |
| alias | `entity_alias.alias_norm = norm(q)` → canonical | alias | 0.95 (verdict backfill: 0.85) |
| translit | `name_translit` / `alias_translit = translit(norm(q))` | translit | 0.90 |
| word | `name_norm <% q` (pg_trgm word_similarity; surname in full name) | word | 0.80·ws |
| prefix | `name_norm LIKE q || '%'` | prefix | 0.70 |
| trigram | `name_norm % q` | trigram | sim |
| vector | name-only embedding kNN over Milvus `entity_er_vec` (only if nothing ≥ floor) | vector | 0.80·cos |

Then: **liveness** (one FETCH of all candidate VIDs, drop dead), **canonicalization** (alias →
canonical, group by canonical, keep all `matched_via`), rank by score then log(mention_count),
`ambiguous` if top-2 within ε or top < floor. `strict=True` stops after translit (for exact-lookup
tools). `norm()` = NFKC, casefold, ё→е, strip «»"'„“, collapse spaces — **the same function as the
Lens board's `normalize_id`** (moved to a shared module, behaviour unchanged).

Latency: lexical path ~20–80 ms, no model calls; vector fallback +100–300 ms.

### 2.2 Data
- `entity` (Postgres mirror): add `name_norm` (generated), `name_translit` (filled by writer/backfill),
  GIN trigram on `name_norm`, btree on both; add `alive boolean` (or delete dead rows after the
  alias backfill).
- New `entity_alias(alias, alias_norm, alias_translit, canonical_vid, canonical_name, source,
  confidence, doc_id, created_at, PK(alias_norm, canonical_vid))`, GIN trigram on `alias_norm`.
  `source ∈ er_merge | er_stored_loser | verdict_backfill | surface_form | manual`.
- Milvus `entity_er_vec`: delete rows of dead vertices (stops ER from resurrecting losers).

### 2.3 Tool contract (every name-taking kb-tools tool)
Every output gets a top-level `resolution` block (`query`, `chosen{name, matched_via, score}`,
`alternatives[≤5]`, `ambiguous`, `status: ok | ambiguous | not_found`). No silent substitution.

| tool | new behaviour |
|---|---|
| `find_entity_by_id` | `resolve(strict=True)`; the entity + props, or `not_found` + candidates |
| `find_entity_by_name` | `resolve(k=limit)` ranked candidates with `matched_via/matched_text` |
| `find_neighbours` | resolve → **1-hop from that one vertex** (`GO … BIDIRECT` / SUBGRAPH), ranked by `query` via the edge to the centre (reranker fixes); `ambiguous` → candidates, no walk |
| `graph_walk` | resolve `start_entity`, report it |
| `graph_shortest_path`, `graph_personalized_pagerank` | resolve every endpoint/seed; `unresolved: [...]` instead of `hops:-1` / dropped seeds |
| `polarity_evolution` | resolve `name`, query by canonical |
| `graph_search` | stays discovery; add `seeds: [{name, matched_via, score}]`; resolver hits for named spans + kNN; drop dead seeds |
| chunk/doc/stat tools | unchanged |

### 2.4 Ingest (so aliases stop being lost)
- `merge_and_resolve`: persist the **full** `name_map` + cluster `aliases` (+ pre-merge surface
  forms) as `er_merge` alias rows, written after the canonical upsert succeeds.
- `merge_loser_into_canonical`: insert `loser→canonical (er_stored_loser)`, re-point alias rows
  that pointed at the loser, delete the loser's mirror row and its `entity_er_vec` row.
- Optional: fill `surface_forms` so the dormant Wikibase alias path starts working.

## 3. Migration (no re-ingest for most of it)
1. `name_norm`/`name_translit` + indexes: SQL + one Python pass over ~379k rows (minutes).
2. Liveness pass over the mirror (FETCH in batches of 500) → dead set.
3. Alias backfill: for each dead name D, `er_verdict` SAME pairs (D, X) with X alive → `D→X`,
   `verdict_backfill`, confidence 0.85, chains followed; **gate: hand-check a random 200 first**
   (decision 3). Never overrides an exact/casefold hit; always reported as `matched_via=alias`.
4. Delete (or flag) dead mirror rows and dead `entity_er_vec` rows.
5. Aliases from same-script auto-merges (cos ≥ 0.85) never reached any table: recovered only by
   re-ingest with the new write path, or covered by casefold/translit/word matching — accept.

## 4. Staged plan (each stage shippable and tested)

| stage | content | acceptance |
|---|---|---|
| R0 | eval fixtures: a small resolution test set from the live facts (Росатом→Rosatom, Лихачев→Алексей Лихачёв, «ГК «Росатом», РОСАТОМ, Likhachev, surname-only, Роснано / АО «Роснано, unknown name) as unit fixtures over fake stores + a read-only live script | baseline numbers per tool |
| R1 | shared `norm()`; `entity` columns + indexes (migration in `scripts/setup_db.py`, idempotent); `entity_alias` table | schema tests; board keys unchanged |
| R2 | `resolve()` over exact/casefold/alias/translit/word/prefix/trigram + liveness + canonicalization (vector later) | unit tests per step; live script: all fixture names resolve, latency < 100 ms |
| R3 | tool contract: `find_entity_by_id`, `find_entity_by_name`, `find_neighbours` (real 1-hop), `graph_walk`, `shortest_path`, `PPR`, `polarity_evolution`, `graph_search` seeds; `resolution` block everywhere | tool tests: no silent substitution, `not_found`/`ambiguous` paths; live: «Росатом» neighbours are Rosatom's |
| R4 | backfill scripts: translit pass, liveness pass, verdict alias backfill (dry-run + 200-sample review), dead-row cleanup (mirror + Milvus) | dry-run report reviewed by the user before any write |
| R5 | ingest write path: persist `name_map`/aliases; loser merge keeps aliases and cleans mirror/Milvus | ingest tests; a re-ingested doc with "ГК «Росатом»" resolves via `er_merge` |
| R6 | vector fallback (name-only kNN) — only if R0 eval shows cross-script misses left after translit | eval delta |

Order with the Lens plan: R0–R3 slot into Lens stage S3 (after S1 board write gate and S2 reranker
fixes); R4 needs the user's go-ahead (it writes to Postgres/Milvus); R5 affects ingest and ships
separately; R6 optional.

## 5. Risks / decisions
- `er_verdict` noise → aliases only for dead names with a live partner, confidence 0.85, reported;
  200-pair manual review before writing (decision 3, accepted).
- The same `norm()` must serve board keys and the resolver (decision 4, accepted) — changing it later
  changes every board key; extract it unchanged.
- Canonical display names stay as stored (Latin "Rosatom"); the resolution block shows what was asked
  (decision 2, accepted).
- Nebula `entity_name_idx` stays; the resolver's lexical steps run on Postgres, so the mirror must be
  kept in sync (R5 cleans it on merges).
