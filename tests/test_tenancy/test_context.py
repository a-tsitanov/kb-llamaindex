import pytest

from src.config import settings
from src.tenancy.context import (
    DEFAULT_GRAPH_ID,
    DEFAULT_TENANT_ID,
    GraphContext,
    InvalidGraphId,
    default_graph_context,
    graph_scoped_id,
    new_graph_context,
    transitional_default_graph,
    validate_graph_id,
)


@pytest.mark.parametrize("gid", ["ab", "acme", "client_1", "a" + "b" * 30])
def test_valid_ids(gid):
    assert validate_graph_id(gid) == gid


@pytest.mark.parametrize(
    "gid",
    ["", "a", "1abc", "Acme", "acme-x", "acme x", "a" + "b" * 31, "kb`; DROP SPACE kb; --", "g_x;", "é"],
)
def test_invalid_ids(gid):
    with pytest.raises(InvalidGraphId):
        validate_graph_id(gid)


def test_default_context_uses_legacy_names():
    ctx = default_graph_context()
    assert ctx == GraphContext(
        id=DEFAULT_GRAPH_ID,
        nebula_space="kb",
        nebula_partition_num=100,
        chunks_collection=settings.milvus.collection,
        er_vec_collection="entity_er_vec",
        report_vec_collection="community_report_vec",
        pg_schema="public",
        minio_prefix="",
    )
    assert ctx.is_default
    assert transitional_default_graph() == ctx


def test_new_graph_context_names():
    ctx = new_graph_context("acme")
    assert ctx.nebula_space == "g_acme"
    assert ctx.nebula_partition_num == 10
    assert ctx.chunks_collection == "g_acme_chunks"
    assert ctx.er_vec_collection == "g_acme_er_vec"
    assert ctx.report_vec_collection == "g_acme_report_vec"
    assert ctx.pg_schema == "g_acme"
    assert ctx.minio_prefix == "acme/"
    assert not ctx.is_default


def test_new_graph_context_rejects_reserved_and_invalid():
    with pytest.raises(InvalidGraphId):
        new_graph_context(DEFAULT_GRAPH_ID)
    with pytest.raises(InvalidGraphId):
        new_graph_context("Bad-Id")


def test_graph_scoped_id_keeps_default_ids_unchanged():
    assert graph_scoped_id("ingest", DEFAULT_GRAPH_ID, "doc1") == "ingest-doc1"
    assert graph_scoped_id("ingest", "acme", "doc1") == "ingest-acme-doc1"


def test_default_context_tenant_is_default():
    assert default_graph_context().tenant_id == DEFAULT_TENANT_ID
    assert new_graph_context("acme").tenant_id == DEFAULT_TENANT_ID


def test_new_graph_context_tenant_override():
    ctx = new_graph_context("acme", tenant_id="t1")
    assert ctx.tenant_id == "t1"
    # the tenant is metadata only: physical names stay derived from the id
    assert ctx.nebula_space == new_graph_context("acme").nebula_space
