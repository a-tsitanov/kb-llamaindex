from itertools import permutations

import pytest

from src.analytics.primitives import connections as conn
from src.graph.nebula_store import entity_vid
from tests.test_analytics.conftest import _NebulaStmtStore, _ngql_list

_RELATED_FULL_YIELD = (
    "YIELD src(edge) AS s, dst(edge) AS d, `RELATED`.rel_type AS rl, "
    "`RELATED`.weight AS w, `RELATED`.polarity AS pol;"
)


def _fetch_name_label(vids) -> str:
    return (
        f"FETCH PROP ON `Entity` {_ngql_list(vids)} YIELD id(vertex) AS vid, "
        "`Entity`.name AS name, `Entity`.label AS label;"
    )


@pytest.mark.asyncio
async def test_entity_dossier_assembles_sections():
    # The nebula seam assembles the same 4 sections (core, neighbors,
    # identifiers, communities) from GO/FETCH reads; the fake answers the
    # exact nGQL each section issues.
    vid = entity_vid("Ромашка")
    lutik, inn = entity_vid("ООО Лютик"), entity_vid("7701234567")
    store = _NebulaStmtStore({
        # core
        f'FETCH PROP ON `Entity` "{vid}" YIELD '
        "`Entity`.name AS name, `Entity`.description AS description, "
        "`Entity`.label AS label, `Entity`.mention_count AS mention_count;": [
            {"name": "Ромашка", "description": "d", "label": "Organization",
             "mention_count": 4},
        ],
        # neighbors
        f'GO FROM "{vid}" OVER `RELATED` BIDIRECT {_RELATED_FULL_YIELD}': [
            {"s": vid, "d": lutik, "rl": "OWNS", "w": 2.0, "pol": "affirmed"},
        ],
        _fetch_name_label([lutik]): [
            {"vid": lutik, "name": "ООО Лютик", "label": "Organization"},
        ],
        # identifiers
        f'GO FROM "{vid}" OVER `RELATED` BIDIRECT YIELD '
        "src(edge) AS s, dst(edge) AS d;": [{"s": vid, "d": inn}],
        _fetch_name_label([inn]): [{"vid": inn, "name": "7701234567", "label": "INN"}],
        # communities
        f'GO FROM "{vid}" OVER `IN_COMMUNITY` YIELD dst(edge) AS c;': [{"c": "c1"}],
        'FETCH PROP ON `Community` "c1" YIELD '
        "`Community`.level AS level, `Community`.title AS title;": [
            {"level": 0, "title": "Поставки"},
        ],
    })
    res = await conn.entity_dossier(store, name="Ромашка")
    row = res.rows[0]
    assert row["core"]["name"] == "Ромашка"
    assert row["connections"][0]["rel"] == "OWNS"
    assert row["identifiers"][0]["id_type"] == "INN"
    assert row["communities"][0]["title"] == "Поставки"
    assert res.params["name"] == "Ромашка"


@pytest.mark.asyncio
async def test_shared_identifier_entities_min_owners():
    inn, email = entity_vid("7701234567"), entity_vid("a@x.ru")
    a, b = entity_vid("A"), entity_vid("B")
    responses = {
        'LOOKUP ON `Entity` WHERE `Entity`.label == "INN" '
        "YIELD id(vertex) AS vid, `Entity`.name AS name;": [
            {"vid": inn, "name": "7701234567"},
        ],
        'LOOKUP ON `Entity` WHERE `Entity`.label == "Email" '
        "YIELD id(vertex) AS vid, `Entity`.name AS name;": [
            {"vid": email, "name": "a@x.ru"},
        ],
    }
    go_edges = [{"s": a, "d": inn}, {"s": b, "d": inn}, {"s": a, "d": email}]
    owner_rows = [
        {"vid": a, "name": "A", "label": "Organization"},
        {"vid": b, "name": "B", "label": "Organization"},
    ]
    # The seam batches id/owner vids from dicts/sets; key every ordering.
    for ids in permutations([inn, email]):
        responses[
            f"GO FROM {_ngql_list(ids)} OVER `RELATED` BIDIRECT YIELD "
            "src(edge) AS s, dst(edge) AS d;"
        ] = go_edges
    for owners in permutations([a, b]):
        responses[_fetch_name_label(owners)] = owner_rows
    store = _NebulaStmtStore(responses)

    res = await conn.shared_identifier_entities(store, min_owners=2)
    assert res.params["min_owners"] == 2
    # min_owners is enforced on the executed read: the INN shared by A and B
    # survives, the Email owned by A alone does not.
    assert res.rows == [{"value": "7701234567", "id_type": "INN", "owners": ["A", "B"]}]


@pytest.mark.asyncio
async def test_connection_path_clamps_hops_inline():
    store = _NebulaStmtStore()
    res = await conn.connection_path(store, source="A", target="B", max_hops=99)
    # hops clamped (max 12) -- reflected in params, and inlined into the
    # real nGQL literal (FIND SHORTEST PATH bound) issued via the seam.
    assert res.params["max_hops"] == 12
    assert store.calls == [
        f'FIND SHORTEST PATH FROM "{entity_vid("A")}" TO "{entity_vid("B")}" '
        "OVER * BIDIRECT UPTO 12 STEPS YIELD path AS p;"
    ]


@pytest.mark.asyncio
async def test_failsoft():
    assert (await conn.entity_dossier(None, name="X")).rows == []
    assert (await conn.identifier_lookup(None, value="x")).rows == []


# --- Routed through the seam (fake build_analytics_graph_ops) ------------


