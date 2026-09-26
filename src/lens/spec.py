"""View-spec: LLM-written extraction rules made of paths, never values.

``materialize`` is also the validator: every path must resolve against the
real payload, every type must be in the vocabulary.  Any problem raises
``SpecError`` with all messages so the Normalizer can ask for one repair.

Path scopes inside a rule:
- ``$...``      relative to the current item (or the payload root when ``each`` is null)
- ``$root...``  the whole payload (e.g. the "center" of a neighbours response)
- ``$args...``  the tool call arguments (e.g. the entity id the call was about)

Relation endpoints may be objects of this call OR ``known_keys`` (objects already on
the canvas and the user's @mentions) — that is how new results attach to old ones.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.lens.model import AggregateEl, Column, ObjectEl, Ref, RelationEl
from src.lens.paths import PathError, iter_path


class ObjectRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    each: str | None = None
    id: str
    label: str
    type: str  # fixed type, or the fallback when ``type_path`` is set
    type_path: str | None = None  # per-item type, mapped onto the vocabulary
    attrs: dict[str, str] = Field(default_factory=dict)


# Source type names (KB extractor labels etc.) → Lens vocabulary. Keys are lower-case.
TYPE_ALIASES = {
    "organization": "organization", "organisation": "organization", "company": "organization",
    "person": "person", "people": "person",
    "location": "location", "geographiclocation": "location", "place": "location",
    "country": "location", "city": "location",
    "event": "event", "eventoraction": "event",
    "concept": "topic", "topic": "topic",
    "document": "document", "email": "document", "url": "document",
}


class RelationRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    each: str
    from_id: str
    to_each: str | None = None
    to_id: str
    kind: str


class ViewSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objects: list[ObjectRule] = Field(default_factory=list)
    relations: list[RelationRule] = Field(default_factory=list)


@dataclass
class Materialized:
    objects: list[ObjectEl] = field(default_factory=list)
    relations: list[RelationEl] = field(default_factory=list)
    aggregates: list[AggregateEl] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.objects or self.relations or self.aggregates)


class SpecError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass
class _Ctx:
    payload: Any
    args: dict


def _scoped(item: Any, path: str, ctx: _Ctx) -> list[tuple[str, Any]]:
    if path.startswith("$root"):
        return iter_path(ctx.payload, "$" + path[len("$root"):])
    if path.startswith("$args"):
        return iter_path(ctx.args, "$" + path[len("$args"):])
    return iter_path(item, path)


def _scalar(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return v.strip() or None
    return None


def _one(item: Any, path: str, ctx: _Ctx) -> str | None:
    m = _scoped(item, path, ctx)
    return _scalar(m[0][1]) if len(m) == 1 else None


def _expand(matches: list[tuple[str, Any]]) -> list[tuple[str, Any]]:
    """``each`` that hits ONE list (``$.entities`` instead of ``$.entities[*]``) means
    its elements — LLMs write it that way often enough to be worth forgiving."""
    if len(matches) == 1 and isinstance(matches[0][1], list):
        base, lst = matches[0]
        return [(f"{base}[{i}]", v) for i, v in enumerate(lst)]
    return matches


def _items(ctx: _Ctx, each: str | None) -> list[tuple[str, Any]]:
    return _expand(_scoped(ctx.payload, each, ctx)) if each else [("$", ctx.payload)]


def _item_type(rule: ObjectRule, item: Any, ctx: _Ctx, vocabulary: Collection[str]) -> str:
    if rule.type_path is None:
        return rule.type
    raw = _one(item, rule.type_path, ctx)
    if raw is None:
        return rule.type
    mapped = TYPE_ALIASES.get(raw.lower(), raw.lower())
    return mapped if mapped in vocabulary else rule.type


def _objects_for(
    rule: ObjectRule, ctx: _Ctx, ns: str, call_id: str, errors: list[str],
    vocabulary: Collection[str],
) -> dict[str, ObjectEl] | None:
    """Objects of one rule, deduplicated by key (refs merged)."""
    try:
        items = _items(ctx, rule.each)
    except PathError as e:
        errors.append(f"object rule {rule.name!r}: {e}")
        return None
    if rule.each and not items:
        errors.append(f"object rule {rule.name!r}: each {rule.each!r} matched nothing")
        return None
    built: dict[str, ObjectEl] = {}
    try:
        for base, item in items:
            id_v, label_v = _one(item, rule.id, ctx), _one(item, rule.label, ctx)
            if id_v is None or label_v is None:
                continue
            attrs: dict[str, Any] = {}
            for name, rel in rule.attrs.items():
                m = _scoped(item, rel, ctx)
                if len(m) == 1:
                    attrs[name] = m[0][1]
                elif len(m) > 1:
                    attrs[name] = [v for _, v in m]
            key = f"{ns}:{id_v}"
            ref = Ref(call_id=call_id, path=base)
            if key in built:
                built[key].refs.append(ref)
            else:
                built[key] = ObjectEl(key=key, type=_item_type(rule, item, ctx, vocabulary),
                                      label=label_v, attrs=attrs, refs=[ref])
    except PathError as e:
        errors.append(f"object rule {rule.name!r}: {e}")
        return None
    if not built:
        errors.append(
            f"object rule {rule.name!r}: id {rule.id!r} / label {rule.label!r} "
            "resolved on no item"
        )
        return None
    return built


def _add_relation(relations: dict[str, RelationEl], rel: RelationEl) -> None:
    if rel.key in relations:
        known = {(r.call_id, r.path) for r in relations[rel.key].refs}
        relations[rel.key].refs.extend(r for r in rel.refs if (r.call_id, r.path) not in known)
    else:
        relations[rel.key] = rel


def materialize(
    spec: ViewSpec,
    payload: Any,
    *,
    namespace: str,
    call_id: str,
    vocabulary: Sequence[str],
    aggregate_threshold: int,
    args: dict | None = None,
    known_keys: Collection[str] = (),
    aggregate_preview: int = 0,
) -> Materialized:
    """``aggregate_preview``: when a rule is aggregated, its first N objects still go on
    the canvas so a big list is never a black box."""
    ctx = _Ctx(payload=payload, args=args or {})
    errors: list[str] = []
    out = Materialized()
    objects: dict[str, ObjectEl] = {}
    for rule in spec.objects:
        if rule.type not in vocabulary:
            errors.append(
                f"object rule {rule.name!r}: type {rule.type!r} not in vocabulary "
                f"{sorted(vocabulary)}"
            )
            continue
        built = _objects_for(rule, ctx, namespace, call_id, errors, vocabulary)
        if built is None:
            continue
        if rule.each and len(built) > aggregate_threshold:
            # ``/rows`` resolves each column against ONE row (item-relative paths
            # only); $root/$args scopes read the whole payload/args and can't be
            # resolved that way.
            if rule.id.startswith(("$root", "$args")) or rule.label.startswith(
                ("$root", "$args")
            ):
                errors.append(
                    f"aggregated rule {rule.name!r} must use item-relative id/label paths"
                )
                continue
            columns = [Column(name="id", path=rule.id), Column(name="label", path=rule.label)]
            for k, v in rule.attrs.items():
                if v.startswith(("$root", "$args")):
                    continue
                columns.append(Column(name=k, path=v))
            item_type = Counter(o.type for o in built.values()).most_common(1)[0][0]
            out.aggregates.append(AggregateEl(
                key=f"agg:{call_id}:{rule.name}",
                label=f"{item_type} · {len(built)}",
                item_type=item_type,
                count=len(built),
                rows_ref=Ref(call_id=call_id, path=rule.each),
                columns=columns,
            ))
            built = dict(list(built.items())[:aggregate_preview])
        for key, o in built.items():
            if key in objects:
                objects[key].refs.extend(o.refs)
            else:
                objects[key] = o

    endpoints = set(objects) | set(known_keys)
    relations: dict[str, RelationEl] = {}
    for rule in spec.relations:
        try:
            items = _expand(_scoped(payload, rule.each, ctx))
            if not items:
                errors.append(f"relation {rule.kind!r}: each {rule.each!r} matched nothing")
                continue
            for base, item in items:
                from_v = _one(item, rule.from_id, ctx)
                if from_v is None:
                    continue
                targets = _scoped(item, rule.to_each, ctx) if rule.to_each else [("$", item)]
                for _, target in targets:
                    to_v = _one(target, rule.to_id, ctx)
                    fk, tk = f"{namespace}:{from_v}", f"{namespace}:{to_v}"
                    if to_v is None or fk == tk or fk not in endpoints or tk not in endpoints:
                        continue
                    _add_relation(relations, RelationEl(
                        from_key=fk, to_key=tk, kind=rule.kind,
                        refs=[Ref(call_id=call_id, path=base)]))
        except PathError as e:
            errors.append(f"relation {rule.kind!r}: {e}")

    if errors:
        raise SpecError(errors)
    out.objects = list(objects.values())
    out.relations = list(relations.values())
    return out
