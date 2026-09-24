from __future__ import annotations

from src.graph import wiki_graph_ops as wgo

# --- Nebula: fake store -------------------------------------------------


class _NebulaRecStore:
    """Records nGQL statements (positional; nebula never binds param_map);
    returns canned rows keyed by the first matching substring of the
    statement (not popped — a substring may back several calls)."""

    def __init__(self, canned: list[tuple[str, list[dict]]] | None = None):
        self.calls: list[tuple[str, dict | None]] = []
        self._canned = list(canned or [])

    def structured_query(self, stmt, param_map=None):
        self.calls.append((stmt, param_map))
        assert param_map is None, "nebula ops must not use param_map"
        for substr, rows in self._canned:
            if substr in stmt:
                return rows
        return []


# --- Nebula: dirty-flag bookkeeping --------------------------------------


def test_nebula_mark_dirty_issues_update_vertex_per_name():
    from src.graph.nebula_store import entity_vid

    store = _NebulaRecStore()
    wgo.NebulaWikiGraphOps(store).mark_dirty(["A", "B"])

    assert len(store.calls) == 2
    stmt_a, pm_a = store.calls[0]
    stmt_b, pm_b = store.calls[1]
    assert pm_a is None and pm_b is None
    assert "UPDATE VERTEX ON `Entity`" in stmt_a
    assert entity_vid("A") in stmt_a
    assert "SET wiki_dirty = true, wiki_dirty_at =" in stmt_a
    assert "UPDATE VERTEX ON `Entity`" in stmt_b
    assert entity_vid("B") in stmt_b
    assert "SET wiki_dirty = true, wiki_dirty_at =" in stmt_b


def test_nebula_select_dirty_issues_lookup_ordered_limited_and_maps_names():
    store = _NebulaRecStore(canned=[
        ("LOOKUP ON `Entity`", [{"name": "A", "at": 100}, {"name": "B", "at": 200}]),
    ])

    result = wgo.NebulaWikiGraphOps(store).select_dirty(3)

    assert result == ["A", "B"]
    assert len(store.calls) == 1
    stmt, pm = store.calls[0]
    assert pm is None
    assert "wiki_dirty == true" in stmt
    assert "| ORDER BY $-.at ASC | LIMIT 3" in stmt


def test_nebula_clear_dirty_issues_update_vertex():
    from src.graph.nebula_store import entity_vid

    store = _NebulaRecStore()
    wgo.NebulaWikiGraphOps(store).clear_dirty("A", "h9")

    assert len(store.calls) == 1
    stmt, pm = store.calls[0]
    assert pm is None
    assert "UPDATE VERTEX ON `Entity`" in stmt
    assert entity_vid("A") in stmt
    assert 'SET wiki_dirty = false, wiki_hash = "h9", wiki_synced_at =' in stmt


def test_nebula_mark_all_dirty_issues_lookup_then_per_vid_update():
    store = _NebulaRecStore(canned=[
        ("LOOKUP ON `Entity`", [{"vid": "vidA"}, {"vid": "vidB"}]),
    ])

    wgo.NebulaWikiGraphOps(store).mark_all_dirty()

    assert len(store.calls) == 3  # 1 LOOKUP + 2 per-vid UPDATE
    lookup_stmt, lookup_pm = store.calls[0]
    assert lookup_pm is None
    assert "wiki_dirty == false" in lookup_stmt
    for stmt, pm in store.calls[1:]:
        assert pm is None
        assert "UPDATE VERTEX ON `Entity`" in stmt
        assert "SET wiki_dirty = true, wiki_dirty_at =" in stmt
    assert "vidA" in store.calls[1][0]
    assert "vidB" in store.calls[2][0]


# --- Nebula: article-context subgraph read -------------------------------


def test_nebula_read_subgraph_assembles_one_row_sorted_by_mention_count():
    from src.graph.nebula_store import entity_vid

    vid_a, vid_b, vid_c = entity_vid("A"), entity_vid("B"), entity_vid("C")
    store = _NebulaRecStore(canned=[
        ("AS page_title", [{
            "name": "A", "label": "Organization", "description": "Desc A",
            "qid": "Q1", "page_title": "Page A",
        }]),
        ("OVER `RELATED` BIDIRECT", [
            {"s": vid_a, "d": vid_b, "rl": "RELATED_TO"},   # out: A -> B
            {"s": vid_c, "d": vid_a, "rl": "MENTIONS"},      # in: C -> A
        ]),
        ("AS mc", [
            {"vid": vid_b, "nn": "B", "nl": "Person", "mc": 5},
            {"vid": vid_c, "nn": "C", "nl": "Document", "mc": 9},
        ]),
    ])

    result = wgo.NebulaWikiGraphOps(store).read_subgraph("A", max_relations=2)

    assert len(result) == 1
    row = result[0]
    assert row["name"] == "A"
    assert row["label"] == "Organization"
    assert row["description"] == "Desc A"
    assert row["qid"] == "Q1"
    assert row["page_title"] == "Page A"
    rels = row["relations"]
    assert len(rels) == 2
    # sorted by neighbour mention_count DESC -> C (mc=9) before B (mc=5)
    assert rels[0] == {"rl": "MENTIONS", "dir": "in", "nn": "C", "nl": "Document", "rd": ""}
    assert rels[1] == {"rl": "RELATED_TO", "dir": "out", "nn": "B", "nl": "Person", "rd": ""}
    assert all(pm is None for _, pm in store.calls)