class _FakeOps:
    """Records (method, args) calls; returns canned rows per method name."""

    def __init__(self, **returns):
        self.calls: dict[str, tuple] = {}
        self._returns = returns

    def _record(self, method: str, *args):
        self.calls[method] = args
        return self._returns.get(method, [])

    def entity_core(self, name):
        return self._record("entity_core", name)

    def entity_neighbors(self, name, top_n):
        return self._record("entity_neighbors", name, top_n)

    def entity_identifiers(self, name, id_types, top_n):
        return self._record("entity_identifiers", name, id_types, top_n)

    def entity_communities(self, name):
        return self._record("entity_communities", name)

    def neighbors_by_relation(self, name, rel, polarity, top_n):
        return self._record("neighbors_by_relation", name, rel, polarity, top_n)

    def common_connections(self, a, b, top_n):
        return self._record("common_connections", a, b, top_n)

    def identifier_lookup(self, value):
        return self._record("identifier_lookup", value)

    def shared_identifier_entities(self, id_types, min_owners, top_n):
        return self._record("shared_identifier_entities", id_types, min_owners, top_n)

    def connection_path(self, source, target, hops):
        return self._record("connection_path", source, target, hops)

    def cooccurrence(self, name, top_n):
        return self._record("cooccurrence", name, top_n)


def _patch_ops(monkeypatch, ops):
    monkeypatch.setattr(conn, "build_analytics_graph_ops", lambda store: ops)


@pytest.mark.asyncio
async def test_entity_dossier_routes_through_seam(monkeypatch):
    ops = _FakeOps(
        entity_core=[{"name": "A"}],
        entity_neighbors=[{"rel": "OWNS", "name": "B", "ntype": "Organization", "w": 1.0}],
        entity_identifiers=[{"id_type": "INN", "value": "1"}],
        entity_communities=[{"level": 0, "title": "T"}],
    )
    _patch_ops(monkeypatch, ops)

    res = await conn.entity_dossier(object(), name="A", top_n=10)

    assert ops.calls["entity_core"] == ("A",)
    assert ops.calls["entity_neighbors"] == ("A", 10)
    assert ops.calls["entity_identifiers"][0] == "A"
    assert ops.calls["entity_communities"] == ("A",)
    row = res.rows[0]
    assert row["core"] == {"name": "A"}
    assert row["connections"][0]["name"] == "B"
    assert row["identifiers"][0]["id_type"] == "INN"
    assert row["communities"][0]["title"] == "T"


@pytest.mark.asyncio
async def test_entity_dossier_empty_core_short_circuits(monkeypatch):
    ops = _FakeOps(entity_core=[])
    _patch_ops(monkeypatch, ops)

    res = await conn.entity_dossier(object(), name="Ghost")

    assert res.rows == []
    # neighbours/identifiers/communities never called once core is empty
    assert "entity_neighbors" not in ops.calls


@pytest.mark.asyncio
async def test_neighbors_by_relation_routes_through_seam(monkeypatch):
    ops = _FakeOps(neighbors_by_relation=[{"name": "B", "w": 1.0}])
    _patch_ops(monkeypatch, ops)

    res = await conn.neighbors_by_relation(
        object(), name="A", rel_type="OWNS", polarity="negated", top_n=7
    )

    assert ops.calls["neighbors_by_relation"] == ("A", "OWNS", "negated", 7)
    assert res.rows == [{"name": "B", "w": 1.0}]


@pytest.mark.asyncio
async def test_common_connections_routes_through_seam(monkeypatch):
    ops = _FakeOps(common_connections=[{"name": "M", "type": "Organization", "via": ["OWNS"]}])
    _patch_ops(monkeypatch, ops)

    res = await conn.common_connections(object(), a="A", b="B", top_n=5)

    assert ops.calls["common_connections"] == ("A", "B", 5)
    assert res.rows[0]["name"] == "M"


@pytest.mark.asyncio
async def test_connection_path_routes_through_seam_with_clamped_hops(monkeypatch):
    ops = _FakeOps(connection_path=[{"path": ["A", "B"], "rels": ["OWNS"], "hops": 1}])
    _patch_ops(monkeypatch, ops)

    res = await conn.connection_path(object(), source="A", target="B", max_hops=99)

    assert ops.calls["connection_path"] == ("A", "B", 12)  # clamped
    assert res.rows[0]["path"] == ["A", "B"]


@pytest.mark.asyncio
async def test_shared_identifier_entities_routes_through_seam(monkeypatch):
    ops = _FakeOps(
        shared_identifier_entities=[{"value": "1", "id_type": "INN", "owners": ["A", "B"]}]
    )
    _patch_ops(monkeypatch, ops)

    res = await conn.shared_identifier_entities(object(), id_type="INN", top_n=5)

    assert ops.calls["shared_identifier_entities"] == ("INN", 2, 5)
    assert res.rows[0]["owners"] == ["A", "B"]


@pytest.mark.asyncio
async def test_identifier_lookup_routes_through_seam(monkeypatch):
    ops = _FakeOps(identifier_lookup=[{"name": "A", "labels": ["Organization"], "rel": "HAS_ID"}])
    _patch_ops(monkeypatch, ops)

    res = await conn.identifier_lookup(object(), value="7701234567")

    assert ops.calls["identifier_lookup"] == ("7701234567",)
    assert res.rows[0]["name"] == "A"


@pytest.mark.asyncio
async def test_cooccurrence_routes_through_seam(monkeypatch):
    ops = _FakeOps(cooccurrence=[])
    _patch_ops(monkeypatch, ops)

    res = await conn.cooccurrence(object(), name="A", top_n=5)

    assert ops.calls["cooccurrence"] == ("A", 5)
    assert res.rows == []
