"""Activity input models whose activity touches per-graph storage.

Every model listed here is the parameter of an ``@activity.defn`` that —
directly or via a helper — opens graph (Nebula), Milvus, Postgres or MinIO
storage.  Each carries ``graph_id`` so the activity can resolve its
``GraphContext`` from the payload instead of assuming the default graph.

Not listed (no per-graph storage): ``ClassifyIn`` (local file + LLM),
``Ctx`` (``parse_and_chunk``: parser + run-scoped staging bucket only —
``Ctx`` still carries ``graph_id`` for propagation), ``RerankParams``,
``SynthesizeParams``, ``CoverageParams``, ``PlanParams``, ``RouteParams``,
``ContextualizeParams``, ``MapPartialParams``, ``PlanInput``, ``SynthInput``
(LLM / model only), ``LinkPredictionIn`` (``materialize_link_prediction``
is a documented no-op; the model still carries ``graph_id``).  ``select_dirty_entities(limit: int)`` and
``write_entity_article(name: str)`` touch the graph but take primitives —
the wiki sweep is default-only in Plan A.
"""

from __future__ import annotations

from src.analytics.contracts import (
    CentralityIn,
    ExecInput,
    RiskIn,
)
from src.workflow.contracts import (
    DetectCommunitiesParams,
    DocumentsForCommunitiesParams,
    FinalizeIn,
    IngestParams,
    KGExtracted,
    MapCommunitiesParams,
    MarkDirtyIn,
    MarkFailedIn,
    Merged,
    Parsed,
    RetrieveParams,
    SkipIn,
    SummarizeCommunityParams,
)

STORAGE_ACTIVITY_INPUTS: tuple[type, ...] = (
    # ingest
    IngestParams,                   # fetch_source: AsyncPostgres + build_minio_storage
    Parsed,                         # index_vector (Milvus), inject_canonical (graph)
    KGExtracted,                    # merge_and_resolve: graph + entity vec + ER cache
    Merged,                         # build_property_graph (graph + PG), push_wikibase (graph)
    FinalizeIn,                     # finalize: AsyncPostgres + ingest_metrics
    SkipIn,                         # mark_skipped: IntakeRepository.reject + staging
    MarkFailedIn,                   # mark_failed: AsyncPostgres
    MarkDirtyIn,                    # mark_entities_dirty: graph
    # search
    RetrieveParams,                 # retrieve_subquestion: get_retriever/get_graph_retriever
    DetectCommunitiesParams,        # detect_communities_activity: graph
    SummarizeCommunityParams,       # summarize_community_activity: graph + report vec
    DocumentsForCommunitiesParams,  # documents_for_communities: graph
    MapCommunitiesParams,           # map_communities: graph + report vec
    # analytics
    ExecInput,                      # execute_step: graph
    CentralityIn,                   # materialize_centrality: graph
    RiskIn,                         # materialize_risk: graph
    # Активность наблюдения (`sweep_watch`) входной модели не имеет вовсе:
    # она сама обходит все готовые графы, поэтому graph_id в payload'е ей
    # не нужен — и в списке её нет по этой причине, а не по забывчивости.
)
