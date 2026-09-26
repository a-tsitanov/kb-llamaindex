"""Analytics "connections" graph ops (read-only, fail-soft neighbourhood
reads).

Each method preserves the fail-soft behaviour of
``analytics/store_query.py::run_rows`` (``try/except Exception -> []``,
same warning log) — the seam replaces the raw ``run_rows(store, cypher,
params)`` call inside each primitive, not the fail-soft wrapper itself.

``NebulaAnalyticsGraphOps`` implements the reads in nGQL
(GO/FETCH/FIND SHORTEST PATH; inline values, no param_map — mirrors
``NebulaWikiGraphOps``/``NebulaGraphEdgeExport``). Each method is
fail-soft (``try/except -> []``, same warning log) via
the ``_nebula_fail_soft`` decorator. ``cooccurrence`` is Chunk-dependent
and always returns ``[]`` under nebula (deferred, like doc↔community).
"""
from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, Protocol

from loguru import logger

from src.analytics.ids import ID_TYPES


class AnalyticsGraphOps(Protocol):
    def entity_core(self, name: str) -> list[dict]: ...

    def entity_neighbors(self, name: str, top_n: int) -> list[dict]: ...

    def entity_identifiers(self, name: str, id_types: list[str], top_n: int) -> list[dict]: ...

    def entity_communities(self, name: str) -> list[dict]: ...

    def neighbors_by_relation(
        self, name: str, rel: str, polarity: str | None, top_n: int
    ) -> list[dict]: ...

    def common_connections(self, a: str, b: str, top_n: int) -> list[dict]: ...

    def identifier_lookup(self, value: str) -> list[dict]: ...

    def shared_identifier_entities(
        self, id_types: str | None, min_owners: int, top_n: int
    ) -> list[dict]: ...

    def connection_path(self, source: str, target: str, hops: int) -> list[dict]: ...

    def cooccurrence(self, name: str, top_n: int) -> list[dict]: ...


# Batch size for the read-side chunked GO/FETCH calls in
# ``shared_identifier_entities`` (a graph-wide scan). Deliberately a
# LOCAL constant, not ``settings.nebula.write_batch_size`` — that setting
# governs INSERT VERTEX/EDGE write batching, an unrelated concern.
_SHARED_ID_BATCH = 200


def _nebula_fail_soft(method: Callable[..., list[dict]]) -> Callable[..., list[dict]]:
    """``run_rows``-style ``try/except -> []`` (same
    warning log) at the method level — nebula methods issue several GO/FETCH
    calls each, so the guard wraps the whole method body rather than one
    query."""

    @functools.wraps(method)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> list[dict]:
        try:
            return method(self, *args, **kwargs)
        except Exception as exc:  # fail-soft, like store_query.run_rows
            logger.warning("analytics query failed: {e}", e=exc)
            return []

    return wrapper


