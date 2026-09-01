# Graph Report - agent_v2  (2026-08-30)

## Corpus Check
- 838 files · ~1,082,776 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 9253 nodes · 19209 edges · 462 communities (429 shown, 33 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 990 edges (avg confidence: 0.67)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `94f7bc2f`
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
- superpowers: Analytical layer — design (NL
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

## God Nodes (most connected - your core abstractions)
1. `PrimitiveResult` - 130 edges
2. `entity_vid()` - 107 edges
3. `extract_identifiers()` - 95 edges
4. `_q()` - 91 edges
5. `AsyncPostgres` - 83 edges
6. `Primitive` - 70 edges
7. `build_graph_store()` - 64 edges
8. `_Frozen` - 61 edges
9. `_FakeStore` - 61 edges
10. `SerializedNode` - 60 edges

## Surprising Connections (you probably didn't know these)
- `Production docker-compose` --conceptually_related_to--> `Neo4j property graph store`  [AMBIGUOUS]
  docker-compose.prod.yml → docs/ARCHITECTURE.md
- `Production containerized compose deployment` --conceptually_related_to--> `Production docker-compose`  [INFERRED]
  docs/DEPLOYMENT.md → docker-compose.prod.yml
- `Telegram bot overlay` --semantically_similar_to--> `OpenClaw agent gateway overlay`  [INFERRED] [semantically similar]
  docker-compose.bot.yml → docker-compose.openclaw.yml
- `_run_search()` --calls--> `render()`  [INFERRED]
  src/bot/commands.py → scripts/make_env.py
- `_ReadOnlyGraphStore` --uses--> `ERConfig`  [INFERRED]
  scripts/reresolve_graph.py → src/graph/entity_resolution.py

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

## Communities (462 total, 33 thin omitted)

### Community 0 - "test_workflow: test_search_community.py"
Cohesion: 0.11
Nodes (31): Input to ``summarize_community_activity`` — summarise ONE     community's member, SummarizeCommunityParams, Generate a STRUCTURED REPORT for ONE community via the small LLM,     embed it,, summarize_community_activity(), group_specs_by_level(), Group summarize specs by ``level``, FINEST-first.      Returns a list of per-lev, _FakeLLM, _FakeReportStore (+23 more)

### Community 1 - "test_graph: entity_vid()"
Cohesion: 0.04
Nodes (71): entity_vid(), Stable 128-bit VID as a 32-char hex string from an entity name.      read/write, _FakeNode, _FakePath, _FakeRel, _FakeVal, _NebulaRaisingStore, _NebulaRecStore (+63 more)

### Community 2 - "test_graph: test_lightrag_parse.py"
Cohesion: 0.07
Nodes (52): _correct_entity_label(), _first_keyword(), _normalize_entity_name(), parse_lightrag_output(), parsed_relations_to_relations(), Relation, Fix common entity-label mistakes from the extractor.      * Countries mislabeled, Extract the first comma-separated keyword from the relation     `relationship_ke (+44 more)

### Community 3 - "workflow: get_llm_pool()"
Cohesion: 0.05
Nodes (70): ``synthesize_answer`` activity — final answer composition.  Plain ResponseSynthe, Compose the final answer over accumulated context., synthesize_answer(), Input to the ``rerank_sources`` activity (Search R5).      The merged graph+vect, RerankParams, append_unranked_remainder(), prepare_rerank_pool(), ``rerank_sources`` activity — unified graph+vector rerank (R5).  The orchestrato (+62 more)

### Community 4 - "test_ingestion: test_translate_transform.py"
Cohesion: 0.08
Nodes (46): DocumentTranslateTransform, _drop_doc_translation_metadata(), _exclude_doc_translation_metadata(), _looks_russian(), Any, BaseNode, TransformComponent, Per-chunk translation step that normalises ingest input to Russian without losin (+38 more)

### Community 5 - "test_make_env.py"
Cohesion: 0.07
Nodes (70): Line, Blank, build_reference(), build_values(), Comment, EnvVar, gen_secret(), _int() (+62 more)

### Community 6 - "retrieval: BoundedLLM"
Cohesion: 0.13
Nodes (26): _entity_candidates(), _evidence_phrases(), load_medical_golden_cases(), load_medical_qas(), MedicalQA, Loader for the Medical benchmark corpus.  The corpus comes from `tests/eval/corp, Return parsed Q&A entries, optionally filtered & sampled.      `limit=None`: ret, Extract substring-matchable medical keywords from     `evidence_relations`. (+18 more)

### Community 7 - "test_workflow: graph_admin.py"
Cohesion: 0.09
Nodes (40): CentralityIn, LinkPredictionIn, MaterializeParams, MaterializeResult, RiskIn, StageResult, AnalyticsMaterializeWorkflow, AnalyticsMaterializeWorkflow — offline GDS materialization pipeline.  Sequence: (+32 more)

### Community 8 - "test_graph: test_communities.py"
Cohesion: 0.05
Nodes (59): detect_communities(), detect_hierarchy(), _leiden_rows(), _leiden_stream_cypher(), _project_cypher(), _projection_stats(), Any, Extract ``{nodes, rels}`` from the ``gds.graph.project`` result row     (aliased (+51 more)

### Community 9 - "workflow: orchestrator.py"
Cohesion: 0.06
Nodes (87): AgenticStepStatDict, CommunityBuildResult, CoverageParams, _Frozen, OrchestratorParams, PlanParams, PlanResult, BaseModel (+79 more)

### Community 10 - "test_workflow: IngestParams"
Cohesion: 0.40
Nodes (3): _FakeEmbed, Returns a fixed-length vector; records the embedded text., _stub_activity_ctx()

### Community 11 - "test_api: search_v2.py"
Cohesion: 0.09
Nodes (36): _global_params(), _local_params(), Log loudly when a client sends a reserved (unimplemented) filter, so a     silen, Build the local plan-execute workflow input from the request.      ISO date boun, Build the GraphRAG global map-reduce workflow input., _warn_reserved_filters(), ConversationTurn, Reject a malformed date bound → 422 (FastAPI maps ValueError). (+28 more)

### Community 12 - "test_ingestion: extract_identifiers()"
Cohesion: 0.08
Nodes (62): extract_identifiers(), Run every detector on ``text``; return matches sorted by span.      Multiple occ, _by_type(), Unit tests for ``src/ingestion/identifiers.py``.  Coverage goals:   * One happy-, Body-text 'no symptoms' / 'no warranties' must not match —     the regex earlier, `No. SYMPTOMS` should not match — captured token has no digit., Legit `No. 17-K` style references must still extract., test_amount() (+54 more)

### Community 13 - "test_workflow: contracts.py"
Cohesion: 0.07
Nodes (40): DeliverIn, DeliverResult, MonitorResult, SweepResult, heartbeat_every(), Any, Background heartbeater for long-running Temporal activities.  A long activity th, Emit ``activity.heartbeat(detail)`` every ``interval_s`` seconds     while the w (+32 more)

### Community 14 - "workflow: contracts.py"
Cohesion: 0.09
Nodes (48): fetch_source(), Ctx, `fetch_source` — resolve doc path to a local file + mark processing.  Idempotent, IngestParams, WikibasePushed, DocumentIngestWorkflow, `DocumentIngestWorkflow` — composes 8 activities + best-effort graph half and on, GraphBuildWorkflow (+40 more)

### Community 15 - "storage: push_entities()"
Cohesion: 0.08
Nodes (28): _load_cache_from_neo4j(), main(), Operator-side smoke for :mod:`src.storage.wikibase`.  Pushes a tiny fake corpus, Pull cached base-class QIDs + property PIDs from Neo4j., Self-hosted Wikibase populator settings.      When ``enabled=True``, ``DocumentI, WikibaseSettings, AsyncWikibase, _build_claim() (+20 more)

### Community 16 - "eval: test_scale_bench_smoke.py"
Cohesion: 0.11
Nodes (16): extract_entity_edges(), Stream the ``__Entity__`` graph out via the backend-dispatched     ``GraphEdgeEx, _FakeExport, _FakeStore, _FakeStoreHighDegreeSource, _FakeStoreNullCursor, Returns one page of node rows, then one page of edge rows, then empties., Regression: all edges from a high-degree source must survive multi-page reads. (+8 more)

### Community 17 - "ingestion: identifiers.py"
Cohesion: 0.05
Nodes (64): _account_control_ok(), _canonicalize_contract(), _check_inn_10(), _check_inn_12(), _check_ogrn_13(), _check_ogrn_15(), _extract_addresses(), _extract_amounts() (+56 more)

### Community 18 - "test_api: AsyncPostgres"
Cohesion: 0.09
Nodes (29): DetectCommunitiesParams, DetectCommunitiesResult, DetectedCommunity, Input to ``detect_communities_activity`` — GDS Leiden detection.      ``min_size, Slim cross-activity handle the build workflow fans out over to     summarise.  D, Output of ``detect_communities_activity`` — the communities to     summarise.  E, Output of ``summarize_community_activity`` — the summary text and     whether it, SummarizeCommunityResult (+21 more)

### Community 19 - "graph: analysis.py"
Cohesion: 0.07
Nodes (49): components(), _components_nebula(), _graph_stats_nebula(), _nebula_show_stats(), _nebula_stats_computed_at(), pagerank(), _pagerank_cypher(), _pagerank_nebula() (+41 more)

### Community 20 - "graph: _q()"
Cohesion: 0.17
Nodes (24): AbstractIncomingMessage, handle_message(), Client, Run this document to completion: start its workflow, or ATTACH to the     run th, Process one ingest message: start + await the document workflow,     then ack/re, _start_or_attach(), _attachable(), _FakeMessage (+16 more)

### Community 21 - "test_graph: test_wiki_graph_ops.py"
Cohesion: 0.09
Nodes (32): _NebulaRecStore, Records nGQL statements (positional; nebula never binds param_map);     returns, nebula UPDATE VERTEX raises on a missing vertex; mark_dirty must catch     per-n, Records (cypher, param_map) calls; returns canned rows per call,     popped in c, _RecStore, test_dispatch_returns_nebula_when_backend_nebula(), test_dispatch_returns_neo4j_when_backend_not_nebula(), test_nebula_clear_dirty_issues_update_vertex() (+24 more)

### Community 22 - "test_graph: NebulaGraphStore"
Cohesion: 0.07
Nodes (38): Convert `ParsedEvent` objects → graph nodes + edges.  Called from `LightRAGExtra, _default_entity_types(), LightRAG-style KG extractor as a LlamaIndex `TransformComponent`.  One LLM call, Pull entity-type strings out of `src.graph.schema.EntityType`., _clean_raw_name(), _display_entity_name(), drop_unsupported_dates(), ensure_orphan_entities() (+30 more)

### Community 23 - "test_graph: merge_kg_extraction()"
Cohesion: 0.09
Nodes (53): main(), _parse_args(), Namespace, Offline probe of the LightRAG-style extract + merge stack.  Runs the live projec, _cypher_safe_label(), Convert a free-text predicate/keyword to a Cypher-safe upper-case     relation l, _EntityAgg, _id_to_name() (+45 more)

### Community 24 - "test_storage: ChunkRepository"
Cohesion: 0.08
Nodes (42): ChunkRepository, _escape(), _normalise_chunk_row(), Any, Path, Doc-id / file-path access layer for chunks and source files.  Wraps three lower-, Return on-disk path for the source file of `doc_id` or         None if the docum, Read the source file from disk, capped to `max_chars`.          Returns None if (+34 more)

### Community 25 - "workflow: test_search_drift_roundtrip.py"
Cohesion: 0.08
Nodes (36): DocumentsForCommunitiesParams, DocumentsForCommunitiesResult, MapPartialResult, Output of ``map_community_partial`` — the per-community partial     answer + a s, Input to ``documents_for_communities`` — community ids to resolve     back to th, Output — distinct source doc_ids behind the given communities., _docs_for_communities_nebula(), documents_for_communities() (+28 more)

### Community 26 - "test_graph: test_event_extract.py"
Cohesion: 0.08
Nodes (43): events_to_graph(), EntityNode, Relation, Convert a list of ``ParsedEvent`` objects to graph nodes + relations.      Param, _ev_line(), _event_payload(), _make_ev(), _mk_event() (+35 more)

### Community 27 - "config.py: Settings"
Cohesion: 0.05
Nodes (32): BaseSettings, AgentSettings, AnalyticsSettings, ClassifierSettings, EventsSettings, GraphSettings, IngestAdmissionSettings, IngestionSettings (+24 more)

### Community 28 - "test_graph: MilvusEntityVectorStore"
Cohesion: 0.08
Nodes (20): _emb(), main(), EntityCandidate, EntityVectorStore, _btrunc(), MilvusEntityVectorStore, Any, Truncate to fit a Milvus VARCHAR: max_length counts UTF-8 BYTES, not chars. (+12 more)

### Community 29 - "graph: signals.py"
Cohesion: 0.06
Nodes (24): _list_literal(), NebulaSignalsGraphOps, Neo4jSignalsGraphOps, Any, Protocol, Backend-dispatched analytics "signals" graph ops (P2 decision-ready queues, read, SignalsGraphOps, _NebulaRaisingStore (+16 more)

### Community 30 - "test_graph: resolve_entities()"
Cohesion: 0.06
Nodes (50): _is_cyrillic_name(), _EmbeddingStub, _ent(), _GraphStoreStub, Any, ChatMessage, Tests for `src/graph/entity_resolution.py`.  Stubs the LLM (verdict-by-pair dict, Returns canned canonical entities via structured_query. (+42 more)

### Community 31 - "test_workflow: activities.py"
Cohesion: 0.12
Nodes (28): main(), Run one analytical query against the knowledge graph.  Usage::      python -m sc, AnalysisPlan, AnalyticsOutcome, AnalyzeParams, _Frozen, PlanInput, BaseModel (+20 more)

### Community 32 - "test_bot: Turn"
Cohesion: 0.13
Nodes (26): Wire the pure ``rewrite_query`` to the app's LLM (litellm via build_llm).  Kept, build_rewrite_prompt(), Rewrite a follow-up message into a standalone search query.  "а что по нему?" af, Assemble the rewrite prompt from prior turns + the new question., Return a standalone query. No history → the question verbatim (no LLM     call)., rewrite_query(), InMemorySessionStore, Conversation session state for the Telegram Q&A bot.  A session is a rolling win (+18 more)

### Community 33 - "test_analytics: _FakeStore"
Cohesion: 0.08
Nodes (29): _FakeStore, Captures the last Cypher + params and returns canned rows., test_alerts_clamps_top_n(), test_alerts_filters_passed_as_params(), test_alerts_no_window_means_since_null(), test_alerts_reads_alert_nodes_newest_first(), test_alerts_window_days_sets_since(), test_link_prediction_reads_edges() (+21 more)

### Community 34 - "test_storage: test_ingest_metrics.py"
Cohesion: 0.09
Nodes (13): _nebula_fail_soft(), NebulaAnalyticsGraphOps, Any, Backend-dispatched analytics "connections" graph ops (read-only, fail-soft neigh, Mirrors ``Neo4jAnalyticsGraphOps._rows``'s ``try/except -> []`` (same     warnin, nGQL connections graph ops: GO/FETCH for neighbourhood reads,     FIND SHORTEST, FETCH name+label for a set of Entity vids -> {vid: (name, label)}., Extract ordered node names + edge rel-types from a         ``PathWrapper``-shape (+5 more)

### Community 35 - "graph: entity_resolution.py"
Cohesion: 0.13
Nodes (17): LogRecord, _main(), Live-update the ingest admission ceiling K (max_inflight) on the running ``inges, configure_logging(), _InterceptHandler, Loguru bootstrap.  Call :func:`configure_logging` once at app/worker startup.  T, Forward stdlib ``logging`` records into loguru.      ``temporalio``'s ``activity, Replace loguru's default handler with a project-tuned one.      ``json_output=Tr (+9 more)

### Community 36 - "graph: test_community_summarize.py"
Cohesion: 0.11
Nodes (15): NebulaCommunitySummarize, Backend-dispatched community SUMMARIZE I/O (context reads + report write).  `Neo, nGQL community SUMMARIZE. UPDATE VERTEX is a partial update (preserves     BUILD, community_vid(), Stable 128-bit VID (32-hex-char) for a community, scoped by level.      Mirrors, Fake nebula store: records nGQL; returns canned rows per substring., _RecNebula, _RecStore (+7 more)

### Community 37 - "graph: clamp_top_n()"
Cohesion: 0.08
Nodes (22): contradictions(), ContradictionsParams, incomplete_entities(), IncompleteEntitiesParams, merge_candidates(), MergeCandidatesParams, orphans(), OrphansParams (+14 more)

### Community 38 - "test_workflow: rerank.py"
Cohesion: 0.06
Nodes (41): BotRepository, build_list_users_query(), build_recent_requests_query(), Any, AsyncConnection, Postgres access for the Telegram bot: who may use it, and what was asked.  Same, Requests this user started today, for the quota check.          Counts EVERY row, Record a request BEFORE the work starts; returns its id.          A crash mid-se (+33 more)

### Community 39 - "analytics: PrimitiveResult"
Cohesion: 0.10
Nodes (52): Primitive, PrimitiveResult, register(), count_entities(), count_relationships(), CountEntitiesParams, CountRelationshipsParams, distribution_by_polarity() (+44 more)

### Community 40 - "analytics: Claim"
Cohesion: 0.44
Nodes (9): Claim, detect_contradictions(), Structural pass: group by EXACT ``(subject, attribute)`` and flag groups     whe, Pure contradiction detection over claims (TDD, no I/O)., test_agreement_yields_no_contradiction(), test_asserted_only_same_value_no_polarity_conflict(), test_polarity_conflict_on_same_value_is_a_contradiction(), test_tie_has_no_single_consensus() (+1 more)

### Community 41 - "test_graph: test_nebula_schema.py"
Cohesion: 0.07
Nodes (32): ensure_schema(), _execute_with_retry(), _migrate_related_validity_to_string(), _probe_edge_write_ready(), _probe_tag_write_ready(), Any, NebulaGraph schema for the KB graph (nGQL DDL).  Mirrors the Neo4j model: `:__En, # NOTE: `entity_wiki_dirty_idx` (on the ALTER-added `wiki_dirty` column) is (+24 more)

### Community 42 - "test_workflow: test_search_global.py"
Cohesion: 0.12
Nodes (40): Resolved, _anchor_date(), _dateparser_day(), _day_bounds(), _month_bounds(), _nearest_month_day(), _nearest_year(), date (+32 more)

### Community 43 - "test_workflow: Ctx"
Cohesion: 0.33
Nodes (3): Guard: the analytics materialize heartbeat window must exceed its GIL-held compu, A window sized to *today's* compute is stale by the next deploy.      The graph, test_heartbeat_window_survives_observed_graph_growth()

### Community 44 - "test_workflow: test_search_orchestrator.py"
Cohesion: 0.12
Nodes (21): Input to the ``route_query`` activity — the raw user question., Output of ``route_query`` — the chosen search mode.      Fail-safe: any classifi, RouteParams, RouteResult, Temporal activities for the plan-execute search subsystem (R2).  ``SEARCH_V2_ACT, classify_route(), _get_route_llm(), ``route_query`` activity — classify a question's search mode (R7a).  Decision C (+13 more)

### Community 45 - "test_graph: test_nebula_store_subgraph.py"
Cohesion: 0.07
Nodes (12): _Cell, _Elem, _Node, NebulaGraphStore.subgraph maps GET SUBGRAPH results into _map_walk_rows shape., GET SUBGRAPH frontier vertex: an edge endpoint one step past the last     hop, r, _Rel, _ResultSet, _Session (+4 more)

### Community 46 - "test_graph: LightRAGExtractor"
Cohesion: 0.07
Nodes (44): _extraction_text(), _is_transient_llm_error(), LightRAGExtractor, Any, BaseException, BaseNode, ChatMessage, TransformComponent (+36 more)

### Community 47 - "test_ingestion: test_classifier.py"
Cohesion: 0.09
Nodes (38): apply_rules(), classify_with_llm(), _ext(), LLMVerdict, BaseModel, Path, Input document classifier — decides whether a freshly-fetched document is worth, Deterministic skip rules.  Returns ``skip=True`` + a human reason     for blocke (+30 more)

### Community 48 - "MinioStorage"
Cohesion: 0.13
Nodes (17): _NebulaRaisingStore, _NebulaRecStore, _RaisingStore, _RecStore, test_dispatch_nebula(), test_dispatch_neo4j_default(), test_nebula_contradictions_two_match_empty_chunks(), test_nebula_fail_soft_returns_empty_on_raise() (+9 more)

### Community 49 - "mcp: tools_server.py"
Cohesion: 0.09
Nodes (39): _c(), channel_message_stats(), channel_message_timeline(), find_entity_by_id(), find_entity_by_name(), find_neighbours(), _g(), get_chunks_by_doc_id() (+31 more)

### Community 50 - "workflow: SerializedNode"
Cohesion: 0.08
Nodes (30): _backfill_cypher(), main(), Backfill ``__Entity__.er_vec`` (native vector list) from the legacy ``er_embeddi, wiki_rebuild(), build_nebula_graph_store(), Process-global NebulaGraph store (mirrors build_neo4j_graph_store).      The sto, build_graph_store(), build_neo4j_graph_store() (+22 more)

### Community 51 - "test_graph: test_aggregations_graph_ops.py"
Cohesion: 0.08
Nodes (29): _NebulaRaisingStore, _NebulaRecStore, _RaisingStore, Records nGQL statements (nebula never binds param_map); returns canned     rows, Records (cypher, param_map); returns canned rows popped in call order., _RecStore, test_dispatch_returns_nebula_when_backend_nebula(), test_dispatch_returns_neo4j_when_backend_not_nebula() (+21 more)

### Community 52 - "test_scripts: datetime"
Cohesion: 0.09
Nodes (26): make_search(), Build an async ``search(query) -> answer`` bound to one search mode.      Raises, build_entity_search_query(), EntitySearchRepository, Any, AsyncConnection, Postgres access for the entity search mirror.  Pure query builders (asserted exa, One name-search query. `mode`: exact / prefix / substring. (+18 more)

### Community 53 - "graph: communities.py"
Cohesion: 0.12
Nodes (28): Neo4j GDS Leiden (gds.leiden.stream), ADR-0009 Hierarchical Leiden communities + structured reports, ADR-0015 Community detection backend — in-worker leidenalg (offload from GDS), _graphscope_rows(), Offline graph-community detection (Search R6, decision C1).  DECOUPLED / OFFLINE, graphscope backend: stream edges + distributed single-level Leiden.      Same ro, Flat GraphScope partition -> rows [{name, communityId, ids:[cid]}]     (same sha, single_level_rows_graphscope() (+20 more)

### Community 54 - "test_graph: test_index.py"
Cohesion: 0.05
Nodes (49): ExtractorMode, KGExtractor, main(), _pending(), One-time E1 backfill: stamp a sentinel ``created_at`` on pre-existing graph elem, build_kg_extractor(), ensure_chunk_date_indexes(), ensure_community_indexes() (+41 more)

### Community 55 - "test_config: LiteLLMSettings"
Cohesion: 0.07
Nodes (30): LLMTier, LiteLLMSettings, Any, LLMRole, Connection to a LiteLLM proxy (or any OpenAI-compatible endpoint).      ``llama-, Accept a JSON string (pydantic-settings env), a dict, or an         empty/None v, Merge any provided overrides onto the full default map so a         partial ``ro, Base model for the no-role legacy path: the deprecated         ``llm_model`` if (+22 more)

### Community 56 - "test_graph: test_nebula_store_writes.py"
Cohesion: 0.13
Nodes (34): SimpleNamespace, _Cast, _FakeSession, _no_entity_mirror(), _node(), _q_expect(), upsert_nodes/upsert_relations emit the expected nGQL (no live DB)., This file's contract is "no live DB" (see module docstring). The     entity-tabl (+26 more)

### Community 57 - "api: ingest.py"
Cohesion: 0.06
Nodes (39): FastAPI, X-API-Key auth dependency.  Same simple shared-key model enterprise-kb uses — co, require_api_key(), lifespan(), FastAPI app entry point.  Wires routes, CORS, and the dishka DI container.  Inge, `GET /api/v1/documents/{doc_id}` — download the original source file.  Streams t, find_entities(), Any (+31 more)

### Community 58 - "analytics: catalog.py"
Cohesion: 0.07
Nodes (54): _clip(), format_answer(), format_channels(), format_entities(), format_fragments(), format_history(), format_timeline(), format_users() (+46 more)

### Community 59 - "test_config: test_settings.py"
Cohesion: 0.06
Nodes (25): ApiSettings, LLMPoolSettings, PostgresSettings, External-statistics subsystem (MCP-3).      Defaults are read-side only — nothin, FastAPI surface — host, port, auth keys, CORS, log level., Per-process LLM concurrency pool (K+N model).      ONE semaphore of size ``n`` (, StatsSettings, Stage-0 smoke tests.  Goals:   * importing the package doesn't raise on an empty (+17 more)

### Community 60 - "superpowers: leidenalg/igraph community backend (community_backend flag)"
Cohesion: 0.07
Nodes (35): GraphRAG community system, Hierarchical Leiden detection (detect_hierarchy), Hierarchical communities + dynamic selection plan, Structured community reports (report_vec, incremental), Dynamic community selection (semantic kNN v1 + descent v2), leidenalg/igraph community backend (community_backend flag), Community detection offload plan, Search date filters (Rev 2) plan (+27 more)

### Community 61 - "test_analytics: test_planner.py"
Cohesion: 0.08
Nodes (38): Human-readable catalog (name + description + params) for the planner prompt., render_catalog_for_planner(), coerce_entity_type(), Map a user/LLM-supplied entity type to its canonical casing, or None     if it i, parse_plan(), plan_query(), Any, NL → AnalysisPlan. Plain achat + tolerant parse + strict pydantic validation.  M (+30 more)

### Community 62 - "analytics: dynamics.py"
Cohesion: 0.38
Nodes (4): pick_priority(), Canonical channel-group enum, imported by ingest/search/rerank/tg_ingest.  A doc, Return whichever group name ranks earlier in GROUP_PRIORITY.     Unknown names s, test_pick_priority_returns_earlier_in_order()

### Community 63 - "test_workflow: merge_and_resolve()"
Cohesion: 0.15
Nodes (34): merge_and_resolve(), Relation, Repoint a relation's name-endpoints through ``alias`` (folded entity     name ->, _rewrite_endpoints(), _base_patches(), _ctx(), _epoch(), _make_entity() (+26 more)

### Community 64 - "test_observability: test_ingest_metrics_extractor.py"
Cohesion: 0.16
Nodes (33): datetime, HistoryEvent, parse_activity_timings(), WorkflowHistory, Pure-functional extractor that turns Temporal workflow history into ``MetricRow`, Resolve the right oneof attributes block for a terminal event., Return one ``MetricRow`` per (activity, attempt) found in the     given workflow, _terminal_attrs() (+25 more)

### Community 65 - "graph: events_llm.py"
Cohesion: 0.10
Nodes (32): _indicators_search(), Three modes, deliberately behind one tool.      No query and no source is not an, _series(), Helper-level tests — FastMCP tool invocation internals are not exercised, same c, `jsonb` normalises key order, so two rows differing only in the     order they w, No query and no source means the caller does not yet know what     exists — answ, `== 100`, not `<= 100`: the old assertion held for any value the     cap might h, The `source`-only branch takes a different path to the repo and     was not cove (+24 more)

### Community 66 - "test_graph: test_entity_resolution.py"
Cohesion: 0.15
Nodes (19): backfill(), build_page_query(), escape_ngql(), main(), Any, One-off fill of the Postgres `entity` table from the graph.  Resumable, idempote, One page of entities, in name order, after `last_name`.      NebulaGraph shards, One page, retried on a transient store refusal.      `ORDER BY` makes graphd sor (+11 more)

### Community 67 - "retrieval: build_vector_index()"
Cohesion: 0.13
Nodes (20): Lane, LLMPool, Any, Per-process LLM concurrency pool - single home for LLM gating (K+N).  ONE ``asyn, Test hook - drop the singleton so the next get_llm_pool rebuilds., A named counting async gate: bounded concurrency + an in_use counter.      Usabl, Registry of role -> gated LLM, all sharing ONE global N semaphore., reset_for_tests() (+12 more)

### Community 68 - "workflow: worker.py"
Cohesion: 0.14
Nodes (22): Runtime, _build_runtime(), _child_main(), main(), _metrics_host_base(), metrics_port_for(), Temporal worker entry point.  Run with::      uv run python -m src.workflow.work, Resolve the ``WORKER_GROUPS`` env spec to a canonical-ordered list.      Empty / (+14 more)

### Community 69 - "setup_wikibase.py"
Cohesion: 0.10
Nodes (29): _api_url(), _bootstrap_credentials(), _configure_wbi(), _Counter, _ensure_item(), _ensure_property(), _find_entity_by_label(), _identifier_properties() (+21 more)

### Community 70 - "test_workflow: test_search_retrieve.py"
Cohesion: 0.13
Nodes (31): Input to the ``retrieve_subquestion`` activity.      One deterministic retrieval, RetrieveParams, Run the deterministic retrieve pipeline for one sub-question., Pick the top entity_name from a ``graph_search`` observation.      PURE (no I/O), retrieve_subquestion(), top_entity_name(), _DispatchRecorder, _gs_obs() (+23 more)

### Community 71 - "test_retrieval: test_hf_offline.py"
Cohesion: 0.12
Nodes (28): SentenceTransformerRerank, HFSettings, Offline HuggingFace model loading for air-gapped deploys.      Two project model, configure_hf(), Offline HuggingFace cache wiring for air-gapped deploys.  ``configure_hf()`` tra, Set ``os.environ[name]`` only when it is not already set, so an     operator's e, Apply ``settings.hf`` to the HuggingFace env vars (idempotent).      * ``cache_d, _set_if_absent() (+20 more)

### Community 72 - "graph: events.py"
Cohesion: 0.06
Nodes (33): epoch_days_to_period(), is_meaningful_entity(), Constants + pure helpers for the analytical layer (no I/O, no LLM)., Bucket an epoch-day integer into a period label.      granularity: ``year`` → ``, Whether an entity row is worth showing in a themes/events answer.      Always dr, alerts(), Any, entity_new_connections() (+25 more)

### Community 73 - "IngestSchedulerWorkflow"
Cohesion: 0.09
Nodes (21): AdmissionState, Pure admission-control state machine (Track 5).  Bounds how many documents inges, FIFO admission with a hard ``max_inflight`` ceiling.      ``submit`` enqueues (d, Pop up to ``free_slots`` documents off the front of the queue         into fligh, IngestSchedulerWorkflow, ``IngestSchedulerWorkflow`` — long-lived document admission control (Track 5, va, Recycle (continue_as_new) once event history crosses the         threshold — reg, Still-queued documents handed to the next run on recycle.         In-flight docs (+13 more)

### Community 74 - "ingest_queue: ingest_submit.py"
Cohesion: 0.10
Nodes (31): _apply_name_map(), _consolidate_cluster(), _embed_entities(), _format_cluster_prompt(), _format_pair_prompt(), _Item, _load_candidates_native(), _load_candidates_via_store() (+23 more)

### Community 75 - "test_graph: test_event_merge.py"
Cohesion: 0.07
Nodes (53): _cos(), dedup_cross_channel_events(), event_key(), merge_events(), EntityNode, Relation, E2 event de-duplication: deterministic (type, participants, ts-bucket) match-key, Fold entity-channel EventOrAction nodes into same-chunk event-channel     events (+45 more)

### Community 76 - "observability: trace_request()"
Cohesion: 0.12
Nodes (27): _count_by(), get_current_trace(), Any, Structured tracing for the search endpoints.  A trace is a list of `TraceEvent`, Bind a fresh Trace to the current context for the duration     of the `with` blo, Append an event to the current trace.  Cheap no-op if no     trace is active (al, Convenience: time the wrapped block, append one event., One structured event in the request trace. (+19 more)

### Community 77 - "retrieval: DateBounds"
Cohesion: 0.16
Nodes (30): decide(), EdgeConflict, _key(), _label(), load_stored_edges(), _load_stored_nebula(), _load_stored_neo4j(), Any (+22 more)

### Community 78 - "events_eval.py"
Cohesion: 0.18
Nodes (5): EventsLlmGraphOps, NebulaEventsLlmGraphOps, Protocol, Backend-dispatched analytics "events_llm" graph ops (E2 event reads, read-only,, FETCH the event columns for a set of VIDs, keyed by vid; only rows         whose

### Community 79 - "test_api: analyze.py"
Cohesion: 0.12
Nodes (6): _all_names(), GraphScope community-detection backend (single-level Leiden, distributed).  Mirr, Dedup names across node_names + edge endpoints (mirrors     community_leiden.bui, Build a GraphScope graph from `edges` and run its modularity community     algor, _run_graphscope_community(), single_level_rows_graphscope maps a mocked GraphScope partition to rows.

### Community 80 - "storage: backfill_doc_id.py"
Cohesion: 0.14
Nodes (27): _iter_rows(), _load_path_index(), main(), MilvusClient, Backfill the `doc_id` metadata field on legacy Milvus chunks.  Chunks indexed be, Yield Milvus rows in batches via query_iterator (offset-paging has     a 16 384, BackfillStats, build_path_index() (+19 more)

### Community 81 - "reresolve_graph.py"
Cohesion: 0.10
Nodes (26): _amain(), _apply_merges(), _is_write_cypher(), _load_all_entities(), _loader_cypher(), main(), _parse_args(), _plan_merges() (+18 more)

### Community 82 - "tg_ingest.py"
Cohesion: 0.08
Nodes (36): _components_from_edges(), graph_stats(), _personalized_pagerank_from_edges(), Recompute Nebula's own tag/edge counts (`SUBMIT JOB STATS`).      `graph_stats`, Weakly-connected components via in-worker igraph (no GDS under nebula)., Seed-biased PageRank via in-worker igraph (no GDS under nebula)., Undirected shortest path via in-worker igraph (no GDS under nebula)., Operational snapshot: entity/relationship counts, degree     distribution (p50/p (+28 more)

### Community 83 - "graph: communities.py"
Cohesion: 0.08
Nodes (39): Prepend the channel group so the synthesis LLM sees each source's     type/trust, with_group_prefix(), Wire-friendly projection of LlamaIndex ``NodeWithScore``.      Only the bits the, Input to the ``synthesize_answer`` activity., SerializedNode, SynthesizeParams, apply_group_weights(), Bias rerank order by channel group. The cross-encoder emits unbounded     logits (+31 more)

### Community 84 - "test_graph: test_rollups_graph_ops.py"
Cohesion: 0.17
Nodes (9): _NebulaRecStore, _RaisingStore, _RecStore, test_dispatch_nebula(), test_dispatch_neo4j_default(), test_nebula_amount_edges_adds_cp_filter(), test_nebula_amount_edges_matches_amount_label(), test_neo4j_amount_edges_issues_moved_cypher() (+1 more)

### Community 85 - "build_graph_store()"
Cohesion: 0.12
Nodes (39): Context, _bounds_or_error(), _global_params(), kb_analyze(), kb_auto_search(), kb_drift_search(), kb_global_search(), kb_search() (+31 more)

### Community 86 - "eval: score_case()"
Cohesion: 0.13
Nodes (28): finalize(), mark_failed(), mark_skipped(), _persist_ingest_metrics(), `finalize` (success path) and `mark_failed` (workflow-level on-failure) — write, Classifier said skip: write the ``skipped`` terminal status +     reason and cle, Pull parent + child workflow histories, derive per-activity     durations, and p, _rmtree() (+20 more)

### Community 87 - "eval: test_medical_fixture.py"
Cohesion: 0.17
Nodes (11): ChunkRepositoryProtocol, get_chunks_by_doc_id(), Fetch all chunks of one document in source order., Read raw source text of one document (pre-chunking, pre-translation)., read_full_document(), _StubChunkRepo, test_get_chunks_by_doc_id_builds_sources(), test_get_chunks_by_doc_id_no_repo() (+3 more)

### Community 88 - "graph: MilvusCommunityReportVectorStore"
Cohesion: 0.14
Nodes (14): _emb(), main(), build_community_report_vector_store(), CommunityRef, CommunityReport, CommunityReportVectorStore, MilvusCommunityReportVectorStore, Any (+6 more)

### Community 89 - "graph: domain.py"
Cohesion: 0.11
Nodes (16): communication_stats(), CommunicationStatsParams, issue_resolution_stats(), IssueResolutionStatsParams, _Params, Any, BaseModel, P3 domain rollups — issue/resolution + communication intensity primitives. (+8 more)

### Community 90 - "test_analytics: test_aggregations.py"
Cohesion: 0.18
Nodes (19): _FakeOps, _patch_ops(), The most-mentioned-entities surface must not let degenerate names     (numerish,, Records (method, args) calls; returns canned rows per method name., test_count_entities_excludes_identifiers_by_default(), test_count_entities_failsoft(), test_count_entities_routes_through_seam(), test_count_relationships_filters_rel_type_and_polarity() (+11 more)

### Community 91 - "test_analytics: _FakeOps"
Cohesion: 0.16
Nodes (16): _FakeOps, _patch_ops(), Records (method, args) calls; returns canned rows per method name., test_common_connections_routes_through_seam(), test_connection_path_clamps_hops_inline(), test_connection_path_routes_through_seam_with_clamped_hops(), test_cooccurrence_routes_through_seam(), test_cooccurrence_via_shared_chunks() (+8 more)

### Community 92 - "bot: __main__.py"
Cohesion: 0.27
Nodes (9): make_analyze(), SearchFn, Return a search that tries ``primary`` first and only falls back to     ``fallba, Build an async ``analyze(query) -> answer`` over the analytical layer     (POST, with_fallback(), Search fallback combinator (TDD): primary mode, fall back to a second mode only, test_empty_primary_triggers_fallback(), test_non_empty_primary_wins_and_fallback_not_called() (+1 more)

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
Cohesion: 0.15
Nodes (26): _node_content_len(), `index_vector` — embed + Milvus insert.  Loads parsed nodes from staging, snapsh, Strip metadata so every node's ``_node_content`` fits the Milvus     VARCHAR cap, Truncate any chunk whose ``text`` field exceeds the Milvus cap     (a chunking p, Length of the ``_node_content`` VARCHAR Milvus will actually     store for this, _restore_metadata(), _restore_text(), _snapshot_for_milvus() (+18 more)

### Community 97 - "test_graph: resolve()"
Cohesion: 0.26
Nodes (11): cluster_claims(), cosine(), Claim, EmbedFn, Greedy single-pass clustering of claims by slot-embedding similarity.     Each c, _slot_text(), _embed(), Semantic claim clustering (TDD): group claims about the same fact slot across di (+3 more)

### Community 98 - "test_analytics: test_events_llm.py"
Cohesion: 0.10
Nodes (25): event_dossier(), event_timeline(), Any, Event dossier: core event info + actors., Events a named entity participated in, ordered by resolved start time (untimed l, (entity, event_type) pairs whose event ingest-rate surged recently., trending_events(), build_events_llm_graph_ops() (+17 more)

### Community 99 - "workflow: materialize_activities.py"
Cohesion: 0.15
Nodes (23): compute_risk(), normalize(), Pure composite risk scoring (no I/O). Components arrive already normalized to 0., RiskResult, _gather_risk_nebula(), _get_store(), materialize_centrality(), materialize_link_prediction() (+15 more)

### Community 100 - "aggregations_graph_ops.py"
Cohesion: 0.11
Nodes (11): AggregationsGraphOps, _canonical_label(), _list_literal(), _nebula_fail_soft(), NebulaAggregationsGraphOps, Protocol, Backend-dispatched analytics "aggregations" graph ops (read-only, fail-soft coun, Mirrors ``Neo4jAggregationsGraphOps._rows``'s ``try/except -> []``     (same war (+3 more)

### Community 101 - "test_graph: write_entity_article()"
Cohesion: 0.17
Nodes (20): Read an entity's 1-hop subgraph from the graph store and hash it for change dete, Stable sha256 over the entity's facts AND its source-document set.     Order-ind, Distinct source-document ids that mention this entity, sorted.     Used both for, read_citations(), read_entity_subgraph(), read_source_docs(), subgraph_hash(), _ctx() (+12 more)

### Community 102 - "test_graph: test_er_graph_ops.py"
Cohesion: 0.11
Nodes (22): _graph_half(), Records (cypher, param_map) calls; returns canned rows per call,     popped in c, Fake nebula store: records nGQL statements (asserts no param_map —     nebula bi, Safety guarantee: if a redirected-edge re-insert fails, the loser     must NOT b, _RecNebula, _RecStore, test_dispatch_returns_nebula_when_backend_nebula(), test_dispatch_returns_neo4j_when_backend_not_nebula() (+14 more)

### Community 103 - "SEARCH.md — search subsystem deep reference"
Cohesion: 0.10
Nodes (40): ADR-0001 Temporal for durable orchestration, ADR-0002 Claim-check staging via MinIO, ADR-0003 Task-queue isolation (avoid head-of-line blocking), ADR-0004 Per-process LLMPool (tier + role lanes), ADR-0006 Milvus HNSW as default chunk index, ADR-0010 Dynamic community selection (lexical/semantic/descent, fail-open), ADR-0011 Plan-execute SearchOrchestratorWorkflow (ReAct removed), ADR-0012 Wikibase anchor + continuous anti-drift wiki editor (+32 more)

### Community 104 - "retrieval: build_llm()"
Cohesion: 0.10
Nodes (22): main(), assert_api_key_env_set(), log_banner(), parse_args(), Any, Tiny argparse — fastmcp's runtime takes `transport`, `host`,     `port` via kwar, Best-effort startup check.      When ``KB_MCP_REQUIRE_AUTH=true``, exits with a, main() (+14 more)

### Community 105 - "GraphRetriever"
Cohesion: 0.09
Nodes (37): build_page_query(), escape_ngql(), migrate(), Any, Copy the ER verdict cache out of the graph and into Postgres.  One-off, resumabl, Copy every verdict into `cache`.  Returns `(copied, last_key)`.      `last_key`, Escape a string for inline use inside a double-quoted nGQL literal.      Verdict, One page of verdicts, ordered by key, after `last_key`.      `ORDER BY` is what (+29 more)

### Community 106 - "mcp: _shared.py"
Cohesion: 0.15
Nodes (15): build_tool_schema(), find_entity_by_name(), _injected_params(), BaseModel, Atomic retrieval tools as pure async functions.  Each function is a standalone u, Find entities whose NAME matches the query via the full-text index.      Partial, Names of the DI-injected dependency args.      Every tool function takes its dep, Pydantic schema of the LLM-facing kwargs for ``name``.      Derived from the rea (+7 more)

### Community 107 - "workflow: KGExtracted"
Cohesion: 0.20
Nodes (11): _coarsest_from_rows(), _group_by_levels(), members_hash(), CommunityRef, Order-insensitive content hash of a community's members.      Lets a re-run skip, Map a Leiden dendrogram stream into ``CommunityRef``s across levels.      ``rows, Group the COARSEST dendrogram column (today's ``communityId``) into     ``Commun, CommunityRef (+3 more)

### Community 108 - "workflow: test_search_route.py"
Cohesion: 0.12
Nodes (36): _ask(), _ctx(), Command handlers: admission, quota, the gate, and the audit around them.  The or, The audit is of what was attempted, not only of what ran., Otherwise N failures wedge the bot permanently., So /history can show an old answer with its provenance without     re-running an, The audit trail must not become a way to read other people's     questions., It re-runs the work; it does not replay a stored answer. (+28 more)

### Community 109 - "test_graph: test_events_llm_graph_ops.py"
Cohesion: 0.12
Nodes (19): _NebulaRaisingStore, _NebulaRecStore, _RaisingStore, _RecStore, test_dispatch_nebula(), test_dispatch_neo4j_default(), test_nebula_event_actors_go_then_fetch_names(), test_nebula_event_core_empty_when_not_event() (+11 more)

### Community 110 - "wipe_db.py"
Cohesion: 0.13
Nodes (24): confirm(), main(), _parse_args(), Namespace, DESTRUCTIVE — wipe all data stores.  Drops:   * Temporal   — terminate running +, Drop EVERY collection, not just ``settings.milvus.collection`` —     the stack h, Dispatch on the configured graph backend (mirrors     ``src.graph.store.build_gr, DROP the whole Nebula space.  ``nebula_schema.ensure_schema``     re-creates the (+16 more)

### Community 111 - "test_analytics: test_claim_nli.py"
Cohesion: 0.17
Nodes (20): build_nli_prompt(), nli_verdict(), parse_nli_verdict(), LLM NLI verdict over a pair of claim values (hybrid method B, iteration 4).  Emb, Tolerant parse → CONTRADICT / AGREE / NEUTRAL. contradiction wins over     agree, Ask the LLM for the NLI relation. Fail-open to NEUTRAL on any error., Drop structurally-flagged contradictions that NLI judges to be mere     phrasing, refine_contradictions() (+12 more)

### Community 112 - "graph: community_writeback.py"
Cohesion: 0.13
Nodes (8): _carry_params(), NebulaCommunityWriteback, Neo4jCommunityWriteback, Any, Backend-dispatched community BUILD write-back (the `:Community` + `IN_COMMUNITY`, nGQL community BUILD write-back. INSERT is upsert-by-VID; both call     sites pr, Map the clean-keyed carry dict to the `carry_*` params the neo4j     MERGE Cyphe, Runs the historical Cypher constants verbatim — zero behaviour change.

### Community 113 - "retrieval: GroupFilter"
Cohesion: 0.14
Nodes (26): bounds_from_iso(), date_metadata_filters(), DateBounds, _field_in_range(), filter_nodes(), iso_to_epoch_days(), node_metadata_in_range(), overfetch_top_k() (+18 more)

### Community 114 - "storage: AsyncMediaWiki"
Cohesion: 0.14
Nodes (14): AsyncMediaWiki, AsyncClient, Minimal async MediaWiki Action API client (login + read/edit page + sitelink). U, Link a Wikibase Item to its MediaWiki article page. Best-effort., _api_url(), get_mediawiki(), Process-singleton MediaWiki client for wiki activities., _client_returning() (+6 more)

### Community 115 - "test_analytics: config.py"
Cohesion: 0.08
Nodes (47): index_vector(), inject_canonical(), `inject_canonical` — write canonical identifier entities to Neo4j., parse_and_chunk(), Ctx, _scrub(), Ctx, GraphBuildResult (+39 more)

### Community 116 - "superpowers: DocumentIngestWorkflow"
Cohesion: 0.09
Nodes (24): Ingest Temporal Workflow plan, Pydantic v2 workflow contracts, DocumentIngestWorkflow, fetch_source activity, inject_canonical activity, merge_and_resolve activity, parse_and_chunk activity, StagingStore MinIO claim-check (+16 more)

### Community 117 - "build_ingestion_pipeline()"
Cohesion: 0.17
Nodes (22): combined_metadata_filters(), filter_nodes_by_group(), group_metadata_filters(), GroupFilter, node_group_ok(), MetadataFilter, MetadataFilters, Channel-group search filter — the doc_group analogue of date_filters.  `doc_grou (+14 more)

### Community 118 - "test_scripts: test_tg_ingest_reingest.py"
Cohesion: 0.14
Nodes (18): main(), Reingest the newest ``limit`` messages of each requested channel at     ``priori, Choose the run mode from parsed args: reingest wins over the legacy     backfill, reingest_channels(), select_mode(), _FakeDialog, _FakeEntity, _FakeMsg (+10 more)

### Community 119 - "analytics: materialize.py"
Cohesion: 0.20
Nodes (21): GoldenCase, load_golden_cases(), Path, Score one (case, response) pair.      `sources`: each dict must have `chunk_id`, One entry from `golden_qa/*.json`., score_case(), Unit tests for `tests/eval/answer_quality.py` — the scorer.  These tests run wit, If the answer simply doesn't mention the topic, we don't     penalize — honesty (+13 more)

### Community 120 - "test_graph: extract_entity_edges()"
Cohesion: 0.07
Nodes (21): alert_vid(), AlertStore, NebulaAlertStore, Neo4jAlertStore, Any, Protocol, Backend-dispatched Arc-2 :Alert store (upsert / read / mark_watched).  ``Neo4jAl, 32-hex VID for an :Alert, mirroring entity_vid/verdict_vid. (+13 more)

### Community 121 - "workflow: contextualize.py"
Cohesion: 0.28
Nodes (14): ConversationTurnDict, _bound_history(), _build_prompt(), contextualize_query(), _get_contextualize_llm(), Rewrite a follow-up question into a standalone one using recent conversation his, Small-tier LLM (role ``route`` → small per ``_DEFAULT_ROLE_TIERS``).      Reuses, Rewrite a follow-up into a standalone question (small tier).      Fail-open: emp (+6 more)

### Community 122 - "test_workflow: test_article.py"
Cohesion: 0.16
Nodes (22): EntityContext, _fmt_citations(), _fmt_relations(), _fmt_sources(), Bot-section splice + LLM render for entity wiki articles.  The bot owns ONLY the, Replace the marked bot section with `bot_md` (wrapped in markers).     If no mar, Deterministic '== Источники ==' section with download links to the     original, LLM-render the bot section grounded ONLY in `ctx` (graph facts) and     `citatio (+14 more)

### Community 123 - "test_graph: test_quality_graph_ops.py"
Cohesion: 0.20
Nodes (11): dispatch(), filter_by_metadata(), NodeWithScore, Protocol, In-memory filter over already-accumulated sources.      Pure / synchronous; does, Dispatch a tool call by name.  Used by the Temporal     ``tool_execution`` activ, RetrieverProtocol, test_dispatch_raises_on_unknown_tool() (+3 more)

### Community 124 - "test_graph: test_signals_graph_ops.py"
Cohesion: 0.15
Nodes (6): _ExplodingWriteback, _FakeWriteback, _patch_two_cliques(), test_detect_communities_raises_when_writeback_fails(), test_detect_communities_routes_writeback_through_seam(), test_detect_hierarchy_raises_when_writeback_fails()

### Community 125 - "test_graph: test_alerts.py"
Cohesion: 0.10
Nodes (29): monitor_sweep(), monitor_watch(), Admin operations: trigger wiki/monitor sweeps and monitor watchlist., build_alert_store(), alert_key(), mark_watched(), Any, Arc 2 — Alert store + watchlist Cypher helpers (called off-loop from activities) (+21 more)

### Community 126 - "test_graph: stamp_first_seen()"
Cohesion: 0.17
Nodes (19): Any, E1 — emulate ON CREATE stamping (created_at/first_doc_id) post-upsert.  The enti, Stamp created_at/first_doc_id on newly-created graph elements.      Sets the fie, stamp_first_seen(), _stamp_first_seen_nebula(), _stamp_first_seen_neo4j(), Tests for E1 — ON-CREATE-emulated first_seen stamping.  Covers the backend dispa, When relations list is empty, only the entity pass fires. (+11 more)

### Community 127 - "test_retrieval: test_graph_walk_retriever.py"
Cohesion: 0.19
Nodes (20): True if a walk-relation dict should be surfaced to the agent.      Drops edges t, _relation_is_live(), _FakeStore, Unit tests for GraphRetriever.awalk — bounded N-hop graph traversal.  Uses a fak, Captures the Cypher + params and returns canned rows., Build a GraphRetriever without touching PropertyGraphIndex., _rel(), _retriever_with_store() (+12 more)

### Community 128 - "workflow: global_search.py"
Cohesion: 0.15
Nodes (21): clear_dirty(), mark_dirty(), Dirty-flag bookkeeping for the wiki editor (Neo4j __Entity__ props).  Routes thr, select_dirty(), build_wiki_graph_ops(), Backend-dispatched wiki-editor graph ops (dirty-flag bookkeeping + article-conte, ArticleOutcome, WikiSweepWorkflow — select dirty entities, (re)write each article. (+13 more)

### Community 129 - "workflow: StagingStore"
Cohesion: 0.12
Nodes (16): _parse_uri(), Any, Find and delete orphaned ``{run_id}/`` prefixes.  Returns         the list of ru, Thin wrapper around the MinIO client for stage blobs., Pickle `obj` and upload to ``{run_id}/{stage}.pkl``.          Returns the full `, Reverse of `write_pickle`., Best-effort cleanup of every blob under ``{run_id}/``., Return ``run_id`` prefixes whose newest blob is older than         ``older_than_ (+8 more)

### Community 130 - "eval: identifier_recall.py"
Cohesion: 0.15
Nodes (20): check_thresholds(), evaluate_case(), format_report(), _is_extra(), load_cases(), main(), _match(), _parse_args() (+12 more)

### Community 131 - "retrieval: test_answer_template.py"
Cohesion: 0.20
Nodes (14): build_query(), load_template(), Server-side answer templates (Track 6, variant a).  Lets a caller shape the SHAP, Russian-output instruction (the default when no template is set)., Resolve a template.  A bare safe name that matches a file under     ``prompts/an, Compose the synthesis instruction.  No template → the RU preamble;     otherwise, ru_query(), Unit tests for server-side answer templates (Track 6, variant a). (+6 more)

### Community 132 - "test_retrieval: _StubGraphRetriever"
Cohesion: 0.15
Nodes (23): find_entity_by_id(), graph_search(), graph_walk(), Knowledge-graph traversal: matched entities + their neighbours up     to ``depth, Bounded multi-hop graph traversal from a known entity.      Unlike ``graph_searc, Exact lookup by canonical name (E.164 phone, INN, email …)., _node(), NodeWithScore (+15 more)

### Community 133 - "test_workflow: CoverageResult"
Cohesion: 0.15
Nodes (17): _embed_report(), _get_embed_model(), _get_summary_llm(), _parse_report(), Any, Small-tier LLM for community summaries.      Uses the ``retrieve`` role (small t, Embedding model for report vectors (same model as ER / ingest).      Indirected, Split a rendered context body into ``<=budget``-char batches, each     keeping t (+9 more)

### Community 134 - "ner_eval.py"
Cohesion: 0.16
Nodes (16): _accumulate_lang(), Extractor, format_report(), _llm_only_extractor_factory(), main(), NERStats, _norm(), Path (+8 more)

### Community 135 - "test_api: test_ingest.py"
Cohesion: 0.16
Nodes (19): detect_contradictions_clustered(), TrustFn, Semantic claim clustering (hybrid method B, iteration 3).  Claims from different, Cluster claims semantically, then flag clusters where sources disagree.      ``t, End-to-end contradiction detection (hybrid method B, iteration 5).  Assembles th, _consensus(), Contradiction, contradiction_for_group() (+11 more)

### Community 136 - "test_graph: test_domain_graph_ops.py"
Cohesion: 0.13
Nodes (15): _NebulaRaisingStore, _NebulaRecStore, _RaisingStore, Returns canned rows keyed by first matching substring of the statement., _RecStore, test_dispatch_nebula(), test_dispatch_neo4j_default(), test_nebula_comms_adds_name_filter() (+7 more)

### Community 137 - "test_graph: test_dynamics_graph_ops.py"
Cohesion: 0.14
Nodes (15): _NebulaRaisingStore, _NebulaRecStore, _RaisingStore, _RecStore, test_dispatch_nebula(), test_dispatch_neo4j_default(), test_nebula_fail_soft(), test_nebula_polarity_evolution_optional_filters() (+7 more)

### Community 138 - "test_scripts: test_reresolve_graph.py"
Cohesion: 0.12
Nodes (6): Unit tests for the pure / stubbed helpers in scripts/reresolve_graph.py.  The wh, Inner stub that records every structured_query call and exposes     an arbitrary, _RecordingStore, test_proxy_delegates_arbitrary_attribute(), test_proxy_noops_write_without_touching_inner(), test_proxy_passes_read_through_to_inner()

### Community 139 - "diagrams: activity: retrieve_subquestion (hybrid)"
Cohesion: 0.12
Nodes (21): 3b · coverage gap? — coverage_check (small LLM) decision, extra SubQueryRetrievalWorkflow(gap) — budget max_coverage_rounds (1), dedup by chunk_id, find_entity_by_name — full-text entity lookup, graph_search — path_depth = graph_search_path_depth (1), matched entities + neighbours + chunks, graph_walk (seed) — start = top graph_search entity, hops = graph_walk_hops (2, ≤3), FAIL-OPEN, MCP-1 tool: kb_search(query, max_refinements=3) — @mcp.tool timeout=1800s, submits workflow, polls get_state, MCP client (Hermes / OpenWebUI) (+13 more)

### Community 140 - "superpowers: WikiGraphOps Protocol (dirty bookkeeping, subgraph,"
Cohesion: 0.12
Nodes (21): build_graph_edge_export (backend dispatch nebula vs neo4j), detect_communities (leidenalg end-to-end under nebula), extract_entity_edges (routes through GraphEdgeExport seam), GraphEdgeExport Protocol (stream_names/stream_edges seam), NebulaGraphEdgeExport (LOOKUP names + batched GO over RELATED, reads weight), Neo4jGraphEdgeExport (keyset Cypher pagination, byte-for-byte), RELATED weight column (mention_count-derived, weighted Leiden parity), Nebula graph-compute read design (extract_entity_edges + RELATED weight) (+13 more)

### Community 141 - "test_graph: index.py"
Cohesion: 0.07
Nodes (41): _period_bounds(), _period_in_window(), _polarity_evolution(), date, First and last day covered by a bucket key from     ``epoch_days_to_period``., Keep a bucket that OVERLAPS the window.      Overlap rather than containment: a, No `period_start`/`value` here, deliberately — see the tool docstring.      Rows, How often a topic is mentioned across ingested documents, per period     — the c (+33 more)

### Community 142 - "test_retrieval: test_query_planner.py"
Cohesion: 0.16
Nodes (19): decompose(), _parse_subquestions(), LLM, Query decomposition for the plan-execute search flow (R2).  A compound question, Parse the planner's reply into a list of sub-questions.      Tolerant of three s, Split ``question`` into ≤``max_subqueries`` sub-questions.      Returns ``[quest, _strip_marker(), Unit tests for the query planner (R2 plan-execute flow).  Stubs the LLM so the s (+11 more)

### Community 143 - "test_workflow: MapCommunitiesParams"
Cohesion: 0.13
Nodes (12): Temporal worker / client connection settings., TemporalSettings, And the operator's value wins over that default., The CODE's default, not whatever the developer's `.env` says.      This used to, test_community_backend_defaults_to_gds(), test_community_backend_is_constrained(), test_community_backend_reads_the_environment(), Dedicated merge queue (decouples GraphBuildWorkflow's merge stage     from a bur (+4 more)

### Community 144 - "test_graph_edge_export.py"
Cohesion: 0.15
Nodes (16): Fake nebula store: records nGQL (asserts inline, no param_map);     returns cann, Records (cypher, param_map) calls; returns canned pages per call,     popped in, _RecNebula, _RecStore, test_dispatch_returns_nebula_when_backend_nebula(), test_dispatch_returns_neo4j_when_backend_not_nebula(), test_nebula_stream_edges_chunks_go_calls_by_batch_size(), test_nebula_stream_edges_names_none_falls_back_to_internal_stream_names() (+8 more)

### Community 145 - "test_ingest_queue: RabbitMQSettings"
Cohesion: 0.11
Nodes (21): AbstractChannel, AbstractQueue, Event, RabbitMQSettings, RabbitMQ ingest-queue connection (Track B).      Only consumed when ``INGEST_QUE, Allow a comma-separated env string (RABBITMQ_QUEUES=a,b) as well         as a JS, Queue used when /ingest doesn't name one (the first configured)., main() (+13 more)

### Community 146 - "test_retrieval: test_hybrid.py"
Cohesion: 0.13
Nodes (14): numeric_rollup(), NumericRollupParams, _Params, parse_amount(), Any, BaseModel, Arc 1 — numeric rollups over Amount identifier entities (mini-OLAP). Parsing is, build_rollups_graph_ops() (+6 more)

### Community 147 - "diagrams: DocumentIngestWorkflow (IngestParams to IngestResult, queue"
Cohesion: 0.14
Nodes (20): build_property_graph: PropertyGraphIndex Neo4j upsert (chunks, MENTIONS, entities, relations, fulltext), Client entry: POST /api/v1/ingest (202 job_id) + CLI src.ingestion.run (direct, no Temporal), CommunityBuildWorkflow (offline, admin/schedule, queue kb-graph-build): GDS Leiden + report build, Document ingest flow architecture diagram (D2), DocumentIngestWorkflow (IngestParams to IngestResult, queue kb-ingest), extract_kg step: per-chunk LLM KG extraction (LightRAG), queue kb-ingest-llm, LLMPool-gated, GraphBuildWorkflow (child, queue kb-ingest-merge): merge_and_resolve + build_property_graph, Graph half (best-effort; failure implies graph_status=vector_only) (+12 more)

### Community 148 - "superpowers: Phase 3 er_vec slice —"
Cohesion: 0.15
Nodes (19): NebulaGraph migration plan (Phases 0-4; strangler-fig, backend-dispatched), Phase 3 er_vec slice — ER candidate-kNN via Milvus, backend-dispatched, Milvus collection entity_er_vec (PK name, er_vec FLOAT_VECTOR dim=1536 COSINE HNSW, canonicals only), EntityVectorStore seam (Protocol knn/upsert; Neo4j + Milvus impls; build_entity_vector_store), AgentSettings.er_vector_backend (native|milvus, default native; nebula forces Milvus), Phase 2 vertical slice — Nebula read-path design, find-by-name → nGQL LOOKUP ON Entity (parity gap vs Neo4j fulltext, accepted), Generic RELATED edge + rel_type property (entity–entity relations avoid edge-label injection) (+11 more)

### Community 149 - "superpowers: channel group enum (src/retrieval/groups.py)"
Cohesion: 0.11
Nodes (20): Channel groups implementation plan, doc_group chunk metadata (dynamic field), channel group enum (src/retrieval/groups.py), GroupFilter (Milvus push-down + graph post-filter), per-group rerank weights (AGENT_GROUP_WEIGHTS), tg_ingest resolve_group_map (folder → group), Manual channel reingest + low-priority lane plan, x-max-priority RabbitMQ ingest queue (+12 more)

### Community 150 - "superpowers: doc_group chunk metadata (mirrors doc_date_epoch"
Cohesion: 0.16
Nodes (20): doc_group chunk metadata (mirrors doc_date_epoch push-down), Group search filter (Milvus IN/NIN MetadataFilter + graph post-filter), AGENT_GROUP_WEIGHTS rerank weights (official 1.30 … opinion 0.80), GROUPS enum (news, analytics, digest, opinion, official, data) src/retrieval/groups.py, Channel groups design (six editorial groups → RAG), Synthesis group context ([group] prefix per source), RabbitMQSettings.max_priority (RABBITMQ_MAX_PRIORITY default 10), PRIO_LIVE=5 / PRIO_BACKFILL=0 priority constants (+12 more)

### Community 151 - "analytics: StepResult"
Cohesion: 0.11
Nodes (32): StepResult, build_synthesis_prompt(), extract_numbers(), faithfulness_score(), _norm(), numbers_in_rows(), ChatMessage, Synthesis prompt + numeric-faithfulness checker.  The LLM verbalizes; it must no (+24 more)

### Community 152 - "test_graph: test_alert_store.py"
Cohesion: 0.05
Nodes (73): BasePydanticVectorStore, BaseRetriever, BM25Retriever, IngestionCache, IngestionPipeline, MilvusSettings, _build_cache(), build_ingestion_pipeline() (+65 more)

### Community 153 - "test_graph: ERConfig"
Cohesion: 0.20
Nodes (10): _acquire_session(), Get a session from the pool, re-probing a written-off address first.      nebula, _FakePool, The nebula3 ConnectionPool recovers after graphd restarts.  Regression (2026-08-, get_session fails while the address is written off (S_BAD)., interval_check > 0 is what starts nebula3's periodic re-probe., test_acquire_session_does_not_reprobe_a_healthy_pool(), test_acquire_session_reprobes_a_written_off_address() (+2 more)

### Community 154 - "graph: GLiNERExtractor"
Cohesion: 0.16
Nodes (15): _default_entity_types(), gliner_ner_callable(), GLiNERExtractor, _load_gliner(), Any, BaseNode, TransformComponent, Optional GLiNER span-based entity extractor as a LlamaIndex ``TransformComponent (+7 more)

### Community 155 - "test_graph: test_communities_graph_ops.py"
Cohesion: 0.15
Nodes (13): _NebulaRaisingStore, _NebulaRecStore, _RaisingStore, _RecStore, test_dispatch_nebula(), test_dispatch_neo4j_default(), test_nebula_community_overview_matches_by_level(), test_nebula_entity_communities_empty_when_no_edges() (+5 more)

### Community 156 - "diagrams: Temporal Worker (activities + workflows"
Cohesion: 0.16
Nodes (19): Clients layer, System Architecture Diagram (layered: Clients / Edge-API / Temporal / Stores / Observability), Edge / API layer, FastAPI :8000, Hermes Agent client, LiteLLM proxy :4000, MCP-1 :9001, MCP-2 :9002 (+11 more)

### Community 157 - "superpowers: Automatic event detection — design"
Cohesion: 0.18
Nodes (14): Search date filters — design (Rev 2), Single stamping point in parse_and_chunk (chunk metadata epoch dates → Milvus + :Chunk), epoch-days canonical filter value (doc_date_epoch, inserted_at_epoch), Uniform post-filter for both stores (over-fetch + drop out-of-range; Milvus push-down deferred), Automatic event detection — design, Event model — :__Entity__:EventOrAction specialization (event_type/trigger/event_ts + created_at), Event resolution/dedup (event-specific match key: type + participants + event_ts proximity), first_seen / created_at stamping (ON CREATE on nodes/rels/events; one-time backfill sentinel) (+6 more)

### Community 158 - "test_analytics: test_claim_extract.py"
Cohesion: 0.20
Nodes (17): build_extract_prompt(), extract_claims(), _one(), parse_claims(), Claim, LLM extraction of atomic claims from a document (offline, hybrid method B).  Mir, Pure, tolerant parse of an LLM claims array. Never raises., Extract claims from one document. Fail-open ([]) on any LLM error. (+9 more)

### Community 159 - "test_graph: test_analysis_nebula.py"
Cohesion: 0.11
Nodes (12): build_community_summarize(), CommunitySummarize, Neo4jCommunitySummarize, Any, Protocol, Runs the historical Cypher constants verbatim — zero behaviour change., _build_child_context(), _build_member_context() (+4 more)

### Community 160 - "graph: CanonicalLinker"
Cohesion: 0.19
Nodes (11): CanonicalCandidate, CanonicalLinker, Any, Canonical entity linker — resolve a mention to an existing Wikibase QID.  Turns, One linking candidate — an existing Wikibase item.      ``score`` is an alias-ma, Resolve a mention → existing Wikibase QID, else ``None``.      ``index`` exposes, Return the QID this mention links to, or ``None`` to mint new., _FakeIndex (+3 more)

### Community 161 - "graph_edge_export.py"
Cohesion: 0.15
Nodes (9): build_graph_edge_export(), GraphEdgeExport, NebulaGraphEdgeExport, Neo4jGraphEdgeExport, Any, Protocol, Backend-dispatched graph edge EXPORT (Leiden read-phase).  ``Neo4jGraphEdgeExpor, nGQL graph edge EXPORT. Node names via keyset ``LOOKUP``; edges via a     batche (+1 more)

### Community 162 - "graph: lightrag_extract.py"
Cohesion: 0.05
Nodes (43): 0. Весь слой на пальцах (прочитайте это, если у вас 10 минут), 10.1 Воронка (от макро к микро), 10.2 Чек-лист недоверия (вешать над монитором), 10. Методология: воронка аналитика и чек-лист недоверия, 11. Справочник: примитивы → теория, 1.1 От property graph к графу анализа, 1.2 Три измерения поверх топологии, 1.3 Двудольная природа и co-occurrence (+35 more)

### Community 163 - "test_graph: write_with_retry()"
Cohesion: 0.18
Nodes (17): _is_transient(), Any, BaseException, Bounded retry for transient Neo4j write failures (Track A3).  Concurrent ``MERGE, True for Neo4j transient/contention errors that are safe to retry.      Matches, Call ``fn(*args, **kwargs)``, retrying on transient Neo4j errors.      Up to ``m, write_with_retry(), T (+9 more)

### Community 164 - "test_mcp: test_tools_server.py"
Cohesion: 0.15
Nodes (20): Bounded-concurrency wrapper for the project LLM.  The default LlamaIndex ``LLM``, Return an already-wrapped LLM untouched; wrap a raw one.      Lets DI bootstrap, wrap_if_needed(), _make_inner(), Unit tests for the BoundedLLM wrapper.  We don't talk to a real LLM — verify the, With two gates (caps 2 and 3), the tighter gate (2) bounds in-flight., If the inner call raises, all gates are released (no leak)., N=2 parallel calls must serialise into 2 batches when 4 are launched.      We us (+12 more)

### Community 165 - "run_answer_eval.py"
Cohesion: 0.18
Nodes (19): _centrality_update_stmt(), _flush_centrality_batch(), Any, Offline GDS compute + write-back into Neo4j. Mirrors src/graph/communities.py., Compute EVERY metric from ONE export + ONE igraph build, write batched.      ``c, Nebula path: every metric from ONE compute, written in batches.      Prefer this, Full-refresh :LIKELY_LINK edges via gds.nodeSimilarity.stream.      Deletes ALL, Run the GDS centrality stream for ``metric`` and write scores back to __Entity__ (+11 more)

### Community 166 - "test_graph: test_centrality_graph_ops.py"
Cohesion: 0.16
Nodes (12): _NebulaRaisingStore, _NebulaRecStore, _RaisingStore, _RecStore, test_dispatch(), test_nebula_fail_soft(), test_nebula_link_prediction_empty(), test_nebula_top_central_reads_column() (+4 more)

### Community 167 - "test_graph: test_events_graph_ops.py"
Cohesion: 0.21
Nodes (14): MonitorIn, _BurstStore, _FakeStore, MonkeyPatch, Tests for detect_alerts activity (Arc 2 monitoring sweep)., Records all structured_query calls and returns scripted rows., One edge row + one risk row → one alert of each kind., When both endpoints are watched, two new_connection alerts are emitted. (+6 more)

### Community 168 - "download_models.py"
Cohesion: 0.15
Nodes (15): ArgumentParser, build_arg_parser(), _download_gliner(), _download_reranker(), _force_online(), main(), Pre-download the project's HuggingFace models into a local cache.  Two models fl, Download the cross-encoder reranker into the cache. (+7 more)

### Community 169 - "test_retrieval: test_llm_factory.py"
Cohesion: 0.17
Nodes (17): _capture(), _capture_kwargs(), Role-keyed LLM factory tests.  Confirms each wrapper resolves its model name thr, Default config ⇒ no extra_body wired into the request., Patch OpenAILike, call ``build_llm(...)`` once, return the model     name that t, Legacy path: no role kwarg ⇒ small tier (effective_base)., Explicit LITELLM_LLM_MODEL still wins for the no-role path., Like ``_capture`` but returns the full kwargs dict OpenAILike saw. (+9 more)

### Community 170 - "superpowers: kb-llamaindex Conference Deck plan"
Cohesion: 0.14
Nodes (17): Graph-scale & GraphRAG-parity backlog, AgentSettings config class, Claims/covariates extraction (KG_CLAIMS_KEY), kb-llamaindex Conference Deck plan, Entity Resolution 12-step pipeline, LightRAG-style KG extractor, Marp Markdown decks (A/D), Milvus vector index (+9 more)

### Community 171 - "superpowers: LLMPool (per-process role lanes +"
Cohesion: 0.15
Nodes (17): LiteLLM proxy gateway, LiteLLM Redis cache plan, LiteLLM proxy Redis response cache, Project-side Redis LLM cache plan, CachedLLM (OpenAILike read-through), LLMCacheSettings, Interactive .env Builder plan, scripts/make_env.py (+9 more)

### Community 172 - "graph: admin.py"
Cohesion: 0.13
Nodes (21): cap_synth_sources(), distinct_doc_ids(), How many chunks to let the cross-encoder score.      Derived from the number tha, ``(start_to_close, schedule_to_close)`` for ``rerank_sources``.      Derived fro, Distinct, order-preserving doc_ids from a source pool's metadata.     Skips sour, Bound the pool fed to synthesis.  This is now the ONLY cap on the     synthesis, rerank_candidate_count(), rerank_timeouts() (+13 more)

### Community 173 - "er_graph_ops.py"
Cohesion: 0.07
Nodes (17): build_er_graph_ops(), _CompositeERGraphOps, ERGraphOps, NebulaERGraphOps, Neo4jERGraphOps, Any, Protocol, Backend-dispatched entity-resolution GRAPH ops (verdict cache + edge-redirect me (+9 more)

### Community 174 - "test_retrieval: RoundGraphData"
Cohesion: 0.13
Nodes (23): Build a retriever backed only by a KbGraphStore (structured_query),         with, _FakeStore, Nebula read slice: store-only retriever construction + aretrieve guard., Accepts the `p` map the previous MATCH form returned, so a caller     or fake fe, graph_search under nebula: er_vec kNN picks entities, then subgraph-expand., The walk seeds from BOTH the vector kNN and the entity-table lexical     hit — a, A naive try/except around the whole seeding block would blank both     paths on, Exercise `_entity_table_names`'s OWN try/except (not an outer mock     of the se (+15 more)

### Community 175 - "test_workflow: push_wikibase.py"
Cohesion: 0.18
Nodes (11): build_series_query(), date, Rows for one indicator, newest revision per period unless pinned., `dims={}` is "the rows carrying NO dimensions", not "any row".      Containment, A partial cut must stay a containment match — asking for     `{"region": "Москва, test_series_query_applies_date_bounds_and_dims(), test_series_query_defaults_to_latest_revision(), test_series_query_empty_dims_means_strictly_undimensioned() (+3 more)

### Community 176 - "test_graph: test_community_read.py"
Cohesion: 0.08
Nodes (20): build_community_read(), CommunityRead, NebulaCommunityRead, Neo4jCommunityRead, Any, Protocol, Backend-dispatched community READ (map-phase summary fetch).  `Neo4jCommunityRea, Runs the historical Cypher constant verbatim — zero behaviour change. (+12 more)

### Community 177 - "ingest_scale_bottlenecks.svg: DocumentIngestWorkflow"
Cohesion: 0.15
Nodes (16): Ingest scale bottlenecks — architecture diagram, DocumentIngestWorkflow, Entity Resolution — FIXED: native vector kNN now DEFAULT ON (was 5000-window → recall→0 as graph grows), extract_kg activity, GraphBuildWorkflow (kb-ingest-merge), admit K=1, IngestSchedulerWorkflow (singleton) — docs run ONE-AT-A-TIME, inject_canonical activity — MED: no heartbeat (only long stage w/o one), LiteLLM proxy (single) (+8 more)

### Community 178 - "superpowers: Analytical layer — design (NL"
Cohesion: 0.16
Nodes (16): Analytical layer — design (NL analytical Q&A over the graph), AnalyticalQueryWorkflow (plan → execute primitives|cypher → synthesize + provenance), AnalyticsMaterializeWorkflow (offline GDS: centrality/link-prediction → Neo4j properties), cypher_guard — guarded read-only text-to-Cypher fallback (denylist, timeout, LIMIT; kill switch), analytical planner (small-tier LLM NL → validated AnalysisPlan), Primitive catalog (~24 primitives, 4 families; open/closed registry in catalog.py), Provenance chain (answer + primitive/Cypher + raw rows + source chunks; numbers from executor not LLM), Actionable signals — from graph metrics to decisions (+8 more)

### Community 179 - "setup_db.py"
Cohesion: 0.13
Nodes (9): The stats DDL is asserted as text, not by hitting a live Postgres — the point is, Not pinned as a literal string: the expected clause is built here     from the s, A nullable `dims` would silently break the UNIQUE constraint,     because NULL n, DROP CONSTRAINT IF EXISTS before ADD CONSTRAINT is what makes     re-running thi, `setup_db` must exit 0 both times it is run against an     already-created table, test_constraints_ddl_drops_before_it_adds_so_reruns_never_conflict(), test_dims_is_not_null_with_empty_default(), test_indicator_constrains_value_kind_and_granularity() (+1 more)

### Community 180 - "test_analytics: ids.py"
Cohesion: 0.20
Nodes (21): clamp_top_n(), Clamp a requested row cap into ``[1, hard_max]``; ``None``/<=0 → default., common_connections(), CommonConnectionsParams, connection_path(), ConnectionPathParams, cooccurrence(), CooccurrenceParams (+13 more)

### Community 181 - "bot: pipeline.py"
Cohesion: 0.08
Nodes (31): is_allowed(), parse_allowed_users(), Telegram user whitelist. An empty whitelist denies EVERYONE — a personal KB bot, True iff ``user_id`` is whitelisted. Empty whitelist → always False., Parse a comma-separated ``BOT_ALLOWED_USERS`` into a set of user ids.     Non-in, The bot's answer pipeline: whitelist → session → follow-up rewrite → KB search →, Any, Seeding the first administrators.  Its own module rather than part of the entryp (+23 more)

### Community 182 - "bot: with_fallback()"
Cohesion: 0.26
Nodes (10): compute_all(), compute_centrality(), Any, In-worker centrality (igraph) over the exported __Entity__ graph.  Mirrors src/g, Return ``{entity_name -> score}`` for ``metric`` over the weighted     undirecte, Stream the graph once, compute every metric. Returns     ``{metric -> {name -> s, test_compute_betweenness_hub_is_broker(), test_compute_empty_graph_returns_empty() (+2 more)

### Community 183 - "test_config: TemporalSettings"
Cohesion: 0.04
Nodes (48): 10.1 Temporal UI (http://localhost:8080), 10.2 Grafana-дашборды (http://localhost:3001), 10.3 Postgres-запросы, 10.4 Prometheus (http://localhost:9092), 10. Observability — что смотреть когда, 11. Траблшутинг, 12.1 Связанные runbook'и, 12.2 Архитектурные документы (+40 more)

### Community 184 - "test_graph: community_graphscope.py"
Cohesion: 0.09
Nodes (22): 10. Прогон тестового набора, 11. Операции сброса / очистки, 12. Смена моделей, 13. Чеклист продакшена, 14. Траблшутинг, 15. Куда смотреть, 1. Предварительные требования, 2. Клонирование и установка (+14 more)

### Community 185 - "graph: community_read.py"
Cohesion: 0.19
Nodes (21): _api_key_header(), ASGI tests for `POST /api/v1/ingest`.  The MinIO client, Postgres, and the Tempo, MinIO container fully down: the SDK raises a urllib3     `MaxRetryError`, not an, Reuse policy on the Temporal side raises     ``WorkflowAlreadyStartedError`` whe, Admission is always-on: every upload MUST route through the singleton     Ingest, A valid `document_date` is converted to epoch-days and snapshotted     onto Inge, A malformed `document_date` is rejected with 422 before any     upload / Postgre, rabbitmq backend: an unconfigured `queue` is rejected with 422     before any up (+13 more)

### Community 186 - "ingestion: identifier_transform.py"
Cohesion: 0.17
Nodes (12): build_augment_block(), build_custom_kg_payload(), dedupe_by_canonical(), Keep first occurrence per (entity_type, canonical) pair.      Preserves source o, Assemble a ``rag.ainsert_custom_kg`` payload from identifier matches.      One e, Format the canonical-identifiers block appended to document text.      Produces, test_build_augment_block_empty_input(), test_build_augment_block_format() (+4 more)

### Community 187 - "retrieval: atomic_tools.py"
Cohesion: 0.12
Nodes (21): _edge_stmts(), One giant INSERT EDGE ... VALUES blows nebula's max query size (4 MiB)     and t, Regression: the level-0 root community held 60117 members and produced a     456, Fast path unchanged: a small community still emits ONE statement., Records structured_query(cypher, param_map) calls; returns [] (or a     canned v, Fake NebulaGraphStore: records structured_query(q) statements; returns     a can, _RecSession, _RecStore (+13 more)

### Community 188 - "test_retrieval: get_chunks_by_doc_id()"
Cohesion: 0.07
Nodes (38): ADR-0005 Deterministic identifier canonicalization before LLM, ADR-0007 Entity Resolution (candidates + LLM judge + verdict cache + union-find), ADR-0008 Optional native-vector kNN ER over 5000-row window, _candidate_pairs(), _cosine(), _deep_normalize(), _deterministic_pairs(), _initials_signature() (+30 more)

### Community 189 - "test_graph: _FakeClient"
Cohesion: 0.15
Nodes (13): Nebula centrality write-back: compute once, write batched.  Two defects, both me, Nebula rejects a request over `max_allowed_query_size` (4 MiB) with     `SyntaxE, Fail-soft must survive batching: an ER-merged or deleted vertex raises     `Vert, Records every nGQL request; optionally fails any request mentioning a vid., The whole point: betweenness must be computed ONCE, not once per metric., 273069 sequential round-trips is the thing being removed., _RecStore, test_batch_respects_the_statement_size_budget() (+5 more)

### Community 190 - "superpowers: Seven Tracks plan"
Cohesion: 0.13
Nodes (15): Always-on ingest admission (IngestSchedulerWorkflow), K+N single-semaphore LLM pool, K+N throttle migration plan, Answer template (Track 6), doc-by-id MinIO-aware load (Track 3), Ingest classifier + force (Track 2), Seven Tracks plan, Prod docker compose stack (Track 1) (+7 more)

### Community 191 - "di: providers.py"
Cohesion: 0.19
Nodes (10): Provider, build_api_container(), build_worker_container(), CommonProvider, BaseEmbedding, Shared singletons available to both API and worker., Worker container — currently exposes only `CommonProvider`.      The Temporal wo, Tests for `src/di/providers.py`.  Live LLM / Milvus / Neo4j is not exercised — t (+2 more)

### Community 192 - "merge_identifier_duplicates.py"
Cohesion: 0.20
Nodes (14): _amain(), apply_merges(), _build_merge_cypher(), canonicalize_for_type(), collect_entity_nodes(), group_by_canonical(), main(), _parse_args() (+6 more)

### Community 193 - "set_admission.py: get_temporal_client()"
Cohesion: 0.12
Nodes (29): ExecInput, PrimitiveCall, step_from_primitive(), execute_step(), Run a single primitive from CATALOG; fail-soft on unknown primitive or bad kwarg, test_step_from_primitive_counts_rows(), test_step_from_primitive_default_error_detail_is_empty(), test_step_from_primitive_default_error_is_empty() (+21 more)

### Community 194 - "graph: alert_store.py"
Cohesion: 0.07
Nodes (34): AsyncConnectionPool, AsyncIngestMetrics, build_ingest_metrics_store(), MetricRow, AsyncConnection, BaseModel, Async Postgres wrapper for the ``ingest_metrics`` table.  Owned by the analytics, Factory consistent with the rest of ``src/storage/``. (+26 more)

### Community 195 - "graph: event_ts_resolver.py"
Cohesion: 0.16
Nodes (23): coverage_check(), _parse(), ``coverage_check`` activity — pre-synthesis completeness gate.  After the orches, Judge whether gathered evidence fully covers the query., CoverageResult, Output of ``coverage_check``.      ``complete`` — is the gathered evidence suffi, build_evidence(), Pure coverage-gate helpers for the plan-execute flow (R4).  Extracted as plain f (+15 more)

### Community 196 - "test_api: test_search_v2_routes.py"
Cohesion: 0.30
Nodes (10): make_agent(), Ask the openclaw agent one question over its OpenAI-compatible endpoint.  opencl, Build `agent(question) -> answer`. Raises on non-2xx / transport     error so th, _patch(), The openclaw agent client — a plain OpenAI call, against a mock transport., openclaw maps OpenAI `user` to its sessionKey — this is what makes a     follow-, test_empty_choices_yield_empty_string(), test_posts_model_and_message() (+2 more)

### Community 197 - "test_analytics: _FakeOps"
Cohesion: 0.32
Nodes (8): _FakeOps, _patch(), Records (method, args); returns canned rows per method name., test_contradictions_routes_through_seam(), test_failsoft_all_primitives_return_empty_without_store(), test_incomplete_entities_resolves_and_threads_expected(), test_merge_candidates_routes_through_seam(), test_orphans_threads_min_degree()

### Community 198 - "test_graph: test_retriever_triplet_parse.py"
Cohesion: 0.27
Nodes (10): _build(), _FakePGIndex, _FakeRetriever, _node(), NodeWithScore, GraphRetriever.aretrieve must extract entities/relations from the TextNode-shape, test_duplicate_triplets_across_nodes_deduped(), test_multi_hop_chain_line_yields_pairwise_relations() (+2 more)

### Community 199 - "test_ingest_queue: test_consumer.py"
Cohesion: 0.09
Nodes (30): admit(), check_quota(), ConcurrencyGate, Decision, is_admin(), Who may ask, how much, and how many at once.  Pure and synchronous (except the g, Whether this user may run anything at all.      Fail closed: anything that is no, Daily budget. ``quota <= 0`` means unlimited. (+22 more)

### Community 200 - "Architecture Decision Records (ADR) practice"
Cohesion: 0.19
Nodes (13): ADR-0001: Temporal for durable orchestration, ADR-0002: Claim-check staging via MinIO, ADR-0003: Task-queue isolation to avoid head-of-line blocking, ADR-0009: Hierarchical Leiden communities + structured reports, ADR-0010: Dynamic community selection (lexical/semantic/descent), ADR-0015: Community-detection backend = in-worker leidenalg, Architecture Decision Records (ADR) practice, CONCEPTS.md (planned educational companion) (+5 more)

### Community 201 - "ANALYTICS-GUIDE.md: Centralities (four notions of importance)"
Cohesion: 0.14
Nodes (14): Betweenness centrality, Bonacich (1987) Power and Centrality, Brin & Page (1998) PageRank, Burst detection (temporal dynamics), Burt (1992) Structural Holes, Centralities (four notions of importance), Degree centrality, Eigenvector centrality (+6 more)

### Community 202 - "CONCEPTS.md: Entity Resolution (ER)"
Cohesion: 0.11
Nodes (19): (a) Генерация кандидатов через косинусное сходство (векторизованная), (b) LLM-как-судья для пограничных пар + кэш вердиктов (`:ERVerdict`), (c) Union-find / кластеризация связных компонент, (d) Зажим гипер-хабов (hyper-hub clamp), (e) Выбор канонического, Entity Resolution (ER), (f) Источник кандидатов: инкрементальное окно против нативного-векторного kNN, FLAT против HNSW (Milvus) (+11 more)

### Community 203 - "superpowers: Wikibase populator runbook"
Cohesion: 0.21
Nodes (14): Wikibase populator runbook, QID writeback idempotency, scripts/setup_wikibase.py bootstrap, scripts/smoke_wikibase_push.py, WDQS / Blazegraph SPARQL endpoint, Self-hosted Wikibase, Wikibase population plan, push_entities orchestrator (src/storage/wikibase.py) (+6 more)

### Community 204 - "superpowers: Agentic Search plan (Plan #2)"
Cohesion: 0.20
Nodes (14): ReAct agent (/agent, react_agent.py), Agentic Search plan (Plan #2), CommunityBuildWorkflow (GDS Leiden offline), GlobalSearchWorkflow (community map-reduce), graph_walk multi-hop tool, SearchOrchestratorWorkflow, SubQueryRetrievalWorkflow, Search drift-fix + dead-code audit plan (+6 more)

### Community 205 - "workflow: wiki_sweep.py"
Cohesion: 0.31
Nodes (6): find_neighbours(), GraphRetrieverProtocol, Any, Neighbours of an entity: matched node + relations up to ``hops``     triplet-hop, test_find_neighbours_passes_hops_as_path_depth(), test_find_neighbours_returns_entities_and_relations()

### Community 206 - "build_er_graph_ops()"
Cohesion: 0.15
Nodes (21): Query-builder tests are exact-string; row mapping is tested against a stub conne, A registered indicator with no rows yet must still be listed —     otherwise a f, `build_indicators_query` was covered as a pure builder, but nothing     ever cal, `get_indicator` has no builder function (inline SQL) and does no     internal `r, The success path: neither the RETURNING handling nor the commit     was executed, `_conn()` yields a pooled connection whose default row factory is     NOT dict_r, _repo_with(), test_get_indicator_returns_none_when_absent() (+13 more)

### Community 207 - "Neo4jWikiGraphOps"
Cohesion: 0.14
Nodes (3): Neo4jWikiGraphOps, Any, Runs the historical wiki-editor Cypher verbatim — zero behaviour     change from

### Community 208 - "test_workflow: select_communities_descent()"
Cohesion: 0.23
Nodes (12): RouteLabel, dispatch_for_route(), merge_doc_ids(), Pure: map a route label to the workflow that serves it.      Unknown / unexpecte, Union of two doc_id lists, order-preserving, deduped., Routing dispatch tests (Search R7a).  The route→workflow mapping lives in the pu, test_dispatch_date_scoped_downgrades_global_to_local(), test_dispatch_date_scoped_leaves_local_and_drift_intact() (+4 more)

### Community 209 - "eval: run_scale_bench.py"
Cohesion: 0.22
Nodes (9): 4. Платформа, Claim-check staging, LLMPool (пер-процессная конкурентность), MCP-серверы, Scale-bench harness 🆕, Документ-уровневый контроль допуска 🆕, Долговечные воркфлоу Temporal + очереди, Продакшен docker-compose + Dockerfile (Track 1) 🆕 (+1 more)

### Community 210 - "test_retrieval: test_atomic_tools.py"
Cohesion: 0.16
Nodes (5): AbstractAsyncContextManager, BoundedLLM, Any, LLM, Wraps an LLM with a process-wide asyncio.Semaphore, or through an     ordered li

### Community 211 - "test_storage: test_minio_stream.py"
Cohesion: 0.08
Nodes (24): _chunks(), _is_session_dead(), NebulaGraphStore, Any, NebulaGraph implementation of the KbGraphStore seam (write path).  Phase 1 scope, Bounded GET SUBGRAPH from `vid`, mapped to the shape         GraphRetriever._map, Map a nebula3 ResultSet to a list of column->value dicts., True when a failed ResultSet blames an expired/unknown session. (+16 more)

### Community 212 - "superpowers: NebulaGraph cutover — neo4j decommissioned"
Cohesion: 0.36
Nodes (8): nGQL translation rules (nebula 3.8), Cypher→nGQL MATCH translation rules, NebulaGraph cutover — neo4j decommissioned, NebulaGraph backend, Neo4j graph backend (retained seam), NebulaGraph cutover-readiness assessment, Neo4j→nebula data-migration blocker, Wiki-editor crash set under nebula

### Community 213 - "superpowers: Spec — Seven Tracks (build"
Cohesion: 0.18
Nodes (13): Spec — Seven Tracks (build order for 7 capabilities), Track 6 — templated answers (answer_template threaded through synthesis), Track 2 — input document classifier (skip) with force-override, Track 1 — production docker-compose (whole app in compose, external litellm/ollama), Track 5 — document-level admission control (IngestSchedulerWorkflow, MAX_INFLIGHT_DOCS), Track 7a — meaningful relation weight + tags (mention_count/confidence, provenance aggregation), Track 3 — source-document-by-id bugfix (doc_id in Milvus + MinIO-aware chunk_repository), Track 4 — weighted Leiden at 50k: instrumentation + knobs (no silent GDS-error swallow) (+5 more)

### Community 214 - "test_workflow: dispatch_for_route()"
Cohesion: 0.39
Nodes (7): _pages_to_delete(), Titles to delete: every listed (main-namespace) page except keep-list., Unit tests for the pure helpers in scripts/wipe_db.py.  The I/O wipe functions (, test_pages_to_delete_custom_keep(), test_pages_to_delete_empty(), test_pages_to_delete_excludes_keep_list(), test_pages_to_delete_keeps_main_page_by_default()

### Community 215 - "eval: diag_kg_lightrag.py"
Cohesion: 0.29
Nodes (7): Deterministic identifier canonicalization, LightRAG KG extraction, Document parsing & chunking, Relation polarity & temporal validity, extract_kg activity, merge_and_resolve activity, Translation context budget

### Community 216 - "Neo4jAggregationsGraphOps"
Cohesion: 0.11
Nodes (17): community_overview(), CommunityOverviewParams, entity_communities(), EntityCommunitiesParams, _Params, personalized_pagerank(), PersonalizedPagerankParams, Any (+9 more)

### Community 218 - "workflow: retrieve.py"
Cohesion: 0.09
Nodes (23): entity_activity(), EntityActivityParams, _iso_to_epoch_days(), _Params, polarity_evolution(), PolarityEvolutionParams, Any, BaseModel (+15 more)

### Community 219 - "test_retrieval: test_graph_path_depth.py"
Cohesion: 0.29
Nodes (9): RoundGraphData, _build(), _FakePGIndex, _FakeRetriever, Unit tests for GraphRetriever per-call ``path_depth``.  Uses a fake PropertyGrap, test_default_depth_prebuilt_and_reused(), test_depth_clamped_to_max(), test_depth_clamped_to_min() (+1 more)

### Community 220 - "diagrams: GlobalSearchWorkflow (mode=global): GraphRAG map-reduce over"
Cohesion: 0.29
Nodes (12): AutoSearchWorkflow (mode=auto): router decides local|global|drift, CommunityBuildWorkflow: community summaries built offline, dispatch_for_route: local | global | drift, Drift step 0: contextualize ONCE (children get history cleared), Drift step 2: global with drift_mode=True, seeded by local sources, Drift step 1: run local (child), DriftSearchWorkflow (mode=drift): specific + corpus context, heaviest mode, Entry surfaces: MCP kb_search/_global/_drift/_auto + FastAPI /api/v1/search/{local,global,drift,auto} on kb-search-small queue (+4 more)

### Community 221 - "presentation: Conference deck A (tech/ML)"
Cohesion: 0.20
Nodes (11): Conference deck A (tech/ML), Eval gate (287 tests + golden Q&A), Per-request tracing (trace_request), Postgres job-state store, /agent ReAct loop (8 tools), /selfrag reflective synthesis, Three query endpoints: /search, /agent, /selfrag (legacy), Conference deck D (internal defense) (+3 more)

### Community 222 - "superpowers: Nebula community-BUILD (nGQL) implementation plan"
Cohesion: 0.18
Nodes (12): Nebula Community TAG + level index DDL, community_vid VID scheme (blake2b level-scoped), CommunityWriteback seam, Nebula community-BUILD (nGQL) implementation plan, NebulaCommunityWriteback (nGQL INSERT/LOOKUP/DELETE/FETCH), Neo4jCommunityWriteback (verbatim Cypher), CommunitySummarize seam, Nebula community-SUMMARIZE (nGQL) implementation plan (+4 more)

### Community 223 - "message_stats.py"
Cohesion: 0.27
Nodes (10): format_status_rows(), format_timeline(), main(), Namespace, CLI for processed-message statistics — a thin wrapper over the same AsyncPostgre, Render status_counts_by output as an aligned text table., _run(), CLI wiring: `channels` calls status_counts_by('source_channel', ...) and its row (+2 more)

### Community 224 - "test_config: test_preflight.py"
Cohesion: 0.36
Nodes (10): Return a list of actionable config problems (empty == OK).          Hard problem, Boot-time preflight: actionable problems instead of mid-request stack traces., _settings(), test_preflight_clean_prod_has_no_problems(), test_preflight_dev_allows_placeholders(), test_preflight_flags_placeholder_key_in_multikey_api_keys(), test_preflight_flags_placeholder_minio_secret_in_prod(), test_preflight_flags_placeholder_secret_in_prod() (+2 more)

### Community 226 - "test_graph: test_store.py"
Cohesion: 0.23
Nodes (5): Process-global Neo4j graph-store cache + driver-pool kwargs (Track A2).  No live, _RecordingStore, test_build_installs_query_logging_only_when_flag_on(), test_query_logging_wrapper_is_idempotent(), test_query_logging_wrapper_logs_and_passes_through()

### Community 227 - "ARCHITECTURE.md: DocumentIngestWorkflow"
Cohesion: 0.18
Nodes (13): R7b legacy search cutover (BREAKING), FastAPI API service, Ingest path (DocumentIngestWorkflow), MCP servers (MCP-1 kb_search, MCP-2 atomic tools), Temporal task queues, Search path (local/global/drift/auto), Temporal worker (queue pools), Durable Execution (Temporal) (+5 more)

### Community 228 - "test_analytics: detect_contradictions_e2e()"
Cohesion: 0.29
Nodes (11): Complete, detect_contradictions_e2e(), EmbedFn, TrustFn, ``docs`` = list of ``{"doc_id","source","text"}``. Returns NLI-confirmed     con, _embed(), _extract(), End-to-end contradiction pipeline (TDD): extract → cluster → structural → NLI-re (+3 more)

### Community 229 - "ARCHITECTURE.md: Production docker-compose"
Cohesion: 0.13
Nodes (16): Dedicated kb-ingest-merge queue, R1 two-tier model architecture, Dev docker-compose stack, LiteLLM config (OpenAI upstream), LiteLLM scale config (Ollama fleet), LiteLLM vLLM config, LiteLLM proxy, Congestion collapse (root cause of hangs) (+8 more)

### Community 230 - "superpowers: GraphRetriever.for_store (store-only, no PropertyGraphIndex)"
Cohesion: 0.20
Nodes (11): Nebula read-slice (Phase 2) implementation plan, GraphRetriever.for_store (store-only, no PropertyGraphIndex), NebulaGraphStore.subgraph mapper, nGQL GET SUBGRAPH bounded walk, nGQL LOOKUP find-by-name (afind_entities_by_name nebula branch), generic RELATED edge + rel_type property, afind_entities_by_name (fulltext partial-name recall), Graph-search entity recall design (+3 more)

### Community 231 - "api: stats.py"
Cohesion: 0.39
Nodes (6): build_burst_cypher(), E3 — shared burst computation over event created_at (single source for the trend, Parameterized burst query grouped by (participant entity, event_type).      rece, test_burst_cypher_core_shape(), test_burst_cypher_counts_distinct_events(), test_burst_cypher_watched_only_adds_clause()

### Community 232 - "test_graph: test_retriever_fulltext.py"
Cohesion: 0.08
Nodes (28): build_fulltext_query(), _dedupe_entities(), _dedupe_relations(), _find_by_name_ngql(), GraphRetriever, _parse_triplet_chains(), PropertyGraphIndex, Graph-search wrapper for the agent loop.  Returns a ``RoundGraphData`` with stru (+20 more)

### Community 234 - "eval: bench_flat_vs_hnsw()"
Cohesion: 0.15
Nodes (13): 2. Поиск, 3. Якоря знаний, Drift: мягкий fallback 🆕, Быстрый справочник по конфигу (env-переменные новых возможностей), Возможности, Глубокий разбор новых возможностей, Двойной walk-seed 🆕, Иерархические сообщества + динамический выбор 🆕 (+5 more)

### Community 235 - "CONCEPTS.md: LLMPool concurrency gating"
Cohesion: 0.11
Nodes (28): ChannelsFn, make_search_full(), KB search adapter for the bot: POST /api/v1/search/{mode} and return the synthes, Like ``make_search`` but returns the WHOLE payload, not just the text.      ``ma, make_channels(), make_timeline(), Ingest-volume adapters for `/channels` and `/volume`.  Both hit routes that alre, Per-channel ingest totals → the `rows` list. (+20 more)

### Community 236 - "runbook: DocumentIngestWorkflow (parent)"
Cohesion: 0.33
Nodes (6): RabbitMQ / taskiq broker, Input document classifier (classify_document), DocumentIngestWorkflow (parent), GraphBuildWorkflow (child), vector_only fallback, Manual reingest + low-priority RabbitMQ lane

### Community 237 - "adr: Neo4j property graph store"
Cohesion: 0.47
Nodes (6): ADR-0007: Entity Resolution = candidate-gen + LLM-judge + cache + union-find, ADR-0008: Optional native-vector kNN ER over 5000-row window, Neo4j property graph store, Entity Resolution 12-step pipeline, Native vector kNN ER (er_vec), Batch graph consolidation (reresolve_graph)

### Community 238 - "ANALYTICS-GUIDE.md: Community detection / Leiden"
Cohesion: 0.24
Nodes (10): Edge et al. (2024) GraphRAG (arXiv:2404.16130), Fortunato & Barthelemy (2007) Resolution Limit, Leiden & modularity, Resolution limit (modularity defect), Traag et al. (2019) From Louvain to Leiden, Community reports (map-reduce summarization), Community detection / Leiden, Hierarchical communities + dynamic selection (+2 more)

### Community 239 - "CONCEPTS.md: Local search (vector + graph"
Cohesion: 0.20
Nodes (10): Auto mode / query routing, Coverage check (bounded refinement round), DRIFT search (local + global), Global search (community map-reduce), Local search (vector + graph expansion), Plan-execute orchestrator, Reranking (bge cross-encoder), Drift soft fallback (+2 more)

### Community 240 - "superpowers: WikiSweepWorkflow (dirty-entity sweep)"
Cohesion: 0.20
Nodes (10): community_report_vec Milvus collection, MilvusCommunityReportVectorStore, AsyncMediaWiki client (Action API), Continuous wiki article editor design, subgraph_hash dirty tracking (skip unchanged), WikiSweepWorkflow (dirty-entity sweep), dynamic community selection (v1 semantic kNN + v2 hierarchy descent), community_report_vec native Neo4j index (+2 more)

### Community 241 - "test_retrieval: find_entity_by_name()"
Cohesion: 0.14
Nodes (15): build_indicators_query(), build_sources_query(), Any, AsyncConnection, Postgres access for the statistics subsystem.  The single query layer for `stat_, The registry itself, optionally scoped to one source., JSON-safe projection: dates to ISO, NUMERIC to float, UUID to str., Async wrapper over the two `stat_*` tables. (+7 more)

### Community 242 - "test_api: test_documents.py"
Cohesion: 0.42
Nodes (9): _get(), _key(), ASGI tests for GET /api/v1/documents/{doc_id}., _row(), _storage(), test_download_requires_api_key(), test_download_sanitizes_filename_header(), test_download_streams_original() (+1 more)

### Community 243 - "test_graph: _FakeWriteback"
Cohesion: 0.36
Nodes (7): doc_id list → relative download links (preserves order)., to_document_refs(), _key(), The search response carries documents[] (links) built from outcome.documents., _stub_client(), test_local_response_has_documents(), test_to_document_refs_builds_urls()

### Community 244 - "superpowers: LLMPool (per-process role-keyed pool)"
Cohesion: 0.25
Nodes (9): BoundedLLM gating wrapper (ordered semaphores), LLM pool consolidation design, hierarchical tier+lane sizing (over-subscription + judge_floor), LLMPool (per-process role-keyed pool), render_bot_section / splice_bot_section (anti-drift, grounded), K+N throttle migration design, IngestAdmission K (always-on max_inflight), K+N throttle model (single N semaphore + FIFO K admission) (+1 more)

### Community 245 - "superpowers: Community-detection offload from Neo4j —"
Cohesion: 0.22
Nodes (10): Community-detection offload from Neo4j — design, community_backend config selector (gds|leidenalg, default gds until parity benchmark), Edge-extractor — streams (s.name,t.name,weight) in batches (no GDS projection), leidenalg + python-igraph clusterer (hierarchical Leiden in worker RAM), Hierarchical community-summaries — leaf-level context fix, ADR-0009 (hierarchical-leiden) + ADR-0010 (dynamic-community-selection), descent community-selection mode (only mode that walks the hierarchy via PARENT_OF), Persist IN_COMMUNITY member-edges at all levels (_MERGE_SUBCOMMUNITY_CYPHER gains member block) (+2 more)

### Community 246 - "NebulaEventsLlmGraphOps"
Cohesion: 0.08
Nodes (25): 10. Troubleshooting, 11. Cross-references, 1. Three-server overview, 2. Запуск, 3.1 Контракт, 3.2 Что происходит под капотом, 3.3 Cancellation, 3.4 Concurrency защита (+17 more)

### Community 247 - "retrieval: GraphRetrieverProtocol"
Cohesion: 0.21
Nodes (17): Provenance, analyze(), `POST /api/v1/analyze` — plan → compute → synthesize analytical Q&A., Map AnalyzeRequest → AnalyzeParams., _to_params(), AnalyzeRequest, AnalyzeResponse, BaseModel (+9 more)

### Community 248 - "test_observability: test_litellm_models.py"
Cohesion: 0.31
Nodes (8): _proxy_returns(), Unit tests for the LiteLLM model-validator that runs at API + worker startup.  T, Build a context manager that patches httpx.Client.get to return     a fake LiteL, Connectivity failure → empty available list → no validation;     only an at-star, test_all_models_registered_logs_info(), test_missing_model_raises_in_strict_mode(), test_missing_model_warns_in_non_strict_mode(), test_proxy_unreachable_does_not_block_boot()

### Community 251 - "nebula_bootstrap.py: _connect()"
Cohesion: 0.08
Nodes (39): bench_cost_curve(), bench_milvus_vs_native(), bench_native_vs_milvus(), bench_native_vs_window(), _driver(), _load(), _milvus_client(), ndarray (+31 more)

### Community 252 - "ARCHITECTURE.md: Neo4j property graph store"
Cohesion: 0.29
Nodes (8): 42-primitive Cypher catalog, Provenance-is-ground-truth rule, Graph analytics (/api/v1/analyze), Neo4j property graph store, Wikibase / MediaWiki anchor, Neo4j property graph & indexes, wipe_db reset procedure, Graph analytics layer (Waves 0-3)

### Community 253 - "superpowers: EntityVectorStore seam (knn/upsert)"
Cohesion: 0.32
Nodes (8): er_vector_backend dispatch (native/milvus, forced under nebula), ER-vec → Milvus (Phase 3) implementation plan, entity_er_vec Milvus collection, EntityVectorStore seam (knn/upsert), MilvusEntityVectorStore, Neo4jEntityVectorStore (native index wrapper), CommunityReportVectorStore seam, report_vec → Milvus (semantic slice) implementation plan

### Community 254 - "backfill_er_vector.py: configure_logging()"
Cohesion: 0.16
Nodes (24): _api_key_header(), _body(), _post(), _post_raw(), ASGI tests for `POST /api/v1/statistics/load`.  `StatsRepository` is patched so, A stored NaN poisons everything downstream: `align` yields     `divergence: NaN`, `dims` is `dict[str, Any]` — pydantic never looks inside it.  A     NaN/Infinity, `IndicatorIn.dims_schema` is the same shape (`dict[str, Any]`) and     the same (+16 more)

### Community 255 - "ingest_medical.py"
Cohesion: 0.16
Nodes (19): cache_with_pool(), _GraphOpsSpy, The ER verdict cache, once it lives in Postgres rather than the graph.  No live, One round trip per batch, not one per key — ER passes hundreds of     candidate, A key the cache has never seen must be ABSENT, not `False`.     `False` means "j, Without `row_factory=dict_row` live psycopg3 returns tuples and the     mapping, The cache goes to Postgres; `merge_loser_into_canonical` is a real     graph ope, The cache is OPTIONAL and FAIL-SAFE, and moving its storage must     not narrow (+11 more)

### Community 256 - "test_scripts: _pages_to_delete()"
Cohesion: 0.10
Nodes (24): BinaryIO, MinioSettings, S3-compatible upload storage.      User uploads land in `bucket` synchronously f, MilvusClient, MinioStorage, Path, Yield the object's bytes in chunks, releasing the HTTP         connection in a f, Split an ``s3://bucket/key`` URI into ``(bucket, key)``.          Raises ``Value (+16 more)

### Community 257 - "KbGraphStore"
Cohesion: 0.32
Nodes (4): KbGraphStore, Any, Protocol, The graph-store surface the app actually uses.  A narrow subset of LlamaIndex's

### Community 258 - "test_analytics: test_domain.py"
Cohesion: 0.25
Nodes (3): test_communication_stats_counts_pairs(), test_issue_resolution_stats_computes_rate(), test_issue_resolution_stats_empty_no_div_by_zero()

### Community 259 - "test_graph: test_community_vector_store.py"
Cohesion: 0.15
Nodes (14): extract_kg(), `extract_kg` — LightRAG-style KG extraction (heaviest stage).  One LLM call per, Pull out small JSON-serialisable samples of what the extractor     emitted.  The, _summarise_kg(), EntitySample, Compact entity representation suitable for inclusion in     activity results (ke, RelationSample, extract_kg must obtain its LLM from the shared pool, not a raw     ungated build (+6 more)

### Community 260 - "runbook: Per-role/tier LLM selection"
Cohesion: 0.29
Nodes (7): ADR-0004: Per-process LLMPool owns LLM concurrency, ADR-0013: Multi-model role/tier selection + snapshot-at-submit, LiteLLM proxy (LLM/embed gateway), ingest_metrics (Postgres per-run timings), Prometheus + Grafana ingest analytics, LLMPool (per-process concurrency owner), Per-role/tier LLM selection

### Community 261 - "presentation: 5-step ingestion pipeline"
Cohesion: 0.29
Nodes (7): ADR-0005: Deterministic identifier canonicalization before LLM extraction, Cross-chunk merge, IdentifierCanonicalization ingest step, 5-step ingestion pipeline, KG extraction fix: SchemaLLMPathExtractor -> SimpleLLMPathExtractor, LightRAG-style KG extraction, Russian-output guarantee

### Community 262 - "runbook: Milvus chunk vector index"
Cohesion: 0.33
Nodes (7): ADR-0006: Milvus HNSW as default chunk index, Milvus chunk vector index, doc_id backfill for legacy Milvus chunks, Hermes Agent integration, atomic_tools.py (pure retrieval functions), BoundedLLM GPU semaphore, MCP-2 atomic tools server

### Community 263 - "Runbook index"
Cohesion: 0.24
Nodes (12): ADR-0011: Plan-execute SearchOrchestratorWorkflow, ADR-0014: Source download via stable API endpoint, Bruno API collection, Bruno sample upload document (RU medical PII fixture), Graph analytics layer (plan->compute->synthesize, 42 primitives), Analytics materialization (AnalyticsMaterializeWorkflow), Monitoring Arc-2, MCP-1 search server (5 tools via Temporal) (+4 more)

### Community 264 - "superpowers: GET /api/v1/documents/{doc_id} download endpoint"
Cohesion: 0.29
Nodes (7): Source document download design, DocumentRef search-response document links, GET /api/v1/documents/{doc_id} download endpoint, MinioStorage stream_object / stat_object, Wiki article quality + source-download links design, relation ranking+cap (WIKI_MAX_RELATIONS) + citation dedup, Источники source-download section (deterministic)

### Community 265 - "superpowers: Hermes ↔ kb-llamaindex RAG integration"
Cohesion: 0.29
Nodes (7): Hermes ↔ kb-llamaindex RAG integration design, Hermes Agent (persistent MCP-client consumer), knowledge-base SKILL.md (tool-selection + templates), kb MCP-2 tools_server (6 atomic tools, SSE), client-managed bounded history (stateless), contextualize_query activity (follow-up → standalone), Conversation history (multi-turn search) design

### Community 266 - "build_property_graph_index()"
Cohesion: 0.08
Nodes (22): Global Constraints, Notes for the implementer, Task 1: The store, Task 2: Policy — admission, quota, concurrency, Task 3: API clients for the new commands, Task 4: Commands, Task 5: Wiring, config, container, Telegram Bot — Commands, Users, History Implementation Plan (+14 more)

### Community 267 - "check_ingestion.py"
Cohesion: 0.48
Nodes (6): check_events(), check_milvus(), check_neo4j(), check_postgres(), main(), Diagnostic — show what landed in each backend after ingestion.  Pings every stor

### Community 268 - "test_config: WikiSettings"
Cohesion: 0.29
Nodes (6): Hybrid (BM25 + dense) retrieval over corpus chunks., vector_search(), _StubRetriever, test_dispatch_routes_to_vector_search(), test_vector_search_returns_sources_and_observation(), test_vector_search_top_k_truncates_observation_not_sources()

### Community 269 - "test_graph: schema.py"
Cohesion: 0.06
Nodes (52): Minio, main(), Remove orphaned ``kb-staging/{workflow_run_id}/`` prefixes from MinIO.  Workflow, Dishka DI providers.  Two containers:   * **API** — long-lived: PG client + shar, build_entity_vector_store(), Neo4jEntityVectorStore, Any, Dispatch: nebula (or the opt-in flag) -> Milvus; else Neo4j native. (+44 more)

### Community 270 - "ingestion: _extract_addresses()"
Cohesion: 0.10
Nodes (20): 1. Пред-загрузка онлайн (наполнение кеша), 2. Скопируйте кеш на air-gapped-хост, затем гоняйте оффлайн, Deprecated-алиас `LITELLM_LLM_MODEL`, LLMPool — гейтинг конкурентности, Smoke-верификация, Snapshot мультимодели в момент /ingest, Альтернатива: плоский `--local-dir` (без blob'ов/симлинков), Базлайн для сравнительного eval (R9) (+12 more)

### Community 271 - "retrieval: pick_priority()"
Cohesion: 0.47
Nodes (6): Telegram bot overlay, LiteLLM overlay, OpenClaw agent gateway overlay, Production docker-compose, Scale-out worker override, Telegram ingest harness overlay

### Community 273 - "test_api: test_graph_admin.py"
Cohesion: 0.52
Nodes (6): _key(), _post(), ASGI tests for the /admin/graph/* analysis endpoints (Track 7b)., test_graph_stats_endpoint_returns_analysis(), test_graph_stats_requires_api_key(), test_pagerank_endpoint_wraps_top()

### Community 274 - "test_mcp: test_hermes_skill.py"
Cohesion: 0.43
Nodes (5): Validates the Hermes knowledge-base skill: frontmatter is present and the body r, _split_frontmatter(), test_skill_body_references_every_tool(), test_skill_covers_the_four_pillars(), test_skill_frontmatter_has_name_and_description()

### Community 275 - "test_mcp: test_search_server.py"
Cohesion: 0.29
Nodes (3): Smoke tests for the MCP-1 search server.  We don't talk to a real Temporal clust, assert_api_key_env_set raises SystemExit when require=true and     api_keys list, test_auth_gate_blocks_when_keys_missing()

### Community 276 - "test_workflow: test_completion_no_walltime_cap.py"
Cohesion: 0.23
Nodes (22): Ctx, _gate_checks(), handle_approve(), handle_ask(), handle_channels(), handle_deny(), handle_find(), handle_history() (+14 more)

### Community 277 - "knowledge-base Hermes skill (routes to kb-llamaindex"
Cohesion: 0.40
Nodes (6): Hermes MCP servers config example (SSE, 30-min timeout), kbsearch MCP server (:9001/sse; kb_search/global/drift/auto), kbtools MCP server (:9002/sse; vector/graph_search/graph_walk/find_* tools), knowledge-base Hermes skill (routes to kb-llamaindex retrieval tools), Entity dossier answer template (Russian), Russian sample news text fixture (entities: ООО Ромашка, phones, INN-style)

### Community 278 - "tg_ingest.py: load_state()"
Cohesion: 0.06
Nodes (58): dialog_in_folders(), dialog_slug(), _filter_title(), load_state(), _message_to_doc(), post_ingest(), Any, Path (+50 more)

### Community 280 - "test_api: test_admin_wiki.py"
Cohesion: 0.33
Nodes (5): ASGI tests for POST /admin/wiki/rebuild.  The WIKI_ENABLED default is False, so, WIKI_ENABLED defaults False → route returns disabled without infra., `?all=true` (when enabled) marks every entity dirty via     build_wiki_graph_ops, test_wiki_rebuild_all_routes_mark_all_dirty_through_seam(), test_wiki_rebuild_returns_disabled_when_off()

### Community 281 - "test_api: test_monitor_route.py"
Cohesion: 0.33
Nodes (5): ASGI tests for POST /admin/monitor/sweep and /admin/monitor/watch.  The MONITOR_, MONITOR_ENABLED defaults False → returns disabled without touching Temporal., POST /admin/monitor/watch patches mark_watched and build_neo4j_graph_store., test_monitor_sweep_returns_disabled_when_off(), test_monitor_watch_calls_mark_watched()

### Community 282 - "test_api: test_route_skeletons.py"
Cohesion: 0.33
Nodes (5): Route skeleton tests — confirm the search endpoints are registered.  R7b cutover, The plan-execute / GraphRAG endpoints are wired; without an API     key (or with, R7b: the legacy ReAct + judge-based routes are gone → 404., test_legacy_search_routes_removed(), test_new_search_routes_registered()

### Community 283 - "test_scripts: test_setup_db.py"
Cohesion: 0.33
Nodes (3): Stage-1 unit tests for ``scripts/setup_db.py``.  Live-DB integration is verified, Idempotency contract: re-running the script against an existing     DB must not, test_documents_ddl_uses_create_if_not_exists()

### Community 284 - "CONCEPTS.md: ANN vector search"
Cohesion: 0.50
Nodes (5): Milvus vector store, ANN vector search, FLAT vs HNSW (Milvus index), RAG (Retrieval-Augmented Generation), Text embeddings

### Community 285 - "INGEST.md: GraphBuildWorkflow (child)"
Cohesion: 0.16
Nodes (13): _NebulaRecStore, _RaisingStore, _RecStore, test_dispatch_nebula(), test_dispatch_neo4j_default(), test_nebula_entity_new_connections_name_anchored(), test_nebula_new_edges_respects_top_n(), test_nebula_new_edges_scans_and_filters_by_created_at() (+5 more)

### Community 287 - "graph: AlertStore"
Cohesion: 0.15
Nodes (15): AnswerFn, Classifier, classify_intent(), Route a question to the analytical layer (graph aggregation via /analyze) or the, ANALYTICAL for aggregation/statistics/contradiction questions, else SEARCH., make_router(), Route each query to the analytical layer or the retrieval layer by intent.  ``ma, Build ``answer(query)`` that dispatches to ``analyze`` for analytical     intent (+7 more)

### Community 288 - "graph: NoOpKGExtractor"
Cohesion: 0.31
Nodes (15): _fake_ctx(), _outcome(), Date-interval params on the MCP-1 search tools (mirrors the REST ``/search/local, No date params supplied → all four epoch fields stay None (prior     behaviour,, _stub_client(), test_kb_auto_search_invalid_date_returns_error_without_raising(), test_kb_auto_search_omitted_dates_keep_none_epochs(), test_kb_auto_search_threads_bounds_to_local_leg_only() (+7 more)

### Community 289 - "test_ingestion: build_custom_kg_payload()"
Cohesion: 0.25
Nodes (17): _base_class_qids(), _neo4j_store(), _property_pids(), Any, Unit tests for `src.storage.wikibase.push_entities`.  The :class:`AsyncWikibase`, PhoneNumber entity related to a Person → Person Item gets an     external-id cla, Owner-owner relation with unseen label → ``create_property``     fires once; the, PhoneNumber entity with no relation → no Item created for it,     and ``external (+9 more)

### Community 290 - "retrieval: _injected_params()"
Cohesion: 0.14
Nodes (18): Any, Sync execution; returns raw rows. Mirrors src/graph/analysis.py::_run_query., Run ``cypher`` off the event loop; ``[]`` on no-store or a transient error., _run_query(), run_rows(), test_run_rows_failsoft_on_none_store(), test_run_rows_passes_cypher_and_params(), Exception (+10 more)

### Community 292 - "test_analytics: test_rollups.py"
Cohesion: 0.05
Nodes (44): ContextualizeParams, ContextualizeResult, GlobalSearchParams, Input to the ``contextualize_query`` activity., Standalone, self-contained rewrite of ``query`` (== original on no-op/failure)., Final workflow output — mapped onto SearchResponse by route handler., Workflow input for ``GlobalSearchWorkflow`` — what the     ``/search/global`` ro, SearchOutcome (+36 more)

### Community 293 - "test_graph: _Boom"
Cohesion: 0.15
Nodes (14): _first_non_finite_float(), IndicatorIn, load_statistics(), LoadRequest, LoadResponse, _non_finite_anywhere_is_not_a_value(), ObservationIn, Any (+6 more)

### Community 294 - "test_workflow: test_search_pooled_llm.py"
Cohesion: 0.18
Nodes (14): AbstractRobustConnection, Ingest message priority levels (RabbitMQ backend).  A single work queue declared, close_publisher(), _get_connection(), publish_ingest(), RabbitMQ producer for the ingest queue (Track B).  ``/ingest`` → :func:`submit_d, Return the per-process robust connection, opening it lazily., Publish one document to a configured ingest queue (``queue``,     default the fi (+6 more)

### Community 295 - "CAPACITY_TUNING.md: LLM_POOL_N throttle"
Cohesion: 0.13
Nodes (23): _main(), Idempotently create/update the Temporal Schedule that runs MonitorSweepWorkflow, _main(), Idempotently create/update the Temporal Schedule that runs WikiSweepWorkflow eve, _outcome_to_response(), `POST /api/v1/search/local` — plan-execute-synthesize search (R2).  Submits ``Se, Map the workflow's ``SearchOutcome`` onto the shared response shape     (identic, Run ``GlobalSearchWorkflow`` — map-reduce over the R6 community     summaries fo (+15 more)

### Community 296 - "superpowers: Graph-scale follow-ups (items 8/13/12) plan"
Cohesion: 0.50
Nodes (4): Community.level + Chunk.doc_id indexes, Drift graceful fallback to local answer, Dual walk-seed (graph_search + fulltext), Graph-scale follow-ups (items 8/13/12) plan

### Community 297 - "superpowers: GraphScope community backend (distributed single-level"
Cohesion: 0.50
Nodes (4): GraphScope community backend (Phase 4) implementation plan, GraphScope community backend (distributed single-level Leiden), _run_graphscope_community adapter (lazy, manual-gate), single_level_rows_graphscope mapping

### Community 298 - "superpowers: Analytics query fixes implementation plan"
Cohesion: 0.50
Nodes (4): coerce_entity_type (bogus planner type → None), Analytics query fixes implementation plan, is_meaningful_entity quality gate (drop identifiers + degenerate names), trend-fallback keyword broadening ('упомин')

### Community 299 - "superpowers: scripts/make_env.py builder"
Cohesion: 0.50
Nodes (4): cross-field validation (MILVUS_DIM, LLM_POOL sizing, Temporal caps), Interactive .env builder design, scripts/make_env.py builder, parse_example structure-preserving model (Line/KV)

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

### Community 306 - "ARCHITECTURE.md: Postgres (documents, ingest_metrics)"
Cohesion: 0.67
Nodes (3): Postgres (documents, ingest_metrics), init service (setup_db), Multimodel snapshot at /ingest

### Community 307 - "superpowers: Wiki article quality + source-download"
Cohesion: 0.67
Nodes (3): Wiki article quality + source-download links plan, Relation rank/cap + per-doc citation dedup, Deterministic Источники source-download section

### Community 308 - "superpowers: Marp two-version deck (A tech"
Cohesion: 0.67
Nodes (3): kb-llamaindex conference deck design, Marp two-version deck (A tech / D internal), Three-endpoints narrative (/search, /agent, /selfrag)

### Community 309 - "superpowers: TG → ingest test harness"
Cohesion: 1.00
Nodes (3): TG → ingest test harness — design, RabbitMQ in dev compose (default service; validates INGEST_QUEUE_BACKEND=rabbitmq end-to-end), scripts/tg_ingest.py (Telethon backfill → POST /api/v1/ingest per message)

### Community 310 - "graph: read_alerts()"
Cohesion: 0.18
Nodes (16): description, Field, _dims_cuts(), _parse_date(), _points(), Any, date, MCP-3: exact-statistics tools.  Returns data, never prose.  No LLM call exists a (+8 more)

### Community 313 - "test_workflow: test_community_build_hardening.py"
Cohesion: 0.40
Nodes (5): MinIO (claim-check + uploads), Claim-check pattern (MinIO staging), GraphBuildWorkflow (child), Graph half (extract→merge/ER→Neo4j), vector_only degradation

### Community 326 - "test_workflow: _stub_activity_ctx()"
Cohesion: 0.16
Nodes (17): main(), main(), Probe KG extraction on real medical chunks.  Splits the medical corpus into chun, Deep diagnostic: try every layer of SchemaLLMPathExtractor.  Steps:   1. Plain `, build_extraction_llm(), build_judge_llm(), build_llm(), build_search_llm() (+9 more)

### Community 365 - "ERGraphOps seam (ensure_verdict_schema/load_verdicts/store_verdicts/merge_loser_into_canonical)"
Cohesion: 0.24
Nodes (10): Nebula analytics — connections primitive (nGQL) + AnalyticsGraphOps pattern, AnalyticsGraphOps seam (Protocol; Neo4j-verbatim + Nebula-nGQL impls; build_analytics_graph_ops), connections.py primitives via nGQL (entity_dossier, common_connections, connection_path; cooccurrence→[] Chunk-dependent), Nebula analytics Tier-A port (nGQL) — remaining primitive families, Per-family <Family>GraphOps sibling seams (aggregations/quality/domain/events/rollups/signals/communities), Nebula entity-resolution graph ops — verdict cache + edge-redirect merge + canonical stamp, ERGraphOps seam (ensure_verdict_schema/load_verdicts/store_verdicts/merge_loser_into_canonical), ERVerdict TAG + verdict cache (er_key index; blake2b verdict_vid upsert) (+2 more)

### Community 366 - "test_stats_routes.py"
Cohesion: 0.20
Nodes (14): RewriteFn, is_empty_answer(), Shared answer helpers: detect an empty/no-result answer so neither the search-fa, True for a blank answer or a known empty-synthesis marker., answer_question(), SearchFn, Produce the bot's reply for one incoming message.      Denied users get ``DENIED, _passthrough_rewrite() (+6 more)

### Community 368 - "test_entity_vector_store.py"
Cohesion: 0.16
Nodes (17): _maybe_summarize_descriptions(), Any, Return one consolidated description for `descriptions`.      Path A — concat: wh, Remove `<think>...</think>` / `<thinking>...</thinking>` blocks.      Qwen3 (and, strip_thinking(), Tests for `src/retrieval/_common.py`., qwen3 sometimes emits an open <think> when generation truncates.     Everything, Tags that aren't <think>/<thinking> stay put. (+9 more)

### Community 369 - "Automatic event detection — design"
Cohesion: 0.36
Nodes (5): _FakeGraphStore, EntityVectorStore: Neo4j impl query/mapping + factory dispatch (DB-free)., test_factory_dispatches_on_backend(), test_neo4j_knn_maps_rows_with_embedding_and_label(), test_neo4j_upsert_is_noop()

### Community 370 - "Nebula community-BUILD (nGQL) — full BUILD stage, backend-dispatched"
Cohesion: 0.14
Nodes (24): bench_dedup_recall(), _candidate_norm_pairs(), Run _candidate_pairs and return the surfaced pairs as norm-sets., For each ``knn_k``, fraction of planted duplicate pairs surfaced     as candidat, bench_flat_vs_hnsw(), _build_and_query(), _client(), ndarray (+16 more)

### Community 371 - "LiteLLM proxy Redis response cache"
Cohesion: 0.17
Nodes (14): _auth_required(), build_sse_auth(), is_valid_key(), Shared helpers for the two MCP servers (auth + DI bootstrap)., True unless KB_MCP_REQUIRE_AUTH is explicitly disabled., Match against the configured API key list., Build a FastMCP auth provider for HTTP/SSE transports.      Returns a ``StaticTo, StaticTokenVerifier (+6 more)

### Community 372 - "NebulaGraph migration plan (Phases 0-4; strangler-fig, backend-dispatched)"
Cohesion: 0.25
Nodes (6): _NameRetriever, Stands in for GraphRetriever's name lookup., `GraphMemoryExceeded` reached callers as `{"entities": []}` — which     reads as, A genuine empty result carries no error key, so a caller can tell     "nothing m, test_find_entity_by_name_omits_error_when_it_ran(), test_find_entity_by_name_passes_the_failure_through()

### Community 374 - "AnalyticsGraphOps seam (Protocol; Neo4j-verbatim + Nebula-nGQL impls; build_analytics_graph_ops)"
Cohesion: 0.11
Nodes (17): 1. Boundary, 2. Schema (`scripts/setup_db.py`), 3. Storage layer (`src/storage/stats.py`), 4. Alignment math (`src/stats/align.py`), 5. MCP-3 tools (`src/mcp/stats_server.py`), 6. Required change on the semantic side (MCP-2), 7. Write path (`src/api/routes/stats_data.py`), 8. Config (+9 more)

### Community 375 - "_timeline"
Cohesion: 0.13
Nodes (15): 1. Инжест, Backfill `doc_id` на legacy-чанки 🆕, Entity Resolution (ER) 🆕(native-vector), KG-экстракция LightRAG, Аналитика по графу (analytical-query layer, Waves 0–3) 🆕, Взвешенные связи и теги 🆕, Детерминированная канонизация идентификаторов, Классификатор входных документов 🆕 (+7 more)

### Community 376 - "alerts.py"
Cohesion: 0.14
Nodes (14): main(), Idempotent DB initialisation.  Stage 1 scope:   * Postgres — create ``documents`, `'a', 'b', 'c'` for a SQL `IN (...)` clause — sorted so the     generated DDL te, Register the three custom Search Attributes used by the     analytics layer (Sta, Enforce the configured closed-workflow retention on the namespace.      Bounds P, Verify Milvus reachable; collection lifecycle owned by     ``MilvusVectorStore``, Ensure the user-upload bucket exists.  Same MinIO instance the     Milvus backen, setup_milvus() (+6 more)

### Community 377 - "test_config_wave2.py"
Cohesion: 0.24
Nodes (14): _load_base_classes(), _load_properties(), push_wikibase(), _fake_merged(), Tests for the push_wikibase activity.  Three behaviours:   * cache disabled -> s, If push_entities returns counters where created+updated == 0     yet we DID rece, An ingest with no entities to push (empty merged blob) IS a     valid no-op — st, push_entities makes one sequential Wikibase REST round-trip per     owner/relati (+6 more)

### Community 379 - "AnalyticsGraphOps seam (Protocol; Neo4j-verbatim + Nebula-nGQL impls; build_analytics_graph_ops)"
Cohesion: 0.16
Nodes (14): ERConfig, _llm_judge_pairs(), For each input pair, return True when LLM judges SAME, else     False (DIFFERENT, Tuning knobs for entity resolution., _mk_item(), EntityNode, The vectorised cosine path is an optimisation — it must yield the     EXACT same, When a vector_store is passed with native kNN on, ER pulls candidates     from s (+6 more)

### Community 380 - "find_entity_by_name tool"
Cohesion: 0.18
Nodes (6): _FakeClient, _I, _S, _store(), test_knn_filters_level_and_maps(), test_upsert_rows()

### Community 382 - "Wiki-editor runbook"
Cohesion: 0.14
Nodes (13): 1. Что это, 2. Включение, 3. Поток данных, 4. Конфигурация (`WIKI_*`), 5.1 `WIKI_SITE_GLOBAL_ID` должен совпадать с реальным site id, 5.2 `WIKIBASE_BOT_PASSWORD` должен быть ≥ 8 символов, 5.3 Без `wikibase_qid` sitelink не создаётся, но статья пишется, 5.4 Ссылки на скачивание исходников требуют аутентификации (+5 more)

### Community 383 - "test_search_deps_lock.py"
Cohesion: 0.08
Nodes (32): SchemaLLMPathExtractor, build_property_graph_index(), BaseEmbedding, LLM, PropertyGraphIndex, PropertyGraphStore, Compose a PropertyGraphIndex from store + embed + extractor.      Pass ``nodes``, _build_chunk_repo_once() (+24 more)

### Community 384 - "Capacity Tuning Under Load"
Cohesion: 0.15
Nodes (12): 1. The one mental model that matters, 2. The K + N model, 2a. The knobs, 2b. Temporal — isolation, not throttle (`TEMPORAL_*`, `src/config.py:207`), 2c. Proxy client (`LITELLM_*`, `src/config.py:137`), 3. Invariants you must not break, 4. Right-sizing `LLM_POOL_N` (the procedure), 5. Recommended load-side changes (deferred from the fix) (+4 more)

### Community 385 - "PostgresERVerdictCache"
Cohesion: 0.18
Nodes (12): mirror_entities(), node_to_row(), Any, Fail-soft mirror of graph entities into the Postgres `entity` table.  Called fro, Map a write-path node (as ``upsert_nodes`` iterates it: ``.name``,     ``.label`, Upsert entity rows into Postgres. Fail-soft, fail-FAST.      ``timeout=1`` decou, get_pg_sync_pool(), ConnectionPool (+4 more)

### Community 386 - "Конвейер инжеста"
Cohesion: 0.17
Nodes (12): Claim-check staging (MinIO), Две половины + деградация, Допуск документов (admission control), Канонизация идентификаторов (детерминированная, до LLM), Классификатор входных документов (opt-in), Конвейер инжеста, Кратко, Очереди, воркеры, конкурентность LLM (+4 more)

### Community 387 - "Runbook по аналитике ingest"
Cohesion: 0.17
Nodes (12): 10. Дальнейшие улучшения, 1. Обзор, 2. Поднятие (bring-up), 3. Воркер — Prometheus exporter, 4. Тегирование версий (version tagging), 5. Smoke (end-to-end проверка), 6. Дашборды, 6a. Колонка model по активностям (multimodel-плагин) (+4 more)

### Community 388 - "Hermes ↔ RAG Integration plan"
Cohesion: 0.18
Nodes (14): EntitiesFn, Cut a reply into sendable pieces. Never returns an empty list —     Telegram rej, split_for_telegram(), make_rewrite(), Build an async ``rewrite(history, question) -> standalone_query`` backed     by, _api_key(), build_ctx(), main() (+6 more)

### Community 389 - "test_community_build_hardening.py"
Cohesion: 0.06
Nodes (45): messages_stats(), MessagesStatsResponse, BaseModel, date, FromDishka, Processed-message statistics over the `documents` table.  Two read-only endpoint, StatRow, timeline_stats() (+37 more)

### Community 390 - "Архитектура"
Cohesion: 0.20
Nodes (10): 1. Компоненты с высоты птичьего полёта, 2. Хранилища данных — что в каждом, 3. Путь приёма (ingest), 4. Путь поиска, 5. Надёжное исполнение и очереди, 6. Якорь знаний и редактор wiki, 7. Наблюдаемость, 8. Конфигурация (+2 more)

### Community 391 - "Часть 3 — Поиск и извлечение"
Cohesion: 0.20
Nodes (10): DRIFT-поиск — комбинация локального и глобального, Авторежим и маршрутизация запросов, Глобальный поиск — map-reduce по сообществам, Декомпозиция plan-execute и оркестратор, Контекстуализация истории диалога, Локальный поиск — векторное извлечение + расширение по графу, Основы RAG (Retrieval-Augmented Generation), Проверка покрытия — ограниченный цикл доработки (+2 more)

### Community 392 - "Runbook — допуск документов (admission control)"
Cohesion: 0.20
Nodes (9): Runbook — допуск документов (admission control), Включение, Выбор K, Диагностика, Зачем, Изменение K в рантайме, Как работает, Оговорка (+1 more)

### Community 393 - "Search — памятка по использованию и тюнингу"
Cohesion: 0.11
Nodes (17): 1. Поднять SSE-сервисы, 2. Зарегистрировать в Hermes, 3. Установить скилл, 4. Smoke-проверка, 5. Приёмочные сценарии, Hermes Agent integration runbook, Search — памятка по использованию и тюнингу, Wiki-rebuild (отдельный admin-триггер, не путать с communities) (+9 more)

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
Cohesion: 0.18
Nodes (14): bench_graph_write(), _driver(), _gen_workload(), _is_retryable(), _pct(), Exception, Neo4j concurrent-write contention benchmark (Track A baseline).  Reproduces the, Execute one writer's rounds in its own session.  Returns timing +     deadlock/r (+6 more)

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
Cohesion: 0.14
Nodes (3): _StubConn, _StubCursor, _StubPool

### Community 404 - "ER native vector kNN (снятие окна 5000)"
Cohesion: 0.33
Nodes (6): ER native vector kNN (снятие окна 5000), Включение — строгий порядок (backfill → флаг), Зачем, Откат, Проверка, Требования

### Community 405 - "Hermes Agent integration runbook"
Cohesion: 0.16
Nodes (8): _ctx_chat(), Later rewrites must see the real conversation., A broken turn would poison every later rewrite., _Session, test_a_failed_search_is_not_persisted(), test_followup_is_rewritten_before_searching(), test_rewrite_failure_costs_context_not_the_answer(), test_session_keeps_what_the_user_typed_not_the_rewrite()

### Community 406 - "Leiden community detection — diagnostics"
Cohesion: 0.33
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
Cohesion: 0.29
Nodes (7): Backend selection, Cleanup, Design, Migration, Seam, Storage, Synchronous access

### Community 412 - "PropertyGraphIndex"
Cohesion: 0.18
Nodes (11): Backlog, Векторный поиск по реестру показателей, ~~Индексные файлы Milvus раздуты в 22 раза~~ — закрыто 2026-08-17, Канал оценки не подаётся в сравнение, Латентные ограничения, Операционное, Очередь работ, ~~Перечитывает ли openclaw память без перезапуска~~ — закрыто (+3 more)

### Community 413 - "test_summarize_produces_report_and_persists"
Cohesion: 0.24
Nodes (12): Client, Producer-side dispatch for document admission (Track B).  ``/ingest`` calls :fun, Hand one document to the configured ingest backlog backend.      ``queue`` / ``p, Signal-with-start the admission singleton (the original path)., submit_document(), _submit_to_scheduler(), _params(), Producer dispatch by INGEST_QUEUE_BACKEND (Track B2).  No broker / no Temporal s (+4 more)

### Community 414 - "Таблица сущностей в Postgres для поиска"
Cohesion: 0.18
Nodes (11): Врезка во вход графа, Где сущности живут сейчас, Задача, Запись при ингесте, Побочные выгоды, Поиск, Проверка, Разовая заливка существующих (+3 more)

### Community 415 - "Continuous wiki editor (WikiSweepWorkflow)"
Cohesion: 0.67
Nodes (4): ADR-0012: Wikibase canonical anchor + continuous wiki editor, Wikibase canonical anchor, Continuous wiki editor (WikiSweepWorkflow), Wikibase populator (push_wikibase)

### Community 416 - "DetectCommunitiesParams"
Cohesion: 0.23
Nodes (13): check_thresholds(), `by_endpoint_and_doc[endpoint][doc_type]` → metrics dict.      Returns list of v, _hit_endpoint(), main(), _parse_args(), AsyncClient, Namespace, R9 CLI — run the 15 golden Q&A through the live search endpoints.  R7b cutover: (+5 more)

### Community 417 - "test_search_v2_routes.py"
Cohesion: 0.22
Nodes (6): _FakeClient, _FakeResp, Unit tests for MinioStorage stat/stream (stub minio client)., _storage(), test_stat_object_returns_name_size_type(), test_stream_object_yields_and_releases()

### Community 418 - "test_community_vector_store.py"
Cohesion: 0.18
Nodes (9): The `er_verdict` DDL, asserted as text like the other setup_db tests.  The table, The PRIMARY KEY *is* the lookup index — `er_key = ANY(...)` is the     only acce, `same` is the cached answer.  A NULL would be a third state that     neither `lo, Deliberate: nothing queries by age, and an index on `updated` would     only ser, `PostgresERVerdictCache.ensure_verdict_schema` carries its own copy     so a wor, test_ddl_matches_the_one_the_worker_creates_on_a_fresh_database(), test_key_is_the_primary_key(), test_no_secondary_index_is_created() (+1 more)

### Community 419 - "_gather_context"
Cohesion: 0.04
Nodes (90): CommunitySummaryRef, MapCommunitiesParams, MapCommunitiesResult, MapPartialParams, One community's stored summary — the unit the global MAP step     produces a par, Input to the ``map_communities`` activity — fetch community     summaries to map, Output of ``map_communities`` — the community summaries to map     over.  Empty, Input to ``map_community_partial`` — produce a partial answer for     ONE commun (+82 more)

### Community 420 - "Optional Synthesis Implementation Plan"
Cohesion: 0.20
Nodes (9): File Structure, Global Constraints, Notes for the implementer, Optional Synthesis Implementation Plan, Task 1: The flag, and the local short-circuit, Task 2: Global, drift and auto, Task 3: MCP-1 surface and docs, Verification (+1 more)

### Community 421 - "Global Constraints"
Cohesion: 0.25
Nodes (8): Global Constraints, Move the ER Verdict Cache to Postgres Implementation Plan, Notes for the implementer, Task 1: Postgres-backed verdict cache behind the existing seam, Task 2: The migration script, Task 3: Execute the migration and switch over, Task 4: Reclaim the graph, Verification

### Community 422 - "ingest.py"
Cohesion: 0.16
Nodes (15): download_document(), FromDishka, IngestEnqueuedResponse, job_status(), JobProgressResponse, BaseModel, FromDishka, UUID (+7 more)

### Community 423 - "backfill_er_vector.py"
Cohesion: 0.12
Nodes (23): _align_tool(), _fake_primitive(), _indicator_series(), The end-to-end composition MCP-2 `topic_trend` → MCP-3 `stat_align`.  No task ow, The MCP-3 side: what `stat_series` returns per row., `month` is `topic_trend`'s default, and its `"2026-03"` labels are     exactly w, `since`/`until` drop buckets; the rows that survive must still     carry the key, test_composition_survives_the_windowed_subset() (+15 more)

### Community 424 - "handle_agent"
Cohesion: 0.33
Nodes (9): handle_agent(), Free-form question to the openclaw agent, which chains MCP tools.     Same cost, _ctx_agent(), openclaw keeps its own per-session memory; the bot must hand it a     per-chat k, test_agent_costs_a_slot_and_quota_like_ask(), test_agent_fails_soft(), test_agent_needs_admission(), test_agent_passes_the_chat_session_for_followups() (+1 more)

### Community 425 - "Hermes Agent integration runbook"
Cohesion: 0.24
Nodes (3): Neo4jAggregationsGraphOps, Any, Runs the historical aggregations Cypher verbatim — zero behaviour     change fro

### Community 426 - "handle_entity"
Cohesion: 0.33
Nodes (9): handle_entity(), Entity lookup by name prefix. Cheap — no concurrency slot, no     quota: it is a, _ctx_with_entities(), It is an index read, not a search. Rationing it would ration the     only fast c, test_entity_costs_no_quota_and_no_slot(), test_entity_empty_query_asks_for_one(), test_entity_fails_soft(), test_entity_needs_admission() (+1 more)

### Community 427 - "build_search_query"
Cohesion: 0.25
Nodes (8): build_search_query(), Trigram search over the registry — the only searchable surface     the subsystem, `%` is psycopg's placeholder marker, so the trigram operator has     to be writt, The counter-proof: with one `%` psycopg reads `% %s` as a broken     placeholder, test_search_query_filters_by_source(), test_search_query_single_percent_would_not_survive_conversion(), test_search_query_uses_trigram_similarity_and_caps_limit(), test_trigram_operator_survives_psycopg_placeholder_expansion()

### Community 428 - "Rerank Orders the Output Implementation Plan"
Cohesion: 0.25
Nodes (7): Global Constraints, Notes for the implementer, Rerank Orders the Output Implementation Plan, Task 1: Return the ranked pool, cap only for synthesis, Task 2: Documentation, The problem in one paragraph, Verification

### Community 429 - "BACKLOG.md"
Cohesion: 0.29
Nodes (3): Entity Search Table Implementation Plan, Notes for the implementer, Verification

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
Cohesion: 0.29
Nodes (7): Global Constraints, Task 1: The table, Task 2: The search repository, Task 3: Fail-soft upsert grafted onto the entity write, Task 4: One-off backfill script, Task 5: Deploy — table, backfill, verify, Task 6: Join the table into the graph-search entry

### Community 434 - "WikiSettings"
Cohesion: 0.38
Nodes (5): Continuous wiki-article editor (Project A). Generates per-entity     MediaWiki p, WikiSettings, test_wiki_settings_defaults(), test_wiki_settings_env_override(), test_wiki_settings_new_fields_defaults()

### Community 435 - "Any"
Cohesion: 0.33
Nodes (6): `graph_stats` выдаёт отказ за измеренный ноль, `topic_trend` не чинится связыванием параметров, Граф: что установлено 2026-08-16, Кэш вердиктов ER вынесен из графа, Поиск сущностей по подстроке — через ключ-хранилище, Полные проходы по рёбрам не выполнимы

### Community 436 - "Технический долг, найденный по ходу"
Cohesion: 0.33
Nodes (6): ~~`StatsSettings` — три ручки из четырёх мёртвые~~ — закрыто 2026-08-16, ~~Нет теста на `except`-ветку оркестратора~~ — закрыто 2026-08-16, ~~Перечисления granularity/value_kind продублированы~~ — закрыто 2026-08-16, Реранкер: хвост вне отранжированной головы, ~~Стаб БД в тестах не моделирует `row_factory`~~ — закрыто 2026-08-16, Технический долг, найденный по ходу

### Community 437 - "Close the Statistics Subsystem Gaps Implementation Plan"
Cohesion: 0.33
Nodes (5): Close the Statistics Subsystem Gaps Implementation Plan, Global Constraints, Task 1: Make the documented settings real, and cover the untested fallback, Task 2: One source for the enums, and a stub that cannot lie, Verification

### Community 438 - "load_state"
Cohesion: 0.23
Nodes (12): mirror_with_pool(), The Postgres entity-table mirror: fail-soft, keyed on vid.  Same honest-stub app, FAIL-SOFT: the mirror must never break the graph write., nebula_store.row() defaults mention_count to 0     (`int(props.get('mention_coun, FAIL-FAST: the mirror must not absorb the shared sync pool's 30s     pool_timeou, FAIL-SOFT + FAIL-FAST: connection() itself raising (pool exhausted,     Postgres, test_a_postgres_error_is_swallowed(), test_an_unavailable_pool_is_swallowed_without_blocking() (+4 more)

### Community 439 - "Пред-существующие дефекты репозитория"
Cohesion: 0.40
Nodes (5): Дефолт графового бэкенда разошёлся с документацией и тестом, Пред-существующие дефекты репозитория, Пять падений в `test_api`, не связанных с порядком, ~~Результат тестов зависит от порядка запуска~~ — закрыто 2026-08-17, Тесты проверяют дефолт кода, читая объект с `.env`

### Community 440 - "_FakeResp"
Cohesion: 0.15
Nodes (3): _StubConn, _StubCursor, _StubPool

### Community 441 - "_FakeEntity"
Cohesion: 0.23
Nodes (9): Source trust — how much a document's origin is believed (0..1).  Trust is *polic, Trust of a document group, clamped to [0, 1].      Lookup is case-insensitive an, trust_for(), Source-trust lookup + trust-weighted claim consensus., test_known_group_is_looked_up_case_insensitively(), test_out_of_range_trust_is_clamped(), test_trust_makes_the_credible_source_win(), test_unknown_or_empty_group_gets_the_default() (+1 more)

### Community 443 - "_patch_deps"
Cohesion: 0.21
Nodes (11): aggregate_by(), CaseScore, _contains(), _content_words(), _norm(), Answer-quality eval primitives (R9).  Given a golden Q&A case and a `SearchRespo, Split on sentence terminators; cheap and good-enough for eval., Group `scores` by attribute (`doc_type`, `category`, `endpoint`)     and return (+3 more)

### Community 446 - "DynamicsGraphOps"
Cohesion: 0.25
Nodes (9): DocumentRef, BaseModel, Pydantic shapes for the search API.  The sole search surface after the R7b cutov, SourceCitation, deduplicate_nodes(), node_to_citation(), NodeWithScore, Shared helpers used by both legacy `agentic_search` and the new ReAct / reflecti (+1 more)

### Community 447 - "CommunityBuildWorkflow"
Cohesion: 0.27
Nodes (10): _build(), _fc_flag(), Any, Function-calling on by default; ``LITELLM_FUNCTION_CALLING=false``     forces th, _load_chunk(), main(), Benchmark: LLM extraction latency with thinking ON vs OFF.  Phase-0 cheap win fo, _run_variant() (+2 more)

### Community 448 - "reset_for_tests"
Cohesion: 0.27
Nodes (5): main(), PostgresERVerdictCache, The verdict cache, in the database built for unique-keyed lookups.      Historic, Cached verdicts for `keys`, as `{key: same}`.          A key that is NOT in the, Upsert freshly-judged verdicts.  Idempotent; a re-judged pair         overwrites

### Community 449 - "._validate_iso_date"
Cohesion: 0.31
Nodes (8): _configured_models(), _list_available_models(), Startup validation: every model the operator put in ``LITELLM_*_MODEL`` env vars, Return the ``model_name`` list LiteLLM proxy currently     serves.  Empty list o, Return non-empty ``{label: model_name}`` requested by env.      Two-tier model:, Probe the LiteLLM proxy and warn (or raise) on missing models.      ``source`` i, _strict_mode(), validate_litellm_models()

### Community 450 - ".achat"
Cohesion: 0.32
Nodes (7): main(), _parse_args(), prepare_txt(), Namespace, Path, Ingest the Medical benchmark corpus through `/api/v1/ingest`.  Converts `tests/e, Materialize medical.json → medical.txt in /tmp for upload.

### Community 451 - "test_community_vector_store.py"
Cohesion: 0.36
Nodes (5): _FakeGraphStore, CommunityReportVectorStore: Neo4j impl query/mapping + factory dispatch., test_factory_dispatches(), test_neo4j_knn_maps_rows(), test_neo4j_upsert_is_noop()

### Community 452 - "0. Продакшен: контейнеризованный compose"
Cohesion: 0.29
Nodes (7): 0. Продакшен: контейнеризованный compose, 0a. Образ (`Dockerfile`), 0b. Стек (`docker-compose.prod.yml`), 0c. Env (`.env.prod.example` / `.env.reference`), 0d. Команды, 0e. Temporal UI: CSRF через HTTP, 0f. Прод-харденинг

### Community 453 - "Move the ER verdict cache out of the graph"
Cohesion: 0.29
Nodes (5): Move the ER verdict cache out of the graph, Non-goals, Problem, Risks, Verification

### Community 454 - "test_completion_no_walltime_cap.py"
Cohesion: 0.38
Nodes (6): _activity_block(), Guard: LLM-bound ingest activities are bounded by ATTEMPT COUNT, not wall-clock., Permanently-failing docs must give up and free their slot (incident #2)., test_extract_kg_has_no_walltime_cap(), test_merge_and_resolve_has_no_walltime_cap(), test_retry_policies_bounded_to_max_attempts()

### Community 455 - "_walk_seeds"
Cohesion: 0.53
Nodes (5): Seed entity name(s) for graph_walk.      Legacy (dual=False): graph_search's top, _walk_seeds(), test_walk_seeds_dedupes_when_same(), test_walk_seeds_single_when_dual_off_matches_legacy(), test_walk_seeds_unions_distinct_graph_and_fulltext_seeds()

### Community 456 - "_FlakyStore"
Cohesion: 0.33
Nodes (4): _FlakyStore, Retrying forever on a host that is genuinely out of memory would     hang the ba, test_a_transient_store_refusal_is_retried(), test_retries_are_bounded_and_the_error_surfaces()

### Community 457 - "load_medical_source"
Cohesion: 0.40
Nodes (5): load_medical_source(), Return the raw `context` text from `medical.json`., Smoke: feed the medical corpus through the ingestion pipeline     (sentence spli, test_medical_source_chunks_through_pipeline(), test_source_loads_and_is_substantial()

### Community 459 - "test_search_pooled_llm.py"
Cohesion: 0.50
Nodes (3): _fake_llm(), _pool(), Regression: every search-side LLM accessor goes through the LLM pool, so the glo

### Community 460 - "pg_sync_pool.py"
Cohesion: 0.50
Nodes (3): close_pg_sync_pool(), Process-global SYNCHRONOUS Postgres connection pool.  The async twin of this mod, Close the pool on process shutdown.

## Ambiguous Edges - Review These
- `Neo4j property graph store` → `Production docker-compose`  [AMBIGUOUS]
  docker-compose.prod.yml · relation: conceptually_related_to
- `ADR-0015: Community-detection backend = in-worker leidenalg` → `Leiden community-detection diagnostics`  [AMBIGUOUS]
  docs/runbook/leiden-diagnostics.md · relation: conceptually_related_to
- `ReAct agent (/agent, react_agent.py)` → `SearchOrchestratorWorkflow`  [AMBIGUOUS]
  docs/superpowers/plans/2026-05-25-agentic-search.md · relation: conceptually_related_to

## Knowledge Gaps
- **643 isolated node(s):** `kb-llamaindex`, `start.sh script`, `DepthProbe`, `Scenario`, `graphify` (+638 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **33 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `Neo4j property graph store` and `Production docker-compose`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `ADR-0015: Community-detection backend = in-worker leidenalg` and `Leiden community-detection diagnostics`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `ReAct agent (/agent, react_agent.py)` and `SearchOrchestratorWorkflow`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **Why does `_q()` connect `test_storage: test_ingest_metrics.py` to `workflow: global_search.py`, `test_workflow: contracts.py`, `test_retrieval: test_hybrid.py`, `graph: signals.py`, `graph_edge_export.py`, `graph: test_community_summarize.py`, `graph: clamp_top_n()`, `er_graph_ops.py`, `test_graph: test_community_read.py`, `graph: events.py`, `retrieval: DateBounds`, `events_eval.py`, `test_storage: test_minio_stream.py`, `Neo4jAggregationsGraphOps`, `graph: domain.py`, `workflow: retrieve.py`, `graph: centrality.py`, `workflow: materialize_activities.py`, `aggregations_graph_ops.py`, `test_graph: test_er_graph_ops.py`, `test_graph: test_retriever_fulltext.py`, `graph: community_writeback.py`, `test_graph: extract_entity_edges()`, `test_graph: stamp_first_seen()`?**
  _High betweenness centrality (0.036) - this node is a cross-community bridge._
- **Why does `entity_vid()` connect `test_graph: entity_vid()` to `workflow: global_search.py`, `test_graph_edge_export.py`, `test_graph: test_wiki_graph_ops.py`, `test_graph: test_communities_graph_ops.py`, `graph_edge_export.py`, `test_storage: test_ingest_metrics.py`, `graph: test_community_summarize.py`, `run_answer_eval.py`, `er_graph_ops.py`, `test_retrieval: RoundGraphData`, `test_graph: test_nebula_store_writes.py`, `retrieval: atomic_tools.py`, `test_graph: _FakeClient`, `retrieval: DateBounds`, `events_eval.py`, `test_storage: test_minio_stream.py`, `Neo4jAggregationsGraphOps`, `workflow: materialize_activities.py`, `test_graph: test_er_graph_ops.py`, `test_graph: test_retriever_fulltext.py`, `test_graph: test_events_llm_graph_ops.py`, `graph: community_writeback.py`, `test_graph: extract_entity_edges()`, `test_graph: stamp_first_seen()`?**
  _High betweenness centrality (0.036) - this node is a cross-community bridge._
- **Why does `build_graph_store()` connect `workflow: SerializedNode` to `workflow: global_search.py`, `test_graph: schema.py`, `test_workflow: contracts.py`, `storage: push_entities()`, `test_api: AsyncPostgres`, `test_graph: test_alert_store.py`, `workflow: test_search_drift_roundtrip.py`, `test_workflow: activities.py`, `_gather_context`, `mcp: tools_server.py`, `test_graph: test_index.py`, `api: ingest.py`, `test_workflow: merge_and_resolve()`, `merge_identifier_duplicates.py`, `reset_for_tests`, `test_graph: test_entity_resolution.py`, `set_admission.py: get_temporal_client()`, `setup_wikibase.py`, `reresolve_graph.py`, `workflow: materialize_activities.py`, `GraphRetriever`, `test_analytics: config.py`, `test_config_wave2.py`, `test_graph: test_alerts.py`, `test_search_deps_lock.py`?**
  _High betweenness centrality (0.024) - this node is a cross-community bridge._
- **Are the 54 inferred relationships involving `PrimitiveResult` (e.g. with `CountEntitiesParams` and `CountRelationshipsParams`) actually correct?**
  _`PrimitiveResult` has 54 INFERRED edges - model-reasoned connections that need verification._