from src.config import TemporalSettings


def test_community_backend_reads_the_environment(monkeypatch):
    """And the operator's value wins over that default."""
    monkeypatch.setenv("TEMPORAL_COMMUNITY_BACKEND", "leidenalg")
    assert TemporalSettings().community_backend == "leidenalg"


def test_community_backend_is_constrained():
    import typing

    hints = typing.get_type_hints(TemporalSettings)
    # Literal["gds","leidenalg"]
    assert "gds" in typing.get_args(hints["community_backend"])
    assert "leidenalg" in typing.get_args(hints["community_backend"])