class NebulaAnalyticsGraphOps:
    """nGQL connections graph ops: GO/FETCH for neighbourhood reads,
    FIND SHORTEST PATH for ``connection_path``. Values are inline-quoted
    (nebula binds no params — ``_q``/``entity_vid`` from ``nebula_store``).
    Every method (except ``cooccurrence``, which never queries) is
    fail-soft via ``_nebula_fail_soft``."""

    def __init__(self, store: Any):
        self._store = store

    def _exec(self, stmt: str) -> list[dict]:
        return list(self._store.structured_query(stmt) or [])

    @_nebula_fail_soft
    def entity_core(self, name: str) -> list[dict]:
        from src.graph.nebula_store import _q, entity_vid

        vid = entity_vid(name)
        rows = self._exec(
            f"FETCH PROP ON `Entity` {_q(vid)} YIELD "
            "`Entity`.name AS name, `Entity`.description AS description, "
            "`Entity`.label AS label, `Entity`.mention_count AS mention_count;"
        )
        if not rows:
            return []
        r = rows[0]
        return [{
            "name": r.get("name") or "",
            "description": r.get("description") or "",
            "labels": [r.get("label") or ""],
            "mention_count": r.get("mention_count"),
        }]

    @_nebula_fail_soft
    def entity_neighbors(self, name: str, top_n: int) -> list[dict]:
        from src.graph.nebula_store import _q, entity_vid

        vid = entity_vid(name)
        edge_rows = self._exec(
            f"GO FROM {_q(vid)} OVER `RELATED` BIDIRECT YIELD "
            "src(edge) AS s, dst(edge) AS d, `RELATED`.rel_type AS rl, "
            "`RELATED`.weight AS w, `RELATED`.polarity AS pol;"
        )
        if not edge_rows:
            return []
        neighbours: list[tuple[str, Any, Any]] = []
        nvids: set[str] = set()
        for row in edge_rows:
            s, d = row.get("s"), row.get("d")
            if s is None or d is None:
                continue
            if row.get("pol") == "negated":
                continue
            nvid = d if s == vid else s
            neighbours.append((nvid, row.get("rl"), row.get("w")))
            nvids.add(nvid)
        if not neighbours:
            return []
        props_by_vid = self._fetch_entity_props(nvids)
        out = []
        for nvid, rl, w in neighbours:
            if nvid not in props_by_vid:
                continue
            nname, nlabel = props_by_vid[nvid]
            if nlabel in ID_TYPES:
                continue
            out.append({"rel": rl, "name": nname, "ntype": nlabel, "w": w})
        out.sort(key=lambda x: x["w"] if x["w"] is not None else 0, reverse=True)
        return out[:top_n]

    @_nebula_fail_soft
    def entity_identifiers(self, name: str, id_types: list[str], top_n: int) -> list[dict]:
        from src.graph.nebula_store import _q, entity_vid

        vid = entity_vid(name)
        edge_rows = self._exec(
            f"GO FROM {_q(vid)} OVER `RELATED` BIDIRECT YIELD "
            "src(edge) AS s, dst(edge) AS d;"
        )
        if not edge_rows:
            return []
        nvids: set[str] = set()
        for row in edge_rows:
            s, d = row.get("s"), row.get("d")
            if s is None or d is None:
                continue
            nvids.add(d if s == vid else s)
        if not nvids:
            return []
        props_by_vid = self._fetch_entity_props(nvids)
        out = []
        for nname, nlabel in props_by_vid.values():
            if nlabel in id_types:
                out.append({"id_type": nlabel, "value": nname})
        return out[:top_n]

    @_nebula_fail_soft
    def entity_communities(self, name: str) -> list[dict]:
        from src.graph.nebula_store import _q, entity_vid

        vid = entity_vid(name)
        edge_rows = self._exec(
            f"GO FROM {_q(vid)} OVER `IN_COMMUNITY` YIELD dst(edge) AS c;"
        )
        if not edge_rows:
            return []
        cvids = {r.get("c") for r in edge_rows if r.get("c")}
        if not cvids:
            return []
        listed = ", ".join(_q(v) for v in cvids)
        rows = self._exec(
            f"FETCH PROP ON `Community` {listed} YIELD "
            "`Community`.level AS level, `Community`.title AS title;"
        )
        return [{"level": r.get("level"), "title": r.get("title") or ""} for r in rows]

    @_nebula_fail_soft
    def neighbors_by_relation(
        self, name: str, rel: str, polarity: str | None, top_n: int
    ) -> list[dict]:
        from src.graph.nebula_store import _q, entity_vid

        vid = entity_vid(name)
        edge_rows = self._exec(
            f"GO FROM {_q(vid)} OVER `RELATED` BIDIRECT YIELD "
            "src(edge) AS s, dst(edge) AS d, `RELATED`.rel_type AS rl, "
            "`RELATED`.weight AS w, `RELATED`.polarity AS pol, "
            "`RELATED`.valid_from AS vf, `RELATED`.valid_to AS vt;"
        )
        if not edge_rows:
            return []
        neighbours: list[tuple[str, Any, Any, Any]] = []
        nvids: set[str] = set()
        for row in edge_rows:
            s, d = row.get("s"), row.get("d")
            if s is None or d is None:
                continue
            if row.get("rl") != rel:
                continue
            if polarity is not None and row.get("pol") != polarity:
                continue
            nvid = d if s == vid else s
            neighbours.append((nvid, row.get("w"), row.get("vf"), row.get("vt")))
            nvids.add(nvid)
        if not neighbours:
            return []
        listed = ", ".join(_q(v) for v in nvids)
        prop_rows = self._exec(
            f"FETCH PROP ON `Entity` {listed} YIELD id(vertex) AS vid, "
            "`Entity`.name AS name;"
        )
        names_by_vid = {r["vid"]: r.get("name") or "" for r in prop_rows if r.get("vid")}
        out = []
        for nvid, w, vf, vt in neighbours:
            if nvid not in names_by_vid:
                continue
            out.append({
                "name": names_by_vid[nvid], "w": w,
                "valid_from": vf, "valid_to": vt,
            })
        out.sort(key=lambda x: x["w"] if x["w"] is not None else 0, reverse=True)
        return out[:top_n]

    @_nebula_fail_soft
    def common_connections(self, a: str, b: str, top_n: int) -> list[dict]:
        from src.graph.nebula_store import _q, entity_vid

        va, vb = entity_vid(a), entity_vid(b)

        def _neighbours(vid: str) -> dict[str, set[str]]:
            rows = self._exec(
                f"GO FROM {_q(vid)} OVER `RELATED` BIDIRECT YIELD "
                "src(edge) AS s, dst(edge) AS d, `RELATED`.rel_type AS rl, "
                "`RELATED`.polarity AS pol;"
            )
            out: dict[str, set[str]] = {}
            for row in rows:
                s, d = row.get("s"), row.get("d")
                if s is None or d is None:
                    continue
                if row.get("pol") == "negated":
                    continue
                nvid = d if s == vid else s
                out.setdefault(nvid, set()).add(row.get("rl") or "")
            return out

        na = _neighbours(va)
        nb = _neighbours(vb)
        shared_vids = set(na) & set(nb)
        if not shared_vids:
            return []
        props_by_vid = self._fetch_entity_props(shared_vids)
        out = []
        for mvid in shared_vids:
            if mvid not in props_by_vid:
                continue
            mname, mtype = props_by_vid[mvid]
            via = sorted(na[mvid]) + sorted(nb[mvid])
            out.append({"name": mname, "type": mtype, "via": via})
        out.sort(key=lambda x: len(x["via"]), reverse=True)
        return out[:top_n]

    @_nebula_fail_soft
    def identifier_lookup(self, value: str) -> list[dict]:
        from src.graph.nebula_store import _q, entity_vid

        vid = entity_vid(value)
        self_rows = self._exec(
            f"FETCH PROP ON `Entity` {_q(vid)} YIELD `Entity`.label AS label;"
        )
        if not self_rows or self_rows[0].get("label") not in ID_TYPES:
            return []
        edge_rows = self._exec(
            f"GO FROM {_q(vid)} OVER `RELATED` BIDIRECT YIELD "
            "src(edge) AS s, dst(edge) AS d, `RELATED`.rel_type AS rl;"
        )
        if not edge_rows:
            return []
        neighbours: list[tuple[str, Any]] = []
        nvids: set[str] = set()
        for row in edge_rows:
            s, d = row.get("s"), row.get("d")
            if s is None or d is None:
                continue
            nvid = d if s == vid else s
            neighbours.append((nvid, row.get("rl")))
            nvids.add(nvid)
        if not nvids:
            return []
        props_by_vid = self._fetch_entity_props(nvids)
        out = []
        for nvid, rl in neighbours:
            if nvid not in props_by_vid:
                continue
            nname, nlabel = props_by_vid[nvid]
            if nlabel in ID_TYPES:
                continue
            out.append({"name": nname, "labels": [nlabel], "rel": rl})
        return out

    @_nebula_fail_soft
    def shared_identifier_entities(
        self, id_types: str | None, min_owners: int, top_n: int
    ) -> list[dict]:
        # "Correct but simple" graph-wide scan (per design doc — lower
        # priority than the per-entity reads above). No dedicated `label`
        # index exists on `Entity` (only `name`/`wiki_dirty` are indexed);
        # LOOKUP falls back to a full `Entity` tag-scan filtered
        # server-side by the WHERE predicate — O(entities), i.e. a
        # graph-wide scan. GO/FETCH
        # calls are chunked (``_SHARED_ID_BATCH``) to bound round-trips.
        from src.graph.nebula_store import _chunks, _q

        candidate_labels = [id_types] if id_types else list(ID_TYPES)
        id_vids: dict[str, tuple[str, str]] = {}  # vid -> (name, id_type)
        for label in candidate_labels:
            rows = self._exec(
                f"LOOKUP ON `Entity` WHERE `Entity`.label == {_q(label)} "
                "YIELD id(vertex) AS vid, `Entity`.name AS name;"
            )
            for r in rows:
                v = r.get("vid")
                if v:
                    id_vids[v] = (r.get("name") or "", label)
        if not id_vids:
            return []

        owners_by_id: dict[str, set[str]] = {v: set() for v in id_vids}
        for chunk in _chunks(list(id_vids), _SHARED_ID_BATCH):
            listed = ", ".join(_q(v) for v in chunk)
            edge_rows = self._exec(
                f"GO FROM {listed} OVER `RELATED` BIDIRECT YIELD "
                "src(edge) AS s, dst(edge) AS d;"
            )
            for row in edge_rows:
                s, d = row.get("s"), row.get("d")
                if s is None or d is None or s == d:
                    continue
                if s in owners_by_id:
                    owners_by_id[s].add(d)
                if d in owners_by_id:
                    owners_by_id[d].add(s)

        all_owner_vids: set[str] = set()
        for owners in owners_by_id.values():
            all_owner_vids |= owners
        owner_props = self._fetch_entity_props(all_owner_vids)

        out = []
        for vid, (idname, id_type) in id_vids.items():
            owner_names = sorted({
                owner_props[ov][0] for ov in owners_by_id.get(vid, set())
                if ov in owner_props and owner_props[ov][1] not in ID_TYPES
            })
            if len(owner_names) >= min_owners:
                out.append({"value": idname, "id_type": id_type, "owners": owner_names})
        out.sort(key=lambda x: len(x["owners"]), reverse=True)
        return out[:top_n]

    @_nebula_fail_soft
    def connection_path(self, source: str, target: str, hops: int) -> list[dict]:
        from src.graph.nebula_store import _q, entity_vid

        va, vb = entity_vid(source), entity_vid(target)
        rows = self._exec(
            f"FIND SHORTEST PATH FROM {_q(va)} TO {_q(vb)} OVER * BIDIRECT "
            f"UPTO {int(hops)} STEPS YIELD path AS p;"
        )
        if not rows:
            return []
        path = rows[0].get("p")
        if path is None:
            return []
        names, rels = self._path_names_and_rels(path)
        if not names:
            return []
        return [{"path": names, "rels": rels, "hops": len(rels)}]

    def cooccurrence(self, name: str, top_n: int) -> list[dict]:
        self._log_cooccurrence_deferred_once(name)
        return []

    # -- shared helpers ----------------------------------------------

    def _fetch_entity_props(self, vids: set[str]) -> dict[str, tuple[str, str]]:
        """FETCH name+label for a set of Entity vids -> {vid: (name, label)}."""
        from src.graph.nebula_store import _q

        if not vids:
            return {}
        listed = ", ".join(_q(v) for v in vids)
        rows = self._exec(
            f"FETCH PROP ON `Entity` {listed} YIELD id(vertex) AS vid, "
            "`Entity`.name AS name, `Entity`.label AS label;"
        )
        out: dict[str, tuple[str, str]] = {}
        for r in rows:
            v = r.get("vid")
            if v:
                out[v] = (r.get("name") or "", r.get("label") or "")
        return out

    def _path_names_and_rels(self, path: Any) -> tuple[list[str], list[str]]:
        """Extract ordered node names + edge rel-types from a
        ``PathWrapper``-shaped object (``.nodes()``/``.relationships()`` —
        the nebula3 data API; see ``nebula_store.subgraph`` for the same
        node/edge-reading pattern). Node names are resolved via a separate
        FETCH (path nodes carry only a vid unless the query used
        ``WITH PROP``, which this one does not). Edge rel-type is read
        from the ``RELATED.rel_type`` property when present (all
        entity-entity edges share the single nebula edge type `RELATED`,
        with the semantic type stored in that property — see
        ``nebula_store.upsert_relations``); falls back to
        ``relationship.edge_name()`` (-> "RELATED") if the path didn't
        carry edge properties."""
        from src.graph.nebula_store import _q

        nodes = path.nodes() if hasattr(path, "nodes") else []
        vids: list[str] = []
        for n in nodes:
            if not hasattr(n, "get_id"):
                continue
            vid = n.get_id().cast()
            if vid is not None:
                vids.append(vid)
        if not vids:
            return [], []

        listed = ", ".join(_q(v) for v in vids)
        prop_rows = self._exec(
            f"FETCH PROP ON `Entity` {listed} YIELD id(vertex) AS vid, "
            "`Entity`.name AS name;"
        )
        names_by_vid = {r["vid"]: r.get("name") or "" for r in prop_rows if r.get("vid")}
        names = [names_by_vid.get(v, "") for v in vids]

        rel_types: list[str] = []
        for r in path.relationships() if hasattr(path, "relationships") else []:
            rl = None
            if hasattr(r, "properties"):
                props = r.properties() or {}
                rt = props.get("rel_type")
                if rt is not None:
                    rl = rt.cast() if hasattr(rt, "cast") else rt
            if not rl and hasattr(r, "edge_name"):
                rl = r.edge_name()
            rel_types.append(rl or "")
        return names, rel_types

    def _log_cooccurrence_deferred_once(self, name: str) -> None:
        if not NebulaAnalyticsGraphOps._cooccurrence_deferred_logged:
            NebulaAnalyticsGraphOps._cooccurrence_deferred_logged = True
            logger.debug(
                "NebulaAnalyticsGraphOps.cooccurrence: Chunk-dependent, "
                "returns [] under nebula (name={name})", name=name,
            )

    # Shared across instances so the deferred note logs once per process.
    _cooccurrence_deferred_logged = False


def build_analytics_graph_ops(store: Any) -> AnalyticsGraphOps:
    return NebulaAnalyticsGraphOps(store)