def test_nebula_read_subgraph_caps_at_max_relations():
    from src.graph.nebula_store import entity_vid

    vid_a, vid_b, vid_c = entity_vid("A"), entity_vid("B"), entity_vid("C")
    store = _NebulaRecStore(canned=[
        ("AS page_title", [{
            "name": "A", "label": "Organization", "description": "",
            "qid": "", "page_title": "",
        }]),
        ("OVER `RELATED` BIDIRECT", [
            {"s": vid_a, "d": vid_b, "rl": "RELATED_TO"},
            {"s": vid_c, "d": vid_a, "rl": "MENTIONS"},
        ]),
        ("AS mc", [
            {"vid": vid_b, "nn": "B", "nl": "Person", "mc": 5},
            {"vid": vid_c, "nn": "C", "nl": "Document", "mc": 9},
        ]),
    ])

    result = wgo.NebulaWikiGraphOps(store).read_subgraph("A", max_relations=1)

    assert len(result[0]["relations"]) == 1
    assert result[0]["relations"][0]["nn"] == "C"  # higher mention_count kept


def test_nebula_read_subgraph_returns_empty_when_entity_not_found():
    store = _NebulaRecStore(canned=[("AS page_title", [])])

    result = wgo.NebulaWikiGraphOps(store).read_subgraph("Ghost", max_relations=10)

    assert result == []
    # missing entity short-circuits before GO/neighbour FETCH.
    assert len(store.calls) == 1


# --- Nebula: chunk-dependent reads (deferred -> []) ----------------------


def test_nebula_read_citations_returns_empty():
    assert wgo.NebulaWikiGraphOps(_NebulaRecStore()).read_citations("A", 5) == []


def test_nebula_read_source_docs_returns_empty():
    assert wgo.NebulaWikiGraphOps(_NebulaRecStore()).read_source_docs("A") == []


# --- Nebula: sweep inline reads/writes -----------------------------------


def test_nebula_read_wiki_hash_extracts_h():
    store = _NebulaRecStore(canned=[("AS h", [{"h": "deadbeef"}])])
    assert wgo.NebulaWikiGraphOps(store).read_wiki_hash("A") == "deadbeef"


def test_nebula_read_wiki_hash_returns_empty_string_when_no_rows():
    store = _NebulaRecStore(canned=[("AS h", [])])
    assert wgo.NebulaWikiGraphOps(store).read_wiki_hash("A") == ""


def test_nebula_write_page_title_issues_update_vertex():
    from src.graph.nebula_store import entity_vid

    store = _NebulaRecStore()
    wgo.NebulaWikiGraphOps(store).write_page_title("A", "T")

    assert len(store.calls) == 1
    stmt, pm = store.calls[0]
    assert pm is None
    assert "UPDATE VERTEX ON `Entity`" in stmt
    assert entity_vid("A") in stmt
    assert 'SET wiki_page_title = "T"' in stmt


def test_nebula_mark_dirty_resilient_to_missing_vertex():
    """nebula UPDATE VERTEX raises on a missing vertex; mark_dirty must catch
    per-name so one missing/merged-away name doesn't abort the whole batch
    (matches neo4j's batch no-op-on-missing)."""
    import src.graph.wiki_graph_ops as wg
    from src.graph.nebula_store import entity_vid

    class _RaiseOnFirst:
        def __init__(self):
            self.updated = []
        def structured_query(self, query, param_map=None):
            assert not param_map
            if entity_vid("Gone") in query:
                raise RuntimeError("Storage Error: Vertex or edge not found.")
            self.updated.append(query)
            return []

    store = _RaiseOnFirst()
    wg.NebulaWikiGraphOps(store).mark_dirty(["Gone", "Alive"])
    # the missing one raised internally but was swallowed; Alive still updated
    joined = "\n".join(store.updated)
    assert entity_vid("Alive") in joined, "surviving name must still be marked"
    assert entity_vid("Gone") not in joined


def test_nebula_mark_dirty_noop_on_empty():
    # ported from test_neo4j_mark_dirty_noop_on_empty.
    store = _NebulaRecStore()
    wgo.NebulaWikiGraphOps(store).mark_dirty([])
    assert store.calls == []
