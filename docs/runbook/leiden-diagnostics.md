# Leiden community detection — diagnostics

When `POST /admin/communities/rebuild` reports **0 communities** on a graph
that clearly has entities, the cause is almost always a **sparse / disconnected
`Entity` graph** (singletons dropped by `community_min_size`), not a Leiden
performance limit (Leiden runs in the worker on igraph via `leidenalg`; 50k
nodes is seconds).

Since `detect_communities` is fail-soft, the worker log distinguishes the
three cases — check it first:

- `communities: leidenalg detection FAILED: …` (or `graphscope detection
  FAILED`) (ERROR) → a real fault (edge export / nGQL error, missing
  `leidenalg`/`igraph`, OOM in the worker). Fix the infra.
- `Leiden returned 0 rows — projected 0 entities / 0 relationships` → empty /
  disconnected edge export. See the checks below.
- `detected 0 communities … from N rows — projected P entities / R relationships`
  with R small relative to P → all-singletons; the graph has entities but too
  few edges to cluster.

## Checks

```ngql
# 1. Are there edges between entities at all? (the #1 cause of "no communities")
#    In Nebula Console / Studio, inside the KB space:
SUBMIT JOB STATS;      # wait for it to finish (SHOW JOBS), then:
SHOW STATS;            # vertices per tag (Entity) and edges per type (RELATED)
```

```bash
# 2. Connectivity — how many singletons vs real components (igraph in the API process)
curl -s -X POST -H "X-API-Key: $API_KEY" http://localhost:8000/admin/graph/components

# 3. Run Leiden directly to see the real community count + any error
uv run python -c "
from src.graph.store import build_graph_store
from src.tenancy.context import default_graph_context
from src.graph.community_leiden import extract_entity_edges, single_level_rows
edges, names = extract_entity_edges(build_graph_store(default_graph_context()))
rows = single_level_rows(edges, names, gamma=1.0)
print('edges', len(edges), 'entities', len(names),
      'communities', len({r['communityId'] for r in rows}))
"
```

## Interpreting

- `RELATED` edge count `== 0` → extraction produced entities but no relations (or merge dropped
  them). Fix is upstream (extraction/merge), not Leiden.
- `distribution` dominated by size-1 components → disconnected
  graph; lower `community_min_size` won't help much — the graph needs denser
  relations.
- community count `> 0` here but the rebuild still wrote 0 → the `min_size` floor
  is dropping them; lower `COMMUNITY_MIN_SIZE` or accept smaller communities.

## Notes

- Leiden runs **weighted** on `RELATED.weight` (distinct co-occurrence count
  from the merge layer); denser ties dominate the partition.
- `seed=19` makes runs deterministic.
- Hierarchy depth is controlled by `AGENT_COMMUNITY_MAX_LEVELS` (1 = single
  level, today's default).

## Tuning resolution & throughput

- `TEMPORAL_COMMUNITY_LEIDEN_GAMMA` (default `1.0`) is the Leiden **resolution**.
  Communities too coarse (a few giant blobs)? Raise it (`1.5`–`2.0`) for more,
  smaller communities. Too fragmented (many tiny ones)? Lower it (`0.5`–`0.8`).
  Re-run the rebuild after changing — detection is offline, off the query path.
- It is snapshotted into `DetectCommunitiesParams` at workflow-start (the
  `/admin/.../rebuild` trigger), so the activity stays Temporal-deterministic.
