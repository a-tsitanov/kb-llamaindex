# Graph Report - kb-llamaindex  (2026-10-08)

## Corpus Check
- 865 files · ~1,110,852 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 11167 nodes · 20667 edges · 1062 communities (528 shown, 534 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 855 edges (avg confidence: 0.64)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `40cad462`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- test_workflow: test_search_community.py
- test_graph: entity_vid()
- test_graph: test_lightrag_parse.py
- workflow: get_llm_pool()
- test_ingestion: test_translate_transform.py
- test_make_env.py
- retrieval: BoundedLLM
- test_workflow: graph_admin.py
- test_graph: test_communities.py
- workflow: orchestrator.py
- test_workflow: IngestParams
- test_api: search_v2.py
- test_ingestion: extract_identifiers()
- test_workflow: contracts.py
- workflow: contracts.py
- storage: push_entities()
- eval: test_scale_bench_smoke.py
- ingestion: identifiers.py
- test_api: AsyncPostgres
- graph: analysis.py
- graph: _q()
- test_graph: test_wiki_graph_ops.py
- test_graph: NebulaGraphStore
- test_graph: merge_kg_extraction()
- test_storage: ChunkRepository
- workflow: test_search_drift_roundtrip.py
- test_graph: test_event_extract.py
- config.py: Settings
- test_graph: MilvusEntityVectorStore
- graph: signals.py
- test_graph: resolve_entities()
- test_workflow: activities.py
- test_bot: Turn
- test_analytics: _FakeStore
- test_storage: test_ingest_metrics.py
- graph: entity_resolution.py
- graph: test_community_summarize.py
- graph: clamp_top_n()
- test_workflow: rerank.py
- analytics: PrimitiveResult
- analytics: Claim
- test_graph: test_nebula_schema.py
- test_workflow: test_search_global.py
- test_workflow: Ctx
- test_workflow: test_search_orchestrator.py
- test_graph: test_nebula_store_subgraph.py
- test_graph: LightRAGExtractor
- test_ingestion: test_classifier.py
- MinioStorage
- mcp: tools_server.py
- workflow: SerializedNode
- test_graph: test_aggregations_graph_ops.py
- test_scripts: datetime
- graph: communities.py
- test_graph: test_index.py
- test_config: LiteLLMSettings
- test_graph: test_nebula_store_writes.py
- api: ingest.py
- analytics: catalog.py
- test_config: test_settings.py
- superpowers: leidenalg/igraph community backend (community_backend flag)
- test_analytics: test_planner.py
- analytics: dynamics.py
- test_workflow: merge_and_resolve()
- test_observability: test_ingest_metrics_extractor.py
- graph: events_llm.py
- test_graph: test_entity_resolution.py
- retrieval: build_vector_index()
- workflow: worker.py
- setup_wikibase.py
- test_workflow: test_search_retrieve.py
- test_retrieval: test_hf_offline.py
- graph: events.py
- IngestSchedulerWorkflow
- ingest_queue: ingest_submit.py
- test_graph: test_event_merge.py
- observability: trace_request()
- retrieval: DateBounds
- events_eval.py
- test_api: analyze.py
- storage: backfill_doc_id.py
- reresolve_graph.py
- tg_ingest.py
- graph: communities.py
- test_graph: test_rollups_graph_ops.py
- build_graph_store()
- eval: score_case()
- eval: test_medical_fixture.py
- graph: MilvusCommunityReportVectorStore
- graph: domain.py
- test_analytics: test_aggregations.py
- test_analytics: _FakeOps
- bot: __main__.py
- graph: centrality.py
- test_ingestion: IdentifierCanonicalizationTransform
- workflow: _search_deps.py
- test_ingestion: index_vector.py
- test_graph: resolve()
- test_analytics: test_events_llm.py
- workflow: materialize_activities.py
- aggregations_graph_ops.py
- test_graph: write_entity_article()
- test_graph: test_er_graph_ops.py
- SEARCH.md — search subsystem deep reference
- retrieval: build_llm()
- GraphRetriever
- mcp: _shared.py
- workflow: KGExtracted
- workflow: test_search_route.py
- test_graph: test_events_llm_graph_ops.py
- wipe_db.py
- test_analytics: test_claim_nli.py
- graph: community_writeback.py
- retrieval: GroupFilter
- storage: AsyncMediaWiki
- test_analytics: config.py
- superpowers: DocumentIngestWorkflow
- build_ingestion_pipeline()
- test_scripts: test_tg_ingest_reingest.py
- analytics: materialize.py
- test_graph: extract_entity_edges()
- workflow: contextualize.py
- test_workflow: test_article.py
- test_graph: test_quality_graph_ops.py
- test_graph: test_signals_graph_ops.py
- test_graph: test_alerts.py
- test_graph: stamp_first_seen()
- test_retrieval: test_graph_walk_retriever.py
- workflow: global_search.py
- workflow: StagingStore
- eval: identifier_recall.py
- retrieval: test_answer_template.py
- test_retrieval: _StubGraphRetriever
- test_workflow: CoverageResult
- ner_eval.py
- test_api: test_ingest.py
- test_graph: test_domain_graph_ops.py
- test_graph: test_dynamics_graph_ops.py
- test_scripts: test_reresolve_graph.py
- diagrams: activity: retrieve_subquestion (hybrid)
- superpowers: WikiGraphOps Protocol (dirty bookkeeping, subgraph,
- test_graph: index.py
- test_retrieval: test_query_planner.py
- test_workflow: MapCommunitiesParams
- test_graph_edge_export.py
- test_ingest_queue: RabbitMQSettings
- test_retrieval: test_hybrid.py
- diagrams: DocumentIngestWorkflow (IngestParams to IngestResult, queue
- superpowers: Phase 3 er_vec slice —
- superpowers: channel group enum (src/retrieval/groups.py)
- superpowers: doc_group chunk metadata (mirrors doc_date_epoch
- analytics: StepResult
- test_graph: test_alert_store.py
- test_graph: ERConfig
- graph: GLiNERExtractor
- test_graph: test_communities_graph_ops.py
- diagrams: Temporal Worker (activities + workflows
- superpowers: Automatic event detection — design
- test_analytics: test_claim_extract.py
- test_graph: test_analysis_nebula.py
- graph: CanonicalLinker
- graph_edge_export.py
- graph: lightrag_extract.py
- test_graph: write_with_retry()
- test_mcp: test_tools_server.py
- run_answer_eval.py
- test_graph: test_centrality_graph_ops.py
- test_graph: test_events_graph_ops.py
- download_models.py
- test_retrieval: test_llm_factory.py
- superpowers: kb-llamaindex Conference Deck plan
- superpowers: LLMPool (per-process role lanes +
- graph: admin.py
- er_graph_ops.py
- test_retrieval: RoundGraphData
- test_workflow: push_wikibase.py
- test_graph: test_community_read.py
- ingest_scale_bottlenecks.svg: DocumentIngestWorkflow
- setup_db.py
- test_analytics: ids.py
- bot: pipeline.py
- bot: with_fallback()
- test_config: TemporalSettings
- test_graph: community_graphscope.py
- graph: community_read.py
- ingestion: identifier_transform.py
- retrieval: atomic_tools.py
- test_retrieval: get_chunks_by_doc_id()
- test_graph: _FakeClient
- superpowers: Seven Tracks plan
- di: providers.py
- merge_identifier_duplicates.py
- set_admission.py: get_temporal_client()
- graph: alert_store.py
- graph: event_ts_resolver.py
- test_api: test_search_v2_routes.py
- test_analytics: _FakeOps
- test_graph: test_retriever_triplet_parse.py
- test_ingest_queue: test_consumer.py
- Architecture Decision Records (ADR) practice
- ANALYTICS-GUIDE.md: Centralities (four notions of importance)
- CONCEPTS.md: Entity Resolution (ER)
- superpowers: Wikibase populator runbook
- superpowers: Agentic Search plan (Plan #2)
- workflow: wiki_sweep.py
- build_er_graph_ops()
- Neo4jWikiGraphOps
- test_workflow: select_communities_descent()
- eval: run_scale_bench.py
- test_retrieval: test_atomic_tools.py
- test_storage: test_minio_stream.py
- superpowers: NebulaGraph cutover — neo4j decommissioned
- superpowers: Spec — Seven Tracks (build
- test_workflow: dispatch_for_route()
- eval: diag_kg_lightrag.py
- Neo4jAggregationsGraphOps
- Neo4jAnalyticsGraphOps
- workflow: retrieve.py
- test_retrieval: test_graph_path_depth.py
- diagrams: GlobalSearchWorkflow (mode=global): GraphRAG map-reduce over
- presentation: Conference deck A (tech/ML)
- superpowers: Nebula community-BUILD (nGQL) implementation plan
- message_stats.py
- test_config: test_preflight.py
- AnalyticsGraphOps
- test_graph: test_store.py
- ARCHITECTURE.md: DocumentIngestWorkflow
- test_analytics: detect_contradictions_e2e()
- ARCHITECTURE.md: Production docker-compose
- superpowers: GraphRetriever.for_store (store-only, no PropertyGraphIndex)
- api: stats.py
- test_graph: test_retriever_fulltext.py
- WikiGraphOps
- eval: bench_flat_vs_hnsw()
- CONCEPTS.md: LLMPool concurrency gating
- runbook: DocumentIngestWorkflow (parent)
- adr: Neo4j property graph store
- ANALYTICS-GUIDE.md: Community detection / Leiden
- CONCEPTS.md: Local search (vector + graph
- superpowers: WikiSweepWorkflow (dirty-entity sweep)
- test_retrieval: find_entity_by_name()
- test_api: test_documents.py
- test_graph: _FakeWriteback
- superpowers: LLMPool (per-process role-keyed pool)
- superpowers: Community-detection offload from Neo4j —
- NebulaEventsLlmGraphOps
- retrieval: GraphRetrieverProtocol
- test_observability: test_litellm_models.py
- test_scripts: test_merge_identifier_duplicates.py
- test_workflow: _FakeNebulaStore
- nebula_bootstrap.py: _connect()
- ARCHITECTURE.md: Neo4j property graph store
- superpowers: EntityVectorStore seam (knn/upsert)
- backfill_er_vector.py: configure_logging()
- ingest_medical.py
- test_scripts: _pages_to_delete()
- KbGraphStore
- test_analytics: test_domain.py
- test_graph: test_community_vector_store.py
- runbook: Per-role/tier LLM selection
- presentation: 5-step ingestion pipeline
- runbook: Milvus chunk vector index
- Runbook index
- superpowers: GET /api/v1/documents/{doc_id} download endpoint
- superpowers: Hermes ↔ kb-llamaindex RAG integration
- build_property_graph_index()
- check_ingestion.py
- test_config: WikiSettings
- test_graph: schema.py
- ingestion: _extract_addresses()
- retrieval: pick_priority()
- test_analytics: test_communities.py
- test_api: test_graph_admin.py
- test_mcp: test_hermes_skill.py
- test_mcp: test_search_server.py
- test_workflow: test_completion_no_walltime_cap.py
- knowledge-base Hermes skill (routes to kb-llamaindex
- tg_ingest.py: load_state()
- eval: hermes_scenarios.py
- test_api: test_admin_wiki.py
- test_api: test_monitor_route.py
- test_api: test_route_skeletons.py
- test_scripts: test_setup_db.py
- CONCEPTS.md: ANN vector search
- INGEST.md: GraphBuildWorkflow (child)
- graph_refresh.sh
- graph: AlertStore
- graph: NoOpKGExtractor
- test_ingestion: build_custom_kg_payload()
- retrieval: _injected_params()
- eval: graph_depth_probes.py
- test_analytics: test_rollups.py
- test_graph: _Boom
- test_workflow: test_search_pooled_llm.py
- CAPACITY_TUNING.md: LLM_POOL_N throttle
- superpowers: Graph-scale follow-ups (items 8/13/12) plan
- superpowers: GraphScope community backend (distributed single-level
- superpowers: Analytics query fixes implementation plan
- superpowers: scripts/make_env.py builder
- Grafana datasources provisioning (Prometheus prom-kb +
- smoke.sh
- conftest.py
- eval: test_identifier_recall_thresholds.py
- test_graph: _is_exempt()
- test_mcp: test_hermes_config_example.py
- ARCHITECTURE.md: Postgres (documents, ingest_metrics)
- superpowers: Wiki article quality + source-download
- superpowers: Marp two-version deck (A tech
- superpowers: TG → ingest test harness
- graph: read_alerts()
- test_api: test_health.py
- test_mcp: test_kb_analyze_registered.py
- test_workflow: test_community_build_hardening.py
- ANALYTICS-GUIDE.md: Link prediction (LIKELY_LINK)
- ingest_scale_bottlenecks.svg: Postgres (psycopg connect per call)
- superpowers: Conversation history (multi-turn search) plan
- superpowers: Deploy redesign Batch 2 (single
- superpowers: Deploy redesign Batch 3 (DX)
- start.sh
- mcp: __init__.py
- workflow: __init__.py
- workflow: __init__.py
- workflow: __init__.py
- eval: __init__.py
- test_workflow: _stub_activity_ctx()
- CONCEPTS.md: Conversation history contextualization
- pyproject.toml: kb-llamaindex
- eval: Synthetic scale-bench harness README (250k-entity
- ERGraphOps seam (ensure_verdict_schema/load_verdicts/store_verdicts/merge_loser_into_canonical)
- test_stats_routes.py
- _FakeVal
- test_entity_vector_store.py
- Automatic event detection — design
- Nebula community-BUILD (nGQL) — full BUILD stage, backend-dispatched
- LiteLLM proxy Redis response cache
- NebulaGraph migration plan (Phases 0-4; strangler-fig, backend-dispatched)
- Continuous Wiki Article Editor plan
- AnalyticsGraphOps seam (Protocol; Neo4j-verbatim + Nebula-nGQL impls; build_analytics_graph_ops)
- _timeline
- alerts.py
- test_config_wave2.py
- test_rollups.py
- AnalyticsGraphOps seam (Protocol; Neo4j-verbatim + Nebula-nGQL impls; build_analytics_graph_ops)
- find_entity_by_name tool
- CLAUDE.md
- Wiki-editor runbook
- test_search_deps_lock.py
- Capacity Tuning Under Load
- PostgresERVerdictCache
- Конвейер инжеста
- Runbook по аналитике ingest
- Hermes ↔ RAG Integration plan
- test_community_build_hardening.py
- Архитектура
- Часть 3 — Поиск и извлечение
- Runbook — допуск документов (admission control)
- Search — памятка по использованию и тюнингу
- File Structure
- Часть 1 — Основы и инжест
- Runbook: аналитика по графу (analytical-query layer)
- Runbook: пакетная консолидация графа (`reresolve_graph`)
- bench_graph_write
- ConnectionPool
- Часть 4 — Якорь знаний, выходы, модели и эксплуатация
- Runbook — входной классификатор документов
- Runbook — backfill `doc_id` на legacy-чанки Milvus
- _StubCursor
- ER native vector kNN (снятие окна 5000)
- Hermes Agent integration runbook
- Leiden community detection — diagnostics
- Message statistics
- test_medical_source_chunks_through_pipeline
- Hermes Agent integration runbook
- Manual channel reingest + low-priority lane
- LLMRole
- PropertyGraphIndex
- test_summarize_produces_report_and_persists
- Таблица сущностей в Postgres для поиска
- Continuous wiki editor (WikiSweepWorkflow)
- DetectCommunitiesParams
- test_search_v2_routes.py
- test_community_vector_store.py
- _gather_context
- Optional Synthesis Implementation Plan
- Global Constraints
- ingest.py
- backfill_er_vector.py
- handle_agent
- Hermes Agent integration runbook
- handle_entity
- build_search_query
- Rerank Orders the Output Implementation Plan
- BACKLOG.md
- Дорожная карта — разделение контуров данных
- Distinguish "could not compute" from "computed zero" Implementation Plan
- Мост к openclaw: РЕШЕНО одним флагом
- Global Constraints
- WikiSettings
- Any
- Технический долг, найденный по ходу
- Close the Statistics Subsystem Gaps Implementation Plan
- load_state
- Пред-существующие дефекты репозитория
- _FakeResp
- _FakeEntity
- _patch_deps
- DynamicsGraphOps
- CommunityBuildWorkflow
- reset_for_tests
- ._validate_iso_date
- .achat
- test_community_vector_store.py
- 0. Продакшен: контейнеризованный compose
- Move the ER verdict cache out of the graph
- test_completion_no_walltime_cap.py
- _walk_seeds
- _FlakyStore
- load_medical_source
- test_config_wave2.py
- test_search_pooled_llm.py
- pg_sync_pool.py
- .get
- Design
- Design
- Design
- Design
- Design
- admin.py
- Phase 2 — Inference
- Speed up `merge_and_resolve` on single-document ingest
- Per-role LLM models + split merge into a child workflow
- Agentic Search Implementation Plan (Plan #2)
- Source Document Download + Search Document Links — Implementation Plan
- Analytics Layer — Activation / Rollout Runbook (Waves 0–3)
- Global Constraints
- Channel Message Statistics Implementation Plan
- Search date filters — design
- Phase 4 (slice) — distributed community-detection via GraphScope, benchmark-first
- Nebula analytics Tier-A port (nGQL) — remaining primitive families
- Nebula community-SUMMARIZE (nGQL) — backend-dispatched
- Nebula graph-compute read (extract_entity_edges + RELATED weight) — end-to-end community-detection under nebula
- build_alert_store
- NebulaCommunityWriteback
- Дорожная карта — аналитический слой и его развитие
- Wikibase populator runbook
- Поток поиска
- Hermes ↔ RAG Integration Implementation Plan
- K+N throttle migration — Implementation Plan
- Global Constraints
- Analytics Layer — LOCAL dev Activation (host-run app + dockerized infra)
- Global Constraints
- Вынос community-detection из Neo4j — дизайн
- Nebula analytics — connections primitive (nGQL) + AnalyticsGraphOps pattern
- Nebula community-READ (map summaries, nGQL) — backend-dispatched
- Nebula ingest write batching — throughput scale-blocker
- Nebula wiki-editor graph ops — the cutover CRASH-set port
- Manual channel reingest command + low-priority ingest lane
- Claim
- fetch_source
- Extraction Quality & Canonical Linking Implementation Plan
- File Structure
- Interactive `.env` Builder Implementation Plan
- LLM Pool Consolidation Implementation Plan
- Global Constraints
- File Structure
- Spec — Seven Tracks (2026-06-15)
- stats.py
- test_retriever_fulltext.py
- Очереди задач Temporal
- QUICKSTART — быстрый запуск kb-llamaindex
- Identifier-aware Search Quality Plan
- Plan — Seven Tracks (2026-06-15)
- Approach — contextualize, don't dump
- Measured numbers (Apple Silicon dev box, live local stack)
- Bruno API-коллекция — kb-llamaindex
- Hierarchical communities + dynamic community selection Implementation Plan
- Deploy redesign — Batch 1 (correctness) Implementation Plan
- Deploy redesign — Batch 2 (single source of truth) Implementation Plan
- File Structure
- File Structure
- 12. Further development / Roadmap
- Phase 2 (vertical slice) — Nebula read-path design
- Search date filters — implementation plan (Rev 2)
- Global Constraints
- TG → ingest test harness — Implementation Plan
- File Structure
- Global Constraints
- Changelog
- ADR-0001: Temporal для надёжной оркестрации
- ADR-0003: Изоляция очередей задач во избежание head-of-line блокировки
- ADR-0007: Entity Resolution = генерация кандидатов + LLM-судья + кэш вердиктов + union-find
- ADR-0008: Опциональный native-vector kNN ER поверх окна в 5000 строк
- ADR-0010: Динамический выбор сообществ (лексический / семантический / спуск, fail-open)
- ADR-0011: Plan-execute SearchOrchestratorWorkflow (Self-RAG/ReAct удалён) + ограниченный цикл покрытия
- ADR-0014: Скачивание исходных документов через стабильный API-endpoint (не presigned URL)
- NebulaGraph cutover — neo4j decommissioned
- Wiki article quality + source-download links — Implementation Plan
- Deploy redesign — Batch 3 (DX) Implementation Plan
- 4. Primitive catalog
- ADR-0009: Иерархические сообщества Leiden + структурированные отчёты (GraphRAG-style global)
- Hermes Agent integration runbook
- Индекс runbook'ов
- nGQL translation rules for the analytics port (live-proven, nebula 3.8)
- Conversation history (multi-turn search) Implementation Plan
- Graph-scale follow-ups (items 8 / 13 / 12) Implementation Plan
- Analytics Layer — PROD Activation Checklist (Waves 0–3)
- Knowledge Base
- [Search R1] — 2026-05-25 — Two-tier model architecture
- [R1] — 2026-05-11 — Model migration to qwen3:8b
- [Search R7b] — 2026-05-26 — Legacy search cutover (BREAKING)
- [Search R5] — 2026-05-26 — Large-tier synthesis queue + unified rerank
- [Search R2] — 2026-05-26 — Plan-execute orchestrator + /search/local
- [Ingest Merge Queue] — 2026-05-26 — Dedicated kb-ingest-merge queue
- [post-Stage-9 fixes] — 2026-05-11 — Live KG extraction wired
- [Stage 0] — 2026-05-09 — Bootstrap
- [Source Trust] — 2026-08-30 — Доверие к источнику решает конфликты фактов
- [Search R7a] — 2026-05-26 — Query routing + GraphRAG global search (additive)
- [Search R6] — 2026-05-26 — Offline community build (GDS Leiden + summaries)
- [Search R4] — 2026-05-26 — Coverage gate on orchestrator
- [Search R3] — 2026-05-26 — Multi-hop graph_walk tool
- [Stage 9] — 2026-05-09 — Eval gate + ops scripts
- [Stage 8] — 2026-05-09 — FastAPI + Taskiq worker
- [Stage 7] — 2026-05-09 — Identifier canonicalization
- [Stage 6] — 2026-05-09 — Knowledge graph (PropertyGraphIndex)
- [Stage 5] — 2026-05-09 — Hybrid retrieval (BM25 + vector + RRF)
- [Offline Models] — 2026-05-26 — Offline HF model loading + pre-download script
- [Stage 4] — 2026-05-09 — Agentic loop (PRIORITY)
- [Stage 3] — 2026-05-09 — Vector index + basic query engine
- [Stage 2] — 2026-05-09 — IngestionPipeline (parsing + chunking)
- [Stage 1] — 2026-05-09 — Minimal infra (Milvus + Postgres + LiteLLM)
- LiteLLM vLLM config
- Evaluation scripts
- knowledge-base Hermes skill (routes to kb-llamaindex retrieval tools)
- Dedicated kb-ingest-merge queue
- R7b legacy search cutover (BREAKING)
- R1 two-tier model architecture
- Neo4j GDS Leiden (gds.leiden.stream)
- ADR-0002: Claim-check staging via MinIO
- ADR-0003: Task-queue isolation to avoid head-of-line blocking
- ADR-0005: Deterministic identifier canonicalization before LLM extraction
- ADR-0008: Optional native-vector kNN ER over 5000-row window
- ADR-0009: Hierarchical Leiden communities + structured reports
- ADR-0010: Dynamic community selection (lexical/semantic/descent)
- ADR-0013: Multi-model role/tier selection + snapshot-at-submit
- ADR-0014: Source download via stable API endpoint
- ADR-0015: Community-detection backend = in-worker leidenalg
- Architecture Decision Records (ADR) practice
- CONCEPTS.md (planned educational companion)
- kb-llamaindex RAG system
- Milvus chunk vector index
- MinIO claim-check staging
- Neo4j property graph store
- Temporal durable orchestration
- Wikibase canonical anchor
- Bonacich (1987) Power and Centrality
- Brin & Page (1998) PageRank
- Burst detection (temporal dynamics)
- Burt (1992) Structural Holes
- Centralities (four notions of importance)
- Degree centrality
- Edge et al. (2024) GraphRAG (arXiv:2404.16130)
- Eigenvector centrality
- Fortunato & Barthelemy (2007) Resolution Limit
- Freeman (1977) Betweenness centrality
- Giant component / macrostructure
- Graph quality / GIGO precondition
- Kleinberg (2003) Bursty and Hierarchical Structure
- Leiden & modularity
- Link prediction (LIKELY_LINK)
- PageRank
- Provenance-is-ground-truth rule
- Resolution limit (modularity defect)
- Composite risk scoring (MCDA)
- Traag et al. (2019) From Louvain to Leiden
- FastAPI API service
- Graph analytics (/api/v1/analyze)
- Ingest path (DocumentIngestWorkflow)
- Temporal task queues
- Search path (local/global/drift/auto)
- Temporal worker (queue pools)
- Wikibase / MediaWiki anchor
- Bruno API collection
- Bruno sample upload document (RU medical PII fixture)
- Congestion collapse (root cause of hangs)
- K+N concurrency model
- LLM_POOL_N throttle
- ANN vector search
- Claim-check pattern (MinIO staging)
- Community reports (map-reduce summarization)
- Coverage check (bounded refinement round)
- DRIFT search (local + global)
- Durable Execution (Temporal)
- FLAT vs HNSW (Milvus index)
- Global search (community map-reduce)
- Hyper-hub clamp (ER)
- LightRAG KG extraction
- Local search (vector + graph expansion)
- Native-vector kNN ER candidate source
- Document parsing & chunking
- Plan-execute orchestrator
- Neo4j property graph & indexes
- Task queue isolation / head-of-line blocking
- RAG (Retrieval-Augmented Generation)
- Reranking (bge cross-encoder)
- Text embeddings
- Union-find clustering (ER)
- ER verdict cache (:ERVerdict)
- init service (setup_db)
- Production containerized compose deployment
- wipe_db reset procedure
- Answer templates
- Drift soft fallback
- Dual walk-seed
- Graph analytics layer (Waves 0-3)
- Hierarchical communities + dynamic selection
- Relation polarity & temporal validity
- Batch graph consolidation (reresolve_graph)
- Weighted relations & tags
- Document admission control (IngestSchedulerWorkflow)
- Input document classifier (classify_document)
- DocumentIngestWorkflow
- extract_kg activity
- GraphBuildWorkflow (child)
- Graph half (extract→merge/ER→Neo4j)
- merge_and_resolve activity
- Vector half (fetch→parse→embed→Milvus)
- vector_only degradation
- Multimodel snapshot at /ingest
- Offline / air-gapped HF models
- Role to tier map (7 roles)
- Translation context budget
- Two physical model tiers (small/large)
- Entity Resolution 12-step pipeline
- Eval gate (287 tests + golden Q&A)
- IdentifierCanonicalization ingest step
- 5-step ingestion pipeline
- KG extraction fix: SchemaLLMPathExtractor -> SimpleLLMPathExtractor
- LightRAG-style KG extraction
- LiteLLM proxy (LLM/embed gateway)
- Per-request tracing (trace_request)
- Postgres job-state store
- /agent ReAct loop (8 tools)
- /selfrag reflective synthesis
- Three query endpoints: /search, /agent, /selfrag (legacy)
- Conference deck D (internal defense)
- Conscious out-of-scope decisions
- R1-R10 roadmap / status
- kb-llamaindex conference decks (Marp)
- DocumentIngestWorkflow (kb-ingest)
- extract_kg (KG extraction activity, kb-ingest-llm)
- GraphBuildWorkflow (merge lane, kb-ingest-merge)
- IngestSchedulerWorkflow (singleton admission control, Track 5)
- merge_and_resolve (merge/ER activity, merge lane)
- WikiSweepWorkflow (continuous wiki editor, kb-wiki)
- LiteLLM gateway/router
- Milvus vector store (chunks)
- MinIO object store (sources + claim-check staging)
- Neo4j graph store
- Arc 2 — continuous monitoring + alerts (risk_score)
- Admission control (IngestSchedulerWorkflow)
- ingest_metrics (Postgres per-run timings)
- Prometheus + Grafana ingest analytics
- Input document classifier (classify_document)
- doc_id backfill for legacy Milvus chunks
- Native vector kNN ER (er_vec)
- Graph analytics layer (plan->compute->synthesize, 42 primitives)
- Analytics materialization (AnalyticsMaterializeWorkflow)
- Monitoring Arc-2
- Hermes Agent integration
- Leiden community-detection diagnostics
- atomic_tools.py (pure retrieval functions)
- BoundedLLM GPU semaphore
- MCP-1 search server (5 tools via Temporal)
- MCP-2 atomic tools server
- DocumentIngestWorkflow (parent)
- GraphBuildWorkflow (child)
- LLMPool (per-process concurrency owner)
- Per-role/tier LLM selection
- vector_only fallback
- Runbook index
- Manual reingest + low-priority RabbitMQ lane
- Batch graph consolidation (reresolve_graph)
- Community rebuild trigger (/admin/communities/rebuild)
- Search modes /search/{local,global,drift,auto}
- Source download endpoint (GET /api/v1/documents/{doc_id})
- Continuous wiki editor (WikiSweepWorkflow)
- Wikibase populator (push_wikibase)
- QID writeback idempotency
- scripts/setup_wikibase.py bootstrap
- scripts/smoke_wikibase_push.py
- WDQS / Blazegraph SPARQL endpoint
- Self-hosted Wikibase
- gemma4:e4b-qat (Google QAT int4 extraction model)
- Ollama (replicated + parallel-slot inference, Path A)
- vLLM (native w4a16-ct QAT inference, Path B fallback)
- AutoSearchWorkflow (routed dispatch)
- CommunityBuildWorkflow (offline community build on kb-graph-build)
- DriftSearchWorkflow (local-then-global, bounded)
- GlobalSearchWorkflow (GraphRAG map-reduce over communities)
- map_communities — community selection (lexical/semantic/descent)
- retrieve_subquestion — deterministic retrieval pipeline
- SearchOrchestratorWorkflow (local plan-execute)
- synthesize_answer — large-tier synthesis activity
- AgentSettings config class
- Claims/covariates extraction (KG_CLAIMS_KEY)
- Cypher→nGQL MATCH translation rules
- NebulaGraph backend
- Neo4j graph backend (retained seam)
- Neo4j→nebula data-migration blocker
- Wiki-editor crash set under nebula
- Entity Resolution 12-step pipeline
- LightRAG-style KG extractor
- LiteLLM proxy gateway
- Marp Markdown decks (A/D)
- Milvus vector index
- ReAct agent (/agent, react_agent.py)
- Three search endpoints (/search /agent /selfrag)
- Pydantic v2 workflow contracts
- DocumentIngestWorkflow
- extract_kg activity
- fetch_source activity
- index_vector activity
- inject_canonical activity
- merge_and_resolve activity
- parse_and_chunk activity
- StagingStore MinIO claim-check
- Temporal workflow engine
- Canon-block out of node.text (augment_text metadata)
- consolidate_identifier_entities (all 24 types)
- Hub-aware graph traversal
- Per-query-type hybrid weighting
- LiteLLM proxy Redis response cache
- merge_kg_extraction summary fan-out
- GraphBuildWorkflow (Temporal child)
- Per-role LLM models (extraction/judge/search)
- CachedLLM (OpenAILike read-through)
- LLMCacheSettings
- push_entities orchestrator (src/storage/wikibase.py)
- push_wikibase activity
- WikibaseSettings (default disabled)
- CommunityBuildWorkflow (GDS Leiden offline)
- GlobalSearchWorkflow (community map-reduce)
- graph_walk multi-hop tool
- SearchOrchestratorWorkflow
- SubQueryRetrievalWorkflow
- Two-tier model config (small/large)
- CanonicalLinker (mention→QID)
- GLiNER optional extractor
- Multilingual NER benchmark harness
- New deterministic identifiers (BankAccount/KPP/IBAN/CreditCard)
- ER verdict cache (:ERVerdict)
- drift_mode AttributeError bug
- Flat local_dir offline HF models
- selfrag/ReAct legacy removal + dead-code audit
- find_entity_by_name tool
- entity_name_fulltext index
- documents_for_communities activity
- GET /api/v1/documents/{doc_id}
- MCP SSE servers (MCP-1 kb_search, MCP-2 tools)
- knowledge-base SKILL.md (4 pillars)
- SSE Bearer auth (StaticTokenVerifier)
- scripts/make_env.py
- BoundedLLM (ordered gates)
- LLMPool (per-process role lanes + tier globals)
- LLMPoolSettings (tier totals + lane caps)
- AsyncMediaWiki Action API client
- mark_entities_dirty ingest hook
- subgraph_hash change detection
- WikiSweepWorkflow
- write_entity_article activity
- Conversation history (multi-turn search) plan
- Drift graceful fallback to local answer
- Dual walk-seed (graph_search + fulltext)
- Graph-scale follow-ups (items 8/13/12) plan
- Hierarchical Leiden detection (detect_hierarchy)
- Hierarchical communities + dynamic selection plan
- Structured community reports (report_vec, incremental)
- Dynamic community selection (semantic kNN v1 + descent v2)
- Relation rank/cap + per-doc citation dedup
- Deterministic Источники source-download section
- K+N single-semaphore LLM pool
- K+N throttle migration plan
- Answer template (Track 6)
- doc-by-id MinIO-aware load (Track 3)
- Ingest classifier + force (Track 2)
- Seven Tracks plan
- Prod docker compose stack (Track 1)
- Relation weight + tags (Track 7a)
- Canonical embedding profile 1536/OpenAI
- init one-shot setup_db service
- Deploy redesign Batch 1 (correctness) plan
- Fail-fast Settings.preflight at boot
- Deploy redesign Batch 2 (single source of truth) plan
- Deploy redesign Batch 3 (DX) plan
- leidenalg/igraph community backend (community_backend flag)
- Community detection offload plan
- Search date filters (Rev 2) plan
- Date post-filter + over-fetch (epoch-days)
- Analytics primitive catalog (src/analytics)
- E1 first_seen novelty stamping
- Analytical Layer Wave 0 (v1a+E1+P1) plan
- Analytics planner (NL→catalog calls)
- P1 knowledge-quality signals
- AnalyticalQueryWorkflow
- AnalyticsMaterializeWorkflow (offline GDS + write-back)
- Analytical Layer Wave 1 (v1b+P2+Arc1) plan
- Composite risk_score (pure risk.py)
- P3 domain rollups (issue/communication)
- E2 LLM event extraction (:EventOrAction + dedup key)
- Arc 2 monitoring sweep + :Alert (MonitorSweepWorkflow)
- Analytical Layer Wave 2 (E2+Arc2+P3) plan
- E3 burst engine + trending_events (events_burst)
- Alert webhook delivery (deliver_alerts)
- Analytical Layer Wave 3 (E3 burst + alert push) plan
- Analytics activation LOCAL dev checklist
- Analytics activation PROD checklist
- Analytics activation rollout runbook
- IN_COMMUNITY member links at every level
- Hierarchical community leaf-context plan
- tg_ingest harness (_message_to_doc/post_ingest/read_and_enqueue)
- TG → ingest test harness plan
- E2 Event Time-Frames plan
- event_ts_resolver (deterministic time-frame resolver)
- NebulaGraphStore write adapter + nGQL schema
- NebulaGraph migration plan
- KbGraphStore seam + GRAPH_BACKEND toggle
- er_vector_backend dispatch (native/milvus, forced under nebula)
- entity_er_vec Milvus collection
- EntityVectorStore seam (knn/upsert)
- MilvusEntityVectorStore
- Neo4jEntityVectorStore (native index wrapper)
- GraphRetriever.for_store (store-only, no PropertyGraphIndex)
- NebulaGraphStore.subgraph mapper
- nGQL GET SUBGRAPH bounded walk
- nGQL LOOKUP find-by-name (afind_entities_by_name nebula branch)
- generic RELATED edge + rel_type property
- community_report_vec Milvus collection
- CommunityReportVectorStore seam
- MilvusCommunityReportVectorStore
- GraphScope community backend (distributed single-level Leiden)
- _run_graphscope_community adapter (lazy, manual-gate)
- single_level_rows_graphscope mapping
- Nebula Community TAG + level index DDL
- community_vid VID scheme (blake2b level-scoped)
- CommunityWriteback seam
- NebulaCommunityWriteback (nGQL INSERT/LOOKUP/DELETE/FETCH)
- Neo4jCommunityWriteback (verbatim Cypher)
- CommunitySummarize seam
- NebulaCommunitySummarize (GO/FETCH reads, UPDATE VERTEX write)
- Neo4jCommunitySummarize (verbatim Cypher)
- coerce_entity_type (bogus planner type → None)
- is_meaningful_entity quality gate (drop identifiers + degenerate names)
- trend-fallback keyword broadening ('упомин')
- doc_group chunk metadata (dynamic field)
- channel group enum (src/retrieval/groups.py)
- GroupFilter (Milvus push-down + graph post-filter)
- per-group rerank weights (AGENT_GROUP_WEIGHTS)
- tg_ingest resolve_group_map (folder → group)
- x-max-priority RabbitMQ ingest queue
- ingest priority lane (PRIO_LIVE=5 / PRIO_BACKFILL=0)
- reingest_channels (folder-scoped, low-priority)
- status_counts_by / timeline_counts (shared SQL)
- message_stats CLI (channels/groups/timeline)
- documents.source_channel/source_group columns + backfill
- /stats/messages + /stats/timeline endpoints
- Marp two-version deck (A tech / D internal)
- Three-endpoints narrative (/search, /agent, /selfrag)
- MinIO claim-check staging (kb-staging blobs)
- DocumentIngestWorkflow
- 8 Temporal ingest activities (fetch/parse/index/kg/merge/build/finalize)
- documents status (completed / vector_only / failed)
- afind_entities_by_name (fulltext partial-name recall)
- find_entity_by_name atomic tool
- entity_name_fulltext Neo4j index
- graph_similarity_top_k vector-recall lift (10→20)
- DocumentRef search-response document links
- GET /api/v1/documents/{doc_id} download endpoint
- MinioStorage stream_object / stat_object
- Hermes Agent (persistent MCP-client consumer)
- knowledge-base SKILL.md (tool-selection + templates)
- kb MCP-2 tools_server (6 atomic tools, SSE)
- cross-field validation (MILVUS_DIM, LLM_POOL sizing, Temporal caps)
- scripts/make_env.py builder
- parse_example structure-preserving model (Line/KV)
- BoundedLLM gating wrapper (ordered semaphores)
- hierarchical tier+lane sizing (over-subscription + judge_floor)
- LLMPool (per-process role-keyed pool)
- AsyncMediaWiki client (Action API)
- render_bot_section / splice_bot_section (anti-drift, grounded)
- subgraph_hash dirty tracking (skip unchanged)
- WikiSweepWorkflow (dirty-entity sweep)
- client-managed bounded history (stateless)
- contextualize_query activity (follow-up → standalone)
- detect_hierarchy (Leiden intermediate levels + PARENT_OF)
- dynamic community selection (v1 semantic kNN + v2 hierarchy descent)
- community_report_vec native Neo4j index
- structured community reports (bottom-up, incremental via members_hash)
- relation ranking+cap (WIKI_MAX_RELATIONS) + citation dedup
- Источники source-download section (deterministic)
- subgraph_hash source_doc_ids fix
- IngestAdmission K (always-on max_inflight)
- K+N throttle model (single N semaphore + FIFO K admission)
- LLM pool leak fix (4 ungated search activities)
- Track 6 — templated answers (answer_template threaded through synthesis)
- Track 2 — input document classifier (skip) with force-override
- Track 1 — production docker-compose (whole app in compose, external litellm/ollama)
- Track 5 — document-level admission control (IngestSchedulerWorkflow, MAX_INFLIGHT_DOCS)
- Track 7a — meaningful relation weight + tags (mention_count/confidence, provenance aggregation)
- Track 3 — source-document-by-id bugfix (doc_id in Milvus + MinIO-aware chunk_repository)
- Track 4 — weighted Leiden at 50k: instrumentation + knobs (no silent GDS-error swallow)
- Canonical embedding profile: text-embedding-3-small / 1536 (Ollama nomic/768 opt-in override)
- config.py as single source of truth (make_env generates .env.example, --check drift/coverage/orphan)
- init one-shot service — auto-run setup_db (service_completed_successfully gate)
- Settings.preflight() — fail-fast boot validator (hard-exit in production)
- community_backend config selector (gds|leidenalg, default gds until parity benchmark)
- Edge-extractor — streams (s.name,t.name,weight) in batches (no GDS projection)
- leidenalg + python-igraph clusterer (hierarchical Leiden in worker RAM)
- Single stamping point in parse_and_chunk (chunk metadata epoch dates → Milvus + :Chunk)
- epoch-days canonical filter value (doc_date_epoch, inserted_at_epoch)
- Uniform post-filter for both stores (over-fetch + drop out-of-range; Milvus push-down deferred)
- AnalyticalQueryWorkflow (plan → execute primitives|cypher → synthesize + provenance)
- AnalyticsMaterializeWorkflow (offline GDS: centrality/link-prediction → Neo4j properties)
- cypher_guard — guarded read-only text-to-Cypher fallback (denylist, timeout, LIMIT; kill switch)
- analytical planner (small-tier LLM NL → validated AnalysisPlan)
- Primitive catalog (~24 primitives, 4 families; open/closed registry in catalog.py)
- Provenance chain (answer + primitive/Cypher + raw rows + source chunks; numbers from executor not LLM)
- 'quality & action' primitive family (contradictions, completeness, orphans, merge candidates)
- Action queues & leads (investigate-next, review queue, recommended merges, watchlist hits)
- risk_score(entity) — transparent weighted composite (affiliation/brokerage/controversy/volatility/opacity), materialized offline
- M3 burst detector (offline z-score/Kleinberg over mention series → :BurstEvent)
- Event model — :__Entity__:EventOrAction specialization (event_type/trigger/event_ts + created_at)
- Event resolution/dedup (event-specific match key: type + participants + event_ts proximity)
- first_seen / created_at stamping (ON CREATE on nodes/rels/events; one-time backfill sentinel)
- events_burst engine + trending_events primitive (burst axis = created_at, DRY build_burst_cypher)
- MonitorSweepWorkflow (detect_alerts → deliver_alerts; ship dark, gated defaults)
- Push delivery — generic outbound webhook (:Alert.pushed_at idempotency, deliver_alerts activity)
- ADR-0009 (hierarchical-leiden) + ADR-0010 (dynamic-community-selection)
- descent community-selection mode (only mode that walks the hierarchy via PARENT_OF)
- Persist IN_COMMUNITY member-edges at all levels (_MERGE_SUBCOMMUNITY_CYPHER gains member block)
- RabbitMQ in dev compose (default service; validates INGEST_QUEUE_BACKEND=rabbitmq end-to-end)
- scripts/tg_ingest.py (Telethon backfill → POST /api/v1/ingest per message)
- dateparser dependency (offline, RELATIVE_BASE = doc_date; nearest-to-doc-date for year-less dates)
- event_ts_resolver.py — pure resolve(raw, doc_date_epoch) → (start,end,precision) (pre-rules + dateparser)
- EventOrAction interval fields (event_ts_raw, event_start_epoch, event_end_epoch, event_ts_precision)
- Milvus collection entity_er_vec (PK name, er_vec FLOAT_VECTOR dim=1536 COSINE HNSW, canonicals only)
- EntityVectorStore seam (Protocol knn/upsert; Neo4j + Milvus impls; build_entity_vector_store)
- AgentSettings.er_vector_backend (native|milvus, default native; nebula forces Milvus)
- find-by-name → nGQL LOOKUP ON Entity (parity gap vs Neo4j fulltext, accepted)
- Generic RELATED edge + rel_type property (entity–entity relations avoid edge-label injection)
- bounded walk → nGQL GET SUBGRAPH (VID deterministic; no server-side cap — flagged risk)
- Milvus collection community_report_vec (PK community_id:level, filter='level==N' during search)
- CommunityReportVectorStore seam (Neo4j + Milvus impls; build_community_report_vector_store)
- community_backend='graphscope' (single-level Leiden distributed; lazy import; NMI/ARI benchmark gate)
- AnalyticsGraphOps seam (Protocol; Neo4j-verbatim + Nebula-nGQL impls; build_analytics_graph_ops)
- connections.py primitives via nGQL (entity_dossier, common_connections, connection_path; cooccurrence→[] Chunk-dependent)
- Per-family <Family>GraphOps sibling seams (aggregations/quality/domain/events/rollups/signals/communities)
- CommunityWriteback seam (ensure_schema/prune/merge_community/merge_subcommunity; community_vid)
- Nebula Community TAG + community_level_idx (report cols declared for SUMMARIZE; report_vec absent — Milvus owns it)
- CommunityRead seam (read_summaries; LOOKUP+FETCH; blank-summary drop; member_count/community_id sort)
- CommunitySummarize seam (read_member_context/read_child_reports/write_report; UPDATE VERTEX partial write)
- ERGraphOps seam (ensure_verdict_schema/load_verdicts/store_verdicts/merge_loser_into_canonical)
- ERVerdict TAG + verdict cache (er_key index; blake2b verdict_vid upsert)
- merge_loser_into_canonical (nGQL edge-redirect out+in, then DELETE VERTEX WITH EDGE last — fail-open leave-intact)
- Backend-dispatched stamp_first_seen (nebula entity UPDATE VERTEX for created_at==0; rel no-op deferred)
- upsert_nodes preserve-rework (read-back FETCH created_at/first_doc_id, re-write in INSERT; fail-open)
- detect_communities (leidenalg end-to-end under nebula)
- extract_entity_edges (routes through GraphEdgeExport seam)
- GraphEdgeExport Protocol (stream_names/stream_edges seam)
- NebulaGraphEdgeExport (LOOKUP names + batched GO over RELATED, reads weight)
- Neo4jGraphEdgeExport (keyset Cypher pagination, byte-for-byte)
- RELATED weight column (mention_count-derived, weighted Leiden parity)
- Nebula graph-compute read design (extract_entity_edges + RELATED weight)
- Multi-VALUES batching (amortise per-item round-trips ~batch_size x)
- Nebula ingest write batching design (throughput scale-blocker)
- NebulaGraphStore.upsert_nodes (batched multi-VALUES INSERT VERTEX)
- NebulaGraphStore.upsert_relations (batched multi-VALUES INSERT EDGE RELATED)
- NebulaSettings.write_batch_size (NEBULA_WRITE_BATCH_SIZE, default 256)
- build_wiki_graph_ops (backend dispatch)
- Entity TAG 6 wiki columns + entity_wiki_dirty_idx
- NebulaWikiGraphOps (nGQL UPDATE VERTEX/LOOKUP/GO/FETCH; chunk-reads return [])
- Neo4jWikiGraphOps (existing Cypher verbatim)
- Nebula wiki-editor graph ops port (cutover crash-set)
- WikiGraphOps Protocol (dirty bookkeeping, subgraph, sweep seam)
- WikiSweepWorkflow / admin wiki rebuild (previously crashed under nebula)
- Group search filter (Milvus IN/NIN MetadataFilter + graph post-filter)
- AGENT_GROUP_WEIGHTS rerank weights (official 1.30 … opinion 0.80)
- GROUPS enum (news, analytics, digest, opinion, official, data) src/retrieval/groups.py
- Channel groups design (six editorial groups → RAG)
- Synthesis group context ([group] prefix per source)
- RabbitMQSettings.max_priority (RABBITMQ_MAX_PRIORITY default 10)
- PRIO_LIVE=5 / PRIO_BACKFILL=0 priority constants
- RabbitMQ priority lane (x-max-priority queue arg)
- _run_reingest CLI mode (--reingest/--reingest-limit, folder-scoped)
- Manual channel reingest + low-priority ingest lane design
- scripts/message_stats.py CLI (channels/groups/timeline subcommands)
- documents.status CHECK adds 'skipped' (latent mark_skipped bug fix)
- documents.source_channel column + index (+ path-regex backfill)
- documents.source_group column + index (not backfillable)
- Channel message-processing statistics design
- stats.py router (/stats/messages, /stats/timeline)
- AsyncPostgres.status_counts_by (channel/group × status pivot)
- AsyncPostgres.timeline_counts (daily buckets, date_field allowlist)
- Entity dossier answer template (Russian)
- Eval scripts README (community backend parity gate GDS→leidenalg)
- _FakeVal
- backfill_er_vector.py
- test_communities.py
- test_analytics_materialize_hardening.py
- test_search_server.py
- test_value_kind_families_partition_the_enumeration
- test_stats_pipeline.py
- build_burst_cypher
- build_search_query
- test_stats_routes.py
- _NameRetriever
- schema.py
- build_tool_schema
- test_completion_no_walltime_cap.py

## God Nodes (most connected - your core abstractions)
1. `PrimitiveResult` - 130 edges
2. `entity_vid()` - 114 edges
3. `_q()` - 97 edges
4. `extract_identifiers()` - 95 edges
5. `AsyncPostgres` - 83 edges
6. `Primitive` - 70 edges
7. `build_graph_store()` - 66 edges
8. `_Frozen` - 61 edges
9. `_FakeStore` - 61 edges
10. `SerializedNode` - 60 edges

## Surprising Connections (you probably didn't know these)
- `test_channel_message_stats_maps_group_by_and_calls_pg()` --indirect_call--> `AsyncPostgres`  [INFERRED]
  tests/test_mcp/test_tools_server.py → src/storage/postgres.py
- `test_channel_message_timeline_stringifies_day()` --indirect_call--> `AsyncPostgres`  [INFERRED]
  tests/test_mcp/test_tools_server.py → src/storage/postgres.py
- `Production docker-compose` --conceptually_related_to--> `Neo4j property graph store`  [AMBIGUOUS]
  docker-compose.prod.yml → docs/ARCHITECTURE.md
- `Telegram bot overlay` --semantically_similar_to--> `OpenClaw agent gateway overlay`  [INFERRED] [semantically similar]
  docker-compose.bot.yml → docker-compose.openclaw.yml
- `_run_search()` --calls--> `render()`  [INFERRED]
  src/bot/commands.py → scripts/make_env.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Ingest pipeline (workflow + claim-check staging)** — docs_ingest_document_ingest_workflow, docs_ingest_extract_kg, docs_ingest_merge_and_resolve, docs_ingest_graph_build_workflow, docs_concepts_claim_check [INFERRED 0.85]
- **LLM concurrency & capacity model** — docs_concepts_llmpool, docs_concepts_queue_isolation, docs_capacity_tuning_llm_pool_n, docs_models_two_tier [INFERRED 0.80]
- **GraphRAG global search** — docs_concepts_leiden, docs_concepts_community_reports, docs_concepts_global_search, docs_features_hierarchical_communities [INFERRED 0.80]
- **Benchmark-gated adoption (measure recall/latency/parity before flipping a default)** — docs_adr_0006_milvus_hnsw_default_index, docs_adr_0008_native_vector_knn_er, docs_adr_0015_community_detection_backend_leidenalg, docs_scale_phase2_3 [INFERRED 0.75]
- **Offline decoupled community build on kb-graph-build (Leiden hierarchy → structured reports)** — docs_search_communitybuildworkflow, docs_adr_0009_hierarchical_leiden_communities, docs_adr_0015_community_detection_backend_leidenalg, docs_queues [EXTRACTED 0.85]
- **Fail-open degradation philosophy across the live search path (never hard-fail on a flaky helper)** — docs_search, docs_adr_0011_plan_execute_search_orchestrator, docs_adr_0010_dynamic_community_selection [INFERRED 0.75]
- **kb-llamaindex storage / infra map** — docs_adr_readme_kb_llamaindex, docs_adr_readme_milvus, docs_adr_readme_neo4j, docs_presentation_kb_llamaindex_conf_a_postgres, docs_presentation_kb_llamaindex_conf_a_litellm [EXTRACTED 0.85]
- **5-step ingestion pipeline stages** — docs_presentation_kb_llamaindex_conf_a_ingestion_pipeline, docs_presentation_kb_llamaindex_conf_a_identifier_canonicalization, docs_presentation_kb_llamaindex_conf_a_lightrag_extraction, docs_presentation_kb_llamaindex_conf_a_cross_chunk_merge, docs_presentation_kb_llamaindex_conf_a_entity_resolution [EXTRACTED 0.85]
- **Graph analytics layer components** — docs_runbook_graph_analytics_analyze_layer, docs_runbook_graph_analytics_materialize, docs_runbook_graph_analytics_monitor_arc2 [EXTRACTED 0.85]
- **DocumentIngestWorkflow ingest activity chain** — docs_superpowers_plans_2026_05_15_ingest_temporal_workflow_documentingest, docs_superpowers_plans_2026_05_15_ingest_temporal_workflow_fetch_source, docs_superpowers_plans_2026_05_15_ingest_temporal_workflow_parse_and_chunk, docs_superpowers_plans_2026_05_15_ingest_temporal_workflow_extract_kg, docs_superpowers_plans_2026_05_15_ingest_temporal_workflow_merge_and_resolve [EXTRACTED 1.00]
- **Agentic search workflow decomposition** — docs_superpowers_plans_2026_05_25_agentic_search_orchestrator, docs_superpowers_plans_2026_05_25_agentic_search_subquery, docs_superpowers_plans_2026_05_25_agentic_search_global, docs_superpowers_plans_2026_05_25_agentic_search_community_build [EXTRACTED 1.00]
- **LLM gating + response-cache stack** — docs_superpowers_plans_2026_06_06_llm_pool_consolidation_llmpool, docs_superpowers_plans_2026_06_06_llm_pool_consolidation_boundedllm, docs_superpowers_plans_2026_05_18_redis_llm_cache_cachedllm, docs_superpowers_plans_2026_05_18_llm_cache_litellm_redis [INFERRED 0.75]
- **Analytical Layer program (Waves 0-3)** — docs_superpowers_plans_2026_06_28_analytical_layer_wave0_plan, docs_superpowers_plans_2026_06_29_analytical_layer_wave1_plan, docs_superpowers_plans_2026_06_30_analytical_layer_wave2_plan, docs_superpowers_plans_2026_07_01_analytical_layer_wave3_plan [EXTRACTED 0.95]
- **Deploy redesign program (Batches 1-3)** — docs_superpowers_plans_2026_06_16_deploy_redesign_batch1_plan, docs_superpowers_plans_2026_06_16_deploy_redesign_batch2_plan, docs_superpowers_plans_2026_06_16_deploy_redesign_batch3_plan [EXTRACTED 0.95]
- **Analytics activation runbooks (local/prod/rollout)** — docs_superpowers_plans_2026_07_01_analytics_activation_local_plan, docs_superpowers_plans_2026_07_01_analytics_activation_prod_plan, docs_superpowers_plans_2026_07_01_analytics_activation_rollout_plan [EXTRACTED 0.90]
- **Nebula backend migration seams (read / build / summarize)** — docs_superpowers_plans_2026_07_10_nebula_read_slice_plan_graphretriever_for_store, docs_superpowers_plans_2026_07_11_nebula_community_build_communitywriteback_seam, docs_superpowers_plans_2026_07_11_nebula_community_summarize_communitysummarize_seam [INFERRED 0.75]
- **Milvus opt-in vector-store seam pattern (er_vec + report_vec)** — docs_superpowers_plans_2026_07_10_er_vec_milvus_plan_entityvectorstore_seam, docs_superpowers_plans_2026_07_10_er_vec_milvus_plan_entity_er_vec_collection, docs_superpowers_plans_2026_07_10_report_vec_milvus_plan_communityreportvectorstore_seam [INFERRED 0.85]
- **Telegram ingest extensions threaded through tg_ingest post_ingest** — docs_superpowers_plans_2026_07_21_channel_groups_group_enum, docs_superpowers_plans_2026_07_22_tg_reingest_command_reingest_channels, docs_superpowers_plans_2026_07_23_channel_message_stats_source_columns [INFERRED 0.75]
- **Backend-dispatched seam pattern (Protocol + Neo4j-verbatim + Nebula-nGQL + build_* dispatch) across the NebulaGraph migration** — docs_superpowers_specs_2026_07_11_nebula_analytics_connections_design_analytics_graph_ops, docs_superpowers_specs_2026_07_11_nebula_community_build_design_community_writeback, docs_superpowers_specs_2026_07_11_nebula_entity_resolution_design_er_graph_ops, docs_superpowers_specs_2026_07_10_er_vec_milvus_design_entity_vector_store [INFERRED 0.85]
- **Graph-analytics product suite: compute primitives + event detection + actionable signals** — docs_superpowers_specs_2026_06_24_analytical_layer_design, docs_superpowers_specs_2026_06_25_event_detection_design, docs_superpowers_specs_2026_06_25_actionable_signals_design [EXTRACTED 0.90]
- **Community lifecycle on Nebula: BUILD → SUMMARIZE → READ backend-dispatched seams** — docs_superpowers_specs_2026_07_11_nebula_community_build_design_community_writeback, docs_superpowers_specs_2026_07_11_nebula_community_summarize_design_community_summarize, docs_superpowers_specs_2026_07_11_nebula_community_read_design_community_read [EXTRACTED 0.90]
- **NebulaGraph migration design specs (2026-07-11 batch)** — docs_superpowers_specs_2026_07_11_nebula_graph_compute_read_design_spec, docs_superpowers_specs_2026_07_11_nebula_ingest_batch_design_spec, docs_superpowers_specs_2026_07_11_nebula_wiki_ops_design_spec [INFERRED 0.85]
- **doc_group used in search filter, rerank, and synthesis** — docs_superpowers_specs_2026_07_21_channel_groups_design_group_search_filter, docs_superpowers_specs_2026_07_21_channel_groups_design_group_weights, docs_superpowers_specs_2026_07_21_channel_groups_design_synthesis_group_context [EXTRACTED 1.00]
- **Shared AsyncPostgres aggregation consumed by HTTP route and CLI** — docs_superpowers_specs_2026_07_23_channel_message_stats_design_status_counts_by, docs_superpowers_specs_2026_07_23_channel_message_stats_design_stats_router, docs_superpowers_specs_2026_07_23_channel_message_stats_design_message_stats_cli [EXTRACTED 1.00]

## Communities (1062 total, 534 thin omitted)

### Community 0 - "test_workflow: test_search_community.py"
Cohesion: 0.10
Nodes (32): Input to ``summarize_community_activity`` — summarise ONE     community's member, SummarizeCommunityParams, Generate a STRUCTURED REPORT for ONE community via the small LLM,     embed it,, summarize_community_activity(), group_specs_by_level(), Group summarize specs by ``level``, FINEST-first.      Returns a list of per-lev, _FakeEmbed, _FakeLLM (+24 more)

### Community 1 - "test_graph: entity_vid()"
Cohesion: 0.05
Nodes (68): entity_vid(), Stable 128-bit VID as a 32-char hex string from an entity name.      read/write, _FakePath, _NebulaRaisingStore, _NebulaRecStore, _RaisingStore, Always raises on structured_query — used to assert the seam's     fail-soft try/, Records nGQL statements (positional; nebula never binds param_map);     returns (+60 more)

### Community 2 - "test_graph: test_lightrag_parse.py"
Cohesion: 0.07
Nodes (52): _first_keyword(), _normalize_entity_name(), parse_lightrag_output(), parsed_relations_to_relations(), Relation, Extract the first comma-separated keyword from the relation     `relationship_ke, Verbatim time phrase or None — reject polarity/location/participant     debris t, Parse one LightRAG extract response.      Strategy:      1. Strip `<think>...</t (+44 more)

### Community 3 - "workflow: get_llm_pool()"
Cohesion: 0.04
Nodes (87): ``synthesize_answer`` activity — final answer composition.  Plain ResponseSynthe, Prepend the channel group so the synthesis LLM sees each source's     type/trust, Compose the final answer over accumulated context., synthesize_answer(), with_group_prefix(), Wire-friendly projection of LlamaIndex ``NodeWithScore``.      Only the bits the, Input to the ``rerank_sources`` activity (Search R5).      The merged graph+vect, RerankParams (+79 more)

### Community 4 - "test_ingestion: test_translate_transform.py"
Cohesion: 0.08
Nodes (46): DocumentTranslateTransform, _drop_doc_translation_metadata(), _exclude_doc_translation_metadata(), _looks_russian(), Any, BaseNode, TransformComponent, Per-chunk translation step that normalises ingest input to Russian without losin (+38 more)

### Community 5 - "test_make_env.py"
Cohesion: 0.07
Nodes (70): Line, Blank, build_reference(), build_values(), Comment, EnvVar, gen_secret(), _int() (+62 more)

### Community 6 - "retrieval: BoundedLLM"
Cohesion: 0.05
Nodes (78): main(), _parse_args(), prepare_txt(), Namespace, Path, Ingest the Medical benchmark corpus through `/api/v1/ingest`.  Converts `tests/e, Materialize medical.json → medical.txt in /tmp for upload., aggregate_by() (+70 more)

### Community 7 - "test_workflow: graph_admin.py"
Cohesion: 0.14
Nodes (21): CentralityIn, LinkPredictionIn, RiskIn, test_centrality_in_defaults(), test_link_prediction_in_empty(), Tests for materialize_activities (centrality + link prediction + risk)., _RISK_WRITE must capture the old risk_score into risk_score_prev BEFORE overwrit, If _with_projection returns None (projection failed), error must be non-empty. (+13 more)

### Community 8 - "test_graph: test_communities.py"
Cohesion: 0.05
Nodes (69): _coarsest_from_rows(), detect_communities(), detect_hierarchy(), _drop_cypher(), _graphscope_rows(), _group_by_levels(), _leiden_rows(), _leiden_stream_cypher() (+61 more)

### Community 9 - "workflow: orchestrator.py"
Cohesion: 0.10
Nodes (25): Scorer, entity_text(), GraphRanker, match_bucket(), Any, Relevance ranking of graph tool results against a question.  The graph tools ret, Like ``rank``, plus ``meta``: ``ranked`` (a scorer's order was applied),, _Data (+17 more)

### Community 10 - "test_workflow: IngestParams"
Cohesion: 0.06
Nodes (47): _default_entity_types(), LightRAG-style KG extractor as a LlamaIndex `TransformComponent`.  One LLM call, Pull entity-type strings out of `src.graph.schema.EntityType`., _clean_raw_name(), _correct_entity_label(), _display_entity_name(), drop_prompt_example_entities(), drop_unsupported_dates() (+39 more)

### Community 11 - "test_api: search_v2.py"
Cohesion: 0.10
Nodes (34): _global_params(), _local_params(), Log loudly when a client sends a reserved (unimplemented) filter, so a     silen, Build the local plan-execute workflow input from the request.      ISO date boun, Build the GraphRAG global map-reduce workflow input., _warn_reserved_filters(), ConversationTurn, Search request shared by all ``/api/v1/search/*`` endpoints.      The mode is se (+26 more)

### Community 12 - "test_ingestion: extract_identifiers()"
Cohesion: 0.08
Nodes (62): extract_identifiers(), Run every detector on ``text``; return matches sorted by span.      Multiple occ, _by_type(), Unit tests for ``src/ingestion/identifiers.py``.  Coverage goals:   * One happy-, Body-text 'no symptoms' / 'no warranties' must not match —     the regex earlier, `No. SYMPTOMS` should not match — captured token has no digit., Legit `No. 17-K` style references must still extract., test_amount() (+54 more)

### Community 13 - "test_workflow: contracts.py"
Cohesion: 0.09
Nodes (26): build_nebula_graph_store(), Process-global NebulaGraph store (mirrors build_neo4j_graph_store).      The sto, build_graph_store(), build_neo4j_graph_store(), _construct_neo4j_graph_store(), _install_query_logging(), _neo4j_driver_kwargs(), PropertyGraphStore (+18 more)

### Community 14 - "workflow: contracts.py"
Cohesion: 0.09
Nodes (29): Runtime, close_pg_pool(), Close the pool on process shutdown (API lifespan / worker exit)., CommunityBuildWorkflow, Offline detect → summarize community build., _build_runtime(), _build_worker(), _child_main() (+21 more)

### Community 15 - "storage: push_entities()"
Cohesion: 0.08
Nodes (36): AsyncWikibase, _build_claim(), _lookup_qid_for_entity(), _persist_property_pid(), _persist_qid_for_entity(), push_entities(), Any, Wikibase push orchestrator.  Projects merged ``EntityNode`` / ``Relation`` lists (+28 more)

### Community 16 - "eval: test_scale_bench_smoke.py"
Cohesion: 0.11
Nodes (14): _FakeExport, _FakeStore, _FakeStoreHighDegreeSource, _FakeStoreNullCursor, Returns one page of node rows, then one page of edge rows, then empties., Regression: all edges from a high-degree source must survive multi-page reads., Records stream_names/stream_edges calls; canned return values., Edge page whose last row carries a null cursor — would loop forever under old co (+6 more)

### Community 17 - "ingestion: identifiers.py"
Cohesion: 0.05
Nodes (64): _account_control_ok(), _canonicalize_contract(), _check_inn_10(), _check_inn_12(), _check_ogrn_13(), _check_ogrn_15(), _extract_addresses(), _extract_amounts() (+56 more)

### Community 18 - "test_api: AsyncPostgres"
Cohesion: 0.14
Nodes (36): merge_and_resolve(), Relation, First N entries of an alias->canonical map, truncated for     heartbeat sanity., Repoint a relation's name-endpoints through ``alias`` (folded entity     name ->, _rewrite_endpoints(), _sample_map(), _base_patches(), _ctx() (+28 more)

### Community 19 - "graph: analysis.py"
Cohesion: 0.06
Nodes (58): components(), _components_from_edges(), _components_nebula(), graph_stats(), _graph_stats_nebula(), _nebula_show_stats(), _nebula_stats_computed_at(), pagerank() (+50 more)

### Community 20 - "graph: _q()"
Cohesion: 0.13
Nodes (21): cap_synth_sources(), distinct_doc_ids(), How many chunks to let the cross-encoder score.      Derived from the number tha, ``(start_to_close, schedule_to_close)`` for ``rerank_sources``.      Derived fro, Distinct, order-preserving doc_ids from a source pool's metadata.     Skips sour, Bound the pool fed to synthesis.  This is now the ONLY cap on the     synthesis, rerank_candidate_count(), rerank_timeouts() (+13 more)

### Community 21 - "test_graph: test_wiki_graph_ops.py"
Cohesion: 0.09
Nodes (32): _NebulaRecStore, Records nGQL statements (positional; nebula never binds param_map);     returns, nebula UPDATE VERTEX raises on a missing vertex; mark_dirty must catch     per-n, Records (cypher, param_map) calls; returns canned rows per call,     popped in c, _RecStore, test_dispatch_returns_nebula_when_backend_nebula(), test_dispatch_returns_neo4j_when_backend_not_nebula(), test_nebula_clear_dirty_issues_update_vertex() (+24 more)

### Community 22 - "test_graph: NebulaGraphStore"
Cohesion: 0.07
Nodes (32): _deep_normalize(), _deterministic_pairs(), _initials_signature(), _load_existing_canonicals(), Read Neo4j entities with `er_canonical_name` and their stored     embedding.  Re, Drop combining marks (é → e, ё → е).  Preserves case., Aggressive normalisation for the deterministic pre-pass —     casefold + drop di, Extract `(surname_lower, first_initial_lower)` from either     "Surname F.M." (d (+24 more)

### Community 23 - "test_graph: merge_kg_extraction()"
Cohesion: 0.12
Nodes (48): _cypher_safe_label(), Convert a free-text predicate/keyword to a Cypher-safe upper-case     relation l, _EntityAgg, _id_to_name(), merge_kg_extraction(), BaseNode, EntityNode, Relation (+40 more)

### Community 24 - "test_storage: ChunkRepository"
Cohesion: 0.08
Nodes (42): ChunkRepository, _escape(), _normalise_chunk_row(), Any, Path, Doc-id / file-path access layer for chunks and source files.  Wraps three lower-, Return on-disk path for the source file of `doc_id` or         None if the docum, Read the source file from disk, capped to `max_chars`.          Returns None if (+34 more)

### Community 25 - "workflow: test_search_drift_roundtrip.py"
Cohesion: 0.12
Nodes (26): _apply_name_map(), _consolidate_cluster(), _embed_entities(), _format_cluster_prompt(), _format_pair_prompt(), _Item, _load_candidates_native(), _load_candidates_via_store() (+18 more)

### Community 26 - "test_graph: test_event_extract.py"
Cohesion: 0.08
Nodes (46): events_to_graph(), EntityNode, Relation, Convert `ParsedEvent` objects → graph nodes + edges.  Called from `LightRAGExtra, Convert a list of ``ParsedEvent`` objects to graph nodes + relations.      Param, ParsedEvent, Intermediate parsed event tuple., _ev_line() (+38 more)

### Community 27 - "config.py: Settings"
Cohesion: 0.18
Nodes (19): MaterializeParams, MaterializeResult, StageResult, AnalyticsMaterializeWorkflow, AnalyticsMaterializeWorkflow — offline GDS materialization pipeline.  Sequence:, Offline materialization: centrality → link prediction → risk., test_materialize_defaults_and_frozen(), test_materialize_result_all_fields() (+11 more)

### Community 28 - "test_graph: MilvusEntityVectorStore"
Cohesion: 0.16
Nodes (11): _emb(), main(), EntityCandidate, EntityVectorStore, _btrunc(), MilvusEntityVectorStore, Any, Truncate to fit a Milvus VARCHAR: max_length counts UTF-8 BYTES, not chars. (+3 more)

### Community 29 - "graph: signals.py"
Cohesion: 0.07
Nodes (26): circular_ownership(), CircularOwnershipParams, investigate_next(), InvestigateNextParams, _Params, Any, BaseModel, P2 — composite, decision-ready signals & queues (read materialized scores + comp (+18 more)

### Community 30 - "test_graph: resolve_entities()"
Cohesion: 0.10
Nodes (31): _EmbeddingStub, _ent(), BCC and Базальноклеточный Рак — same vector + LLM SAME → merge., Иванов И.И. ≡ Иван Иванов via initials regex — no LLM call., Cosine 0.95 but LLM DIFFERENT → not merged., Phone/INN/Email labels are SKIPPED — even with cosine 1.0., When A and B merge, a relation A→B becomes self-loop and is dropped., Cluster size ≥ hyper_hub_threshold → not merged, marked review. (+23 more)

### Community 31 - "test_workflow: activities.py"
Cohesion: 0.13
Nodes (22): _candidate_pairs(), _cosine(), _is_ascii_name(), _is_cyrillic_name(), _name_token_overlap(), _name_tokens(), _normalized_matrix(), _parse_judge_response() (+14 more)

### Community 32 - "test_bot: Turn"
Cohesion: 0.10
Nodes (37): RewriteFn, Wire the pure ``rewrite_query`` to the app's LLM (litellm via build_llm).  Kept, answer_question(), SearchFn, The bot's answer pipeline: whitelist → session → follow-up rewrite → KB search →, Produce the bot's reply for one incoming message.      Denied users get ``DENIED, build_rewrite_prompt(), Rewrite a follow-up message into a standalone search query.  "а что по нему?" af (+29 more)

### Community 33 - "test_analytics: _FakeStore"
Cohesion: 0.07
Nodes (31): _FakeStore, Captures the last Cypher + params and returns canned rows., test_alerts_clamps_top_n(), test_alerts_filters_passed_as_params(), test_alerts_no_window_means_since_null(), test_alerts_reads_alert_nodes_newest_first(), test_alerts_window_days_sets_since(), test_link_prediction_reads_edges() (+23 more)

### Community 34 - "test_storage: test_ingest_metrics.py"
Cohesion: 0.10
Nodes (12): _nebula_fail_soft(), NebulaAnalyticsGraphOps, Any, Backend-dispatched analytics "connections" graph ops (read-only, fail-soft neigh, Mirrors ``Neo4jAnalyticsGraphOps._rows``'s ``try/except -> []`` (same     warnin, nGQL connections graph ops: GO/FETCH for neighbourhood reads,     FIND SHORTEST, FETCH name+label for a set of Entity vids -> {vid: (name, label)}., Extract ordered node names + edge rel-types from a         ``PathWrapper``-shape (+4 more)

### Community 35 - "graph: entity_resolution.py"
Cohesion: 0.04
Nodes (106): AgenticStepStatDict, CommunityBuildResult, CoverageParams, DetectCommunitiesParams, _Frozen, OrchestratorParams, PlanParams, PlanResult (+98 more)

### Community 36 - "graph: test_community_summarize.py"
Cohesion: 0.19
Nodes (17): DeliverIn, DeliverResult, _Frozen, MonitorResult, BaseModel, Frozen wire types for the analytical layer.  Mirrors the style of src/workflow/c, SweepResult, MonitorSweepWorkflow (+9 more)

### Community 37 - "graph: clamp_top_n()"
Cohesion: 0.06
Nodes (26): _list_literal(), NebulaQualityGraphOps, Neo4jQualityGraphOps, Any, Protocol, QualityGraphOps, Backend-dispatched analytics "quality" graph ops (read-only, fail-soft knowledge, nGQL quality graph ops — MATCH for contradictions/orphans, query+Python     for (+18 more)

### Community 38 - "test_workflow: rerank.py"
Cohesion: 0.15
Nodes (20): EntitiesFn, make_agent(), Ask the openclaw agent one question over its OpenAI-compatible endpoint.  opencl, Build `agent(question) -> answer`. Raises on non-2xx / transport     error so th, make_rewrite(), Build an async ``rewrite(history, question) -> standalone_query`` backed     by, _api_key(), build_ctx() (+12 more)

### Community 39 - "analytics: PrimitiveResult"
Cohesion: 0.17
Nodes (20): Claim, _consensus(), detect_contradictions(), _polarity_split(), TrustFn, Pure contradiction detection over extracted claims (no I/O).  A ``Claim`` is one, Structural pass: group by EXACT ``(subject, attribute)`` and flag groups     whe, Group ASSERTED claims by value → distinct sources, ranked by support.      Suppo (+12 more)

### Community 40 - "analytics: Claim"
Cohesion: 0.16
Nodes (15): RoundGraphData, _NameRetriever, Stands in for GraphRetriever's name lookup., `GraphMemoryExceeded` reached callers as `{"entities": []}` — which     reads as, A genuine empty result carries no error key, so a caller can tell     "nothing m, test_find_entity_by_name_omits_error_when_it_ran(), test_find_entity_by_name_passes_the_failure_through(), _build() (+7 more)

### Community 41 - "test_graph: test_nebula_schema.py"
Cohesion: 0.12
Nodes (19): ensure_schema(), Execute SPACE_DDL then SCHEMA_DDL on an open nebula3 session.      Fail-open ove, _FakeSession, The live cache moved to Postgres, but the tag stays so     `AGENT_ER_VERDICT_CAC, `er_verdict_key_idx` had no reader on either path — the Nebula path     fetches, test_ensure_schema_alters_entity_to_add_er_canonical_name(), test_ensure_schema_alters_entity_to_add_first_doc_id(), test_ensure_schema_alters_entity_to_add_wiki_columns() (+11 more)

### Community 42 - "test_workflow: test_search_global.py"
Cohesion: 0.12
Nodes (40): Resolved, _anchor_date(), _dateparser_day(), _day_bounds(), _month_bounds(), _nearest_month_day(), _nearest_year(), date (+32 more)

### Community 43 - "test_workflow: Ctx"
Cohesion: 0.10
Nodes (34): StepResult, build_synthesis_prompt(), extract_numbers(), faithfulness_score(), _norm(), numbers_in_rows(), ChatMessage, Synthesis prompt + numeric-faithfulness checker.  The LLM verbalizes; it must no (+26 more)

### Community 44 - "test_workflow: test_search_orchestrator.py"
Cohesion: 0.14
Nodes (20): Input to the ``route_query`` activity — the raw user question., Output of ``route_query`` — the chosen search mode.      Fail-safe: any classifi, RouteParams, RouteResult, classify_route(), _get_route_llm(), ``route_query`` activity — classify a question's search mode (R7a).  Decision C, Map a router LLM reply to a ``RouteResult``.  Pure / unit-testable.      Toleran (+12 more)

### Community 45 - "test_graph: test_nebula_store_subgraph.py"
Cohesion: 0.08
Nodes (11): _Cell, _Node, NebulaGraphStore.subgraph maps GET SUBGRAPH results into _map_walk_rows shape., GET SUBGRAPH frontier vertex: an edge endpoint one step past the last     hop, r, _Rel, _ResultSet, _Session, _TaglessNode (+3 more)

### Community 46 - "test_graph: LightRAGExtractor"
Cohesion: 0.07
Nodes (44): _extraction_text(), _is_transient_llm_error(), LightRAGExtractor, Any, BaseException, BaseNode, ChatMessage, TransformComponent (+36 more)

### Community 47 - "test_ingestion: test_classifier.py"
Cohesion: 0.14
Nodes (21): parse_and_chunk(), Ctx, _scrub(), Ctx, 5b guard: inject_canonical must heartbeat DURING its blocking Neo4j upsert, not, test_pulses_during_neo4j_upsert(), Channel-groups Task 3: `group` carried on IngestParams/Ctx.  Mirrors the existin, test_contracts_accept_group() (+13 more)

### Community 48 - "MinioStorage"
Cohesion: 0.09
Nodes (20): AdmissionState, Pure admission-control state machine (Track 5).  Bounds how many documents inges, FIFO admission with a hard ``max_inflight`` ceiling.      ``submit`` enqueues (d, Pop up to ``free_slots`` documents off the front of the queue         into fligh, IngestSchedulerWorkflow, Recycle (continue_as_new) once event history crosses the         threshold — reg, Still-queued documents handed to the next run on recycle.         In-flight docs, Enqueue a document for admission (dedup by doc_id). (+12 more)

### Community 49 - "mcp: tools_server.py"
Cohesion: 0.07
Nodes (61): nebula_fetch(), ``Fetch`` over a NebulaGraphStore: FETCH PROP of the names' VIDs, in batches., _c(), channel_message_stats(), channel_message_timeline(), _clamp_depth(), _cosine(), _cross_encoder() (+53 more)

### Community 50 - "workflow: SerializedNode"
Cohesion: 0.11
Nodes (29): BasePydanticVectorStore, MilvusSettings, main(), _parse_args(), Namespace, CLI: ingest a directory into Milvus.  Usage::      python -m src.ingestion.run ., build_vector_index(), build_vector_store() (+21 more)

### Community 51 - "test_graph: test_aggregations_graph_ops.py"
Cohesion: 0.08
Nodes (29): _NebulaRaisingStore, _NebulaRecStore, _RaisingStore, Records nGQL statements (nebula never binds param_map); returns canned     rows, Records (cypher, param_map); returns canned rows popped in call order., _RecStore, test_dispatch_returns_nebula_when_backend_nebula(), test_dispatch_returns_neo4j_when_backend_not_nebula() (+21 more)

### Community 52 - "test_scripts: datetime"
Cohesion: 0.09
Nodes (24): Lexical seeds from the Postgres entity mirror. Fail-soft: an         outage here, build_entity_search_query(), EntitySearchRepository, AsyncConnection, Postgres access for the entity search mirror.  Pure query builders (asserted exa, One name-search query. `mode`: exact / prefix / substring., Async wrapper over the `entity` table., Records every `timeout=` `.connection()` was called with. (+16 more)

### Community 53 - "graph: communities.py"
Cohesion: 0.07
Nodes (35): Flat GraphScope partition -> rows [{name, communityId, ids:[cid]}]     (same sha, single_level_rows_graphscope(), build_graph(), extract_entity_edges(), hierarchy_rows(), Any, In-worker Leiden community detection (leidenalg/igraph).  Produces the SAME ``ro, Stream the ``__Entity__`` graph out via the backend-dispatched     ``GraphEdgeEx (+27 more)

### Community 54 - "test_graph: test_index.py"
Cohesion: 0.06
Nodes (48): ExtractorMode, KGExtractor, build_kg_extractor(), ensure_chunk_date_indexes(), ensure_community_indexes(), ensure_community_report_vector_index(), ensure_entity_fulltext_index(), ensure_entity_lookup_indexes() (+40 more)

### Community 55 - "test_config: LiteLLMSettings"
Cohesion: 0.07
Nodes (28): LLMTier, LiteLLMSettings, Any, LLMRole, Connection to a LiteLLM proxy (or any OpenAI-compatible endpoint).      ``llama-, Accept a JSON string (pydantic-settings env), a dict, or an         empty/None v, Merge any provided overrides onto the full default map so a         partial ``ro, Base model for the no-role legacy path: the deprecated         ``llm_model`` if (+20 more)

### Community 56 - "test_graph: test_nebula_store_writes.py"
Cohesion: 0.10
Nodes (40): SimpleNamespace, _Cast, _FakeSession, _no_entity_mirror(), _node(), _q_expect(), upsert_nodes/upsert_relations emit the expected nGQL (no live DB)., This file's contract is "no live DB" (see module docstring). The     entity-tabl (+32 more)

### Community 57 - "api: ingest.py"
Cohesion: 0.06
Nodes (43): FastAPI, X-API-Key auth dependency.  Same simple shared-key model enterprise-kb uses — co, require_api_key(), lifespan(), FastAPI app entry point.  Wires routes, CORS, and the dishka DI container.  Inge, `GET /api/v1/documents/{doc_id}` — download the original source file.  Streams t, find_entities(), Any (+35 more)

### Community 58 - "analytics: catalog.py"
Cohesion: 0.06
Nodes (58): _clip(), format_answer(), format_channels(), format_entities(), format_fragments(), format_history(), format_timeline(), format_users() (+50 more)

### Community 59 - "test_config: test_settings.py"
Cohesion: 0.07
Nodes (24): ApiSettings, LLMPoolSettings, External-statistics subsystem (MCP-3).      Defaults are read-side only — nothin, FastAPI surface — host, port, auth keys, CORS, log level., Per-process LLM concurrency pool (K+N model).      ONE semaphore of size ``n`` (, StatsSettings, Stage-0 smoke tests.  Goals:   * importing the package doesn't raise on an empty, Every role except synthesis runs on the small (local) model;     synthesis runs (+16 more)

### Community 61 - "test_analytics: test_planner.py"
Cohesion: 0.08
Nodes (38): main(), Run one analytical query against the knowledge graph.  Usage::      python -m sc, AnalyticsOutcome, AnalyzeParams, PlanInput, Provenance, AnalyticalQueryWorkflow input (epoch-day bounds, like OrchestratorParams)., SynthInput (+30 more)

### Community 62 - "analytics: dynamics.py"
Cohesion: 0.38
Nodes (4): pick_priority(), Canonical channel-group enum, imported by ingest/search/rerank/tg_ingest.  A doc, Return whichever group name ranks earlier in GROUP_PRIORITY.     Unknown names s, test_pick_priority_returns_earlier_in_order()

### Community 63 - "test_workflow: merge_and_resolve()"
Cohesion: 0.15
Nodes (21): _fmt_citations(), _fmt_relations(), _fmt_sources(), Bot-section splice + LLM render for entity wiki articles.  The bot owns ONLY the, Replace the marked bot section with `bot_md` (wrapped in markers).     If no mar, Deterministic '== Источники ==' section with download links to the     original, LLM-render the bot section grounded ONLY in `ctx` (graph facts) and     `citatio, render_bot_section() (+13 more)

### Community 64 - "test_observability: test_ingest_metrics_extractor.py"
Cohesion: 0.16
Nodes (33): datetime, HistoryEvent, parse_activity_timings(), WorkflowHistory, Pure-functional extractor that turns Temporal workflow history into ``MetricRow`, Resolve the right oneof attributes block for a terminal event., Return one ``MetricRow`` per (activity, attempt) found in the     given workflow, _terminal_attrs() (+25 more)

### Community 65 - "graph: events_llm.py"
Cohesion: 0.07
Nodes (48): _align_tool(), _indicators_search(), _parse_date(), date, Three modes, deliberately behind one tool.      No query and no source is not an, _series(), Helper-level tests — FastMCP tool invocation internals are not exercised, same c, `jsonb` normalises key order, so two rows differing only in the     order they w (+40 more)

### Community 66 - "test_graph: test_entity_resolution.py"
Cohesion: 0.12
Nodes (23): backfill(), build_page_query(), escape_ngql(), main(), Any, One-off fill of the Postgres `entity` table from the graph.  Resumable, idempote, One page of entities, in name order, after `last_name`.      NebulaGraph shards, One page, retried on a transient store refusal.      `ORDER BY` makes graphd sor (+15 more)

### Community 67 - "retrieval: build_vector_index()"
Cohesion: 0.12
Nodes (22): get_llm_pool(), Lane, LLMPool, Any, Per-process LLM concurrency pool - single home for LLM gating (K+N).  ONE ``asyn, Test hook - drop the singleton so the next get_llm_pool rebuilds., A named counting async gate: bounded concurrency + an in_use counter.      Usabl, Registry of role -> gated LLM, all sharing ONE global N semaphore. (+14 more)

### Community 68 - "workflow: worker.py"
Cohesion: 0.10
Nodes (34): NoOpKGExtractor, TransformComponent, Identity extractor used when KG_NODES_KEY metadata is already     populated upst, build_property_graph(), _is_neo4j_safe(), `build_property_graph` — Chunk + MENTIONS + entity/relation upsert., _strip_neo4j_unsafe_metadata(), inject_canonical() (+26 more)

### Community 69 - "setup_wikibase.py"
Cohesion: 0.10
Nodes (29): _api_url(), _bootstrap_credentials(), _configure_wbi(), _Counter, _ensure_item(), _ensure_property(), _find_entity_by_label(), _identifier_properties() (+21 more)

### Community 70 - "test_workflow: test_search_retrieve.py"
Cohesion: 0.05
Nodes (84): bounds_from_iso(), date_metadata_filters(), DateBounds, _field_in_range(), filter_nodes(), iso_to_epoch_days(), node_metadata_in_range(), overfetch_top_k() (+76 more)

### Community 71 - "test_retrieval: test_hf_offline.py"
Cohesion: 0.18
Nodes (19): HFSettings, Offline HuggingFace model loading for air-gapped deploys.      Two project model, _make_hf_stub(), MonkeyPatch, Tests for offline HuggingFace model loading.  Covers:   * ``HFSettings`` env bin, An explicit operator-set HF_HOME must NOT be overwritten., HuggingFace's own HF_HOME / HF_HUB_OFFLINE must NOT leak into     our settings f, test_build_reranker_explicit_model_overrides_config() (+11 more)

### Community 72 - "graph: events.py"
Cohesion: 0.07
Nodes (19): EventsGraphOps, NebulaEventsGraphOps, Neo4jEventsGraphOps, Any, Protocol, Backend-dispatched analytics "events" graph ops (E1 first-seen "what's new", rea, _NebulaRecStore, _RaisingStore (+11 more)

### Community 73 - "IngestSchedulerWorkflow"
Cohesion: 0.13
Nodes (6): DynamicsGraphOps, NebulaDynamicsGraphOps, Neo4jDynamicsGraphOps, Any, Protocol, Backend-dispatched analytics "dynamics" graph ops (temporal validity reads, read

### Community 74 - "ingest_queue: ingest_submit.py"
Cohesion: 0.18
Nodes (19): inflects(), _latin(), norm_name(), Entity-name normalization shared by the KB name resolver and the Lens board keys, Strip one case ending from each Cyrillic word of a ``norm_name`` string (stem ≥, casefold, ё→е, quotes dropped, whitespace collapsed and stripped., Letter-for-letter romanization: no folds, doubled letters kept., A translit-key hit for a short name (≤ 4 letters) must also match letter for let (+11 more)

### Community 75 - "test_graph: test_event_merge.py"
Cohesion: 0.11
Nodes (17): community_overview(), CommunityOverviewParams, entity_communities(), EntityCommunitiesParams, _Params, personalized_pagerank(), PersonalizedPagerankParams, Any (+9 more)

### Community 76 - "observability: trace_request()"
Cohesion: 0.13
Nodes (23): _count_by(), get_current_trace(), Any, Structured tracing for the search endpoints.  A trace is a list of `TraceEvent`, Append an event to the current trace.  Cheap no-op if no     trace is active (al, Convenience: time the wrapped block, append one event., One structured event in the request trace., Per-request bundle of events. (+15 more)

### Community 77 - "retrieval: DateBounds"
Cohesion: 0.16
Nodes (30): decide(), EdgeConflict, _key(), _label(), load_stored_edges(), _load_stored_nebula(), _load_stored_neo4j(), Any (+22 more)

### Community 78 - "events_eval.py"
Cohesion: 0.08
Nodes (32): build_community_report_vector_store(), CommunityRef, CommunityReport, CommunityReportVectorStore, Neo4jCommunityReportVectorStore, Any, Protocol, TypedDict (+24 more)

### Community 79 - "test_api: analyze.py"
Cohesion: 0.20
Nodes (12): _acquire_session(), _chunks(), _is_session_dead(), NebulaGraphStore, Any, NebulaGraph implementation of the KbGraphStore seam (write path).  Phase 1 scope, Bounded GET SUBGRAPH from `vid`, mapped to the shape         GraphRetriever._map, Map a nebula3 ResultSet to a list of column->value dicts. (+4 more)

### Community 80 - "storage: backfill_doc_id.py"
Cohesion: 0.14
Nodes (27): _iter_rows(), _load_path_index(), main(), MilvusClient, Backfill the `doc_id` metadata field on legacy Milvus chunks.  Chunks indexed be, Yield Milvus rows in batches via query_iterator (offset-paging has     a 16 384, BackfillStats, build_path_index() (+19 more)

### Community 81 - "reresolve_graph.py"
Cohesion: 0.10
Nodes (26): _amain(), _apply_merges(), _is_write_cypher(), _load_all_entities(), _loader_cypher(), main(), _parse_args(), _plan_merges() (+18 more)

### Community 82 - "tg_ingest.py"
Cohesion: 0.10
Nodes (16): _FakeNebulaStore, Nebula backend for graph analysis (TDD). Under nebula there is no GDS: pagerank, The 2026-08-16 defect: the counting scans were refused for memory     and the ha, `SHOW STATS` serves Nebula's own job results: exact, milliseconds,     and no sc, No stats job has ever run — Nebula answers "please execute `submit     job stats, A count aggregate ALWAYS yields a row — verified on the live store,     `MATCH (, The other side of it: an empty graph that ANSWERS zero is zero,     with no erro, test_graph_stats_nebula_counts_degree_dup() (+8 more)

### Community 83 - "graph: communities.py"
Cohesion: 0.14
Nodes (19): DetectCommunitiesResult, DetectedCommunity, Slim cross-activity handle the build workflow fans out over to     summarise.  D, Output of ``detect_communities_activity`` — the communities to     summarise.  E, detect_communities_activity(), Run GDS Leiden detection + materialise ``:Community`` nodes.      ``max_levels =, build_summarize_specs(), Pure spec: detected communities → batchable summarize params.      One ``Summari (+11 more)

### Community 84 - "test_graph: test_rollups_graph_ops.py"
Cohesion: 0.17
Nodes (9): _NebulaRecStore, _RaisingStore, _RecStore, test_dispatch_nebula(), test_dispatch_neo4j_default(), test_nebula_amount_edges_adds_cp_filter(), test_nebula_amount_edges_matches_amount_label(), test_neo4j_amount_edges_issues_moved_cypher() (+1 more)

### Community 85 - "build_graph_store()"
Cohesion: 0.21
Nodes (14): MonitorIn, _BurstStore, _FakeStore, MonkeyPatch, Tests for detect_alerts activity (Arc 2 monitoring sweep)., Records all structured_query calls and returns scripted rows., One edge row + one risk row → one alert of each kind., When both endpoints are watched, two new_connection alerts are emitted. (+6 more)

### Community 86 - "eval: score_case()"
Cohesion: 0.18
Nodes (16): coerce_entity_type(), Map a user/LLM-supplied entity type to its canonical casing, or None     if it i, parse_plan(), plan_query(), Any, NL → AnalysisPlan. Plain achat + tolerant parse + strict pydantic validation.  M, Deterministic fallback for trend/popularity questions the LLM couldn't plan., Call LLM and parse the result into an AnalysisPlan. Fail-open on LLM error. (+8 more)

### Community 87 - "eval: test_medical_fixture.py"
Cohesion: 0.05
Nodes (39): Analytical Layer — Wave 0 Implementation Plan (v1a + E1 + P1), Codebase-grounded decisions (deviations from the specs — read first), Execution Handoff, File Structure, Global Constraints, Phase A — Foundations (`v1a`), Phase B — Primitives (`v1a` Families 1/2/4 + communities), Phase C — Planner · Provenance · Synthesis (`v1a`) (+31 more)

### Community 88 - "graph: MilvusCommunityReportVectorStore"
Cohesion: 0.11
Nodes (12): _emb(), main(), MilvusCommunityReportVectorStore, Any, CommunityRef, Report vectors for the given ``(community_id, level)`` pairs, keyed by         t, _FakeClient, _I (+4 more)

### Community 89 - "graph: domain.py"
Cohesion: 0.09
Nodes (31): DocumentsForCommunitiesParams, DocumentsForCommunitiesResult, MapPartialResult, Output of ``map_community_partial`` — the per-community partial     answer + a s, Input to ``documents_for_communities`` — community ids to resolve     back to th, Output — distinct source doc_ids behind the given communities., partials_to_sources(), Pure: surviving (scored) MAP partials → synthesis context nodes.      Each relev (+23 more)

### Community 90 - "test_analytics: test_aggregations.py"
Cohesion: 0.18
Nodes (19): _FakeOps, _patch_ops(), The most-mentioned-entities surface must not let degenerate names     (numerish,, Records (method, args) calls; returns canned rows per method name., test_count_entities_excludes_identifiers_by_default(), test_count_entities_failsoft(), test_count_entities_routes_through_seam(), test_count_relationships_filters_rel_type_and_polarity() (+11 more)

### Community 91 - "test_analytics: _FakeOps"
Cohesion: 0.16
Nodes (16): _FakeOps, _patch_ops(), Records (method, args) calls; returns canned rows per method name., test_common_connections_routes_through_seam(), test_connection_path_clamps_hops_inline(), test_connection_path_routes_through_seam_with_clamped_hops(), test_cooccurrence_routes_through_seam(), test_cooccurrence_via_shared_chunks() (+8 more)

### Community 92 - "bot: __main__.py"
Cohesion: 0.14
Nodes (16): is_empty_answer(), Shared answer helpers: detect an empty/no-result answer so neither the search-fa, True for a blank answer or a known empty-synthesis marker., make_analyze(), make_search(), SearchFn, KB search adapter for the bot: POST /api/v1/search/{mode} and return the synthes, Return a search that tries ``primary`` first and only falls back to     ``fallba (+8 more)

### Community 93 - "graph: centrality.py"
Cohesion: 0.11
Nodes (15): link_prediction(), LinkPredictionParams, _Params, Any, BaseModel, Family 3 heavy tier (offline-materialized reads): centrality + link prediction., top_central_entities(), TopCentralParams (+7 more)

### Community 94 - "test_ingestion: IdentifierCanonicalizationTransform"
Cohesion: 0.10
Nodes (31): _description_for(), _exclude_augment_from_embed(), _ident_to_dict(), IdentifierCanonicalizationTransform, inject_canonical_entities(), Any, BaseNode, PropertyGraphStore (+23 more)

### Community 95 - "workflow: _search_deps.py"
Cohesion: 0.08
Nodes (51): align(), AlignedResult, _normalise(), pearson(), period_key(), _project(), date, Deterministic series alignment for cross-source comparison.  Pure functions only (+43 more)

### Community 96 - "test_ingestion: index_vector.py"
Cohesion: 0.31
Nodes (15): _fake_ctx(), _outcome(), Date-interval params on the MCP-1 search tools (mirrors the REST ``/search/local, No date params supplied → all four epoch fields stay None (prior     behaviour,, _stub_client(), test_kb_auto_search_invalid_date_returns_error_without_raising(), test_kb_auto_search_omitted_dates_keep_none_epochs(), test_kb_auto_search_threads_bounds_to_local_leg_only() (+7 more)

### Community 97 - "test_graph: resolve()"
Cohesion: 0.07
Nodes (27): Analytical Layer — Wave 1 Implementation Plan (v1b + P2 + Arc 1 rollups), Codebase-grounded facts (verified — build on these), Execution Handoff, File Structure, Global Constraints, Phase A — Config & contracts, Phase B — Pure composite scoring, Phase C — Offline materialization (v1b core) (+19 more)

### Community 98 - "test_analytics: test_events_llm.py"
Cohesion: 0.19
Nodes (13): _FakeOps, _patch(), E2 event read primitives — event_dossier + event_timeline + trending., Records (method, args); returns canned rows per method name., test_event_dossier_assembles_core_and_actors(), test_event_dossier_empty_actors(), test_event_dossier_empty_core_short_circuits(), test_event_dossier_top_n_clamped_into_seam() (+5 more)

### Community 99 - "workflow: materialize_activities.py"
Cohesion: 0.40
Nodes (8): compute_risk(), normalize(), Pure composite risk scoring (no I/O). Components arrive already normalized to 0., RiskResult, test_bands_low_and_high(), test_compute_risk_weighted_and_banded(), test_normalize(), test_unknown_component_ignored()

### Community 100 - "aggregations_graph_ops.py"
Cohesion: 0.20
Nodes (9): _canonical_label(), _list_literal(), _nebula_fail_soft(), NebulaAggregationsGraphOps, Backend-dispatched analytics "aggregations" graph ops (read-only, fail-soft coun, Mirrors ``Neo4jAggregationsGraphOps._rows``'s ``try/except -> []``     (same war, nGQL list literal for a ``NOT IN``/``IN`` filter (inline-quoted, no     param_ma, nGQL aggregations graph ops: plain ``MATCH``+aggregation (nebula     3.8's openC (+1 more)

### Community 101 - "test_graph: write_entity_article()"
Cohesion: 0.17
Nodes (24): AbstractIncomingMessage, handle_message(), Client, Run this document to completion: start its workflow, or ATTACH to the     run th, Process one ingest message: start + await the document workflow,     then ack/re, _start_or_attach(), _attachable(), _FakeMessage (+16 more)

### Community 102 - "test_graph: test_er_graph_ops.py"
Cohesion: 0.11
Nodes (22): _graph_half(), Records (cypher, param_map) calls; returns canned rows per call,     popped in c, Fake nebula store: records nGQL statements (asserts no param_map —     nebula bi, Safety guarantee: if a redirected-edge re-insert fails, the loser     must NOT b, _RecNebula, _RecStore, test_dispatch_returns_nebula_when_backend_nebula(), test_dispatch_returns_neo4j_when_backend_not_nebula() (+14 more)

### Community 103 - "SEARCH.md — search subsystem deep reference"
Cohesion: 0.05
Nodes (37): ADR-0002: Claim-check staging через MinIO для тяжёлого состояния workflow, Контекст, Последствия, Рассмотренные альтернативы, Решение, Ссылки, ADR-0004: Per-process LLMPool (полосы tier + role) владеет конкурентностью LLM, Контекст (+29 more)

### Community 104 - "retrieval: build_llm()"
Cohesion: 0.11
Nodes (9): Smoke tests for the MCP-2 atomic tools server.  Verifies the 8 atomic tools are, filter_by_metadata operates on an in-process accumulator —     doesn't make sens, The MCP tool descriptions came from atomic_tools.TOOL_DESCRIPTIONS     plus a fe, MCP-2 serves over Streamable HTTP (transport='http'), not SSE., test_channel_message_stats_maps_group_by_and_calls_pg(), test_channel_message_timeline_stringifies_day(), test_descriptions_use_atomic_tools_text(), test_filter_by_metadata_intentionally_not_exposed() (+1 more)

### Community 105 - "GraphRetriever"
Cohesion: 0.05
Nodes (45): build_page_query(), escape_ngql(), main(), migrate(), Any, Copy the ER verdict cache out of the graph and into Postgres.  One-off, resumabl, Copy every verdict into `cache`.  Returns `(copied, last_key)`.      `last_key`, Escape a string for inline use inside a double-quoted nGQL literal.      Verdict (+37 more)

### Community 106 - "mcp: _shared.py"
Cohesion: 0.21
Nodes (15): _load_base_classes(), _load_properties(), push_wikibase(), push_wikibase activity.  Reads the merged-entities staging blob, loads the boots, _fake_merged(), Tests for the push_wikibase activity.  Three behaviours:   * cache disabled -> s, If push_entities returns counters where created+updated == 0     yet we DID rece, An ingest with no entities to push (empty merged blob) IS a     valid no-op — st (+7 more)

### Community 107 - "workflow: KGExtracted"
Cohesion: 0.08
Nodes (25): Analytical Layer — Wave 2 Implementation Plan (E2 + Arc 2 + P3), Codebase-grounded facts (verified — build on these), Execution Handoff, File Structure, Global Constraints, Phase A — Config, Phase B — E2 event extraction, Phase C — E2 read primitives (+17 more)

### Community 108 - "workflow: test_search_route.py"
Cohesion: 0.12
Nodes (36): _ask(), _ctx(), Command handlers: admission, quota, the gate, and the audit around them.  The or, The audit is of what was attempted, not only of what ran., Otherwise N failures wedge the bot permanently., So /history can show an old answer with its provenance without     re-running an, The audit trail must not become a way to read other people's     questions., It re-runs the work; it does not replay a stored answer. (+28 more)

### Community 109 - "test_graph: test_events_llm_graph_ops.py"
Cohesion: 0.17
Nodes (24): EntityContext, Read an entity's 1-hop subgraph from the graph store and hash it for change dete, Stable sha256 over the entity's facts AND its source-document set.     Order-ind, Distinct source-document ids that mention this entity, sorted.     Used both for, read_citations(), read_entity_subgraph(), read_source_docs(), subgraph_hash() (+16 more)

### Community 110 - "wipe_db.py"
Cohesion: 0.10
Nodes (31): confirm(), main(), _pages_to_delete(), _parse_args(), Namespace, DESTRUCTIVE — wipe all data stores.  Drops:   * Temporal   — terminate running +, Drop EVERY collection, not just ``settings.milvus.collection`` —     the stack h, Dispatch on the configured graph backend (mirrors     ``src.graph.store.build_gr (+23 more)

### Community 111 - "test_analytics: test_claim_nli.py"
Cohesion: 0.17
Nodes (21): build_nli_prompt(), nli_verdict(), parse_nli_verdict(), LLM NLI verdict over a pair of claim values (hybrid method B, iteration 4).  Emb, Tolerant parse → CONTRADICT / AGREE / NEUTRAL. contradiction wins over     agree, Ask the LLM for the NLI relation. Fail-open to NEUTRAL on any error., Drop structurally-flagged contradictions that NLI judges to be mere     phrasing, refine_contradictions() (+13 more)

### Community 112 - "graph: community_writeback.py"
Cohesion: 0.11
Nodes (8): _carry_params(), CommunityWriteback, Neo4jCommunityWriteback, Any, Protocol, Backend-dispatched community BUILD write-back (the `:Community` + `IN_COMMUNITY`, Map the clean-keyed carry dict to the `carry_*` params the neo4j     MERGE Cyphe, Runs the historical Cypher constants verbatim — zero behaviour change.

### Community 113 - "retrieval: GroupFilter"
Cohesion: 0.09
Nodes (24): AsyncIngestMetrics, build_ingest_metrics_store(), MetricRow, AsyncConnection, BaseModel, Async Postgres wrapper for the ``ingest_metrics`` table.  Owned by the analytics, Factory consistent with the rest of ``src/storage/``., One activity-execution attempt, schema-mirroring ingest_metrics.      Frozen — e (+16 more)

### Community 114 - "storage: AsyncMediaWiki"
Cohesion: 0.14
Nodes (14): AsyncMediaWiki, AsyncClient, Minimal async MediaWiki Action API client (login + read/edit page + sitelink). U, Link a Wikibase Item to its MediaWiki article page. Best-effort., _api_url(), get_mediawiki(), Process-singleton MediaWiki client for wiki activities., _client_returning() (+6 more)

### Community 115 - "test_analytics: config.py"
Cohesion: 0.12
Nodes (32): index_vector(), _node_content_len(), `index_vector` — embed + Milvus insert.  Loads parsed nodes from staging, snapsh, Strip metadata so every node's ``_node_content`` fits the Milvus     VARCHAR cap, Truncate any chunk whose ``text`` field exceeds the Milvus cap     (a chunking p, Length of the ``_node_content`` VARCHAR Milvus will actually     store for this, _restore_metadata(), _restore_text() (+24 more)

### Community 116 - "superpowers: DocumentIngestWorkflow"
Cohesion: 0.08
Nodes (25): Execution Handoff, Ingest Temporal Workflow Implementation Plan, Self-Review, Stage 1 — Scaffolding (additive, no behaviour change), Stage 2 — Activities (extract logic into `src/workflow/activities/`), Stage 3 — Workflow + worker, Stage 4 — Integration test, Stage 5 — Cutover (+17 more)

### Community 117 - "build_ingestion_pipeline()"
Cohesion: 0.11
Nodes (39): Context, _bounds_or_error(), _global_params(), kb_analyze(), kb_auto_search(), kb_drift_search(), kb_global_search(), kb_search() (+31 more)

### Community 118 - "test_scripts: test_tg_ingest_reingest.py"
Cohesion: 0.15
Nodes (16): main(), Choose the run mode from parsed args: reingest wins over the legacy     backfill, select_mode(), _FakeDialog, _FakeEntity, _FakeMsg, iter_messages(entity, limit, reverse) → prepared newest-`limit` msgs., _RecHTTP (+8 more)

### Community 119 - "analytics: materialize.py"
Cohesion: 0.07
Nodes (36): Minio, main(), Remove orphaned ``kb-staging/{workflow_run_id}/`` prefixes from MinIO.  Workflow, build_entity_vector_store(), Neo4jEntityVectorStore, Any, Dispatch: nebula (or the opt-in flag) -> Milvus; else Neo4j native., Wraps the existing in-graph ER vector index (unchanged behavior). (+28 more)

### Community 120 - "test_graph: extract_entity_edges()"
Cohesion: 0.14
Nodes (7): AlertStore, build_alert_store(), NebulaAlertStore, Neo4jAlertStore, Any, Protocol, Backend-dispatched Arc-2 :Alert store (upsert / read / mark_watched).  ``Neo4jAl

### Community 121 - "workflow: contextualize.py"
Cohesion: 0.08
Nodes (23): `/agent` — ReAct loop, Cost / latency — реальные числа, Cost ownership — что стоит re-ingest, Cross-chunk merge, Entity Resolution — что vector сам не разрулит, ER: 12-step pipeline, ER: трейдоффы, Ingestion pipeline — 5 шагов (+15 more)

### Community 122 - "test_workflow: test_article.py"
Cohesion: 0.22
Nodes (15): _gather_risk_nebula(), _get_store(), materialize_centrality(), materialize_link_prediction(), materialize_risk(), Any, Temporal activities for the offline analytics materialization (kb-graph-build)., nebula risk gather: scan non-id entities (name+betweenness) + their     RELATED (+7 more)

### Community 123 - "test_graph: test_quality_graph_ops.py"
Cohesion: 0.38
Nodes (5): ChunkRepositoryProtocol, get_chunks_by_doc_id(), Fetch all chunks of one document in source order., Read raw source text of one document (pre-chunking, pre-translation)., read_full_document()

### Community 124 - "test_graph: test_signals_graph_ops.py"
Cohesion: 0.13
Nodes (6): _ExplodingWriteback, _FakeWriteback, _patch_two_cliques(), test_detect_communities_raises_when_writeback_fails(), test_detect_communities_routes_writeback_through_seam(), test_detect_hierarchy_raises_when_writeback_fails()

### Community 125 - "test_graph: test_alerts.py"
Cohesion: 0.14
Nodes (22): alert_key(), mark_watched(), Any, Arc 2 — Alert store + watchlist Cypher helpers (called off-loop from activities), Read persisted :Alert rows (backend-dispatched); fail-soft → []., SET e.watched on __Entity__ nodes by name list; fail-soft on error., Compose a stable dedup key for an Alert node.      Format: ``kind:entity:detail`, MERGE an :Alert node keyed on (kind, entity, detail); fail-soft on error.      W (+14 more)

### Community 126 - "test_graph: stamp_first_seen()"
Cohesion: 0.17
Nodes (19): Any, E1 — emulate ON CREATE stamping (created_at/first_doc_id) post-upsert.  The enti, Stamp created_at/first_doc_id on newly-created graph elements.      Sets the fie, stamp_first_seen(), _stamp_first_seen_nebula(), _stamp_first_seen_neo4j(), Tests for E1 — ON-CREATE-emulated first_seen stamping.  Covers the backend dispa, When relations list is empty, only the entity pass fires. (+11 more)

### Community 127 - "test_retrieval: test_graph_walk_retriever.py"
Cohesion: 0.19
Nodes (20): True if a walk-relation dict should be surfaced to the agent.      Drops edges t, _relation_is_live(), _FakeStore, Unit tests for GraphRetriever.awalk — bounded N-hop graph traversal.  Uses a fak, Captures the Cypher + params and returns canned rows., Build a GraphRetriever without touching PropertyGraphIndex., _rel(), _retriever_with_store() (+12 more)

### Community 128 - "workflow: global_search.py"
Cohesion: 0.11
Nodes (27): IngestEnqueuedResponse, job_status(), JobProgressResponse, BaseModel, FromDishka, UploadFile, UUID, Document upload + ingestion-status endpoints.  Flow: upload file to MinIO (synch (+19 more)

### Community 129 - "workflow: StagingStore"
Cohesion: 0.12
Nodes (31): AnalysisPlan, ExecInput, PrimitiveCall, assemble_provenance(), Deterministic provenance assembly (no LLM)., step_from_primitive(), test_assemble_provenance_carries_plan_meta(), test_step_from_primitive_counts_rows() (+23 more)

### Community 130 - "eval: identifier_recall.py"
Cohesion: 0.15
Nodes (20): check_thresholds(), evaluate_case(), format_report(), _is_extra(), load_cases(), main(), _match(), _parse_args() (+12 more)

### Community 131 - "retrieval: test_answer_template.py"
Cohesion: 0.16
Nodes (15): bench_cost_curve(), bench_dedup_recall(), _candidate_norm_pairs(), ER candidate-generation scaling + duplicate-recall benchmark.  Drives the REAL `, Run _candidate_pairs and return the surfaced pairs as norm-sets., Time ``_candidate_pairs`` at each entity count.  Returns one row     per size; `, For each ``knn_k``, fraction of planted duplicate pairs surfaced     as candidat, _assign_labels() (+7 more)

### Community 132 - "test_retrieval: _StubGraphRetriever"
Cohesion: 0.09
Nodes (28): _node(), NodeWithScore, Unit tests for src/retrieval/atomic_tools.py.  Each pure function gets mocked re, _StubChunkRepo, _StubGraphData, _StubGraphRetriever, _StubRetriever, test_dispatch_routes_to_graph_walk() (+20 more)

### Community 133 - "test_workflow: CoverageResult"
Cohesion: 0.08
Nodes (29): AbstractChannel, AbstractQueue, AbstractRobustConnection, Event, RabbitMQSettings, RabbitMQ ingest-queue connection (Track B).      Only consumed when ``INGEST_QUE, Allow a comma-separated env string (RABBITMQ_QUEUES=a,b) as well         as a JS, Queue used when /ingest doesn't name one (the first configured). (+21 more)

### Community 134 - "ner_eval.py"
Cohesion: 0.14
Nodes (20): gliner_ner_callable(), Build a plain ``(text, types) -> list[(name, label)]`` callable     backed by a, _accumulate_lang(), Extractor, format_report(), _llm_only_extractor_factory(), main(), NERStats (+12 more)

### Community 135 - "test_api: test_ingest.py"
Cohesion: 0.17
Nodes (19): cluster_claims(), cosine(), detect_contradictions_clustered(), Claim, EmbedFn, TrustFn, Semantic claim clustering (hybrid method B, iteration 3).  Claims from different, Greedy single-pass clustering of claims by slot-embedding similarity.     Each c (+11 more)

### Community 136 - "test_graph: test_domain_graph_ops.py"
Cohesion: 0.07
Nodes (21): DomainGraphOps, NebulaDomainGraphOps, Neo4jDomainGraphOps, Any, Protocol, Backend-dispatched analytics "domain" graph ops (issue/resolution rollup + commu, _NebulaRaisingStore, _NebulaRecStore (+13 more)

### Community 137 - "test_graph: test_dynamics_graph_ops.py"
Cohesion: 0.14
Nodes (15): _NebulaRaisingStore, _NebulaRecStore, _RaisingStore, _RecStore, test_dispatch_nebula(), test_dispatch_neo4j_default(), test_nebula_fail_soft(), test_nebula_polarity_evolution_optional_filters() (+7 more)

### Community 138 - "test_scripts: test_reresolve_graph.py"
Cohesion: 0.12
Nodes (6): Unit tests for the pure / stubbed helpers in scripts/reresolve_graph.py.  The wh, Inner stub that records every structured_query call and exposes     an arbitrary, _RecordingStore, test_proxy_delegates_arbitrary_attribute(), test_proxy_noops_write_without_touching_inner(), test_proxy_passes_read_through_to_inner()

### Community 139 - "diagrams: activity: retrieve_subquestion (hybrid)"
Cohesion: 0.12
Nodes (21): 3b · coverage gap? — coverage_check (small LLM) decision, extra SubQueryRetrievalWorkflow(gap) — budget max_coverage_rounds (1), dedup by chunk_id, find_entity_by_name — full-text entity lookup, graph_search — path_depth = graph_search_path_depth (1), matched entities + neighbours + chunks, graph_walk (seed) — start = top graph_search entity, hops = graph_walk_hops (2, ≤3), FAIL-OPEN, MCP-1 tool: kb_search(query, max_refinements=3) — @mcp.tool timeout=1800s, submits workflow, polls get_state, MCP client (Hermes / OpenWebUI) (+13 more)

### Community 141 - "test_graph: index.py"
Cohesion: 0.07
Nodes (41): _period_bounds(), _period_in_window(), _polarity_evolution(), date, First and last day covered by a bucket key from     ``epoch_days_to_period``., Keep a bucket that OVERLAPS the window.      Overlap rather than containment: a, No `period_start`/`value` here, deliberately — see the tool docstring.      Rows, How often a topic is mentioned across ingested documents, per period     — the c (+33 more)

### Community 142 - "test_retrieval: test_query_planner.py"
Cohesion: 0.20
Nodes (15): bench_graph_write(), _driver(), _gen_workload(), _is_retryable(), _pct(), Exception, Neo4j concurrent-write contention benchmark (Track A baseline).  Reproduces the, Execute one writer's rounds in its own session.  Returns timing +     deadlock/r (+7 more)

### Community 143 - "test_workflow: MapCommunitiesParams"
Cohesion: 0.13
Nodes (12): Temporal worker / client connection settings., TemporalSettings, And the operator's value wins over that default., The CODE's default, not whatever the developer's `.env` says.      This used to, test_community_backend_defaults_to_gds(), test_community_backend_is_constrained(), test_community_backend_reads_the_environment(), Dedicated merge queue (decouples GraphBuildWorkflow's merge stage     from a bur (+4 more)

### Community 144 - "test_graph_edge_export.py"
Cohesion: 0.15
Nodes (16): Fake nebula store: records nGQL (asserts inline, no param_map);     returns cann, Records (cypher, param_map) calls; returns canned pages per call,     popped in, _RecNebula, _RecStore, test_dispatch_returns_nebula_when_backend_nebula(), test_dispatch_returns_neo4j_when_backend_not_nebula(), test_nebula_stream_edges_chunks_go_calls_by_batch_size(), test_nebula_stream_edges_names_none_falls_back_to_internal_stream_names() (+8 more)

### Community 145 - "test_ingest_queue: RabbitMQSettings"
Cohesion: 0.18
Nodes (6): _FakeClient, _FakeIndex, _FakeSchema, _store(), test_knn_maps_hits_with_embedding_and_label(), test_upsert_writes_expected_rows()

### Community 146 - "test_retrieval: test_hybrid.py"
Cohesion: 0.20
Nodes (7): build_rollups_graph_ops(), NebulaRollupsGraphOps, Neo4jRollupsGraphOps, Any, Protocol, Backend-dispatched analytics "rollups" graph op (numeric Amount rollup, read-onl, RollupsGraphOps

### Community 147 - "diagrams: DocumentIngestWorkflow (IngestParams to IngestResult, queue"
Cohesion: 0.14
Nodes (20): build_property_graph: PropertyGraphIndex Neo4j upsert (chunks, MENTIONS, entities, relations, fulltext), Client entry: POST /api/v1/ingest (202 job_id) + CLI src.ingestion.run (direct, no Temporal), CommunityBuildWorkflow (offline, admin/schedule, queue kb-graph-build): GDS Leiden + report build, Document ingest flow architecture diagram (D2), DocumentIngestWorkflow (IngestParams to IngestResult, queue kb-ingest), extract_kg step: per-chunk LLM KG extraction (LightRAG), queue kb-ingest-llm, LLMPool-gated, GraphBuildWorkflow (child, queue kb-ingest-merge): merge_and_resolve + build_property_graph, Graph half (best-effort; failure implies graph_status=vector_only) (+12 more)

### Community 148 - "superpowers: Phase 3 er_vec slice —"
Cohesion: 0.09
Nodes (21): Carry-forward decisions from the Phase 0/1 whole-branch review (decide before the dependent phase builds on them), File Structure, Global Constraints, Migration Strategy & Phase Map, NebulaGraph Migration Implementation Plan, Phase 0 — Backend seam (no Nebula yet), Phase 1 — Nebula dev cluster + schema + write adapter, Phase 2 — Read-path nGQL translation (+13 more)

### Community 149 - "superpowers: channel group enum (src/retrieval/groups.py)"
Cohesion: 0.14
Nodes (14): 10. Testing, 11. Migration, 12. Open Questions / Follow-ups, 1. Motivation, 2. Scope, 3. Architecture, 4. Workflow Definition, 5. Activities (+6 more)

### Community 151 - "analytics: StepResult"
Cohesion: 0.05
Nodes (39): BaseSettings, AgentSettings, AnalyticsSettings, ClassifierSettings, EventsSettings, GraphSettings, IngestAdmissionSettings, IngestionSettings (+31 more)

### Community 152 - "test_graph: test_alert_store.py"
Cohesion: 0.16
Nodes (17): _maybe_summarize_descriptions(), Any, Return one consolidated description for `descriptions`.      Path A — concat: wh, Remove `<think>...</think>` / `<thinking>...</thinking>` blocks.      Qwen3 (and, strip_thinking(), Tests for `src/retrieval/_common.py`., qwen3 sometimes emits an open <think> when generation truncates.     Everything, Tags that aren't <think>/<thinking> stay put. (+9 more)

### Community 153 - "test_graph: ERConfig"
Cohesion: 0.21
Nodes (8): _FakePool, The nebula3 ConnectionPool recovers after graphd restarts.  Regression (2026-08-, get_session fails while the address is written off (S_BAD)., interval_check > 0 is what starts nebula3's periodic re-probe., test_acquire_session_does_not_reprobe_a_healthy_pool(), test_acquire_session_reprobes_a_written_off_address(), test_acquire_session_reraises_when_the_reprobe_does_not_help(), test_pool_is_built_with_a_background_health_check()

### Community 154 - "graph: GLiNERExtractor"
Cohesion: 0.18
Nodes (13): _default_entity_types(), GLiNERExtractor, _load_gliner(), Any, BaseNode, TransformComponent, Optional GLiNER span-based entity extractor as a LlamaIndex ``TransformComponent, Load a real GLiNER model, honouring the offline HF cache.      ``configure_hf()` (+5 more)

### Community 155 - "test_graph: test_communities_graph_ops.py"
Cohesion: 0.15
Nodes (13): _NebulaRaisingStore, _NebulaRecStore, _RaisingStore, _RecStore, test_dispatch_nebula(), test_dispatch_neo4j_default(), test_nebula_community_overview_matches_by_level(), test_nebula_entity_communities_empty_when_no_edges() (+5 more)

### Community 156 - "diagrams: Temporal Worker (activities + workflows"
Cohesion: 0.16
Nodes (19): Clients layer, System Architecture Diagram (layered: Clients / Edge-API / Temporal / Stores / Observability), Edge / API layer, FastAPI :8000, Hermes Agent client, LiteLLM proxy :4000, MCP-1 :9001, MCP-2 :9002 (+11 more)

### Community 157 - "superpowers: Automatic event detection — design"
Cohesion: 0.13
Nodes (14): 1. Problem, 2. Goals / Non-goals, 3. Data model (`:EventOrAction` properties), 4.1 Prompt (`lightrag_prompts.py` EVENT_INSTRUCTION), 4.2 Parse validation (`lightrag_parse.py` `_parse_event`), 4.3 Resolver (`src/graph/event_ts_resolver.py`, new), 4.4 Dedup key (`src/graph/event_merge.py`), 4. Extraction contract changes (+6 more)

### Community 158 - "test_analytics: test_claim_extract.py"
Cohesion: 0.20
Nodes (17): build_extract_prompt(), extract_claims(), _one(), parse_claims(), Claim, LLM extraction of atomic claims from a document (offline, hybrid method B).  Mir, Pure, tolerant parse of an LLM claims array. Never raises., Extract claims from one document. Fail-open ([]) on any LLM error. (+9 more)

### Community 159 - "test_graph: test_analysis_nebula.py"
Cohesion: 0.23
Nodes (22): Ctx, _gate_checks(), handle_approve(), handle_ask(), handle_channels(), handle_deny(), handle_find(), handle_history() (+14 more)

### Community 160 - "graph: CanonicalLinker"
Cohesion: 0.19
Nodes (11): CanonicalCandidate, CanonicalLinker, Any, Canonical entity linker — resolve a mention to an existing Wikibase QID.  Turns, One linking candidate — an existing Wikibase item.      ``score`` is an alias-ma, Resolve a mention → existing Wikibase QID, else ``None``.      ``index`` exposes, Return the QID this mention links to, or ``None`` to mint new., _FakeIndex (+3 more)

### Community 161 - "graph_edge_export.py"
Cohesion: 0.21
Nodes (12): convert(), document(), ingest(), ingest_status(), UploadFile, Minimal web UI for the offline cluster: upload -> doc2md -> KB ingest, plus sear, Pass an upstream JSON (or error text) through with its status code., _relay() (+4 more)

### Community 162 - "graph: lightrag_extract.py"
Cohesion: 0.05
Nodes (43): 0. Весь слой на пальцах (прочитайте это, если у вас 10 минут), 10.1 Воронка (от макро к микро), 10.2 Чек-лист недоверия (вешать над монитором), 10. Методология: воронка аналитика и чек-лист недоверия, 11. Справочник: примитивы → теория, 1.1 От property graph к графу анализа, 1.2 Три измерения поверх топологии, 1.3 Двудольная природа и co-occurrence (+35 more)

### Community 163 - "test_graph: write_with_retry()"
Cohesion: 0.13
Nodes (25): _is_transient(), Any, BaseException, Bounded retry for transient Neo4j write failures (Track A3).  Concurrent ``MERGE, True for Neo4j transient/contention errors that are safe to retry.      Matches, Call ``fn(*args, **kwargs)``, retrying on transient Neo4j errors.      Up to ``m, write_with_retry(), T (+17 more)

### Community 164 - "test_mcp: test_tools_server.py"
Cohesion: 0.09
Nodes (25): AbstractAsyncContextManager, BoundedLLM, Any, LLM, Bounded-concurrency wrapper for the project LLM.  The default LlamaIndex ``LLM``, Return an already-wrapped LLM untouched; wrap a raw one.      Lets DI bootstrap, Wraps an LLM with a process-wide asyncio.Semaphore, or through an     ordered li, wrap_if_needed() (+17 more)

### Community 165 - "run_answer_eval.py"
Cohesion: 0.15
Nodes (22): _centrality_update_stmt(), _flush_centrality_batch(), Any, Offline GDS compute + write-back into Neo4j. Mirrors src/graph/communities.py., Compute EVERY metric from ONE export + ONE igraph build, write batched.      ``c, Nebula path: every metric from ONE compute, written in batches.      Prefer this, Full-refresh :LIKELY_LINK edges via gds.nodeSimilarity.stream.      Deletes ALL, Run the GDS centrality stream for ``metric`` and write scores back to __Entity__ (+14 more)

### Community 166 - "test_graph: test_centrality_graph_ops.py"
Cohesion: 0.16
Nodes (12): _NebulaRaisingStore, _NebulaRecStore, _RaisingStore, _RecStore, test_dispatch(), test_nebula_fail_soft(), test_nebula_link_prediction_empty(), test_nebula_top_central_reads_column() (+4 more)

### Community 167 - "test_graph: test_events_graph_ops.py"
Cohesion: 0.14
Nodes (22): IngestionCache, IngestionPipeline, _build_cache(), build_ingestion_pipeline(), _build_splitter(), BaseEmbedding, Path, TransformComponent (+14 more)

### Community 168 - "download_models.py"
Cohesion: 0.15
Nodes (15): ArgumentParser, build_arg_parser(), _download_gliner(), _download_reranker(), _force_online(), main(), Pre-download the project's HuggingFace models into a local cache.  Two models fl, Download the cross-encoder reranker into the cache. (+7 more)

### Community 169 - "test_retrieval: test_llm_factory.py"
Cohesion: 0.17
Nodes (17): _capture(), _capture_kwargs(), Role-keyed LLM factory tests.  Confirms each wrapper resolves its model name thr, Default config ⇒ no extra_body wired into the request., Patch OpenAILike, call ``build_llm(...)`` once, return the model     name that t, Legacy path: no role kwarg ⇒ small tier (effective_base)., Explicit LITELLM_LLM_MODEL still wins for the no-role path., Like ``_capture`` but returns the full kwargs dict OpenAILike saw. (+9 more)

### Community 170 - "superpowers: kb-llamaindex Conference Deck plan"
Cohesion: 0.10
Nodes (20): Definition of Done, File Structure, HTML preview with auto-reload, kb-llamaindex Conference Deck Implementation Plan, PDF, PPTX, Task 10: Deck D — speaker notes на все 23 слайда, Task 11: Final pass — оба deck-а, fix layout issues, README review (+12 more)

### Community 171 - "superpowers: LLMPool (per-process role lanes +"
Cohesion: 0.10
Nodes (19): Execution handoff, Gotchas, Project-side Redis cache for LLM responses, Self-review, Stage 1 — Redis infra + minimal `CachedLLM` (achat only), Stage 2 — Wrap `astructured_predict`, Stage 3 — Prompt-version sentinel for invalidation hygiene, Stage 4 (optional) — Observability + agent layer (+11 more)

### Community 172 - "graph: admin.py"
Cohesion: 0.17
Nodes (6): build_community_summarize(), CommunitySummarize, Neo4jCommunitySummarize, Any, Protocol, Runs the historical Cypher constants verbatim — zero behaviour change.

### Community 173 - "er_graph_ops.py"
Cohesion: 0.06
Nodes (21): _load_verdict_cache(), Fetch cached verdicts for `keys` from Neo4j.      Returns `{key -> same}`.  Empt, Persist freshly-judged verdicts to Neo4j (`MERGE` by key).      No-op when `stor, _store_verdicts(), build_er_graph_ops(), _CompositeERGraphOps, ERGraphOps, NebulaERGraphOps (+13 more)

### Community 174 - "test_retrieval: RoundGraphData"
Cohesion: 0.11
Nodes (29): Build a retriever backed only by a KbGraphStore (structured_query),         with, _FakeStore, Nebula read slice: store-only retriever construction + aretrieve guard., Алексей Лихачёв" used to return ten other Алексей (the OR of prefixes filled the, Live graph: 200 entities start with "Алексей"; the phrase lookup must still surf, The defect this replaced: a `GraphMemoryExceeded` came back as an     empty enti, Accepts the `p` map the previous MATCH form returned, so a caller     or fake fe, graph_search under nebula: er_vec kNN picks entities, then subgraph-expand. (+21 more)

### Community 175 - "test_workflow: push_wikibase.py"
Cohesion: 0.09
Nodes (25): today_epoch_days(), heartbeat_every(), Any, Background heartbeater for long-running Temporal activities.  A long activity th, Emit ``activity.heartbeat(detail)`` every ``interval_s`` seconds     while the w, deliver_alerts(), detect_alerts(), _get_store() (+17 more)

### Community 176 - "test_graph: test_community_read.py"
Cohesion: 0.08
Nodes (20): build_community_read(), CommunityRead, NebulaCommunityRead, Neo4jCommunityRead, Any, Protocol, Backend-dispatched community READ (map-phase summary fetch).  `Neo4jCommunityRea, Runs the historical Cypher constant verbatim — zero behaviour change. (+12 more)

### Community 177 - "ingest_scale_bottlenecks.svg: DocumentIngestWorkflow"
Cohesion: 0.15
Nodes (16): Ingest scale bottlenecks — architecture diagram, DocumentIngestWorkflow, Entity Resolution — FIXED: native vector kNN now DEFAULT ON (was 5000-window → recall→0 as graph grows), extract_kg activity, GraphBuildWorkflow (kb-ingest-merge), admit K=1, IngestSchedulerWorkflow (singleton) — docs run ONE-AT-A-TIME, inject_canonical activity — MED: no heartbeat (only long stage w/o one), LiteLLM proxy (single) (+8 more)

### Community 179 - "setup_db.py"
Cohesion: 0.07
Nodes (53): _cos(), dedup_cross_channel_events(), event_key(), merge_events(), EntityNode, Relation, E2 event de-duplication: deterministic (type, participants, ts-bucket) match-key, Fold entity-channel EventOrAction nodes into same-chunk event-channel     events (+45 more)

### Community 180 - "test_analytics: ids.py"
Cohesion: 0.07
Nodes (45): apply_rules(), classify_with_llm(), _ext(), LLMVerdict, BaseModel, Path, Input document classifier — decides whether a freshly-fetched document is worth, Deterministic skip rules.  Returns ``skip=True`` + a human reason     for blocke (+37 more)

### Community 181 - "bot: pipeline.py"
Cohesion: 0.09
Nodes (30): is_allowed(), parse_allowed_users(), Telegram user whitelist. An empty whitelist denies EVERYONE — a personal KB bot, True iff ``user_id`` is whitelisted. Empty whitelist → always False., Parse a comma-separated ``BOT_ALLOWED_USERS`` into a set of user ids.     Non-in, Any, Seeding the first administrators.  Its own module rather than part of the entryp, Make the configured ids active admins. Returns the ones seeded.      Without at (+22 more)

### Community 182 - "bot: with_fallback()"
Cohesion: 0.09
Nodes (27): SchemaLLMPathExtractor, build_property_graph_index(), BaseEmbedding, LLM, PropertyGraphIndex, PropertyGraphStore, Compose a PropertyGraphIndex from store + embed + extractor.      Pass ``nodes``, _build_chunk_repo_once() (+19 more)

### Community 183 - "test_config: TemporalSettings"
Cohesion: 0.04
Nodes (48): 10.1 Temporal UI (http://localhost:8080), 10.2 Grafana-дашборды (http://localhost:3001), 10.3 Postgres-запросы, 10.4 Prometheus (http://localhost:9092), 10. Observability — что смотреть когда, 11. Траблшутинг, 12.1 Связанные runbook'и, 12.2 Архитектурные документы (+40 more)

### Community 184 - "test_graph: community_graphscope.py"
Cohesion: 0.07
Nodes (29): 0. Продакшен: контейнеризованный compose, 0a. Образ (`Dockerfile`), 0b. Стек (`docker-compose.prod.yml`), 0c. Env (`.env.prod.example` / `.env.reference`), 0d. Команды, 0e. Temporal UI: CSRF через HTTP, 0f. Прод-харденинг, 10. Прогон тестового набора (+21 more)

### Community 185 - "graph: community_read.py"
Cohesion: 0.21
Nodes (9): Async Postgres client for the documents table.  Tracks ingestion-job state acros, insert_pending persists source_channel/source_group. Integration — skipped when, test_insert_pending_writes_source_columns(), _cleanup(), status_counts_by + timeline_counts aggregate documents rows. Integration — skipp, _seed(), test_status_counts_by_channel(), test_timeline_counts_by_channel_on_doc_date() (+1 more)

### Community 186 - "ingestion: identifier_transform.py"
Cohesion: 0.17
Nodes (12): build_augment_block(), build_custom_kg_payload(), dedupe_by_canonical(), Keep first occurrence per (entity_type, canonical) pair.      Preserves source o, Assemble a ``rag.ainsert_custom_kg`` payload from identifier matches.      One e, Format the canonical-identifiers block appended to document text.      Produces, test_build_augment_block_empty_input(), test_build_augment_block_format() (+4 more)

### Community 187 - "retrieval: atomic_tools.py"
Cohesion: 0.12
Nodes (21): _edge_stmts(), One giant INSERT EDGE ... VALUES blows nebula's max query size (4 MiB)     and t, Regression: the level-0 root community held 60117 members and produced a     456, Fast path unchanged: a small community still emits ONE statement., Records structured_query(cypher, param_map) calls; returns [] (or a     canned v, Fake NebulaGraphStore: records structured_query(q) statements; returns     a can, _RecSession, _RecStore (+13 more)

### Community 188 - "test_retrieval: get_chunks_by_doc_id()"
Cohesion: 0.29
Nodes (6): ADR-0005: Детерминированная канонизация идентификаторов до извлечения LLM, Контекст, Последствия, Рассмотренные альтернативы, Решение, Ссылки

### Community 189 - "test_graph: _FakeClient"
Cohesion: 0.15
Nodes (13): Nebula centrality write-back: compute once, write batched.  Two defects, both me, Nebula rejects a request over `max_allowed_query_size` (4 MiB) with     `SyntaxE, Fail-soft must survive batching: an ER-merged or deleted vertex raises     `Vert, Records every nGQL request; optionally fails any request mentioning a vid., The whole point: betweenness must be computed ONCE, not once per metric., 273069 sequential round-trips is the thing being removed., _RecStore, test_batch_respects_the_statement_size_budget() (+5 more)

### Community 191 - "di: providers.py"
Cohesion: 0.23
Nodes (12): RouteLabel, dispatch_for_route(), merge_doc_ids(), Pure: map a route label to the workflow that serves it.      Unknown / unexpecte, Union of two doc_id lists, order-preserving, deduped., Routing dispatch tests (Search R7a).  The route→workflow mapping lives in the pu, test_dispatch_date_scoped_downgrades_global_to_local(), test_dispatch_date_scoped_leaves_local_and_drift_intact() (+4 more)

### Community 192 - "merge_identifier_duplicates.py"
Cohesion: 0.08
Nodes (63): finalize(), mark_failed(), mark_skipped(), _persist_ingest_metrics(), `finalize` (success path) and `mark_failed` (workflow-level on-failure) — write, Classifier said skip: write the ``skipped`` terminal status +     reason and cle, Pull parent + child workflow histories, derive per-activity     durations, and p, _rmtree() (+55 more)

### Community 193 - "set_admission.py: get_temporal_client()"
Cohesion: 0.06
Nodes (41): BotRepository, build_list_users_query(), build_recent_requests_query(), Any, AsyncConnection, Postgres access for the Telegram bot: who may use it, and what was asked.  Same, Requests this user started today, for the quota check.          Counts EVERY row, Record a request BEFORE the work starts; returns its id.          A crash mid-se (+33 more)

### Community 195 - "graph: event_ts_resolver.py"
Cohesion: 0.21
Nodes (9): _load_cache_from_neo4j(), main(), Operator-side smoke for :mod:`src.storage.wikibase`.  Pushes a tiny fake corpus, Pull cached base-class QIDs + property PIDs from Neo4j., Self-hosted Wikibase populator settings.      When ``enabled=True``, ``DocumentI, WikibaseSettings, _Claim, Internal claim shape carried into ``create_item`` / ``update_item``.      ``data (+1 more)

### Community 196 - "test_api: test_search_v2_routes.py"
Cohesion: 0.16
Nodes (19): decompose(), _parse_subquestions(), LLM, Query decomposition for the plan-execute search flow (R2).  A compound question, Parse the planner's reply into a list of sub-questions.      Tolerant of three s, Split ``question`` into ≤``max_subqueries`` sub-questions.      Returns ``[quest, _strip_marker(), Unit tests for the query planner (R2 plan-execute flow).  Stubs the LLM so the s (+11 more)

### Community 197 - "test_analytics: _FakeOps"
Cohesion: 0.32
Nodes (8): _FakeOps, _patch(), Records (method, args); returns canned rows per method name., test_contradictions_routes_through_seam(), test_failsoft_all_primitives_return_empty_without_store(), test_incomplete_entities_resolves_and_threads_expected(), test_merge_candidates_routes_through_seam(), test_orphans_threads_min_degree()

### Community 198 - "test_graph: test_retriever_triplet_parse.py"
Cohesion: 0.13
Nodes (17): _NebulaRaisingStore, _NebulaRecStore, _RaisingStore, _RecStore, test_dispatch_nebula(), test_dispatch_neo4j_default(), test_nebula_circular_ownership_sorts_by_length(), test_nebula_fail_soft() (+9 more)

### Community 199 - "test_ingest_queue: test_consumer.py"
Cohesion: 0.09
Nodes (30): admit(), check_quota(), ConcurrencyGate, Decision, is_admin(), Who may ask, how much, and how many at once.  Pure and synchronous (except the g, Whether this user may run anything at all.      Fail closed: anything that is no, Daily budget. ``quota <= 0`` means unlimited. (+22 more)

### Community 202 - "CONCEPTS.md: Entity Resolution (ER)"
Cohesion: 0.15
Nodes (13): (a) Генерация кандидатов через косинусное сходство (векторизованная), (b) LLM-как-судья для пограничных пар + кэш вердиктов (`:ERVerdict`), (c) Union-find / кластеризация связных компонент, (d) Зажим гипер-хабов (hyper-hub clamp), (e) Выбор канонического, Entity Resolution (ER), (f) Источник кандидатов: инкрементальное окно против нативного-векторного kNN, FLAT против HNSW (Milvus) (+5 more)

### Community 203 - "superpowers: Wikibase populator runbook"
Cohesion: 0.11
Nodes (18): Execution handoff, Open follow-ups (NOT in this plan), Self-hosted Wikibase population from kb-llamaindex, Self-review, Stage 1 — Infra: compose services + dependency, Stage 2 — Settings + bootstrap script, Stage 3 — `src/storage/wikibase.py` — push orchestrator, Stage 4 — Temporal activity + workflow wire-up (+10 more)

### Community 204 - "superpowers: Agentic Search plan (Plan #2)"
Cohesion: 0.10
Nodes (19): File Structure, PHASE 1 — Drift-баг: подтвердить, покрыть, защитить, PHASE 2 — Аудит: удаление мёртвого кода (только после Phase 3 по рефлексивному синтезу), PHASE 3 — Рефлексивный синтез (наследие selfrag): осознанное решение, PHASE 4 — Offline HF-модели: плоский local_dir вместо blobs+symlinks, Search: Drift-bug fix + selfrag-наследие + аудит мёртвого кода — Implementation Plan, Self-Review, Task 1: Операционно подтвердить причину (running worker) (+11 more)

### Community 205 - "workflow: wiki_sweep.py"
Cohesion: 0.07
Nodes (45): Primitive, Human-readable catalog (name + description + params) for the planner prompt., register(), render_catalog_for_planner(), AlertsParams, _Params, BaseModel, Arc 2 read side — query persisted :Alert nodes (monitor findings). (+37 more)

### Community 206 - "build_er_graph_ops()"
Cohesion: 0.10
Nodes (31): build_series_query(), Rows for one indicator, newest revision per period unless pinned., Query-builder tests are exact-string; row mapping is tested against a stub conne, `dims={}` is "the rows carrying NO dimensions", not "any row".      Containment, A partial cut must stay a containment match — asking for     `{"region": "Москва, A registered indicator with no rows yet must still be listed —     otherwise a f, `build_indicators_query` was covered as a pure builder, but nothing     ever cal, `get_indicator` has no builder function (inline SQL) and does no     internal `r (+23 more)

### Community 207 - "Neo4jWikiGraphOps"
Cohesion: 0.14
Nodes (3): Neo4jWikiGraphOps, Any, Runs the historical wiki-editor Cypher verbatim — zero behaviour     change from

### Community 208 - "test_workflow: select_communities_descent()"
Cohesion: 0.26
Nodes (10): compute_all(), compute_centrality(), Any, In-worker centrality (igraph) over the exported __Entity__ graph.  Mirrors src/g, Return ``{entity_name -> score}`` for ``metric`` over the weighted     undirecte, Stream the graph once, compute every metric. Returns     ``{metric -> {name -> s, test_compute_betweenness_hub_is_broker(), test_compute_empty_graph_returns_empty() (+2 more)

### Community 209 - "eval: run_scale_bench.py"
Cohesion: 0.11
Nodes (22): LogRecord, _backfill_cypher(), main(), Backfill ``__Entity__.er_vec`` (native vector list) from the legacy ``er_embeddi, main(), _pending(), One-time E1 backfill: stamp a sentinel ``created_at`` on pre-existing graph elem, configure_logging() (+14 more)

### Community 210 - "test_retrieval: test_atomic_tools.py"
Cohesion: 0.23
Nodes (10): fetch_source(), Ctx, `fetch_source` — resolve doc path to a local file + mark processing.  Idempotent, fake_minio(), Path, `fetch_source` resolves an s3:// path to a local file, updates PG to `processing, Second activity attempt after worker crash: file already on     disk → no second, test_legacy_local_path_passes_through() (+2 more)

### Community 211 - "test_storage: test_minio_stream.py"
Cohesion: 0.25
Nodes (9): DocumentRef, BaseModel, Pydantic shapes for the search API.  The sole search surface after the R7b cutov, SourceCitation, deduplicate_nodes(), node_to_citation(), NodeWithScore, Shared helpers used by both legacy `agentic_search` and the new ReAct / reflecti (+1 more)

### Community 212 - "superpowers: NebulaGraph cutover — neo4j decommissioned"
Cohesion: 0.20
Nodes (9): 1. Data migration (neo4j → nebula) — NO TOOLING EXISTS (biggest blocker), 2. Wiki-editor subsystem — the ONLY code that CRASHES (not degrades) under nebula, 3. Operational provisioning (ops, not code), 🟡 DEGRADES cleanly — deferrable (business decision, not a crash), ✅ DONE — works under nebula, live-verified on the cluster, 🟡 Functional-completeness gaps (deferred; not crashes), 🔴 MUST-FIX before a nebula-default flip, NebulaGraph cutover-readiness assessment — 2026-07-11 (+1 more)

### Community 213 - "superpowers: Spec — Seven Tracks (build"
Cohesion: 0.12
Nodes (15): Assumptions (confirmed), Batched execution, Component 1 — config.py as the single source of truth, Component 2 — fail-fast preflight at boot, Component 3 — auto-initialization (no manual host scripts), Component 4 — one command, Component 5 — platform + model prefetch, Component 6 — prod-correct defaults exposed (+7 more)

### Community 214 - "test_workflow: dispatch_for_route()"
Cohesion: 0.12
Nodes (19): _NebulaRaisingStore, _NebulaRecStore, _RaisingStore, _RecStore, test_dispatch_nebula(), test_dispatch_neo4j_default(), test_nebula_event_actors_go_then_fetch_names(), test_nebula_event_core_empty_when_not_event() (+11 more)

### Community 216 - "Neo4jAggregationsGraphOps"
Cohesion: 0.12
Nodes (16): _parse_uri(), Any, Find and delete orphaned ``{run_id}/`` prefixes.  Returns         the list of ru, Thin wrapper around the MinIO client for stage blobs., Pickle `obj` and upload to ``{run_id}/{stage}.pkl``.          Returns the full `, Reverse of `write_pickle`., Best-effort cleanup of every blob under ``{run_id}/``., Return ``run_id`` prefixes whose newest blob is older than         ``older_than_ (+8 more)

### Community 218 - "workflow: retrieve.py"
Cohesion: 0.14
Nodes (23): entity_activity(), EntityActivityParams, _iso_to_epoch_days(), _Params, polarity_evolution(), PolarityEvolutionParams, Any, BaseModel (+15 more)

### Community 219 - "test_retrieval: test_graph_path_depth.py"
Cohesion: 0.07
Nodes (35): build_fulltext_query(), _dedupe_entities(), _dedupe_relations(), _find_by_name_ngqls(), GraphRetriever, _name_fetch_cap(), _name_terms(), _parse_triplet_chains() (+27 more)

### Community 220 - "diagrams: GlobalSearchWorkflow (mode=global): GraphRAG map-reduce over"
Cohesion: 0.29
Nodes (12): AutoSearchWorkflow (mode=auto): router decides local|global|drift, CommunityBuildWorkflow: community summaries built offline, dispatch_for_route: local | global | drift, Drift step 0: contextualize ONCE (children get history cleared), Drift step 2: global with drift_mode=True, seeded by local sources, Drift step 1: run local (child), DriftSearchWorkflow (mode=drift): specific + corpus context, heaviest mode, Entry surfaces: MCP kb_search/_global/_drift/_auto + FastAPI /api/v1/search/{local,global,drift,auto} on kb-search-small queue (+4 more)

### Community 222 - "superpowers: Nebula community-BUILD (nGQL) implementation plan"
Cohesion: 0.15
Nodes (13): A. Hierarchy from one Leiden run (`#2`), Approach, B. Structured reports, bottom-up + incremental (`#2`), C. Dynamic selection for global/drift (`#1`), Components touched, Data flow, Hierarchical communities + dynamic selection design, Error handling / back-compat (+5 more)

### Community 223 - "message_stats.py"
Cohesion: 0.27
Nodes (10): format_status_rows(), format_timeline(), main(), Namespace, CLI for processed-message statistics — a thin wrapper over the same AsyncPostgre, Render status_counts_by output as an aligned text table., _run(), CLI wiring: `channels` calls status_counts_by('source_channel', ...) and its row (+2 more)

### Community 224 - "test_config: test_preflight.py"
Cohesion: 0.04
Nodes (86): CommunitySummaryRef, MapCommunitiesParams, MapCommunitiesResult, MapPartialParams, One community's stored summary — the unit the global MAP step     produces a par, Input to the ``map_communities`` activity — fetch community     summaries to map, Output of ``map_communities`` — the community summaries to map     over.  Empty, Input to ``map_community_partial`` — produce a partial answer for     ONE commun (+78 more)

### Community 225 - "AnalyticsGraphOps"
Cohesion: 0.24
Nodes (10): bench_flat_vs_hnsw(), _build_and_query(), _client(), ndarray, Milvus FLAT-vs-HNSW latency + recall benchmark (P1.1).  Runs against a LOCAL Mil, Compare FLAT (exhaustive, = current default) vs HNSW at ``n``     vectors.  Retu, Return a connected MilvusClient or None if unreachable., Create a collection with the given index, insert corpus, run the     query set. (+2 more)

### Community 226 - "test_graph: test_store.py"
Cohesion: 0.25
Nodes (10): bench_hub_walk(), _driver(), _load_graph(), graph_walk hub-degree cliff benchmark (P1.2).  Loads a synthetic degree-skewed g, Load a synthetic graph and time the walk from a normal node vs     each planted, _time_walk(), gen_edges(), Generate an undirected edge list with planted hubs.      Returns ``(edges, hub_n (+2 more)

### Community 227 - "ARCHITECTURE.md: DocumentIngestWorkflow"
Cohesion: 0.22
Nodes (9): Directory layout, Documentation map, Domain, kb-llamaindex, Observability, Prerequisites, Production deployment, Quick start (+1 more)

### Community 228 - "test_analytics: detect_contradictions_e2e()"
Cohesion: 0.29
Nodes (11): Complete, detect_contradictions_e2e(), EmbedFn, TrustFn, ``docs`` = list of ``{"doc_id","source","text"}``. Returns NLI-confirmed     con, _embed(), _extract(), End-to-end contradiction pipeline (TDD): extract → cluster → structural → NLI-re (+3 more)

### Community 229 - "ARCHITECTURE.md: Production docker-compose"
Cohesion: 0.67
Nodes (3): Dev docker-compose stack, LiteLLM config (OpenAI upstream), LiteLLM proxy

### Community 230 - "superpowers: GraphRetriever.for_store (store-only, no PropertyGraphIndex)"
Cohesion: 0.14
Nodes (14): 1. Full-text index `entity_name_fulltext`, 2. `GraphRetriever.afind_entities_by_name(query, *, limit)`, 3. `find_entity_by_name` atomic tool + retrieve-path wiring, 4. Configurable vector recall (B), Approach (A + B), Components, Graph-search entity recall design, Error handling (+6 more)

### Community 231 - "api: stats.py"
Cohesion: 0.10
Nodes (21): 0. Контекстуализация (история диалога), 1. План — `plan_subquestions`, 2. Fan-out — `SubQueryRetrievalWorkflow`, 3. Проверка покрытия (ограниченный цикл), 4. Единый rerank — `rerank_sources`, 5. Синтез — large-tier, Auto — маршрутизируемая диспетчеризация (`AutoSearchWorkflow`), Drift — сначала local, потом global (`DriftSearchWorkflow`) (+13 more)

### Community 232 - "test_graph: test_retriever_fulltext.py"
Cohesion: 0.16
Nodes (15): alert_vid(), 32-hex VID for an :Alert, mirroring entity_vid/verdict_vid., _NebulaRecStore, _RecStore, test_dispatch_nebula(), test_dispatch_neo4j_default(), test_nebula_mark_watched_updates_each_entity(), test_nebula_read_alerts_filters_and_sorts_in_python() (+7 more)

### Community 233 - "WikiGraphOps"
Cohesion: 0.12
Nodes (6): _all_names(), GraphScope community-detection backend (single-level Leiden, distributed).  Mirr, Dedup names across node_names + edge endpoints (mirrors     community_leiden.bui, Build a GraphScope graph from `edges` and run its modularity community     algor, _run_graphscope_community(), single_level_rows_graphscope maps a mocked GraphScope partition to rows.

### Community 234 - "eval: bench_flat_vs_hnsw()"
Cohesion: 0.18
Nodes (3): _FakeNode, _FakeRel, _FakeVal

### Community 235 - "CONCEPTS.md: LLMPool concurrency gating"
Cohesion: 0.12
Nodes (27): ChannelsFn, make_search_full(), Like ``make_search`` but returns the WHOLE payload, not just the text.      ``ma, make_channels(), make_timeline(), Ingest-volume adapters for `/channels` and `/volume`.  Both hit routes that alre, Per-channel ingest totals → the `rows` list., Daily counts → the `buckets` list.      ``date_field=doc_date`` — the post's own (+19 more)

### Community 240 - "superpowers: WikiSweepWorkflow (dirty-entity sweep)"
Cohesion: 0.13
Nodes (15): 1. Motivation, 2. Locked decisions (from brainstorming), 3. Architecture & data flow, 4. Dirty tracking & change detection, 5. Generation, citations, splice (anti-drift), 6. Queue, Schedule, config, admin, 7. Error handling, idempotency, testing, 8. Out of scope (YAGNI) (+7 more)

### Community 241 - "test_retrieval: find_entity_by_name()"
Cohesion: 0.14
Nodes (16): build_indicators_query(), build_sources_query(), Any, AsyncConnection, date, Postgres access for the statistics subsystem.  The single query layer for `stat_, The registry itself, optionally scoped to one source., JSON-safe projection: dates to ISO, NUMERIC to float, UUID to str. (+8 more)

### Community 242 - "test_api: test_documents.py"
Cohesion: 0.42
Nodes (9): _get(), _key(), ASGI tests for GET /api/v1/documents/{doc_id}., _row(), _storage(), test_download_requires_api_key(), test_download_sanitizes_filename_header(), test_download_streams_original() (+1 more)

### Community 243 - "test_graph: _FakeWriteback"
Cohesion: 0.53
Nodes (9): _cmd_all(), _cmd_er_cost(), _cmd_er_recall(), _cmd_graph_write(), _cmd_milvus(), _cmd_walk(), main(), _print_rows() (+1 more)

### Community 244 - "superpowers: LLMPool (per-process role-keyed pool)"
Cohesion: 0.09
Nodes (22): 1. Motivation, 2. Key decisions (locked during brainstorming), 3. Architecture, 4. Lanes, tiers, sizing, 5. Call-site migration, 6. Temporal cap relaxation & interaction risks, 7. Error handling, observability, testing, 8. Rollout / benchmarking (+14 more)

### Community 245 - "superpowers: Community-detection offload from Neo4j —"
Cohesion: 0.11
Nodes (18): 1. Персистенция иерархии (ядро фикса), 2. Обратная совместимость search (обязательно), 3. Гейт carry-over (вторичный симптом 0,1), 4. Стоимость / масштаб, Findings аудита поиска (2026-07-01), Архитектура / точечные изменения, Валидация, Вне scope (+10 more)

### Community 246 - "NebulaEventsLlmGraphOps"
Cohesion: 0.08
Nodes (25): 10. Troubleshooting, 11. Cross-references, 1. Three-server overview, 2. Запуск, 3.1 Контракт, 3.2 Что происходит под капотом, 3.3 Cancellation, 3.4 Concurrency защита (+17 more)

### Community 247 - "retrieval: GraphRetrieverProtocol"
Cohesion: 0.12
Nodes (35): _centre_meta(), dispatch(), _edges_to_centre(), _entity_row(), filter_by_metadata(), find_entity_by_id(), find_entity_by_name(), find_neighbours() (+27 more)

### Community 250 - "test_workflow: _FakeNebulaStore"
Cohesion: 0.22
Nodes (5): _ConcurrencyDetectingSession, _FakeResp, NebulaGraphStore serializes access to its single (non-thread-safe) session.  Reg, execute() flags an in-flight window; if another thread enters while one     is i, test_exec_is_serialized_across_threads()

### Community 251 - "nebula_bootstrap.py: _connect()"
Cohesion: 0.11
Nodes (13): Any, ChatMessage, ChatMessage, ChatMessage, _DeadSession, _LiveSession, NebulaGraphStore self-heals an expired session.  Regression: graphd kills idle s, execute() always reports an expired (server-killed) session. (+5 more)

### Community 253 - "superpowers: EntityVectorStore seam (knn/upsert)"
Cohesion: 0.22
Nodes (9): ER-vec → Milvus (Phase 3) implementation plan, ER-vec → Milvus (Phase 3 er_vec slice) Implementation Plan, File Structure, Global Constraints, Self-Review, Task 1: `EntityVectorStore` seam + Neo4j impl + factory + config, Task 2: `MilvusEntityVectorStore` (direct pymilvus, `entity_er_vec`), Task 3: Wire `resolve_entities` to the vector store (+1 more)

### Community 254 - "backfill_er_vector.py: configure_logging()"
Cohesion: 0.16
Nodes (24): _api_key_header(), _body(), _post(), _post_raw(), ASGI tests for `POST /api/v1/statistics/load`.  `StatsRepository` is patched so, A stored NaN poisons everything downstream: `align` yields     `divergence: NaN`, `dims` is `dict[str, Any]` — pydantic never looks inside it.  A     NaN/Infinity, `IndicatorIn.dims_schema` is the same shape (`dict[str, Any]`) and     the same (+16 more)

### Community 255 - "ingest_medical.py"
Cohesion: 0.16
Nodes (19): cache_with_pool(), _GraphOpsSpy, The ER verdict cache, once it lives in Postgres rather than the graph.  No live, One round trip per batch, not one per key — ER passes hundreds of     candidate, A key the cache has never seen must be ABSENT, not `False`.     `False` means "j, Without `row_factory=dict_row` live psycopg3 returns tuples and the     mapping, The cache goes to Postgres; `merge_loser_into_canonical` is a real     graph ope, The cache is OPTIONAL and FAIL-SAFE, and moving its storage must     not narrow (+11 more)

### Community 256 - "test_scripts: _pages_to_delete()"
Cohesion: 0.07
Nodes (30): BinaryIO, MinioSettings, S3-compatible upload storage.      User uploads land in `bucket` synchronously f, MinioStorage, Path, MinIO storage wrapper for user-uploaded documents.  `/api/v1/ingest` writes each, Yield the object's bytes in chunks, releasing the HTTP         connection in a f, Split an ``s3://bucket/key`` URI into ``(bucket, key)``.          Raises ``Value (+22 more)

### Community 257 - "KbGraphStore"
Cohesion: 0.32
Nodes (4): KbGraphStore, Any, Protocol, The graph-store surface the app actually uses.  A narrow subset of LlamaIndex's

### Community 258 - "test_analytics: test_domain.py"
Cohesion: 0.19
Nodes (11): Provider, build_api_container(), build_worker_container(), CommonProvider, BaseEmbedding, Dishka DI providers.  Two containers:   * **API** — long-lived: PG client + shar, Shared singletons available to both API and worker., Worker container — currently exposes only `CommonProvider`.      The Temporal wo (+3 more)

### Community 259 - "test_graph: test_community_vector_store.py"
Cohesion: 0.20
Nodes (9): 0. Facts this plan rests on (checked 2026-10-08), 1. Step 1 — land the backend work in kb-llamaindex (local only, no push), 2.1 Shape of the new repo (proposed name: `lens`), 2.2 Phases, 2.3 The contract between the projects, 2. Step 2 — new project, 3. Risks, 4. Decisions (2026-10-08) (+1 more)

### Community 261 - "presentation: 5-step ingestion pipeline"
Cohesion: 0.09
Nodes (22): `/agent` — ReAct loop, Cost / latency — реальные числа, Cross-chunk merge, Enterprise corpus — что мы реально индексируем, Entity Resolution — что vector сам не разрулит, ER: 12-step pipeline, ER: трейдоффы, Ingestion pipeline — 5 шагов (+14 more)

### Community 264 - "superpowers: GET /api/v1/documents/{doc_id} download endpoint"
Cohesion: 0.12
Nodes (17): Addition: document links in the search response, Context (verified), Data flow, Decisions, Derivation per mode, Source document download design, Error handling, Goal (+9 more)

### Community 265 - "superpowers: Hermes ↔ kb-llamaindex RAG integration"
Cohesion: 0.14
Nodes (14): 1. Topology & transport, 2. The `knowledge-base` skill (the heart), 3. RAG-side changes (minimal), 4. Verification & acceptance, Architecture, Deliverables, Hermes ↔ kb-llamaindex RAG integration design, Hermes Agent (the consumer) (+6 more)

### Community 266 - "build_property_graph_index()"
Cohesion: 0.08
Nodes (22): Global Constraints, Notes for the implementer, Task 1: The store, Task 2: Policy — admission, quota, concurrency, Task 3: API clients for the new commands, Task 4: Commands, Task 5: Wiring, config, container, Telegram Bot — Commands, Users, History Implementation Plan (+14 more)

### Community 267 - "check_ingestion.py"
Cohesion: 0.16
Nodes (8): _ctx_chat(), Later rewrites must see the real conversation., A broken turn would poison every later rewrite., _Session, test_a_failed_search_is_not_persisted(), test_followup_is_rewritten_before_searching(), test_rewrite_failure_costs_context_not_the_answer(), test_session_keeps_what_the_user_typed_not_the_rewrite()

### Community 268 - "test_config: WikiSettings"
Cohesion: 0.12
Nodes (16): Analytical Layer — Wave 3 Implementation Plan (E3 trending/burst + alert push), File Structure, Global Constraints, Phase A — Config, Phase B — E3 burst engine + primitive, Phase C — E3 burst alerts in the sweep, Phase D — Push delivery, Phase E — Integration (+8 more)

### Community 270 - "ingestion: _extract_addresses()"
Cohesion: 0.10
Nodes (20): 1. Пред-загрузка онлайн (наполнение кеша), 2. Скопируйте кеш на air-gapped-хост, затем гоняйте оффлайн, Deprecated-алиас `LITELLM_LLM_MODEL`, LLMPool — гейтинг конкурентности, Smoke-верификация, Snapshot мультимодели в момент /ingest, Альтернатива: плоский `--local-dir` (без blob'ов/симлинков), Базлайн для сравнительного eval (R9) (+12 more)

### Community 271 - "retrieval: pick_priority()"
Cohesion: 0.32
Nodes (8): Telegram bot overlay, LiteLLM overlay, OpenClaw agent gateway overlay, Production docker-compose, Scale-out worker override, Telegram ingest harness overlay, MCP servers (MCP-1 kb_search, MCP-2 atomic tools), Neo4j property graph store

### Community 272 - "test_analytics: test_communities.py"
Cohesion: 0.18
Nodes (15): build_query(), load_template(), Server-side answer templates (Track 6, variant a).  Lets a caller shape the SHAP, Russian-output instruction (the default when no template is set)., Resolve a template.  A bare safe name that matches a file under     ``prompts/an, Compose the synthesis instruction.  No template → the RU preamble;     otherwise, ru_query(), Unit tests for server-side answer templates (Track 6, variant a). (+7 more)

### Community 273 - "test_api: test_graph_admin.py"
Cohesion: 0.12
Nodes (17): 10. Testing, 11. Risks & open questions, 1. Keystone — `first_seen` / `created_at` stamping (the one migration), 2. Event model, 3. The three detection mechanisms, 4. Event resolution / dedup (the re-report problem), 5. Pipeline, 6. Surface — event-family analytical primitives (+9 more)

### Community 274 - "test_mcp: test_hermes_skill.py"
Cohesion: 0.43
Nodes (5): Validates the Hermes knowledge-base skill: frontmatter is present and the body r, _split_frontmatter(), test_skill_body_references_every_tool(), test_skill_covers_the_four_pillars(), test_skill_frontmatter_has_name_and_description()

### Community 276 - "test_workflow: test_completion_no_walltime_cap.py"
Cohesion: 0.13
Nodes (11): Fetch, _ambiguous(), Candidate, Lexicon, _none(), Any, Protocol, KB name resolution: a name as a user or a model wrote it → the canonical graph e (+3 more)

### Community 277 - "knowledge-base Hermes skill (routes to kb-llamaindex"
Cohesion: 0.67
Nodes (3): Hermes MCP servers config example (SSE, 30-min timeout), kbsearch MCP server (:9001/sse; kb_search/global/drift/auto), kbtools MCP server (:9002/sse; vector/graph_search/graph_walk/find_* tools)

### Community 278 - "tg_ingest.py: load_state()"
Cohesion: 0.31
Nodes (8): _proxy_returns(), Unit tests for the LiteLLM model-validator that runs at API + worker startup.  T, Build a context manager that patches httpx.Client.get to return     a fake LiteL, Connectivity failure → empty available list → no validation;     only an at-star, test_all_models_registered_logs_info(), test_missing_model_raises_in_strict_mode(), test_missing_model_warns_in_non_strict_mode(), test_proxy_unreachable_does_not_block_boot()

### Community 280 - "test_api: test_admin_wiki.py"
Cohesion: 0.15
Nodes (18): BaseRetriever, BM25Retriever, build_bm25_retriever(), build_hybrid_retriever(), BaseNode, LLM, VectorStoreIndex, Hybrid retrieval — BM25 + dense vector + RRF fusion.  NOT wired into the active (+10 more)

### Community 281 - "test_api: test_monitor_route.py"
Cohesion: 0.33
Nodes (5): ASGI tests for POST /admin/monitor/sweep and /admin/monitor/watch.  The MONITOR_, MONITOR_ENABLED defaults False → returns disabled without touching Temporal., POST /admin/monitor/watch patches mark_watched and build_neo4j_graph_store., test_monitor_sweep_returns_disabled_when_off(), test_monitor_watch_calls_mark_watched()

### Community 282 - "test_api: test_route_skeletons.py"
Cohesion: 0.33
Nodes (5): Route skeleton tests — confirm the search endpoints are registered.  R7b cutover, The plan-execute / GraphRAG endpoints are wired; without an API     key (or with, R7b: the legacy ReAct + judge-based routes are gone → 404., test_legacy_search_routes_removed(), test_new_search_routes_registered()

### Community 283 - "test_scripts: test_setup_db.py"
Cohesion: 0.33
Nodes (3): Stage-1 unit tests for ``scripts/setup_db.py``.  Live-DB integration is verified, Idempotency contract: re-running the script against an existing     DB must not, test_documents_ddl_uses_create_if_not_exists()

### Community 285 - "INGEST.md: GraphBuildWorkflow (child)"
Cohesion: 0.13
Nodes (39): PrimitiveResult, count_entities(), count_relationships(), CountEntitiesParams, CountRelationshipsParams, distribution_by_polarity(), distribution_by_relation_type(), distribution_by_type() (+31 more)

### Community 287 - "graph: AlertStore"
Cohesion: 0.15
Nodes (15): AnswerFn, Classifier, classify_intent(), Route a question to the analytical layer (graph aggregation via /analyze) or the, ANALYTICAL for aggregation/statistics/contradiction questions, else SEARCH., make_router(), Route each query to the analytical layer or the retrieval layer by intent.  ``ma, Build ``answer(query)`` that dispatches to ``analyze`` for analytical     intent (+7 more)

### Community 288 - "graph: NoOpKGExtractor"
Cohesion: 0.06
Nodes (52): `POST /api/v1/search/local` — plan-execute-synthesize search (R2).  Submits ``Se, doc_id list → relative download links (preserves order)., Start the OFFLINE ``CommunityBuildWorkflow`` on ``kb-graph-build``.      Fully d, # NOTE: `created_after`/`created_before` are no longer reserved — they (and, rebuild_communities(), to_document_refs(), ContextualizeParams, ContextualizeResult (+44 more)

### Community 289 - "test_ingestion: build_custom_kg_payload()"
Cohesion: 0.25
Nodes (5): _FakeNebulaStore, _FakeReportVecStore, Returns canned rows keyed by first matching substring of the nGQL., test_descent_children_nebula_go_parent_of(), test_descent_root_nebula_reads_tree_and_attaches_milvus_vecs()

### Community 290 - "retrieval: _injected_params()"
Cohesion: 0.19
Nodes (10): Exception, _RaisingStore, Tests for src/analytics/store_query.py (fail-soft except NotImplementedError)., Store whose structured_query always raises the given exception., A structural backend limitation must not be swallowed into []., The re-raised structural failure is the caller's job to report, not this     mod, test_run_rows_does_not_log_on_not_implemented_error(), test_run_rows_logs_warning_on_ordinary_exception() (+2 more)

### Community 292 - "test_analytics: test_rollups.py"
Cohesion: 0.08
Nodes (24): mirror_entities(), node_to_row(), Any, Fail-soft mirror of graph entities into the Postgres `entity` table.  Called fro, Map a write-path node (as ``upsert_nodes`` iterates it: ``.name``,     ``.label`, Upsert entity rows into Postgres. Fail-soft, fail-FAST.      ``timeout=1`` decou, mirror_with_pool(), The Postgres entity-table mirror: fail-soft, keyed on vid.  Same honest-stub app (+16 more)

### Community 293 - "test_graph: _Boom"
Cohesion: 0.15
Nodes (14): _first_non_finite_float(), IndicatorIn, load_statistics(), LoadRequest, LoadResponse, _non_finite_anywhere_is_not_a_value(), ObservationIn, Any (+6 more)

### Community 294 - "test_workflow: test_search_pooled_llm.py"
Cohesion: 0.22
Nodes (14): _outcome_to_response(), Map the workflow's ``SearchOutcome`` onto the shared response shape     (identic, Run ``GlobalSearchWorkflow`` — map-reduce over the R6 community     summaries fo, Run ``DriftSearchWorkflow`` — local plan-execute pass first, then     expand wit, Run ``AutoSearchWorkflow`` — ``route_query`` (small tier) classifies     the que, search_auto(), search_drift(), search_global() (+6 more)

### Community 295 - "CAPACITY_TUNING.md: LLM_POOL_N throttle"
Cohesion: 0.16
Nodes (18): clear_dirty(), mark_dirty(), Dirty-flag bookkeeping for the wiki editor (Neo4j __Entity__ props).  Routes thr, select_dirty(), build_wiki_graph_ops(), Backend-dispatched wiki-editor graph ops (dirty-flag bookkeeping + article-conte, ArticleOutcome, WikiSweepWorkflow — select dirty entities, (re)write each article. (+10 more)

### Community 297 - "superpowers: GraphScope community backend (distributed single-level"
Cohesion: 0.25
Nodes (8): GraphScope community backend (Phase 4) implementation plan, File Structure, Global Constraints, GraphScope community backend (Phase 4 slice) Implementation Plan, Self-Review, Task 1: config + `community_graphscope.py` (adapter + mapping), Task 2: `communities.py` dispatch (`_graphscope_rows` + branch), Task 3: benchmark arm

### Community 298 - "superpowers: Analytics query fixes implementation plan"
Cohesion: 0.22
Nodes (9): Analytics Query Fixes Implementation Plan, Analytics query fixes implementation plan, Global Constraints, Notes for the implementer, Out of scope (deferred — note, do not build), Task 1: Coerce invalid planner `type` → None, Task 2: Quality gate for entity-listing output (identifiers + degenerate names), Task 3: Broaden trend-fallback keywords to catch "самые упоминаемые" (+1 more)

### Community 299 - "superpowers: scripts/make_env.py builder"
Cohesion: 0.14
Nodes (14): 1. Motivation, 2. Locked decisions (from brainstorming), 3. Architecture, 4. Interaction flow, 5. Secret generation, 6. Cross-field validation, 7. CLI, 8. Testing (+6 more)

### Community 300 - "Grafana datasources provisioning (Prometheus prom-kb +"
Cohesion: 0.50
Nodes (4): Grafana dashboards provisioning (kb-llamaindex file provider), Grafana datasources provisioning (Prometheus prom-kb + Postgres-kb), Prometheus dev scrape config (temporal-worker host.docker.internal:9090), Prometheus prod scrape config (7 worker pools 9090-9096)

### Community 301 - "smoke.sh"
Cohesion: 0.83
Nodes (3): curl_ok(), section(), smoke.sh script

### Community 302 - "conftest.py"
Cohesion: 0.50
Nodes (3): _pin_graph_backend_neo4j(), Pytest-asyncio mode is set globally in pyproject.toml.  Project-wide fixtures la, Post-cutover the PROD default is nebula (see src/config.py), but the     DB-free

### Community 304 - "test_graph: _is_exempt()"
Cohesion: 0.67
Nodes (3): _is_exempt(), Path, test_no_direct_neo4j_store_calls_outside_store_py()

### Community 308 - "superpowers: Marp two-version deck (A tech"
Cohesion: 0.11
Nodes (17): Build, kb-llamaindex — Conference Decks, Prerequisites, 1. Цель, 2. Core-темы доклада, 3. Общая структура (shared spine, 22 слайда), 4. Дельты A vs D (6 слайдов), 5. Marp / файловая структура (+9 more)

### Community 309 - "superpowers: TG → ingest test harness"
Cohesion: 0.14
Nodes (13): 1. RabbitMQ in dev compose (infra for the test), 2. `scripts/tg_ingest.py` (the reader → enqueuer), 3. Dependency, 4. Runbook (short, in the script docstring + a docs note), Components, Data flow, Decisions (locked via brainstorming), Error handling (+5 more)

### Community 310 - "graph: read_alerts()"
Cohesion: 0.08
Nodes (38): description, license, main, name, private, type, version, Field (+30 more)

### Community 326 - "test_workflow: _stub_activity_ctx()"
Cohesion: 0.07
Nodes (38): main(), _parse_args(), Namespace, Offline probe of the LightRAG-style extract + merge stack.  Runs the live projec, main(), main(), Probe KG extraction on real medical chunks.  Splits the medical corpus into chun, Deep diagnostic: try every layer of SchemaLLMPathExtractor.  Steps:   1. Plain ` (+30 more)

### Community 365 - "ERGraphOps seam (ensure_verdict_schema/load_verdicts/store_verdicts/merge_loser_into_canonical)"
Cohesion: 0.14
Nodes (13): 1. Schema (`nebula_schema.py`), 2. `upsert_nodes` writes `er_canonical_name`, 3. Seam: `ERGraphOps` (`src/graph/er_graph_ops.py`, new), 4. Integration (`entity_resolution.py`), 5. Tests (DB-free), 6. Manual gate (live-verify), Background (grounded; scope narrowed by investigation), Design (+5 more)

### Community 366 - "test_stats_routes.py"
Cohesion: 0.25
Nodes (7): Offline-развёртывание на srv01/02/03 — журнал этапов, Как управлять, Лог, Этап 1 — копирование (Claude, без sudo), Этап 2 — команды с sudo (пользователь), Этап 3 — запуск (Claude), Этап 4 — docs2md + веб-интерфейс

### Community 368 - "test_entity_vector_store.py"
Cohesion: 0.09
Nodes (23): MilvusClient, AsyncPostgres, Any, AsyncConnection, UUID, Append resolved fact conflicts to the `fact_supersede` audit log.          `rows, Return `(doc_id, path)` for every registered document.          Used by the lega, Per-key (channel or group) count of each pipeline status.          `dimension` M (+15 more)

### Community 369 - "Automatic event detection — design"
Cohesion: 0.20
Nodes (14): _amain(), apply_merges(), _build_merge_cypher(), canonicalize_for_type(), collect_entity_nodes(), group_by_canonical(), main(), _parse_args() (+6 more)

### Community 370 - "Nebula community-BUILD (nGQL) — full BUILD stage, backend-dispatched"
Cohesion: 0.13
Nodes (18): AsyncConnectionPool, EntityLexicon, _like_prefix(), Any, q_alias(), q_norm(), q_prefix(), q_translit() (+10 more)

### Community 371 - "LiteLLM proxy Redis response cache"
Cohesion: 0.07
Nodes (41): clamp_top_n(), epoch_days_to_period(), is_meaningful_entity(), Constants + pure helpers for the analytical layer (no I/O, no LLM)., Bucket an epoch-day integer into a period label.      granularity: ``year`` → ``, Whether an entity row is worth showing in a themes/events answer.      Always dr, Clamp a requested row cap into ``[1, hard_max]``; ``None``/<=0 → default., alerts() (+33 more)

### Community 372 - "NebulaGraph migration plan (Phases 0-4; strangler-fig, backend-dispatched)"
Cohesion: 0.15
Nodes (6): Minimal async chat LLM returning a canned reply (or raising)., _StubLLM, test_plan_query_failopen_on_llm_error(), test_plan_query_happy_path(), test_plan_query_trend_fallback_overrides_broken_picks(), test_plan_query_trend_fallback_when_llm_plans_nothing()

### Community 373 - "Continuous Wiki Article Editor plan"
Cohesion: 0.27
Nodes (10): _build(), _FakePGIndex, _FakeRetriever, _node(), NodeWithScore, GraphRetriever.aretrieve must extract entities/relations from the TextNode-shape, test_duplicate_triplets_across_nodes_deduped(), test_multi_hop_chain_line_yields_pairwise_relations() (+2 more)

### Community 374 - "AnalyticsGraphOps seam (Protocol; Neo4j-verbatim + Nebula-nGQL impls; build_analytics_graph_ops)"
Cohesion: 0.11
Nodes (17): 1. Boundary, 2. Schema (`scripts/setup_db.py`), 3. Storage layer (`src/storage/stats.py`), 4. Alignment math (`src/stats/align.py`), 5. MCP-3 tools (`src/mcp/stats_server.py`), 6. Required change on the semantic side (MCP-2), 7. Write path (`src/api/routes/stats_data.py`), 8. Config (+9 more)

### Community 375 - "_timeline"
Cohesion: 0.05
Nodes (38): 1. Инжест, 2. Поиск, 3. Якоря знаний, 4. Платформа, Backfill `doc_id` на legacy-чанки 🆕, Claim-check staging, Drift: мягкий fallback 🆕, Entity Resolution (ER) 🆕(native-vector) (+30 more)

### Community 376 - "alerts.py"
Cohesion: 0.16
Nodes (13): ERConfig, _llm_judge_pairs(), For each input pair, return True when LLM judges SAME, else     False (DIFFERENT, Tuning knobs for entity resolution., _GraphStoreStub, EntityNode, Returns canned canonical entities via structured_query., When a vector_store is passed with native kNN on, ER pulls candidates     from s (+5 more)

### Community 377 - "test_config_wave2.py"
Cohesion: 0.15
Nodes (14): extract_kg(), `extract_kg` — LightRAG-style KG extraction (heaviest stage).  One LLM call per, Pull out small JSON-serialisable samples of what the extractor     emitted.  The, _summarise_kg(), EntitySample, Compact entity representation suitable for inclusion in     activity results (ke, RelationSample, extract_kg must obtain its LLM from the shared pool, not a raw     ungated build (+6 more)

### Community 378 - "test_rollups.py"
Cohesion: 0.29
Nodes (7): build_prompt(), _extract_json(), _flatten(), Any, NuExtract3 (numind) template-extraction backend for ``ner_eval``.  NuExtract3 is, Render the structured-mode prompt exactly as chat_template.jinja does., Pull the answer object out of the completion (tolerates fences/think).

### Community 379 - "AnalyticsGraphOps seam (Protocol; Neo4j-verbatim + Nebula-nGQL impls; build_analytics_graph_ops)"
Cohesion: 0.25
Nodes (3): test_communication_stats_counts_pairs(), test_issue_resolution_stats_computes_rate(), test_issue_resolution_stats_empty_no_div_by_zero()

### Community 380 - "find_entity_by_name tool"
Cohesion: 0.36
Nodes (5): _FakeGraphStore, CommunityReportVectorStore: Neo4j impl query/mapping + factory dispatch., test_factory_dispatches(), test_neo4j_knn_maps_rows(), test_neo4j_upsert_is_noop()

### Community 382 - "Wiki-editor runbook"
Cohesion: 0.15
Nodes (13): 1. Что это, 2. Включение, 3. Поток данных, 4. Конфигурация (`WIKI_*`), 5.1 `WIKI_SITE_GLOBAL_ID` должен совпадать с реальным site id, 5.2 `WIKIBASE_BOT_PASSWORD` должен быть ≥ 8 символов, 5.3 Без `wikibase_qid` sitelink не создаётся, но статья пишется, 5.4 Ссылки на скачивание исходников требуют аутентификации (+5 more)

### Community 383 - "test_search_deps_lock.py"
Cohesion: 0.36
Nodes (5): _FakeGraphStore, EntityVectorStore: Neo4j impl query/mapping + factory dispatch (DB-free)., test_factory_dispatches_on_backend(), test_neo4j_knn_maps_rows_with_embedding_and_label(), test_neo4j_upsert_is_noop()

### Community 384 - "Capacity Tuning Under Load"
Cohesion: 0.15
Nodes (12): 1. The one mental model that matters, 2. The K + N model, 2a. The knobs, 2b. Temporal — isolation, not throttle (`TEMPORAL_*`, `src/config.py:207`), 2c. Proxy client (`LITELLM_*`, `src/config.py:137`), 3. Invariants you must not break, 4. Right-sizing `LLM_POOL_N` (the procedure), 5. Recommended load-side changes (deferred from the fix) (+4 more)

### Community 385 - "PostgresERVerdictCache"
Cohesion: 0.13
Nodes (21): main(), pass_aliases(), pass_liveness(), pass_names(), _pg(), plan_aliases(), Any, Backfill for KB name resolution (src/graph/name_resolution.py). Resumable, idemp (+13 more)

### Community 386 - "Конвейер инжеста"
Cohesion: 0.17
Nodes (12): Claim-check staging (MinIO), Две половины + деградация, Допуск документов (admission control), Канонизация идентификаторов (детерминированная, до LLM), Классификатор входных документов (opt-in), Конвейер инжеста, Кратко, Очереди, воркеры, конкурентность LLM (+4 more)

### Community 387 - "Runbook по аналитике ingest"
Cohesion: 0.17
Nodes (12): 10. Дальнейшие улучшения, 1. Обзор, 2. Поднятие (bring-up), 3. Воркер — Prometheus exporter, 4. Тегирование версий (version tagging), 5. Smoke (end-to-end проверка), 6. Дашборды, 6a. Колонка model по активностям (multimodel-плагин) (+4 more)

### Community 388 - "Hermes ↔ RAG Integration plan"
Cohesion: 0.12
Nodes (15): #3 — Claims / covariates extraction (HIGH domain value) — L, #5 — DRIFT iterative follow-up questions — M–L, #6 — Relationship-centric global (cheap alternative) — M, #7 — Multimodal: tables/images into the graph — L (ingest track), Config hygiene, Documentation, From the ER / scaling deep-dive (not yet done), From the GraphRAG / LightRAG comparison (+7 more)

### Community 389 - "test_community_build_hardening.py"
Cohesion: 0.19
Nodes (21): _api_key_header(), ASGI tests for `POST /api/v1/ingest`.  The MinIO client, Postgres, and the Tempo, MinIO container fully down: the SDK raises a urllib3     `MaxRetryError`, not an, Reuse policy on the Temporal side raises     ``WorkflowAlreadyStartedError`` whe, Admission is always-on: every upload MUST route through the singleton     Ingest, A valid `document_date` is converted to epoch-days and snapshotted     onto Inge, A malformed `document_date` is rejected with 422 before any     upload / Postgre, rabbitmq backend: an unconfigured `queue` is rejected with 422     before any up (+13 more)

### Community 390 - "Архитектура"
Cohesion: 0.20
Nodes (10): 1. Компоненты с высоты птичьего полёта, 2. Хранилища данных — что в каждом, 3. Путь приёма (ingest), 4. Путь поиска, 5. Надёжное исполнение и очереди, 6. Якорь знаний и редактор wiki, 7. Наблюдаемость, 8. Конфигурация (+2 more)

### Community 391 - "Часть 3 — Поиск и извлечение"
Cohesion: 0.20
Nodes (10): DRIFT-поиск — комбинация локального и глобального, Авторежим и маршрутизация запросов, Глобальный поиск — map-reduce по сообществам, Декомпозиция plan-execute и оркестратор, Контекстуализация истории диалога, Локальный поиск — векторное извлечение + расширение по графу, Основы RAG (Retrieval-Augmented Generation), Проверка покрытия — ограниченный цикл доработки (+2 more)

### Community 392 - "Runbook — допуск документов (admission control)"
Cohesion: 0.22
Nodes (9): Runbook — допуск документов (admission control), Включение, Выбор K, Диагностика, Зачем, Изменение K в рантайме, Как работает, Оговорка (+1 more)

### Community 393 - "Search — памятка по использованию и тюнингу"
Cohesion: 0.18
Nodes (11): Search — памятка по использованию и тюнингу, Wiki-rebuild (отдельный admin-триггер, не путать с communities), Выбор режима + параметры (стрелка = эффект при увеличении), ⚠️ Граф-глубина / hops — это НЕ параметры HTTP-запроса, Если поиск «висит», История диалога (`history`), ⚠️ Правило перезапуска, Примеры запросов (+3 more)

### Community 394 - "File Structure"
Cohesion: 0.13
Nodes (14): File Structure, Global Constraints, Notes for the implementer, Statistics Subsystem (MCP-3) Implementation Plan, Task 1: Alignment primitives (bucketing, resampling, z-score), Task 2: `align()` — gap, lag search, divergence, warnings, Task 3: Schema and settings, Task 4 — Amendment (approved 2026-08-09, after the Task 4 review) (+6 more)

### Community 395 - "Часть 1 — Основы и инжест"
Cohesion: 0.22
Nodes (9): 1. Надёжное исполнение и Temporal, 2. Паттерн claim-check, 3. Изоляция очередей задач и блокировка головы очереди, 4. Пулинг LLM-конкурентности (LLMPool), 5. Парсинг и разбиение документов на чанки, 6. Детерминированная канонизация идентификаторов (до LLM), 7. Извлечение графа знаний (в стиле LightRAG), 8. Текстовые эмбеддинги (+1 more)

### Community 396 - "Runbook: аналитика по графу (analytical-query layer)"
Cohesion: 0.20
Nodes (10): 1. Обзор, 2. Поверхности, 3. Контракт запроса/ответа, 4. Каталог примитивов (42), 5. Материализация (Wave 1), 6. Мониторинг Arc-2 (opt-in, выключен по умолчанию), 7. Смоук + плейбук проверки качества, 8. Диагностика (+2 more)

### Community 397 - "Runbook: пакетная консолидация графа (`reresolve_graph`)"
Cohesion: 0.22
Nodes (9): 1. Что это, 2. Как работает (коротко), 3. Предусловия, 4. Запуск, 5. Стоимость, 6. Проверка, 7. Откат, 8. Связанное (+1 more)

### Community 398 - "bench_graph_write"
Cohesion: 0.14
Nodes (23): ConversationTurnDict, _bound_history(), _build_prompt(), contextualize_query(), _get_contextualize_llm(), Rewrite a follow-up question into a standalone one using recent conversation his, Small-tier LLM (role ``route`` → small per ``_DEFAULT_ROLE_TIERS``).      Reuses, Rewrite a follow-up into a standalone question (small tier).      Fail-open: emp (+15 more)

### Community 399 - "ConnectionPool"
Cohesion: 0.40
Nodes (5): _connect(), main(), ConnectionPool, One-time NebulaGraph bootstrap: register the storaged host.  Run ONCE after the, Init a pool, retrying while graphd is still coming up.      graphd's compose hea

### Community 400 - "Часть 4 — Якорь знаний, выходы, модели и эксплуатация"
Cohesion: 0.25
Nodes (8): SPARQL и WDQS (вкратце), Мультимодельный / ролевой выбор модели, Наблюдаемость, Непрерывный wiki-редактор, Поверхность MCP (Model Context Protocol), Часть 4 — Якорь знаний, выходы, модели и эксплуатация, Шлюз LiteLLM, Якорь знаний Wikibase

### Community 401 - "Runbook — входной классификатор документов"
Cohesion: 0.29
Nodes (6): Runbook — входной классификатор документов, Включение, Диагностика, Как работает, Откат, Принудительный ингест (обход правил)

### Community 402 - "Runbook — backfill `doc_id` на legacy-чанки Milvus"
Cohesion: 0.29
Nodes (6): Runbook — backfill `doc_id` на legacy-чанки Milvus, Диагностика, Запуск, Как работает, Оговорка, Перед применением

### Community 403 - "_StubCursor"
Cohesion: 0.52
Nodes (6): apply(), convertAndIngest(), inject, jobStatus(), readAttachment(), relayJson()

### Community 404 - "ER native vector kNN (снятие окна 5000)"
Cohesion: 0.33
Nodes (6): ER native vector kNN (снятие окна 5000), Включение — строгий порядок (backfill → флаг), Зачем, Откат, Проверка, Требования

### Community 405 - "Hermes Agent integration runbook"
Cohesion: 0.31
Nodes (9): dedup_by_chunk_id(), merge_subquery_sources(), Drop duplicate ``SerializedNode``s by chunk_id, first wins., Flatten per-sub-question source lists into one deduped list., _n(), Unit tests for the plan-execute merge/dedup helpers (R2).  These cover the CORE, test_dedup_empty(), test_dedup_keeps_first_occurrence() (+1 more)

### Community 406 - "Leiden community detection — diagnostics"
Cohesion: 0.40
Nodes (5): Interpreting, Leiden community detection — diagnostics, Notes, Run these in Neo4j Browser, Tuning resolution & throughput

### Community 407 - "Message statistics"
Cohesion: 0.33
Nodes (5): CLI, Historical-data caveat, HTTP endpoints, Message statistics, What it does

### Community 408 - "test_medical_source_chunks_through_pipeline"
Cohesion: 0.15
Nodes (9): The bot's DDL, asserted as text like the other setup_db tests., Fail closed: a row that appears by itself must grant nothing., `denied` is a real status: a refusal is recorded, not dropped., Deliberate: the record of what someone asked must outlive their     account bein, `(telegram_id, started_at DESC)` covers both reads this table has;     anything, test_new_users_are_pending_and_clients(), test_one_index_serves_history_and_the_quota_count(), test_request_has_no_foreign_key_to_the_user() (+1 more)

### Community 409 - "Hermes Agent integration runbook"
Cohesion: 0.22
Nodes (4): Pins the stub's honesty.  On live psycopg3 the pool sets no row     factory by d, _StubConn, _StubCursor, test_forgetting_dict_row_must_not_silently_work()

### Community 410 - "Manual channel reingest + low-priority lane"
Cohesion: 0.33
Nodes (5): Known limitation, Manual channel reingest + low-priority lane, One-time migration (required before deploying this change), Running a reingest, What it does

### Community 411 - "LLMRole"
Cohesion: 0.09
Nodes (20): Global Constraints, Move the ER Verdict Cache to Postgres Implementation Plan, Notes for the implementer, Task 1: Postgres-backed verdict cache behind the existing seam, Task 2: The migration script, Task 3: Execute the migration and switch over, Task 4: Reclaim the graph, Verification (+12 more)

### Community 412 - "PropertyGraphIndex"
Cohesion: 0.09
Nodes (22): Backlog, `graph_stats` выдаёт отказ за измеренный ноль, `topic_trend` не чинится связыванием параметров, Векторный поиск по реестру показателей, Граф: что установлено 2026-08-16, Дефолт графового бэкенда разошёлся с документацией и тестом, ~~Индексные файлы Milvus раздуты в 22 раза~~ — закрыто 2026-08-17, Канал оценки не подаётся в сравнение (+14 more)

### Community 413 - "test_summarize_produces_report_and_persists"
Cohesion: 0.29
Nodes (6): ADR-0008: Опциональный native-vector kNN ER поверх окна в 5000 строк, Контекст, Последствия, Рассмотренные альтернативы, Решение, Ссылки

### Community 414 - "Таблица сущностей в Postgres для поиска"
Cohesion: 0.18
Nodes (11): Врезка во вход графа, Где сущности живут сейчас, Задача, Запись при ингесте, Побочные выгоды, Поиск, Проверка, Разовая заливка существующих (+3 more)

### Community 416 - "DetectCommunitiesParams"
Cohesion: 0.29
Nodes (6): ADR-0010: Динамический выбор сообществ (лексический / семантический / спуск, fail-open), Контекст, Последствия, Рассмотренные альтернативы, Решение, Ссылки

### Community 417 - "test_search_v2_routes.py"
Cohesion: 0.29
Nodes (6): ADR-0012: Wikibase как канонический якорь + непрерывный wiki-редактор с anti-drift bot-секциями, Контекст, Последствия, Рассмотренные альтернативы, Решение, Ссылки

### Community 418 - "test_community_vector_store.py"
Cohesion: 0.17
Nodes (13): _main(), Live-update the ingest admission ceiling K (max_inflight) on the running ``inges, _main(), Idempotently create/update the Temporal Schedule that runs MonitorSweepWorkflow, _main(), Idempotently create/update the Temporal Schedule that runs WikiSweepWorkflow eve, materialize(), Fire-and-forget: start AnalyticsMaterializeWorkflow on the graph-build queue. (+5 more)

### Community 419 - "_gather_context"
Cohesion: 0.29
Nodes (6): ADR-0014: Скачивание исходных документов через стабильный API-endpoint (не presigned URL), Контекст, Последствия, Рассмотренные альтернативы, Решение, Ссылки

### Community 420 - "Optional Synthesis Implementation Plan"
Cohesion: 0.20
Nodes (9): File Structure, Global Constraints, Notes for the implementer, Optional Synthesis Implementation Plan, Task 1: The flag, and the local short-circuit, Task 2: Global, drift and auto, Task 3: MCP-1 surface and docs, Verification (+1 more)

### Community 421 - "Global Constraints"
Cohesion: 0.40
Nodes (5): allow, allowed(), [bindHost, bindPort], ipNum(), target

### Community 422 - "ingest.py"
Cohesion: 0.33
Nodes (5): Board-key normalization, Helper tools (hidden from the model, called by Lens itself), kb-tools MCP — the surface Lens relies on, Meta fields on graph tools, Row shapes

### Community 423 - "backfill_er_vector.py"
Cohesion: 0.06
Nodes (60): dialog_in_folders(), dialog_slug(), _filter_title(), load_state(), _message_to_doc(), post_ingest(), Any, Path (+52 more)

### Community 425 - "Hermes Agent integration runbook"
Cohesion: 0.33
Nodes (5): test_run_rows_failsoft_on_error(), _Boom, A maintenance trigger must not 500 the admin route., test_pagerank_nebula_fail_soft(), test_refresh_stats_fails_soft()

### Community 426 - "handle_entity"
Cohesion: 0.15
Nodes (18): bench_milvus_vs_native(), bench_native_vs_milvus(), bench_native_vs_window(), _driver(), _load(), _milvus_client(), ndarray, Feasibility benchmark: native Neo4j vector kNN for ER candidate generation vs th (+10 more)

### Community 427 - "build_search_query"
Cohesion: 0.13
Nodes (9): The stats DDL is asserted as text, not by hitting a live Postgres — the point is, Not pinned as a literal string: the expected clause is built here     from the s, A nullable `dims` would silently break the UNIQUE constraint,     because NULL n, DROP CONSTRAINT IF EXISTS before ADD CONSTRAINT is what makes     re-running thi, `setup_db` must exit 0 both times it is run against an     already-created table, test_constraints_ddl_drops_before_it_adds_so_reruns_never_conflict(), test_dims_is_not_null_with_empty_default(), test_indicator_constrains_value_kind_and_granularity() (+1 more)

### Community 428 - "Rerank Orders the Output Implementation Plan"
Cohesion: 0.25
Nodes (7): Global Constraints, Notes for the implementer, Rerank Orders the Output Implementation Plan, Task 1: Return the ranked pool, cap only for synthesis, Task 2: Documentation, The problem in one paragraph, Verification

### Community 429 - "BACKLOG.md"
Cohesion: 0.11
Nodes (15): NebulaCommunitySummarize, Backend-dispatched community SUMMARIZE I/O (context reads + report write).  `Neo, nGQL community SUMMARIZE. UPDATE VERTEX is a partial update (preserves     BUILD, community_vid(), Stable 128-bit VID (32-hex-char) for a community, scoped by level.      Mirrors, Fake nebula store: records nGQL; returns canned rows per substring., _RecNebula, _RecStore (+7 more)

### Community 430 - "Дорожная карта — разделение контуров данных"
Cohesion: 0.29
Nodes (7): 1. Принцип, 2. Контуры, 3. Очередь, 4. Отношение к ROADMAP.md, 5. Жёсткое правило, 6. Риски, Дорожная карта — разделение контуров данных

### Community 431 - "Distinguish "could not compute" from "computed zero" Implementation Plan"
Cohesion: 0.29
Nodes (6): Distinguish "could not compute" from "computed zero" Implementation Plan, Global Constraints, Notes for the implementer, Task 1: Report the failure instead of swallowing it, Verification, Why it matters

### Community 432 - "Мост к openclaw: РЕШЕНО одним флагом"
Cohesion: 0.29
Nodes (6): Замеры (полный стек, 2026-08-20), Итог: обёртка не нужна, Мост к openclaw: РЕШЕНО одним флагом, Осталось, Снятая схема WebSocket (для истории, НЕ используется), Тупик, из которого выбрались

### Community 433 - "Global Constraints"
Cohesion: 0.17
Nodes (10): Entity Search Table Implementation Plan, Global Constraints, Notes for the implementer, Task 1: The table, Task 2: The search repository, Task 3: Fail-soft upsert grafted onto the entity write, Task 4: One-off backfill script, Task 5: Deploy — table, backfill, verify (+2 more)

### Community 434 - "WikiSettings"
Cohesion: 0.24
Nodes (3): Neo4jAggregationsGraphOps, Any, Runs the historical aggregations Cypher verbatim — zero behaviour     change fro

### Community 435 - "Any"
Cohesion: 0.13
Nodes (14): Execution handoff, Gotchas to watch for, LLM response cache — survive activity retries without paying LLM twice, Self-review, Stage 1 — LiteLLM Redis cache (the actual fix), Stage 2 (optional) — Cache hygiene + observability, Task 0: Baseline (no code change), Task 1: Add Redis to docker-compose (+6 more)

### Community 436 - "Технический долг, найденный по ходу"
Cohesion: 0.33
Nodes (6): ~~`StatsSettings` — три ручки из четырёх мёртвые~~ — закрыто 2026-08-16, ~~Нет теста на `except`-ветку оркестратора~~ — закрыто 2026-08-16, ~~Перечисления granularity/value_kind продублированы~~ — закрыто 2026-08-16, Реранкер: хвост вне отранжированной головы, ~~Стаб БД в тестах не моделирует `row_factory`~~ — закрыто 2026-08-16, Технический долг, найденный по ходу

### Community 437 - "Close the Statistics Subsystem Gaps Implementation Plan"
Cohesion: 0.33
Nodes (5): Close the Statistics Subsystem Gaps Implementation Plan, Global Constraints, Task 1: Make the documented settings real, and cover the untested fallback, Task 2: One source for the enums, and a stub that cannot lie, Verification

### Community 438 - "load_state"
Cohesion: 0.13
Nodes (15): 1. `src/config.py`, 2. `src/retrieval/llm_pool.py`, 3. Close the leak — route all LLM calls through the pool, 4. Remove the redundant global-search throttle (`map_parallelism`), 5. `src/api/routes/ingest.py` — admission always-on, 6. env + docs, Background / current state, Changes (+7 more)

### Community 439 - "Пред-существующие дефекты репозитория"
Cohesion: 0.13
Nodes (15): 10. Integration points, 11. Testing, 12. Risks & open questions, 1. Catalog of practical data — what is already covered vs added here, 2. Risk & red-flag signals (composite), 3. Knowledge-quality signals (gaps & contradictions) — net-new, high value, 4. Domain rollups / mini-BI — net-new, 5. Action queues & leads — net-new, the most "practical" (+7 more)

### Community 440 - "_FakeResp"
Cohesion: 0.13
Nodes (14): Analytical Layer — Wave 3 Design (E3 trending/burst + alert push channels), Architecture, Decisions (locked via brainstorming), File structure, Global constraints (carried from Waves 0–2), Goal, Part A — E3 burst engine (shared, DRY), Part B — E3 primitive `trending_events` (+6 more)

### Community 441 - "_FakeEntity"
Cohesion: 0.23
Nodes (9): Source trust — how much a document's origin is believed (0..1).  Trust is *polic, Trust of a document group, clamped to [0, 1].      Lookup is case-insensitive an, trust_for(), Source-trust lookup + trust-weighted claim consensus., test_known_group_is_looked_up_case_insensitively(), test_out_of_range_trust_is_clamped(), test_trust_makes_the_credible_source_win(), test_unknown_or_empty_group_gets_the_default() (+1 more)

### Community 443 - "_patch_deps"
Cohesion: 0.13
Nodes (14): Channel groups — design, Component 1 — source of truth: `scripts/tg_ingest.py`, Component 2 — ingest plumbing, Component 3 — search filter (Milvus push-down + graph post-filter), Component 4 — rerank weights, Component 5 — synthesis context, Config summary, Data flow (+6 more)

### Community 446 - "DynamicsGraphOps"
Cohesion: 0.18
Nodes (10): 1. Problem (verified on live data), 2.1 One resolver, one normalization, 2.2 Data, 2.3 Tool contract (every name-taking kb-tools tool), 2.4 Ingest (so aliases stop being lost), 2. Design, 3. Migration (no re-ingest for most of it), 4. Staged plan (each stage shippable and tested) (+2 more)

### Community 449 - "._validate_iso_date"
Cohesion: 0.12
Nodes (8): build_events_llm_graph_ops(), EventsLlmGraphOps, NebulaEventsLlmGraphOps, Neo4jEventsLlmGraphOps, Any, Protocol, Backend-dispatched analytics "events_llm" graph ops (E2 event reads, read-only,, FETCH the event columns for a set of VIDs, keyed by vid; only rows         whose

### Community 450 - ".achat"
Cohesion: 0.21
Nodes (11): _execute_with_retry(), _migrate_related_validity_to_string(), _probe_edge_write_ready(), _probe_tag_write_ready(), Any, NebulaGraph schema for the KB graph (nGQL DDL).  Mirrors the Neo4j model: `:__En, # NOTE: `entity_wiki_dirty_idx` (on the ALTER-added `wiki_dirty` column) is, Execute `stmt`, retrying up to `attempts` times on failure.      Returns True on (+3 more)

### Community 451 - "test_community_vector_store.py"
Cohesion: 0.50
Nodes (3): _fake_llm(), _pool(), Regression: every search-side LLM accessor goes through the LLM pool, so the glo

### Community 452 - "0. Продакшен: контейнеризованный compose"
Cohesion: 0.36
Nodes (10): Return a list of actionable config problems (empty == OK).          Hard problem, Boot-time preflight: actionable problems instead of mid-request stack traces., _settings(), test_preflight_clean_prod_has_no_problems(), test_preflight_dev_allows_placeholders(), test_preflight_flags_placeholder_key_in_multikey_api_keys(), test_preflight_flags_placeholder_minio_secret_in_prod(), test_preflight_flags_placeholder_secret_in_prod() (+2 more)

### Community 453 - "Move the ER verdict cache out of the graph"
Cohesion: 0.50
Nodes (3): @mimo-ai/plugin, dependencies, @mimo-ai/plugin

### Community 454 - "test_completion_no_walltime_cap.py"
Cohesion: 0.23
Nodes (5): Process-global Neo4j graph-store cache + driver-pool kwargs (Track A2).  No live, _RecordingStore, test_build_installs_query_logging_only_when_flag_on(), test_query_logging_wrapper_is_idempotent(), test_query_logging_wrapper_logs_and_passes_through()

### Community 455 - "_walk_seeds"
Cohesion: 0.18
Nodes (9): The `er_verdict` DDL, asserted as text like the other setup_db tests.  The table, The PRIMARY KEY *is* the lookup index — `er_key = ANY(...)` is the     only acce, `same` is the cached answer.  A NULL would be a third state that     neither `lo, Deliberate: nothing queries by age, and an index on `updated` would     only ser, `PostgresERVerdictCache.ensure_verdict_schema` carries its own copy     so a wor, test_ddl_matches_the_one_the_worker_creates_on_a_fresh_database(), test_key_is_the_primary_key(), test_no_secondary_index_is_created() (+1 more)

### Community 456 - "_FlakyStore"
Cohesion: 0.14
Nodes (13): Continuous Wiki Article Editor Implementation Plan, File Structure, Self-Review notes (for the implementer), Task 10: Wire-up — worker pool, admin route, schedule, env, Task 1: `WikiSettings` config, Task 2: `subgraph_hash` + `EntityContext` (pure core), Task 3: `read_entity_subgraph` + `read_citations` (Cypher), Task 4: `splice_bot_section` (pure, anti-drift boundary) (+5 more)

### Community 458 - "test_config_wave2.py"
Cohesion: 0.14
Nodes (14): Backout, Call-site wiring (`write_entity_article`), Config additions (`WikiSettings`, env prefix `WIKI_`), Decisions (locked), Design, Wiki article quality + source-download links design, Goal, Motivation (+6 more)

### Community 460 - "pg_sync_pool.py"
Cohesion: 0.14
Nodes (14): 10. Testing strategy, 11. Phasing, 13. Risks & open questions, 1. Search vs Analytics — the boundary (contract), 2. Architecture, 3. Execution model — planner + hybrid catalog/Cypher, 5. Two-tier runtime & materialization, 6. Schema card (for text-to-Cypher) — generated, not hard-coded (+6 more)

### Community 461 - ".get"
Cohesion: 0.33
Nodes (9): handle_agent(), Free-form question to the openclaw agent, which chains MCP tools.     Same cost, _ctx_agent(), openclaw keeps its own per-session memory; the bot must hand it a     per-chat k, test_agent_costs_a_slot_and_quota_like_ask(), test_agent_fails_soft(), test_agent_needs_admission(), test_agent_passes_the_chat_session_for_followups() (+1 more)

### Community 462 - "Design"
Cohesion: 0.14
Nodes (13): 1. `EntityVectorStore` seam (`src/graph/entity_vector_store.py`, new), 2. Dispatch + config, 3. Milvus collection `entity_er_vec` (direct pymilvus, separate from the chunk collection), 4. ER integration (`src/graph/entity_resolution.py`), 5. Backfill, 6. Parity gate, 7. Out of scope (deferred), Background (current state, from the map) (+5 more)

### Community 463 - "Design"
Cohesion: 0.14
Nodes (13): 1. Seam: `CommunityReportVectorStore` (`src/graph/community_vector_store.py`, new), 2. Milvus collection `community_report_vec`, 3. Config, 4. Write integration (`community.py::summarize_community_activity`), 5. Read integration (`global_search.py::select_communities_semantic`), 6. Backfill + parity, 7. Out of scope (deferred), Background (current state, from the map) (+5 more)

### Community 464 - "Design"
Cohesion: 0.14
Nodes (13): 1. Seam: `CommunityWriteback` (`src/graph/community_writeback.py`, new), 2. Schema additions (`src/graph/nebula_schema.py`), 3. Nebula nGQL translation (`NebulaCommunityWriteback`), 4. Dispatch in `communities.py`, 5. Tests (DB-free), 6. Manual gate (live-verify), Background (current state, grounded), Design (+5 more)

### Community 465 - "Design"
Cohesion: 0.14
Nodes (13): 1. Schema (`nebula_schema.py`), 2. `upsert_nodes` preserve-rework (`nebula_store.py`) — the core, 3. Seam: `FirstSeenStamp` (`src/graph/first_seen.py`, extend in-place), 4. Integration, 5. Tests (DB-free), 6. Manual gate (live-verify), Background (grounded; empirically verified), Design (+5 more)

### Community 466 - "Design"
Cohesion: 0.14
Nodes (13): 1. Schema change (`scripts/setup_db.py`), 2. Populating the columns, 3. Shared aggregation SQL (`src/storage/postgres.py`), 4. HTTP endpoints (`src/api/routes/stats.py`), 5. CLI (`scripts/message_stats.py`), 6. Testing, Background (current state), Channel message-processing statistics (+5 more)

### Community 467 - "admin.py"
Cohesion: 0.31
Nodes (10): messages_stats(), MessagesStatsResponse, BaseModel, date, FromDishka, Processed-message statistics over the `documents` table.  Two read-only endpoint, StatRow, timeline_stats() (+2 more)

### Community 469 - "Phase 2 — Inference"
Cohesion: 0.15
Nodes (12): 2.3 ⚠ About `think=false` on gemma, 3.1 Starting knob values, 3.2 Deploy the split, 3.3 Caveats, Common: keep the role mapping, Decision rule — stay on Ollama or move to vLLM?, Order from here, Path A (PRIMARY) — Ollama, replicated + parallel slots (+4 more)

### Community 470 - "Speed up `merge_and_resolve` on single-document ingest"
Cohesion: 0.15
Nodes (12): Execution handoff, Root-cause analysis (no code changes here — just findings), Self-review, Speed up `merge_and_resolve` on single-document ingest, Stage 1 — Profile the actual cost before changing anything, Stage 2 — Parallelise summary calls + log call counts, Stage 3 — Skip summary entirely on single-doc merges (optional), Task 0: Capture a baseline (+4 more)

### Community 471 - "Per-role LLM models + split merge into a child workflow"
Cohesion: 0.15
Nodes (12): Execution handoff, Per-role LLM models + split merge into a child workflow, Self-review, Stage 1 — Per-role LLM models, Stage 2 — Split merge + graph-build into a child workflow, Task 1: Add three role-specific model fields to `LiteLLMSettings`, Task 2: Role-based factories in `src/retrieval/llm.py`, Task 3: Wire role-specific factories into call sites (+4 more)

### Community 472 - "Agentic Search Implementation Plan (Plan #2)"
Cohesion: 0.15
Nodes (12): Agentic Search Implementation Plan (Plan #2), Cross-cutting, File Structure (target), Phase R0: Scaffold the `search/` package (no behavior change), Phase R1: Two-tier model configuration, Phase R2: Orchestrator + SubQueryRetrievalWorkflow (replace ReAct) + `/search/local`, Phase R3: Multi-hop `graph_walk` tool, Phase R4: Coverage gate on the orchestrator (+4 more)

### Community 473 - "Source Document Download + Search Document Links — Implementation Plan"
Cohesion: 0.15
Nodes (12): File Structure, Final verification, PART A — Download endpoint, PART B — Document links in the search response, Self-Review, Source Document Download + Search Document Links — Implementation Plan, Task 1: `MinioStorage.stat_object` + `stream_object`, Task 2: `GET /api/v1/documents/{doc_id}` route (+4 more)

### Community 474 - "Analytics Layer — Activation / Rollout Runbook (Waves 0–3)"
Cohesion: 0.15
Nodes (12): Analytics Layer — Activation / Rollout Runbook (Waves 0–3), Decision points (need your input), Dependency graph, Load-bearing lesson (from the community_backend incident), Phase 0 — Read side (zero risk, do first), Phase 1 — E1 first_seen stamping, Phase 2 — Materialize tier (risk/centrality/link-prediction), Phase 3 — Arc-2 monitoring (alerts as :Alert nodes) (+4 more)

### Community 475 - "Global Constraints"
Cohesion: 0.15
Nodes (13): Channel Groups Implementation Plan, Channel groups implementation plan, Global Constraints, Notes for the implementer, Task 1: Group enum module, Task 2: Group metadata filter + combined-filter builder, Task 3: Ingest-side plumbing (group → chunk metadata), Task 4: Search-side param plumbing (API → contracts → workflows) (+5 more)

### Community 476 - "Channel Message Statistics Implementation Plan"
Cohesion: 0.15
Nodes (13): Channel Message Statistics Implementation Plan, Channel message statistics implementation plan, File Structure, Final verification, Global Constraints, Task 1: Schema — columns, indexes, CHECK amend, backfill, Task 2: Persist channel/group in `insert_pending`, Task 3: `/ingest` accepts a `channel` Form field (+5 more)

### Community 477 - "Search date filters — design"
Cohesion: 0.15
Nodes (12): Backlog (explicitly out of scope here), Chosen approach (A) — unchanged, Components & changes, Data flow — single stamping point, Data model, Error handling & compatibility, Goal, Ingest (+4 more)

### Community 478 - "Phase 4 (slice) — distributed community-detection via GraphScope, benchmark-first"
Cohesion: 0.15
Nodes (12): 1. Config, 2. `src/graph/community_graphscope.py` (new), 3. `communities.py` dispatch, 4. Benchmark (adoption gate), 5. Tests + manual gate, Background (current seam, grounded), Design, Global Constraints (+4 more)

### Community 479 - "Nebula analytics Tier-A port (nGQL) — remaining primitive families"
Cohesion: 0.15
Nodes (12): Background (grounded), Design, Global Constraints, Goal, Integration (each primitive file), Interfaces produced, Nebula analytics Tier-A port (nGQL) — remaining primitive families, Out of scope (deferred) (+4 more)

### Community 480 - "Nebula community-SUMMARIZE (nGQL) — backend-dispatched"
Cohesion: 0.15
Nodes (12): 1. Seam: `CommunitySummarize` (`src/graph/community_summarize.py`, new), 2. Nebula nGQL translation, 3. Integration (`community.py`), 4. Tests (DB-free), 5. Manual gate (live-verify), Background (current state, grounded), Design, Global Constraints (+4 more)

### Community 481 - "Nebula graph-compute read (extract_entity_edges + RELATED weight) — end-to-end community-detection under nebula"
Cohesion: 0.15
Nodes (12): 1. `RELATED` weight (schema + write), 2. Seam: `GraphEdgeExport` (`src/graph/graph_edge_export.py`, new), 3. `extract_entity_edges` rewire (`community_leiden.py`), 4. Tests (DB-free), 5. Manual gate (live-verify, controller-run), Background (grounded), Design, Global Constraints (+4 more)

### Community 482 - "build_alert_store"
Cohesion: 0.16
Nodes (22): NameResolver, Names in a free-text request that resolve to a KB entity at an exact level:, resolve_spans(), Name resolution cascade over a fake mirror + graph built from live facts (2026-0, resolver(), test_a_query_inside_a_long_name_scores_below_a_short_one(), test_a_typo_is_not_taken_for_another_name_plus_an_ending(), test_alias_beats_translit_and_is_reported() (+14 more)

### Community 484 - "Дорожная карта — аналитический слой и его развитие"
Cohesion: 0.17
Nodes (12): 1. Каркас: три слоя, одна программа, 2. Два типа направлений развития, 3. План по волнам, 4. Шесть эволюционных арок — суть, 5. Зависимости и горизонты, 6. Трассировка: направление → волна → спека, Волна 0 — Фундамент (онлайн, без новой инфраструктуры, без LLM) 🟢, Волна 1 — Тяжёлый тир и композиты (нужна материализация) 🟠 (+4 more)

### Community 485 - "Wikibase populator runbook"
Cohesion: 0.17
Nodes (12): 10. Troubleshooting, 11. Future improvements, 1. Overview, 2. Bring-up, 3. Bootstrap base classes + properties, 4. Enable the push activity, 5. Smoke verify end-to-end, 6. Querying via SPARQL (wdqs) (+4 more)

### Community 486 - "Поток поиска"
Cohesion: 0.17
Nodes (12): Drift — сначала local, потом global, Dual walk-seed, Global — GraphRAG map-reduce (`GlobalSearchWorkflow`), Local — plan-execute (`SearchOrchestratorWorkflow`), Reranker + проверка покрытия, Иерархические сообщества + динамический отбор, Инструменты извлечения, История диалога (многоходовая) (+4 more)

### Community 487 - "Hermes ↔ RAG Integration Implementation Plan"
Cohesion: 0.17
Nodes (11): Background facts (verified against the code), File Structure, Hermes ↔ RAG Integration Implementation Plan, kb_search (тяжёлый escape-hatch для многоходовых вопросов), Self-review (completed by plan author), Task 1: Enforce Bearer auth on the SSE transport, Task 2: Author the `knowledge-base` SKILL.md, Task 3: Operator runbook + example Hermes config (+3 more)

### Community 488 - "K+N throttle migration — Implementation Plan"
Cohesion: 0.17
Nodes (11): File Structure, K+N throttle migration — Implementation Plan, Self-Review notes (author), Task 1: Collapse `LLMPoolSettings` + `IngestAdmissionSettings` in config, Task 2: Rewrite `LLMPool` to one global semaphore, Task 3: Close the leak — route 4 search accessors through the pool, Task 4: Remove the redundant `map_parallelism` throttle, Task 5: Admission always-on in the ingest route (+3 more)

### Community 489 - "Global Constraints"
Cohesion: 0.17
Nodes (11): Community detection offload — Implementation Plan, Global Constraints, Out of scope (future), Post-implementation (NOT a code task — operator decision), Task 1: Dependencies + backend config flag, Task 2: Streamed edge extractor, Task 3: Clusterer — flat single-level rows, Task 4: Clusterer — hierarchy via iterative aggregation (+3 more)

### Community 490 - "Analytics Layer — LOCAL dev Activation (host-run app + dockerized infra)"
Cohesion: 0.17
Nodes (11): 0. Prereqs, Analytics Layer — LOCAL dev Activation (host-run app + dockerized infra), Local caveats (from prior local-dev experience), Local validation run (2026-07-01), Phase 1 — first_seen (host), Phase 2 — materialize (host), Phase 3 — monitor (host), Phase 4 — push (host) (+3 more)

### Community 491 - "Global Constraints"
Cohesion: 0.17
Nodes (12): Manual channel reingest + low-priority lane plan, Global Constraints, Manual channel reingest + low-priority ingest lane — Implementation Plan, Self-Review, Task 1: Priority constants + queue `x-max-priority`, Task 2: Publisher stamps message priority, Task 3: Thread priority through `submit_document`, Task 4: `/ingest` priority form field + validation (+4 more)

### Community 492 - "Вынос community-detection из Neo4j — дизайн"
Cohesion: 0.17
Nodes (11): Архитектура, Бенчмарк и eval (строгий паритет — гейт для флипа дефолта), Вне scope (заметки на будущее), Вынос community-detection из Neo4j — дизайн, Компоненты (каждый тестируется независимо), Конфиг / зависимости, Обработка ошибок, Проблема (+3 more)

### Community 493 - "Nebula analytics — connections primitive (nGQL) + AnalyticsGraphOps pattern"
Cohesion: 0.17
Nodes (11): 1. Seam: `AnalyticsGraphOps` (`src/graph/analytics_graph_ops.py`, new — the pattern for all Tier-A), 2. Integration (`connections.py`), 3. Nebula nGQL sketch (per read), 4. Tests (DB-free) + live gate, Background (grounded), Design, Global Constraints, Goal (+3 more)

### Community 494 - "Nebula community-READ (map summaries, nGQL) — backend-dispatched"
Cohesion: 0.17
Nodes (11): Background (grounded), Design, Global Constraints, Goal, Integration (`global_search.py`), Interfaces produced, Manual gate (live-verify), Nebula community-READ (map summaries, nGQL) — backend-dispatched (+3 more)

### Community 495 - "Nebula ingest write batching — throughput scale-blocker"
Cohesion: 0.17
Nodes (11): 1. Config, 2. `nebula_store.py` — batched upserts, 3. Tests (DB-free), 4. Manual gate (live-verify), Background (grounded), Design, Global Constraints, Goal (+3 more)

### Community 496 - "Nebula wiki-editor graph ops — the cutover CRASH-set port"
Cohesion: 0.17
Nodes (11): 1. Schema (`nebula_schema.py`), 2. Seam: `WikiGraphOps` (`src/graph/wiki_graph_ops.py`, new), 3. Integration, 4. Tests (DB-free) + manual gate, Background (grounded), Design, Global Constraints, Goal (+3 more)

### Community 497 - "Manual channel reingest command + low-priority ingest lane"
Cohesion: 0.17
Nodes (11): Behavior summary, Context (current state), Design, Files touched, Manual channel reingest command + low-priority ingest lane, Out of scope, Part 1 — Priority lane, Part 2 — Reingest CLI mode (`scripts/tg_ingest.py`) (+3 more)

### Community 498 - "Claim"
Cohesion: 0.33
Nodes (9): handle_entity(), Entity lookup by name prefix. Cheap — no concurrency slot, no     quota: it is a, _ctx_with_entities(), It is an index read, not a search. Rationing it would ration the     only fast c, test_entity_costs_no_quota_and_no_slot(), test_entity_empty_query_asks_for_one(), test_entity_fails_soft(), test_entity_needs_admission() (+1 more)

### Community 501 - "Extraction Quality & Canonical Linking Implementation Plan"
Cohesion: 0.18
Nodes (10): Extraction Quality & Canonical Linking Implementation Plan, File Structure, Out of scope (proposed as Plan #2 — Agentic Search Quality), Self-Review notes, Task 1: Multilingual NER benchmark harness, Task 2: GLiNER optional extractor (opt-in, no default switch), Task 3: Expand deterministic identifiers (BankAccount, KPP, IBAN, CreditCard), Task 4: Parallelize the ER LLM-judge batches (+2 more)

### Community 502 - "File Structure"
Cohesion: 0.18
Nodes (10): File Structure, Final verification, Graph-search Entity Recall Implementation Plan, Self-Review, Task 1: `build_fulltext_query` pure helper, Task 2: `ensure_entity_fulltext_index`, Task 3: `GraphRetriever.afind_entities_by_name`, Task 4: `find_entity_by_name` atomic tool (+2 more)

### Community 503 - "Interactive `.env` Builder Implementation Plan"
Cohesion: 0.18
Nodes (10): File Structure, Interactive `.env` Builder Implementation Plan, Self-Review notes (for the implementer), Task 1: Line model + `parse_example`, Task 2: `render` + round-trip invariant, Task 3: `parse_env` (merge default-source), Task 4: `is_secret` + `gen_secret`, Task 5: `validate` (cross-field) (+2 more)

### Community 504 - "LLM Pool Consolidation Implementation Plan"
Cohesion: 0.18
Nodes (10): File Structure, Final verification, LLM Pool Consolidation Implementation Plan, Task 1: `BoundedLLM` accepts ordered gates, Task 2: `LLMPoolSettings` config, Task 3: `LLMPool` + `Lane` + singleton accessor, Task 4: Migrate search-side call-sites to the pool, Task 5: Plug the ingest leak (extract + merge through the pool) (+2 more)

### Community 505 - "Global Constraints"
Cohesion: 0.18
Nodes (10): E2 Event Time-Frames Implementation Plan, Global Constraints, Task 1: Deterministic resolver module, Task 2: Parse-side sanity gate for the ts field, Task 3: Prompt contract — verbatim copy + taxonomy injection, Task 4: Wire resolver + taxonomy into event nodes, Task 5: Dedup key on epochs, Task 6: Primitives read the new fields (+2 more)

### Community 506 - "File Structure"
Cohesion: 0.18
Nodes (11): Nebula read-slice (Phase 2) implementation plan, File Structure, Global Constraints, Nebula Read-Slice (Phase 2 vertical slice) Implementation Plan, Self-Review, Task 1: Data model — generic `RELATED` + `rel_type`, Task 2: Store-only `GraphRetriever` for nebula + `aretrieve` guard, Task 3: find-by-name via nGQL `LOOKUP` (+3 more)

### Community 507 - "Spec — Seven Tracks (2026-06-15)"
Cohesion: 0.18
Nodes (10): Build order, Spec — Seven Tracks (2026-06-15), Track 1 — Production docker-compose, everything in compose (LAST / parallelizable), Track 2 — Input document classifier (skip) with force-override, Track 3 — Source-document-by-id is broken (FIRST, quick, independent), Track 4 — Leiden at 50k: instrumentation + weighted + knobs, Track 5 — Document-level admission control (variant A), Track 6 — Templated answers (variant a: text template) (+2 more)

### Community 508 - "stats.py"
Cohesion: 0.20
Nodes (19): CoverageResult, Output of ``coverage_check``.      ``complete`` — is the gathered evidence suffi, build_evidence(), Pure coverage-gate helpers for the plan-execute flow (R4).  Extracted as plain f, Join merged source texts into one bounded evidence blob for the     coverage jud, Decide whether to issue ONE more sub-question after a coverage check.      Retur, should_run_coverage_round(), _n() (+11 more)

### Community 510 - "test_retriever_fulltext.py"
Cohesion: 0.20
Nodes (6): _Conn, _Cur, _pool(), The entity mirror writer fills the name-resolution columns, and survives an old, test_mirror_falls_back_to_the_old_columns_before_the_migration(), test_mirror_writes_norm_and_translit()

### Community 512 - "Очереди задач Temporal"
Cohesion: 0.20
Nodes (10): Активности, зарегистрированные на `kb-search-small`, Выделенная merge-очередь: `kb-ingest-merge`, Контроль допуска документов: `IngestSchedulerWorkflow` (Track 5, опционально), Лимиты очередей против LLMPool — кто на самом деле владеет конкурентностью, Маппинг tier модели ↔ очередь, Оффлайн-очередь сборки сообществ графа: `kb-graph-build` (Search R6), Очереди задач Temporal, Очередь непрерывного wiki-редактора: kb-wiki (+2 more)

### Community 513 - "QUICKSTART — быстрый запуск kb-llamaindex"
Cohesion: 0.20
Nodes (10): 1. Предусловия, 2. Шаг 1 — конфигурация (`.env`), 3. Шаг 2 — поднять инфраструктуру, 4. Шаг 3 — инициализировать схемы, 5. Шаг 4 — запустить воркер и API, 6. Шаг 5 — проверить (smoke), 7. Включение опциональных возможностей (матрица), 8. Сброс (чистый слейт) (+2 more)

### Community 514 - "Identifier-aware Search Quality Plan"
Cohesion: 0.20
Nodes (9): Execution Handoff, Identifier-aware Search Quality Plan, Self-Review, Stage 1 — Ingestion hygiene, Stage 2 — Retrieval-side smarts, Task 1: Split canon-block out of `node.text`, Task 2: Generalise consolidation to all identifier types, Task 3: Hub-aware graph traversal (+1 more)

### Community 515 - "Plan — Seven Tracks (2026-06-15)"
Cohesion: 0.20
Nodes (9): Plan — Seven Tracks (2026-06-15), Track 1 — prod compose (branch `feat/prod-compose`, parallelizable), Track 2 — classifier + force (branch `feat/ingest-classifier`), Track 3 — doc-by-id (branch `fix/doc-by-id-load`)  ← START HERE, Track 4 — Leiden (branch `feat/leiden-weighted-instrumented`), Track 5 — admission scheduler (branch `feat/ingest-admission-control`), Track 6 — answer template (branch `feat/answer-template`), Track 7a — relation weight + tags (branch `feat/relation-weight-tags`) (+1 more)

### Community 516 - "Approach — contextualize, don't dump"
Cohesion: 0.20
Nodes (10): Approach — contextualize, don't dump, Components touched, Conversation history (multi-turn search) — design, Data flow, Conversation history (multi-turn search) design, Error handling / back-compat, Goal, Problem (+2 more)

### Community 517 - "Measured numbers (Apple Silicon dev box, live local stack)"
Cohesion: 0.20
Nodes (9): Interpreting, Measured numbers (Apple Silicon dev box, live local stack), P0.1 structural — native Neo4j vector kNN vs the 5000-window, P0.2 — ER candidate-gen, single label, real `_candidate_pairs`, P1.1 — Milvus FLAT vs HNSW (clustered vectors, top-k=10, ef=64), P1.2 — graph_walk hub cliff (live Neo4j, 20k nodes, hops=2, cap=50), Run, Synthetic scale-bench harness (+1 more)

### Community 518 - "Bruno API-коллекция — kb-llamaindex"
Cohesion: 0.22
Nodes (8): Bruno API-коллекция — kb-llamaindex, Аутентификация, Заметки, Обновление коллекции, Открыть в Bruno, Переменные окружения, Структура, Типичный сценарий

### Community 519 - "Hierarchical communities + dynamic community selection Implementation Plan"
Cohesion: 0.22
Nodes (8): Hierarchical communities + dynamic community selection Implementation Plan, Phase 0 — SPIKE: verify the dendrogram shape (BLOCKING, decides hierarchy source), Phase 1 — hierarchy detection (levels + PARENT_OF + members_hash), Phase 2 — structured reports, bottom-up, incremental, embedded, Phase 3 — build workflow drives hierarchy bottom-up, reports only what changed, Phase 4 — dynamic selection (v1 semantic + v2 descent), Phase 5 — config, wiring, live verification, Self-Review

### Community 520 - "Deploy redesign — Batch 1 (correctness) Implementation Plan"
Cohesion: 0.22
Nodes (8): Deploy redesign — Batch 1 (correctness) Implementation Plan, File Structure, Self-Review notes (author), Task 1: Lock the canonical embedding profile (1536 / OpenAI), Task 2: Fail-fast preflight at boot, Task 3: `init` one-shot service runs setup_db automatically, Task 4: `setup_wikibase` without the host docker socket, Task 5: Verification sweep + live check

### Community 521 - "Deploy redesign — Batch 2 (single source of truth) Implementation Plan"
Cohesion: 0.22
Nodes (8): Deploy redesign — Batch 2 (single source of truth) Implementation Plan, File Structure, Self-Review notes (author), Task 1: Introspect config.py → env var catalog, Task 2: `--reference` generation + `--check` drift guard, Task 3: Generate + commit `.env.reference`, Task 4: Expose prod-correct defaults (Component 6), Task 5: Verification sweep

### Community 522 - "File Structure"
Cohesion: 0.22
Nodes (9): report_vec → Milvus (semantic slice) implementation plan, File Structure, Global Constraints, report_vec → Milvus (semantic slice) Implementation Plan, Self-Review, Task 1: seam + Neo4j impl + factory + config, Task 2: `MilvusCommunityReportVectorStore` (`community_report_vec`), Task 3: write + read wiring (+1 more)

### Community 523 - "File Structure"
Cohesion: 0.22
Nodes (9): Nebula community-BUILD (nGQL) implementation plan, File Structure, Global Constraints, Nebula community-BUILD (nGQL) Implementation Plan, Notes for the manual gate (post-merge, controller-run), Task 1: Nebula schema — `Community` TAG + level index, Task 2: Seam scaffold — `community_vid`, Protocol, `Neo4jCommunityWriteback`, dispatch, Task 3: `NebulaCommunityWriteback` — nGQL implementation (+1 more)

### Community 524 - "12. Further development / Roadmap"
Cohesion: 0.22
Nodes (9): 12. Further development / Roadmap, Arc 1 — Deeper compute (richer algorithms), Arc 2 — From Q&A to intelligence ⭐ (highest leverage for this domain), Arc 3 — Smarter planning, Arc 4 — Self-improving catalog + trust, Arc 5 — Surfaces & delivery, Arc 6 — Data enrichment (feeding the analytics better data), Highest-leverage for this corpus (what to do first after v1) (+1 more)

### Community 525 - "Phase 2 (vertical slice) — Nebula read-path design"
Cohesion: 0.22
Nodes (8): Global Constraints, Goal, In scope, Interfaces produced, Known gaps to close before enabling `GRAPH_BACKEND=nebula` under load, Out of scope (deferred), Phase 2 (vertical slice) — Nebula read-path design, Verification

### Community 527 - "Search date filters — implementation plan (Rev 2)"
Cohesion: 0.25
Nodes (7): Phase 0 — branch + clean port  ✅ DONE (uncommitted), Phase 1 — data model + ingest stamping  ✅ DONE (uncommitted → committed), Phase 2 — search API + retrieval post-filter, Phase 2 — search API + retrieval post-filter  ✅ DONE (uncommitted), Phase 3 — verify + hand off, Risks / watch, Search date filters — implementation plan (Rev 2)

### Community 528 - "Global Constraints"
Cohesion: 0.25
Nodes (7): Global Constraints, Hierarchical Community Leaf-Context Implementation Plan, Self-Review, Task 1: Member-рёбра на каждом уровне (ядро фикса), Task 2: Заскоупить documents-for-communities на level 0 (back-compat), Task 3: E2E-валидация иерархии на локальном графе, Task 4: Аудит — использует ли поиск уровни иерархии

### Community 529 - "TG → ingest test harness — Implementation Plan"
Cohesion: 0.25
Nodes (7): File Structure, Global Constraints, Self-Review, Task 1: RabbitMQ dev-compose service + telethon optional dep, Task 2: `scripts/tg_ingest.py` — `_message_to_doc` + `post_ingest`, Task 3: `read_and_enqueue` orchestration + `main` CLI, TG → ingest test harness — Implementation Plan

### Community 530 - "File Structure"
Cohesion: 0.25
Nodes (8): Nebula community-SUMMARIZE (nGQL) implementation plan, File Structure, Global Constraints, Nebula community-SUMMARIZE (nGQL) Implementation Plan, Notes for the manual gate (post-merge, controller-run), Task 1: `CommunitySummarize` seam + Neo4j impl + dispatch (additive), Task 2: `NebulaCommunitySummarize` — nGQL implementation, Task 3: Route `community.py` SUMMARIZE through the seam

### Community 534 - "Changelog"
Cohesion: 0.29
Nodes (6): Added, Added, Changelog, Notes, [Search R0] — 2026-05-25 — Search package scaffold, [Search R3b] — 2026-05-26 — Activate graph_walk in retrieve path

### Community 535 - "ADR-0001: Temporal для надёжной оркестрации"
Cohesion: 0.29
Nodes (6): ADR-0001: Temporal для надёжной оркестрации, Контекст, Последствия, Рассмотренные альтернативы, Решение, Ссылки

### Community 536 - "ADR-0003: Изоляция очередей задач во избежание head-of-line блокировки"
Cohesion: 0.29
Nodes (6): ADR-0003: Изоляция очередей задач во избежание head-of-line блокировки, Контекст, Последствия, Рассмотренные альтернативы, Решение, Ссылки

### Community 537 - "ADR-0007: Entity Resolution = генерация кандидатов + LLM-судья + кэш вердиктов + union-find"
Cohesion: 0.29
Nodes (6): ADR-0007: Entity Resolution = генерация кандидатов + LLM-судья + кэш вердиктов + union-find, Контекст, Последствия, Рассмотренные альтернативы, Решение, Ссылки

### Community 538 - "ADR-0008: Опциональный native-vector kNN ER поверх окна в 5000 строк"
Cohesion: 0.21
Nodes (7): check_events(), check_milvus(), check_neo4j(), check_postgres(), main(), Diagnostic — show what landed in each backend after ingestion.  Pings every stor, Wave 2 config tests: EventsSettings (extraction) + MonitorSettings.

### Community 540 - "ADR-0010: Динамический выбор сообществ (лексический / семантический / спуск, fail-open)"
Cohesion: 0.52
Nodes (6): _key(), _post(), ASGI tests for the /admin/graph/* analysis endpoints (Track 7b)., test_graph_stats_endpoint_returns_analysis(), test_graph_stats_requires_api_key(), test_pagerank_endpoint_wraps_top()

### Community 541 - "ADR-0011: Plan-execute SearchOrchestratorWorkflow (Self-RAG/ReAct удалён) + ограниченный цикл покрытия"
Cohesion: 0.29
Nodes (6): ADR-0011: Plan-execute SearchOrchestratorWorkflow (Self-RAG/ReAct удалён) + ограниченный цикл покрытия, Контекст, Последствия, Рассмотренные альтернативы, Решение, Ссылки

### Community 543 - "ADR-0014: Скачивание исходных документов через стабильный API-endpoint (не presigned URL)"
Cohesion: 0.07
Nodes (21): main(), Idempotent DB initialisation.  Stage 1 scope:   * Postgres — create ``documents`, `'a', 'b', 'c'` for a SQL `IN (...)` clause — sorted so the     generated DDL te, Register the three custom Search Attributes used by the     analytics layer (Sta, Enforce the configured closed-workflow retention on the namespace.      Bounds P, Verify Milvus reachable; collection lifecycle owned by     ``MilvusVectorStore``, Ensure the user-upload bucket exists.  Same MinIO instance the     Milvus backen, setup_milvus() (+13 more)

### Community 544 - "NebulaGraph cutover — neo4j decommissioned"
Cohesion: 0.29
Nodes (6): Known nGQL rules that shaped the port (reference), Nebula functional coverage at cutover (all live-verified, merged to local main), NebulaGraph cutover — neo4j decommissioned, Rollback (retained on purpose), What changed (code — this commit), What is DEPLOY (you run this), not code

### Community 545 - "Wiki article quality + source-download links — Implementation Plan"
Cohesion: 0.29
Nodes (6): Task 1: Config — relation cap, docs base URL, citation default, Task 2: wiki_context — hash folds doc_ids, relation cap/rank, citation dedup, read_source_docs, Task 3: article — "Источники" section render, Task 4: wiki_sweep — wire source docs + new params into write_entity_article, Task 5: Docs touch-up + final review, Wiki article quality + source-download links — Implementation Plan

### Community 546 - "Deploy redesign — Batch 3 (DX) Implementation Plan"
Cohesion: 0.29
Nodes (6): Deploy redesign — Batch 3 (DX) Implementation Plan, File Structure, Self-Review notes (author), Task 1: Makefile — one-command bring-up, Task 2: Refresh start.sh + fix stale README + QUICKSTART rewrite, Task 3: Verification

### Community 547 - "4. Primitive catalog"
Cohesion: 0.29
Nodes (7): 4. Primitive catalog, Cross-cutting conventions (apply to every primitive), Family 1 — Aggregations & rankings 🟢, Family 2 — Connections & co-occurrence 🟢, Family 3 — Centrality & clusters, Family 4 — Temporal dynamics 🟢, Tier & dependency summary

### Community 548 - "ADR-0009: Иерархические сообщества Leiden + структурированные отчёты (GraphRAG-style global)"
Cohesion: 0.29
Nodes (6): ADR-0009: Иерархические сообщества Leiden + структурированные отчёты (GraphRAG-style global), Контекст, Последствия, Рассмотренные альтернативы, Решение, Ссылки

### Community 552 - "Hermes Agent integration runbook"
Cohesion: 0.33
Nodes (6): 1. Поднять SSE-сервисы, 2. Зарегистрировать в Hermes, 3. Установить скилл, 4. Smoke-проверка, 5. Приёмочные сценарии, Hermes Agent integration runbook

### Community 553 - "Индекс runbook'ов"
Cohesion: 0.33
Nodes (6): Runbook'и, Архитектурные документы (не runbook'и), Индекс runbook'ов, Недавно выпущенное (хронологически), Планы и спеки, Что обновляется когда

### Community 554 - "nGQL translation rules for the analytics port (live-proven, nebula 3.8)"
Cohesion: 0.33
Nodes (5): Method: every ported primitive gets a live-verify, nGQL translation rules for the analytics port (live-proven, nebula 3.8), Schema facts (the port must respect these), Translation rules (each live-verified), Verified example shapes (copy as starting points)

### Community 555 - "Conversation history (multi-turn search) Implementation Plan"
Cohesion: 0.33
Nodes (5): Conversation history (multi-turn search) Implementation Plan, Phase 1 — request model, contracts, config, Phase 2 — contextualize_query activity, Phase 3 — wire into the workflows + route, Self-Review

### Community 556 - "Graph-scale follow-ups (items 8 / 13 / 12) Implementation Plan"
Cohesion: 0.33
Nodes (5): Graph-scale follow-ups (items 8 / 13 / 12) Implementation Plan, Phase 1 — Item 8: dual walk-seed (graph_search + fulltext), Phase 2 — Item 13: drift graceful fallback on global failure, Phase 3 — Item 12: community indexes, Self-Review

### Community 557 - "Analytics Layer — PROD Activation Checklist (Waves 0–3)"
Cohesion: 0.33
Nodes (5): 0. Pre-requisites, Analytics Layer — PROD Activation Checklist (Waves 0–3), Env block (add to the `x-app-env` anchor; recommended prod values), Linear checklist, Rollback (any phase)

### Community 558 - "Knowledge Base"
Cohesion: 0.33
Nodes (5): Follow-up handling (multi-turn), Knowledge Base, Memory (record and reuse `~/.hermes/`), Response templates (by task type), Tool selection (orient on the problem first)

### Community 561 - "[Search R1] — 2026-05-25 — Two-tier model architecture"
Cohesion: 0.40
Nodes (5): Added, Changed, Notes, Removed, [Search R1] — 2026-05-25 — Two-tier model architecture

### Community 562 - "[R1] — 2026-05-11 — Model migration to qwen3:8b"
Cohesion: 0.40
Nodes (5): Added, Changed, Cleanup (refactoring mandate), [R1] — 2026-05-11 — Model migration to qwen3:8b, Verified

### Community 563 - "[Search R7b] — 2026-05-26 — Legacy search cutover (BREAKING)"
Cohesion: 0.40
Nodes (5): Changed, Kept (SHARED — the new path depends on these), Notes, Removed, [Search R7b] — 2026-05-26 — Legacy search cutover (BREAKING)

### Community 565 - "[Search R5] — 2026-05-26 — Large-tier synthesis queue + unified rerank"
Cohesion: 0.50
Nodes (4): Added, Changed, Notes, [Search R5] — 2026-05-26 — Large-tier synthesis queue + unified rerank

### Community 566 - "[Search R2] — 2026-05-26 — Plan-execute orchestrator + /search/local"
Cohesion: 0.50
Nodes (4): Added, Changed, Notes, [Search R2] — 2026-05-26 — Plan-execute orchestrator + /search/local

### Community 567 - "[Ingest Merge Queue] — 2026-05-26 — Dedicated kb-ingest-merge queue"
Cohesion: 0.50
Nodes (4): Added, Changed, [Ingest Merge Queue] — 2026-05-26 — Dedicated kb-ingest-merge queue, Notes

### Community 568 - "[post-Stage-9 fixes] — 2026-05-11 — Live KG extraction wired"
Cohesion: 0.50
Nodes (4): Added, Fixed, Notes, [post-Stage-9 fixes] — 2026-05-11 — Live KG extraction wired

### Community 569 - "[Stage 0] — 2026-05-09 — Bootstrap"
Cohesion: 0.50
Nodes (4): Added, Decision: directory tree, Notes, [Stage 0] — 2026-05-09 — Bootstrap

### Community 570 - "[Source Trust] — 2026-08-30 — Доверие к источнику решает конфликты фактов"
Cohesion: 0.67
Nodes (3): Added, Notes, [Source Trust] — 2026-08-30 — Доверие к источнику решает конфликты фактов

### Community 571 - "[Search R7a] — 2026-05-26 — Query routing + GraphRAG global search (additive)"
Cohesion: 0.67
Nodes (3): Added, Notes, [Search R7a] — 2026-05-26 — Query routing + GraphRAG global search (additive)

### Community 572 - "[Search R6] — 2026-05-26 — Offline community build (GDS Leiden + summaries)"
Cohesion: 0.67
Nodes (3): Added, Notes, [Search R6] — 2026-05-26 — Offline community build (GDS Leiden + summaries)

### Community 573 - "[Search R4] — 2026-05-26 — Coverage gate on orchestrator"
Cohesion: 0.67
Nodes (3): Added, Notes, [Search R4] — 2026-05-26 — Coverage gate on orchestrator

### Community 574 - "[Search R3] — 2026-05-26 — Multi-hop graph_walk tool"
Cohesion: 0.67
Nodes (3): Added, Notes, [Search R3] — 2026-05-26 — Multi-hop graph_walk tool

### Community 575 - "[Stage 9] — 2026-05-09 — Eval gate + ops scripts"
Cohesion: 0.67
Nodes (3): Added, Notes, [Stage 9] — 2026-05-09 — Eval gate + ops scripts

### Community 576 - "[Stage 8] — 2026-05-09 — FastAPI + Taskiq worker"
Cohesion: 0.67
Nodes (3): Added, Notes, [Stage 8] — 2026-05-09 — FastAPI + Taskiq worker

### Community 577 - "[Stage 7] — 2026-05-09 — Identifier canonicalization"
Cohesion: 0.67
Nodes (3): Added, Notes, [Stage 7] — 2026-05-09 — Identifier canonicalization

### Community 578 - "[Stage 6] — 2026-05-09 — Knowledge graph (PropertyGraphIndex)"
Cohesion: 0.67
Nodes (3): Added, Notes, [Stage 6] — 2026-05-09 — Knowledge graph (PropertyGraphIndex)

### Community 579 - "[Stage 5] — 2026-05-09 — Hybrid retrieval (BM25 + vector + RRF)"
Cohesion: 0.67
Nodes (3): Added, Notes, [Stage 5] — 2026-05-09 — Hybrid retrieval (BM25 + vector + RRF)

### Community 580 - "[Offline Models] — 2026-05-26 — Offline HF model loading + pre-download script"
Cohesion: 0.67
Nodes (3): Added, Changed, [Offline Models] — 2026-05-26 — Offline HF model loading + pre-download script

### Community 581 - "[Stage 4] — 2026-05-09 — Agentic loop (PRIORITY)"
Cohesion: 0.67
Nodes (3): Added, Notes, [Stage 4] — 2026-05-09 — Agentic loop (PRIORITY)

### Community 582 - "[Stage 3] — 2026-05-09 — Vector index + basic query engine"
Cohesion: 0.67
Nodes (3): Added, Notes, [Stage 3] — 2026-05-09 — Vector index + basic query engine

### Community 583 - "[Stage 2] — 2026-05-09 — IngestionPipeline (parsing + chunking)"
Cohesion: 0.67
Nodes (3): Added, Notes, [Stage 2] — 2026-05-09 — IngestionPipeline (parsing + chunking)

### Community 584 - "[Stage 1] — 2026-05-09 — Minimal infra (Milvus + Postgres + LiteLLM)"
Cohesion: 0.67
Nodes (3): Added, Notes, [Stage 1] — 2026-05-09 — Minimal infra (Milvus + Postgres + LiteLLM)

### Community 585 - "LiteLLM vLLM config"
Cohesion: 0.67
Nodes (3): LiteLLM scale config (Ollama fleet), LiteLLM vLLM config, LLMPool concurrency gating

### Community 1065 - "_FakeVal"
Cohesion: 0.32
Nodes (5): _Data, find_entity_by_name atomic tool., _Retriever, test_find_entity_by_name_none_retriever(), test_find_entity_by_name_returns_entities()

### Community 1068 - "test_communities.py"
Cohesion: 0.21
Nodes (10): SentenceTransformerRerank, configure_hf(), Offline HuggingFace cache wiring for air-gapped deploys.  ``configure_hf()`` tra, Set ``os.environ[name]`` only when it is not already set, so an     operator's e, Apply ``settings.hf`` to the HuggingFace env vars (idempotent).      * ``cache_d, _set_if_absent(), build_reranker(), Cross-encoder reranker (BGE-reranker-v2-m3 by default).  Exposed as a separate f (+2 more)

### Community 1073 - "test_analytics_materialize_hardening.py"
Cohesion: 0.33
Nodes (3): Guard: the analytics materialize heartbeat window must exceed its GIL-held compu, A window sized to *today's* compute is stale by the next deploy.      The graph, test_heartbeat_window_survives_observed_graph_growth()

### Community 1074 - "test_search_server.py"
Cohesion: 0.29
Nodes (3): Smoke tests for the MCP-1 search server.  We don't talk to a real Temporal clust, assert_api_key_env_set raises SystemExit when require=true and     api_keys list, test_auth_gate_blocks_when_keys_missing()

### Community 1083 - "test_value_kind_families_partition_the_enumeration"
Cohesion: 0.18
Nodes (9): monitor_sweep(), monitor_watch(), Admin operations: trigger wiki/monitor sweeps and monitor watchlist., wiki_rebuild(), ASGI tests for POST /admin/wiki/rebuild.  The WIKI_ENABLED default is False, so, WIKI_ENABLED defaults False → route returns disabled without infra., `?all=true` (when enabled) marks every entity dirty via     build_wiki_graph_ops, test_wiki_rebuild_all_routes_mark_all_dirty_through_seam() (+1 more)

### Community 1085 - "test_stats_pipeline.py"
Cohesion: 0.33
Nodes (9): _fake_primitive(), _indicator_series(), The end-to-end composition MCP-2 `topic_trend` → MCP-3 `stat_align`.  No task ow, The MCP-3 side: what `stat_series` returns per row., `month` is `topic_trend`'s default, and its `"2026-03"` labels are     exactly w, `since`/`until` drop buckets; the rows that survive must still     carry the key, test_composition_survives_the_windowed_subset(), test_topic_trend_rows_feed_stat_align_at_month_granularity() (+1 more)

### Community 1088 - "build_burst_cypher"
Cohesion: 0.39
Nodes (6): build_burst_cypher(), E3 — shared burst computation over event created_at (single source for the trend, Parameterized burst query grouped by (participant entity, event_type).      rece, test_burst_cypher_core_shape(), test_burst_cypher_counts_distinct_events(), test_burst_cypher_watched_only_adds_clause()

### Community 1089 - "build_search_query"
Cohesion: 0.22
Nodes (8): build_search_query(), Trigram search over the registry — the only searchable surface     the subsystem, `%` is psycopg's placeholder marker, so the trigram operator has     to be writt, The counter-proof: with one `%` psycopg reads `% %s` as a broken     placeholder, test_search_query_filters_by_source(), test_search_query_single_percent_would_not_survive_conversion(), test_search_query_uses_trigram_similarity_and_caps_limit(), test_trigram_operator_survives_psycopg_placeholder_expansion()

### Community 1090 - "test_stats_routes.py"
Cohesion: 0.39
Nodes (6): _api_key_header(), Stats routes: JSON shape, enum validation, auth. pg aggregation methods are patc, test_messages_stats_bad_group_by_422(), test_messages_stats_shape(), test_timeline_bad_date_field_422(), test_timeline_shape()

### Community 1091 - "_NameRetriever"
Cohesion: 0.25
Nodes (14): fetch_from(), FakeGraph, obs(), kb-tools with name resolution: resolve first, act on that one entity, report it;, awalk = the real neighbourhood of one vertex; aretrieve = the old seed-everythin, resolver(), test_a_people_question_filters_to_persons_and_a_timeout_orders_by_edges(), test_find_entity_by_id_is_strict_and_offers_candidates() (+6 more)

### Community 1096 - "build_tool_schema"
Cohesion: 0.40
Nodes (5): build_tool_schema(), _injected_params(), BaseModel, Names of the DI-injected dependency args.      Every tool function takes its dep, Pydantic schema of the LLM-facing kwargs for ``name``.      Derived from the rea

### Community 1098 - "test_completion_no_walltime_cap.py"
Cohesion: 0.38
Nodes (6): _activity_block(), Guard: LLM-bound ingest activities are bounded by ATTEMPT COUNT, not wall-clock., Permanently-failing docs must give up and free their slot (incident #2)., test_extract_kg_has_no_walltime_cap(), test_merge_and_resolve_has_no_walltime_cap(), test_retry_policies_bounded_to_max_attempts()

## Ambiguous Edges - Review These
- `Neo4j property graph store` → `Production docker-compose`  [AMBIGUOUS]
  docker-compose.prod.yml · relation: conceptually_related_to

## Knowledge Gaps
- **2262 isolated node(s):** `@mimo-ai/plugin`, `entrypoint.sh script`, `[bindHost, bindPort]`, `target`, `allow` (+2257 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **534 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `Neo4j property graph store` and `Production docker-compose`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **Why does `entity_vid()` connect `test_graph: entity_vid()` to `PostgresERVerdictCache`, `test_graph_edge_export.py`, `test_workflow: test_completion_no_walltime_cap.py`, `test_graph: test_wiki_graph_ops.py`, `test_graph: test_communities_graph_ops.py`, `test_storage: test_ingest_metrics.py`, `test_graph: write_with_retry()`, `run_answer_eval.py`, `CAPACITY_TUNING.md: LLM_POOL_N throttle`, `er_graph_ops.py`, `BACKLOG.md`, `test_retrieval: RoundGraphData`, `mcp: tools_server.py`, `graph: communities.py`, `test_graph: test_nebula_store_writes.py`, `retrieval: atomic_tools.py`, `test_graph: _FakeClient`, `._validate_iso_date`, `graph: alert_store.py`, `test_graph: test_event_merge.py`, `retrieval: DateBounds`, `test_api: analyze.py`, `test_workflow: dispatch_for_route()`, `test_retrieval: test_graph_path_depth.py`, `test_graph: test_er_graph_ops.py`, `test_graph: test_retriever_fulltext.py`, `graph: community_writeback.py`, `test_graph: extract_entity_edges()`, `test_workflow: test_article.py`, `test_graph: stamp_first_seen()`?**
  _High betweenness centrality (0.029) - this node is a cross-community bridge._
- **Why does `LightRAGExtractor` connect `test_graph: LightRAGExtractor` to `workflow: worker.py`, `test_workflow: _stub_activity_ctx()`, `ner_eval.py`, `test_workflow: IngestParams`, `setup_db.py`, `test_graph: test_index.py`, `test_graph: test_event_extract.py`?**
  _High betweenness centrality (0.027) - this node is a cross-community bridge._
- **Why does `build_graph_store()` connect `test_workflow: contracts.py` to `PostgresERVerdictCache`, `bench_graph_write`, `test_api: AsyncPostgres`, `CAPACITY_TUNING.md: LLM_POOL_N throttle`, `test_workflow: Ctx`, `test_workflow: push_wikibase.py`, `mcp: tools_server.py`, `graph: communities.py`, `bot: with_fallback()`, `api: ingest.py`, `test_value_kind_families_partition_the_enumeration`, `test_graph: test_entity_resolution.py`, `graph: event_ts_resolver.py`, `workflow: worker.py`, `setup_wikibase.py`, `events_eval.py`, `eval: run_scale_bench.py`, `reresolve_graph.py`, `test_config: test_preflight.py`, `GraphRetriever`, `mcp: _shared.py`, `test_graph: test_events_llm_graph_ops.py`, `Automatic event detection — design`, `analytics: materialize.py`, `test_workflow: test_article.py`?**
  _High betweenness centrality (0.023) - this node is a cross-community bridge._
- **Are the 54 inferred relationships involving `PrimitiveResult` (e.g. with `CountEntitiesParams` and `CountRelationshipsParams`) actually correct?**
  _`PrimitiveResult` has 54 INFERRED edges - model-reasoned connections that need verification._
- **Are the 27 inferred relationships involving `AsyncPostgres` (e.g. with `IngestEnqueuedResponse` and `JobProgressResponse`) actually correct?**
  _`AsyncPostgres` has 27 INFERRED edges - model-reasoned connections that need verification._
- **What connects `@mimo-ai/plugin`, `entrypoint.sh script`, `[bindHost, bindPort]` to the rest of the system?**
  _2262 weakly-connected nodes found - possible documentation gaps or missing edges._