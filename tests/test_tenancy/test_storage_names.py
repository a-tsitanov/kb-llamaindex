from src.tenancy.context import default_graph_context, new_graph_context


def test_vector_store_uses_graph_chunks_collection(monkeypatch):
    import src.retrieval.vector_index as vi
    seen = {}

    class FakeMVS:
        def __init__(self, **kw):
            seen.update(kw)
    monkeypatch.setattr(vi, "MilvusVectorStore", FakeMVS)
    vi.build_vector_store(new_graph_context("acme"))
    assert seen["collection_name"] == "g_acme_chunks"
    vi.build_vector_store(default_graph_context())
    assert seen["collection_name"] == default_graph_context().chunks_collection


def test_er_and_report_factories_use_graph_collections(monkeypatch):
    from src.graph import community_vector_store_milvus as cm
    from src.graph import entity_vector_store_milvus as em
    from src.graph.community_vector_store import build_community_report_vector_store
    from src.graph.entity_vector_store import build_entity_vector_store

    monkeypatch.setattr(em, "MilvusClient", lambda **kw: object(), raising=False)
    monkeypatch.setattr(cm, "MilvusClient", lambda **kw: object(), raising=False)
    g = new_graph_context("acme")
    assert build_entity_vector_store(g)._collection == "g_acme_er_vec"
    assert build_community_report_vector_store(g)._collection == "g_acme_report_vec"
    d = default_graph_context()
    assert build_entity_vector_store(d)._collection == "entity_er_vec"
    assert build_community_report_vector_store(d)._collection == "community_report_vec"


def test_chunk_repository_uses_graph_collection():
    from src.storage.chunk_repository import ChunkRepository
    repo = ChunkRepository(graph=new_graph_context("acme"), milvus_client=object(), pg=object())
    assert repo._collection == "g_acme_chunks"


def test_minio_keys_are_prefixed_only_for_non_default():
    from src.storage.minio import graph_object_key
    assert graph_object_key(default_graph_context(), "d1/f.pdf") == "d1/f.pdf"
    assert graph_object_key(new_graph_context("acme"), "d1/f.pdf") == "acme/d1/f.pdf"
