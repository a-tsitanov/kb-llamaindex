from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.lens.config import LensSettings
from src.lens.model import (
    AggregateEl,
    Column,
    ObjectEl,
    Op,
    Ref,
    RelationEl,
)


def test_mcp_servers_parse_from_json_env(monkeypatch):
    monkeypatch.setenv(
        "LENS_MCP_SERVERS",
        '[{"name":"kb-tools","url":"http://mcp-tools:9002/mcp","token":"k1"}]',
    )
    s = LensSettings()
    assert s.mcp_servers[0].name == "kb-tools"
    assert s.mcp_servers[0].token.get_secret_value() == "k1"


def test_role_models_fall_back_to_litellm_large(monkeypatch):
    from src.config import settings

    monkeypatch.setattr(settings.litellm, "model_large", "big-model")
    s = LensSettings(model_planner="", model_normalizer="norm")
    assert s.planner_model() == "big-model"
    assert s.normalizer_model() == "norm"


def test_default_vocabulary_contains_core_types():
    s = LensSettings()
    assert {"person", "organization", "event", "ip", "certificate", "other"} <= set(s.vocabulary)


def test_relation_key_is_stable():
    r = RelationEl(from_key="kb:1", to_key="kb:2", kind="участник")
    assert r.key == "kb:1|участник|kb:2"


def test_aggregate_has_kind_discriminator():
    a = AggregateEl(
        key="agg:c1:hosts", label="ip · 30", item_type="ip", count=30,
        rows_ref=Ref(call_id="c1", path="$.hosts[*]"),
        columns=[Column(name="id", path="$.ip")],
    )
    assert a.model_dump()["kind"] == "aggregate"


def test_op_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        Op(workspace_id="w", seq=1, kind="explode", payload={}, input_id=None,
           created_at=datetime.now(UTC))


def test_object_defaults():
    o = ObjectEl(key="kb:1", type="person", label="X")
    assert o.attrs == {} and o.refs == []


def test_namespace_keys_and_cors_lists():
    # explicit stream_secret: a developer .env may set LENS_STREAM_SECRET
    s = LensSettings(api_keys=" a, b ,", cors_origins="http://x, http://y", stream_secret="")
    assert s.keys_list() == ["a", "b"] and s.cors_list() == ["http://x", "http://y"]
    assert s.stream_secret_value() == "a"
    s2 = LensSettings(mcp_servers=[{"name": "kb-tools", "namespace": "kb", "url": "u"}])
    assert s2.mcp_servers[0].ns == "kb"


def test_aggregate_preview_default():
    assert LensSettings().aggregate_preview == 10
