from src.config import TemporalSettings


def test_community_backend_reads_the_environment(monkeypatch):
    """And the operator's value wins over that default."""
    monkeypatch.setenv("TEMPORAL_COMMUNITY_BACKEND", "leidenalg")
    assert TemporalSettings().community_backend == "leidenalg"


def test_community_backend_is_constrained():
    import typing

    hints = typing.get_type_hints(TemporalSettings)
    # Literal["leidenalg","graphscope"] — "gds" removed with Neo4j
    assert typing.get_args(hints["community_backend"]) == ("leidenalg", "graphscope")


def test_community_backend_default_is_leidenalg(monkeypatch):
    monkeypatch.delenv("TEMPORAL_COMMUNITY_BACKEND", raising=False)
    monkeypatch.delenv("COMMUNITY_BACKEND", raising=False)
    from src.config import TemporalSettings

    assert TemporalSettings().community_backend == "leidenalg"


def test_legacy_gds_value_maps_to_leidenalg(monkeypatch):
    from src.config import TemporalSettings

    s = TemporalSettings(community_backend="gds")
    assert s.community_backend == "leidenalg"


def test_removed_flags_are_gone():
    from src.config import AgentSettings, TemporalSettings

    assert "centrality_backend" not in TemporalSettings.model_fields
    assert "er_vector_backend" not in AgentSettings.model_fields
    assert "community_vector_backend" not in AgentSettings.model_fields
