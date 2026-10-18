import pytest

from src.graph.community_vector_store_milvus import MilvusCommunityReportVectorStore
from src.graph.entity_vector_store_milvus import MilvusEntityVectorStore


class _Client:
    def __init__(self, exists=False, fail=False):
        self.exists, self.fail, self.created = exists, fail, []

    def has_collection(self, name):
        if self.fail:
            raise ConnectionError("milvus down")
        return self.exists

    def create_schema(self, **kw):
        class _S:
            def add_field(self, *a, **k):
                pass
        return _S()

    def prepare_index_params(self):
        class _I:
            def add_index(self, **k):
                pass
        return _I()

    def create_collection(self, collection_name, **kw):
        self.created.append(collection_name)


@pytest.mark.parametrize("cls", [MilvusEntityVectorStore, MilvusCommunityReportVectorStore])
def test_ensure_collection_creates(cls):
    c = _Client()
    cls("g_acme_x", client=c).ensure_collection()
    assert c.created == ["g_acme_x"]


@pytest.mark.parametrize("cls", [MilvusEntityVectorStore, MilvusCommunityReportVectorStore])
def test_ensure_collection_raises_but_private_ensure_fails_open(cls):
    with pytest.raises(ConnectionError):
        cls("g_acme_x", client=_Client(fail=True)).ensure_collection()
    cls("g_acme_x", client=_Client(fail=True))._ensure()  # still fail-open
