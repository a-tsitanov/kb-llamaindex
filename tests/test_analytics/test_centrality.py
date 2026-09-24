import pytest

from src.analytics.primitives import centrality as c
from tests.test_analytics.conftest import _FakeStore


@pytest.mark.asyncio
async def test_top_central_reads_metric_property():
    # _FakeStore drives the default NebulaCentralityGraphOps path.
    store = _FakeStore(rows=[{"name": "A", "score": 0.9}])
    res = await c.top_central_entities(store, metric="betweenness", top_n=5)
    assert res.params["top_n"] == 5 and res.params["metric"] == "betweenness"
    assert res.rows[0]["name"] == "A"
    # metric inlined (as a column name) into the seam's nGQL
    assert store.last_cypher == (
        "MATCH (e:`Entity`) WHERE e.`Entity`.betweenness > 0 "
        "RETURN e.`Entity`.name AS name, e.`Entity`.betweenness AS score "
        "ORDER BY score DESC LIMIT 5;"
    )


@pytest.mark.asyncio
async def test_top_central_rejects_unknown_metric():
    store = _FakeStore(rows=[{"x": 1}])
    res = await c.top_central_entities(store, metric="bogus")
    assert res.rows == []  # allowlist guard → empty, no injection
