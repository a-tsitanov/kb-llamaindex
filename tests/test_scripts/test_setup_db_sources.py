"""Реестр источников (``source``, ``source_slug``) — форма DDL."""
from src.storage.pg_schema import _SOURCE_DDL, GRAPH_DDL, graph_tables


def test_both_tables_are_created_idempotently():
    assert "CREATE TABLE IF NOT EXISTS source (" in _SOURCE_DDL
    assert "CREATE TABLE IF NOT EXISTS source_slug (" in _SOURCE_DDL


def test_source_is_keyed_by_peer_id():
    assert "peer_id    BIGINT PRIMARY KEY" in _SOURCE_DDL


def test_slug_history_is_keyed_by_peer_and_slug():
    assert "PRIMARY KEY (peer_id, slug)" in _SOURCE_DDL


def test_state_is_constrained():
    assert "CHECK (state IN ('active','left'))" in _SOURCE_DDL


def test_trust_is_nullable_and_defaults_absent():
    assert "trust      DOUBLE PRECISION," in _SOURCE_DDL


def test_tables_are_in_graph_ddl_and_ready_check():
    assert _SOURCE_DDL in GRAPH_DDL
    assert {"source", "source_slug"} <= set(graph_tables())
