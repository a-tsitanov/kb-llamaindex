"""upsert_nodes/upsert_relations emit the expected nGQL (no live DB)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import src.graph.nebula_store as nebula_store_mod
from src.config import settings
from src.graph.nebula_store import NebulaGraphStore, entity_vid


@pytest.fixture(autouse=True)
def _no_entity_mirror(monkeypatch):
    """This file's contract is "no live DB" (see module docstring). The
    entity-table mirror grafted onto upsert_nodes would otherwise reach for
    a real Postgres pool on every call and, with Postgres unreachable,
    stall behind mirror_entities' own fail-fast timeout — no-op it so this
    file stays fast and DB-free."""
    monkeypatch.setattr(nebula_store_mod, "mirror_entities", lambda rows: None)


# Columns upsert_nodes does not own (wiki sweep, analytics materialize, the
# monitor's watch flag); they are read back and written again unchanged.
PRESERVED_COLS = (
    "wiki_dirty, wiki_dirty_at, wiki_hash, wiki_synced_at, wiki_page_title, "
    "wikibase_qid, pagerank, betweenness, eigenvector, risk_score, risk_band, "
    "risk_components, completeness_score, watched, risk_score_prev"
)
DEFAULT_TAIL = 'false, 0, "", 0, "", "", 0.0, 0.0, 0.0, 0.0, "", "", 0.0, false, 0.0'


class _Cast:
    """Wraps a plain python value with a nebula-ValueWrapper-like .cast()."""

    def __init__(self, value):
        self._value = value

    def cast(self):
        return self._value


class _FakeSession:
    """Records executed statements. Also answers `FETCH PROP ON `Entity``
    read-backs (used by upsert_nodes' created_at/first_doc_id preserve
    logic) with canned rows, or a failure response when fetch_fails=True."""

    def __init__(self, fetch_rows: list[dict] | None = None, fetch_fails: bool = False,
                 edge_rows: list[dict] | None = None):
        self.executed = []
        self._edge_rows = edge_rows
        self._fetch_rows = fetch_rows if fetch_rows is not None else []
        self._fetch_fails = fetch_fails

    def execute(self, stmt, *a, **k):
        self.executed.append(stmt)
        if self._edge_rows is not None and "FETCH PROP ON `RELATED`" in stmt:
            rows = self._edge_rows
            cols = list(rows[0]) if rows else ["s", "d"]
            return SimpleNamespace(
                is_succeeded=lambda: True, error_msg=lambda: "",
                keys=lambda: cols, row_size=lambda: len(rows),
                row_values=lambda i: [_Cast(rows[i].get(c)) for c in cols],
            )
        if "FETCH PROP ON `Entity`" in stmt:
            if self._fetch_fails:
                return SimpleNamespace(
                    is_succeeded=lambda: False,
                    error_msg=lambda: "fetch boom",
                    keys=lambda: [],
                    row_size=lambda: 0,
                )
            rows = self._fetch_rows
            cols = list(rows[0]) if rows else ["vid", "ca", "fdi"]
            return SimpleNamespace(
                is_succeeded=lambda: True,
                error_msg=lambda: "",
                keys=lambda: cols,
                row_size=lambda: len(rows),
                row_values=lambda i, _rows=rows, _cols=cols: [
                    _Cast(_rows[i].get(c)) for c in _cols
                ],
            )
        return SimpleNamespace(
            is_succeeded=lambda: True,
            error_msg=lambda: "",
            keys=lambda: [],
            row_size=lambda: 0,
        )


def _store_with_session(sess):
    return NebulaGraphStore(sess)


def test_entity_vid_is_stable_fixed_string():
    v = entity_vid("Иванов")
    assert isinstance(v, str)
    assert v == entity_vid("Иванов")
    assert len(v) == 32  # 128-bit blake2b hex digest -> FIXED_STRING(32)
    assert all(c in "0123456789abcdef" for c in v)


def test_upsert_nodes_inserts_entity_vertex():
    sess = _FakeSession()
    store = _store_with_session(sess)
    node = SimpleNamespace(name="Иванов", label="PERSON",
                           properties={"description": "d", "mention_count": 3})
    store.upsert_nodes([node])
    blob = "\n".join(sess.executed)
    assert "INSERT VERTEX `Entity`" in blob
    assert f'"{entity_vid("Иванов")}"' in blob  # quoted FIXED_STRING VID
    assert "Иванов" in blob


def test_upsert_nodes_writes_er_canonical_name_from_properties():
    sess = _FakeSession()
    store = _store_with_session(sess)
    node = SimpleNamespace(name="Иванов", label="PERSON",
                           properties={"description": "d", "mention_count": 3,
                                       "er_canonical_name": "Canon"})
    store.upsert_nodes([node])
    blob = "\n".join(sess.executed)
    assert (
        "INSERT VERTEX `Entity` (name, description, mention_count, created_at, label, "
        "er_canonical_name, first_doc_id, event_type, event_ts_raw, event_start_epoch, "
        "event_end_epoch, event_ts_precision, " + PRESERVED_COLS + ") VALUES" in blob
    )
    assert '"Canon"' in blob


def test_upsert_nodes_defaults_er_canonical_name_to_empty_when_absent():
    sess = _FakeSession()
    store = _store_with_session(sess)
    node = SimpleNamespace(name="Иванов", label="PERSON",
                           properties={"description": "d", "mention_count": 3})
    store.upsert_nodes([node])
    blob = "\n".join(sess.executed)
    assert '"Иванов", "d", 3, 0, "PERSON", "", "", ' in blob


# --- created_at/first_doc_id read-back preserve (first-seen) -----------


def test_upsert_nodes_preserves_watch_analytics_and_wiki_columns_for_existing_entity():
    """INSERT VERTEX resets every omitted column, so a re-mention used to wipe
    the watch flag, the materialized risk/centrality and the wiki linkage."""
    vid_a = entity_vid("A")
    sess = _FakeSession(fetch_rows=[{
        "vid": vid_a, "ca": 111, "fdi": "d0",
        "wiki_dirty": True, "wiki_dirty_at": 5, "wiki_hash": "h", "wiki_synced_at": 6,
        "wiki_page_title": "A_(page)", "wikibase_qid": "Q42",
        "pagerank": 0.25, "betweenness": 0.5, "eigenvector": 0.125,
        "risk_score": 0.75, "risk_band": "high", "risk_components": "{}",
        "completeness_score": 0.5, "watched": True, "risk_score_prev": 0.375,
    }])
    store = _store_with_session(sess)
    node = SimpleNamespace(name="A", label="PERSON", properties={"description": "x"})

    store.upsert_nodes([node])

    inserts = [s for s in sess.executed if s.startswith("INSERT VERTEX")]
    assert len(inserts) == 1
    assert (
        '"d0", "", "", 0, 0, "", true, 5, "h", 6, "A_(page)", "Q42", 0.25, 0.5, 0.125, '
        '0.75, "high", "{}", 0.5, true, 0.375)'
    ) in inserts[0]


def test_upsert_nodes_readback_fetches_preserved_columns():
    sess = _FakeSession()
    store = _store_with_session(sess)
    store.upsert_nodes([SimpleNamespace(name="A", label="", properties={})])
    fetch = next(s for s in sess.executed if "FETCH PROP ON `Entity`" in s)
    for col in ("watched", "risk_score", "pagerank", "wikibase_qid", "wiki_dirty"):
        assert f"`Entity`.{col} AS {col}" in fetch


def test_upsert_nodes_readback_failure_does_not_overwrite_existing_entities():
    """Without the read-back we cannot tell new from existing, so the INSERT
    must not touch existing vertices at all (IF NOT EXISTS)."""
    sess = _FakeSession(fetch_fails=True)
    store = _store_with_session(sess)
    store.upsert_nodes([SimpleNamespace(name="A", label="", properties={})])
    inserts = [s for s in sess.executed if s.startswith("INSERT VERTEX")]
    assert len(inserts) == 1
    assert inserts[0].startswith("INSERT VERTEX IF NOT EXISTS `Entity`")


def test_upsert_nodes_preserves_created_at_and_first_doc_id_for_existing_entity():
    vid_a = entity_vid("A")
    sess = _FakeSession(fetch_rows=[{"vid": vid_a, "ca": 111, "fdi": "d0"}])
    store = _store_with_session(sess)
    node = SimpleNamespace(
        name="A", label="PERSON",
        properties={"created_at": 999, "first_doc_id": "dNEW", "description": "newdesc"},
    )

    store.upsert_nodes([node])

    inserts = [s for s in sess.executed if s.startswith("INSERT VERTEX")]
    assert len(inserts) == 1
    # created_at/first_doc_id come from the read-back (111/"d0"), NOT props
    # (999/"dNEW"); description still overwrites from props ("newdesc").
    expected_row = f'{_q_expect(vid_a)}:("A", "newdesc", 0, 111, "PERSON", "", "d0", "", "", 0, 0, "", ' + DEFAULT_TAIL + ')'
    assert expected_row in inserts[0]
    assert "999" not in inserts[0]
    assert "dNEW" not in inserts[0]


def test_upsert_nodes_uses_props_for_new_entity_when_not_in_readback():
    vid_b = entity_vid("B")
    sess = _FakeSession(fetch_rows=[])  # empty read-back -> B is new
    store = _store_with_session(sess)
    node = SimpleNamespace(
        name="B", label="ORG",
        properties={"created_at": 7, "first_doc_id": "dB", "description": "d"},
    )

    store.upsert_nodes([node])

    inserts = [s for s in sess.executed if s.startswith("INSERT VERTEX")]
    assert len(inserts) == 1
    expected_row = f'{_q_expect(vid_b)}:("B", "d", 0, 7, "ORG", "", "dB", "", "", 0, 0, "", ' + DEFAULT_TAIL + ')'
    assert expected_row in inserts[0]


def test_upsert_nodes_readback_failure_treats_all_as_new_and_still_inserts():
    vid_c = entity_vid("C")
    sess = _FakeSession(fetch_fails=True)
    store = _store_with_session(sess)
    node = SimpleNamespace(
        name="C", label="PERSON",
        properties={"created_at": 42, "first_doc_id": "dC", "description": "d"},
    )

    store.upsert_nodes([node])  # must not raise despite the FETCH failure

    fetch_attempts = [s for s in sess.executed if "FETCH PROP ON `Entity`" in s]
    assert len(fetch_attempts) == 1  # read-back was attempted, then failed open

    inserts = [s for s in sess.executed if s.startswith("INSERT VERTEX")]
    assert len(inserts) == 1  # INSERT still issued (fail-open, no crash)
    expected_row = f'{_q_expect(vid_c)}:("C", "d", 0, 42, "PERSON", "", "dC", "", "", 0, 0, "", ' + DEFAULT_TAIL + ')'
    assert expected_row in inserts[0]


def test_upsert_relations_inserts_related_with_rel_type():
    sess = _FakeSession()
    store = _store_with_session(sess)
    rel = SimpleNamespace(source_id="Иванов", target_id="Москва",
                          label="WORKS_AT", properties={"polarity": "pos"})
    store.upsert_relations([rel])
    blob = "\n".join(sess.executed)
    assert "INSERT EDGE `RELATED`" in blob
    assert f'"{entity_vid("Иванов")}" -> "{entity_vid("Москва")}"' in blob
    assert '"WORKS_AT"' in blob            # original type preserved as rel_type value


def test_upsert_relations_writes_weight_from_properties():
    sess = _FakeSession()
    store = _store_with_session(sess)
    rel = SimpleNamespace(source_id="a", target_id="b", label="WORKS_AT",
                          properties={"weight": 7.0})
    store.upsert_relations([rel])
    blob = "\n".join(sess.executed)
    assert ("INSERT EDGE `RELATED` (rel_type, polarity, valid_from, valid_to, weight, "
            "created_at, first_doc_id, source_trust, superseded_at) VALUES") in blob
    # weight, then created_at=0, first_doc_id="", source_trust=0.0, superseded_at=0
    assert '7.0, 0, "", 0.0, 0)' in blob


def test_upsert_relations_defaults_weight_to_one_when_absent():
    sess = _FakeSession()
    store = _store_with_session(sess)
    rel = SimpleNamespace(source_id="a", target_id="b", label="WORKS_AT", properties={})
    store.upsert_relations([rel])
    blob = "\n".join(sess.executed)
    # default weight 1.0, then created_at=0, first_doc_id="", trust/supersede zeros
    assert '1.0, 0, "", 0.0, 0)' in blob


def test_upsert_relations_rel_type_is_a_value_not_identifier():
    sess = _FakeSession()
    store = _store_with_session(sess)
    rel = SimpleNamespace(source_id="a", target_id="b",
                          label='X`; DROP SPACE', properties={})
    store.upsert_relations([rel])
    blob = "\n".join(sess.executed)
    assert "INSERT EDGE `RELATED`" in blob     # always RELATED edge type
    assert "INSERT EDGE `X" not in blob        # label never spliced as an edge-type identifier
    # one FETCH read-back + one INSERT; the label never becomes a 3rd (injected) stmt
    inserts = [s for s in sess.executed if s.startswith("INSERT EDGE `RELATED`")]
    assert len(inserts) == 1
    assert "DROP SPACE" in blob                 # present only as an escaped rel_type value


def test_q_escapes_newlines():
    sess = _FakeSession()
    store = _store_with_session(sess)
    node = SimpleNamespace(name="Иванов", label="PERSON",
                           properties={"description": "line1\nline2", "mention_count": 3})
    store.upsert_nodes([node])
    blob = "\n".join(sess.executed)
    assert "INSERT VERTEX" in blob
    assert "line1\\nline2" in blob
    assert "line1\nline2" not in blob


def test_structured_query_rejects_params():
    sess = _FakeSession()
    store = _store_with_session(sess)

    with pytest.raises(NotImplementedError):
        store.structured_query("MATCH ...", {"name": "X"})

    # None and empty dict are both "no params" and must pass through.
    store.structured_query("YIELD 1", {})
    store.structured_query("YIELD 1")
    assert sess.executed == ["YIELD 1", "YIELD 1"]


# --- write batching (multi-VALUES INSERT) -------------------------------


def _node(i: int) -> SimpleNamespace:
    return SimpleNamespace(
        name=f"Entity{i}",
        label="PERSON",
        properties={"description": f"desc{i}", "mention_count": i, "created_at": 1000 + i},
    )


def _rel(i: int) -> SimpleNamespace:
    return SimpleNamespace(
        source_id=f"Entity{i}",
        target_id=f"Entity{i + 1}",
        label="WORKS_WITH",
        properties={
            "polarity": "pos", "valid_from": 100 + i, "valid_to": 200 + i,
            "weight": float(i) + 1.0,
        },
    )


def test_upsert_nodes_batches_into_multi_values_statements(monkeypatch):
    monkeypatch.setattr(settings.nebula, "write_batch_size", 2)
    sess = _FakeSession()
    store = _store_with_session(sess)
    nodes = [_node(i) for i in range(5)]

    store.upsert_nodes(nodes)

    inserts = [s for s in sess.executed if s.startswith("INSERT VERTEX")]
    fetches = [s for s in sess.executed if "FETCH PROP ON `Entity`" in s]
    assert len(inserts) == 3  # 2 + 2 + 1
    assert len(fetches) == 3  # one read-back per chunk
    for stmt in inserts:
        assert stmt.startswith(
            "INSERT VERTEX `Entity` (name, description, mention_count, created_at, label, "
            "er_canonical_name, first_doc_id, event_type, event_ts_raw, event_start_epoch, "
            "event_end_epoch, event_ts_precision, " + PRESERVED_COLS + ") VALUES "
        )
    # first two statements have 2 comma-joined rows, last has 1
    assert inserts[0].count(":(") == 2
    assert inserts[1].count(":(") == 2
    assert inserts[2].count(":(") == 1
    # VID present and correctly quoted
    vid0 = entity_vid("Entity0")
    assert f'{_q_expect(vid0)}:(' in inserts[0]
    assert '"desc0"' in inserts[0]
    assert '"PERSON"' in inserts[0]


def _q_expect(value: str) -> str:
    return f'"{value}"'


def test_upsert_relations_batches_into_multi_values_statements(monkeypatch):
    monkeypatch.setattr(settings.nebula, "write_batch_size", 2)
    sess = _FakeSession()
    store = _store_with_session(sess)
    rels = [_rel(i) for i in range(5)]

    store.upsert_relations(rels)

    # each batch does a FETCH read-back then an INSERT; assert on the INSERTs.
    inserts = [s for s in sess.executed if s.startswith("INSERT EDGE `RELATED`")]
    assert len(inserts) == 3  # 2 + 2 + 1
    for stmt in inserts:
        assert stmt.startswith(
            "INSERT EDGE `RELATED` (rel_type, polarity, valid_from, valid_to, weight, "
            "created_at, first_doc_id, source_trust, superseded_at) VALUES "
        )
    assert inserts[0].count(" -> ") == 2
    assert inserts[1].count(" -> ") == 2
    assert inserts[2].count(" -> ") == 1
    src0, tgt0 = entity_vid("Entity0"), entity_vid("Entity1")
    assert f'"{src0}" -> "{tgt0}"' in inserts[0]
    assert '"WORKS_WITH"' in inserts[0]


def test_upsert_nodes_empty_list_emits_no_statements():
    sess = _FakeSession()
    store = _store_with_session(sess)
    store.upsert_nodes([])
    assert sess.executed == []


def test_upsert_relations_empty_list_emits_no_statements():
    sess = _FakeSession()
    store = _store_with_session(sess)
    store.upsert_relations([])
    assert sess.executed == []


def test_upsert_nodes_batch_size_ge_len_emits_one_statement(monkeypatch):
    monkeypatch.setattr(settings.nebula, "write_batch_size", 100)
    sess = _FakeSession()
    store = _store_with_session(sess)
    nodes = [_node(i) for i in range(5)]
    store.upsert_nodes(nodes)
    inserts = [s for s in sess.executed if s.startswith("INSERT VERTEX")]
    assert len(inserts) == 1
    assert inserts[0].count(":(") == 5


def test_upsert_relations_batch_size_ge_len_emits_one_statement(monkeypatch):
    monkeypatch.setattr(settings.nebula, "write_batch_size", 100)
    sess = _FakeSession()
    store = _store_with_session(sess)
    rels = [_rel(i) for i in range(5)]
    store.upsert_relations(rels)
    inserts = [s for s in sess.executed if s.startswith("INSERT EDGE `RELATED`")]
    assert len(inserts) == 1  # one INSERT (a single FETCH read-back precedes it)
    assert inserts[0].count(" -> ") == 5


# --- upsert_relations reports the pairs it created (entity-watch edge_new) --


def test_upsert_relations_returns_only_pairs_missing_from_the_readback():
    a, b, c = entity_vid("A"), entity_vid("B"), entity_vid("C")
    sess = _FakeSession(edge_rows=[{"s": a, "d": b, "ca": 5, "fdi": "d0", "st": 0.0, "sa": 0}])
    store = _store_with_session(sess)
    rels = [
        SimpleNamespace(source_id="A", target_id="B", label="X", properties={}),
        SimpleNamespace(source_id="A", target_id="C", label="Y", properties={}),
    ]
    assert store.upsert_relations(rels) == [(a, c)]


def test_upsert_relations_readback_failure_reports_no_new_pairs():
    """Unknown != new: without the read-back, claim nothing (no false events)."""
    sess = _FakeSession(fetch_fails=True)
    sess.execute = _fail_fetch(sess.execute)
    store = _store_with_session(sess)
    rel = SimpleNamespace(source_id="A", target_id="B", label="X", properties={})
    assert store.upsert_relations([rel]) == []


def _fail_fetch(orig):
    def run(stmt, *a, **k):
        if "FETCH PROP ON `RELATED`" in stmt:
            return SimpleNamespace(is_succeeded=lambda: False, error_msg=lambda: "boom",
                                   keys=lambda: [], row_size=lambda: 0)
        return orig(stmt, *a, **k)
    return run
