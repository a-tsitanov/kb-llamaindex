# Evaluation scripts

## Community backend

`TEMPORAL_COMMUNITY_BACKEND` defaults to `leidenalg` (in-worker
leidenalg/igraph). A legacy `gds` value maps to `leidenalg` with a
warning. The Neo4j-GDS-vs-leidenalg parity gate (`bench_community_backends.py`)
that used to justify this decision was removed with Neo4j — see
`docs/superpowers/plans/2026-09-24-remove-neo4j.md`.
