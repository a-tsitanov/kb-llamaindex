from dataclasses import replace

from src.tenancy.cache import evict_stale_generations
from src.tenancy.context import default_graph_context, new_graph_context


def test_cache_key_includes_generation():
    g = replace(new_graph_context("acme"), generation=7)
    assert g.cache_key == "acme#7"
    assert default_graph_context().cache_key == "default#0"


def test_evict_drops_only_older_generations_of_same_id():
    old = replace(new_graph_context("acme"), generation=1)
    new = replace(new_graph_context("acme"), generation=2)
    other = new_graph_context("acme_x")
    cache = {old.cache_key: "o", new.cache_key: "n", other.cache_key: "x"}
    assert evict_stale_generations(cache, new) == ["o"]
    assert cache == {new.cache_key: "n", other.cache_key: "x"}
