"""Wiki-editor graph ops (dirty-flag bookkeeping + article-context
reads/writes).

``NebulaWikiGraphOps`` implements the ops in nGQL; chunk-dependent
reads (`read_citations`/`read_source_docs`) return `[]` under nebula
(chunks are not nebula graph nodes — deferred, like doc↔community).
"""
from __future__ import annotations

import time
from typing import Any, Protocol

from loguru import logger


class WikiGraphOps(Protocol):
    def mark_dirty(self, names: list[str]) -> None: ...

    def select_dirty(self, limit: int) -> list[str]: ...

    def clear_dirty(self, name: str, digest: str) -> None: ...

    def mark_all_dirty(self) -> None: ...

    def read_subgraph(self, name: str, max_relations: int) -> list[dict]: ...

    def read_citations(self, name: str, k: int) -> list[dict]: ...

    def read_source_docs(self, name: str) -> list[str]: ...

    def read_wiki_hash(self, name: str) -> str: ...

    def write_page_title(self, name: str, title: str) -> None: ...


class NebulaWikiGraphOps:
    """nGQL wiki-editor graph ops. ``UPDATE VERTEX`` is a partial update
    (preserves the entity's other columns); values are inline-quoted
    (nebula binds no params here). Chunk-dependent reads (citations,
    source docs) are out of scope under nebula (chunks aren't nebula graph
    nodes) and always return ``[]``."""

    # Shared across instances so the chunk-deferred note logs once per
    # process, not once per entity/ops-instance.
    _chunk_deferred_logged = False

    def __init__(self, store: Any):
        self._store = store

    def mark_dirty(self, names: list[str]) -> None:
        from loguru import logger

        from src.graph.nebula_store import _q, entity_vid

        now = int(time.time() * 1000)
        for name in names:
            vid = entity_vid(name)
            # Per-name resilience: nebula UPDATE VERTEX RAISES on a missing
            # vertex, and mark_dirty is called with
            # relation endpoints that may reference an ER-merged-away entity
            # with no live vertex. Catch per-name so one missing name doesn't
            # abort the rest of the batch (missing names are a no-op).
            try:
                self._store.structured_query(
                    f"UPDATE VERTEX ON `Entity` {_q(vid)} SET "
                    f"wiki_dirty = true, wiki_dirty_at = {now};"
                )
            except Exception as exc:
                logger.debug("mark_dirty: skipped {n} (no live vertex?): {e}", n=name, e=exc)

    def select_dirty(self, limit: int) -> list[str]:
        rows = self._store.structured_query(
            "LOOKUP ON `Entity` WHERE `Entity`.wiki_dirty == true YIELD "
            "`Entity`.name AS name, `Entity`.wiki_dirty_at AS at "
            f"| ORDER BY $-.at ASC | LIMIT {int(limit)};"
        )
        return [r["name"] for r in (rows or []) if r.get("name")]

    def clear_dirty(self, name: str, digest: str) -> None:
        from src.graph.nebula_store import _q, entity_vid

        vid = entity_vid(name)
        now = int(time.time() * 1000)
        self._store.structured_query(
            f"UPDATE VERTEX ON `Entity` {_q(vid)} SET "
            f"wiki_dirty = false, wiki_hash = {_q(digest)}, "
            f"wiki_synced_at = {now};"
        )

    def mark_all_dirty(self) -> None:
        # Per-vertex UPDATE (no bulk "SET on all matches" in nGQL) —
        # expensive at scale. Admin-only / rare (full-rebuild trigger).
        from src.graph.nebula_store import _q

        rows = self._store.structured_query(
            "LOOKUP ON `Entity` WHERE `Entity`.wiki_dirty == false "
            "YIELD id(vertex) AS vid;"
        )
        now = int(time.time() * 1000)
        for row in rows or []:
            vid = row.get("vid")
            if not vid:
                continue
            self._store.structured_query(
                f"UPDATE VERTEX ON `Entity` {_q(vid)} SET "
                f"wiki_dirty = true, wiki_dirty_at = {now};"
            )

    def read_subgraph(self, name: str, max_relations: int) -> list[dict]:
        from src.graph.nebula_store import _q, entity_vid

        vid = entity_vid(name)
        ent_rows = self._store.structured_query(
            f"FETCH PROP ON `Entity` {_q(vid)} YIELD "
            "`Entity`.name AS name, `Entity`.label AS label, "
            "`Entity`.description AS description, "
            "`Entity`.wikibase_qid AS qid, "
            "`Entity`.wiki_page_title AS page_title;"
        )
        if not ent_rows:
            return []
        ent = ent_rows[0]

        edge_rows = self._store.structured_query(
            f"GO FROM {_q(vid)} OVER `RELATED` BIDIRECT YIELD "
            "src(edge) AS s, dst(edge) AS d, `RELATED`.rel_type AS rl;"
        ) or []

        neighbours: list[tuple[str, str, Any]] = []
        neighbour_vids: set[str] = set()
        for row in edge_rows:
            s, d = row.get("s"), row.get("d")
            if s is None or d is None:
                continue
            nvid = d if s == vid else s
            direction = "out" if s == vid else "in"
            neighbours.append((nvid, direction, row.get("rl")))
            neighbour_vids.add(nvid)

        props_by_vid: dict[str, tuple[str, str, int]] = {}
        if neighbour_vids:
            listed = ", ".join(_q(v) for v in neighbour_vids)
            prop_rows = self._store.structured_query(
                f"FETCH PROP ON `Entity` {listed} YIELD id(vertex) AS vid, "
                "`Entity`.name AS nn, `Entity`.label AS nl, "
                "`Entity`.mention_count AS mc;"
            ) or []
            for r in prop_rows:
                v = r.get("vid")
                if v:
                    props_by_vid[v] = (
                        r.get("nn") or "", r.get("nl") or "",
                        int(r.get("mc") or 0),
                    )

        scored: list[tuple[int, str, dict]] = []
        for nvid, direction, rl in neighbours:
            if nvid not in props_by_vid:
                continue
            nn, nl, mc = props_by_vid[nvid]
            scored.append((mc, nn, {
                "rl": rl, "dir": direction, "nn": nn, "nl": nl, "rd": "",
            }))
        scored.sort(key=lambda t: (-t[0], t[1]))
        relations = [rel for _, _, rel in scored][:max_relations]

        return [{
            "name": ent.get("name") or "",
            "label": ent.get("label") or "",
            "description": ent.get("description") or "",
            "qid": ent.get("qid") or "",
            "page_title": ent.get("page_title") or "",
            "relations": relations,
        }]

    def _log_chunk_deferred_once(self, method: str, name: str) -> None:
        if not NebulaWikiGraphOps._chunk_deferred_logged:
            NebulaWikiGraphOps._chunk_deferred_logged = True
            logger.debug(
                "NebulaWikiGraphOps.{method}: chunk-dependent, returns [] "
                "under nebula (name={name})", method=method, name=name,
            )

    def read_citations(self, name: str, k: int) -> list[dict]:
        self._log_chunk_deferred_once("read_citations", name)
        return []

    def read_source_docs(self, name: str) -> list[str]:
        self._log_chunk_deferred_once("read_source_docs", name)
        return []

    def read_wiki_hash(self, name: str) -> str:
        from src.graph.nebula_store import _q, entity_vid

        vid = entity_vid(name)
        rows = self._store.structured_query(
            f"FETCH PROP ON `Entity` {_q(vid)} YIELD `Entity`.wiki_hash AS h;"
        )
        return (rows[0].get("h") or "") if rows else ""

    def write_page_title(self, name: str, title: str) -> None:
        from src.graph.nebula_store import _q, entity_vid

        vid = entity_vid(name)
        self._store.structured_query(
            f"UPDATE VERTEX ON `Entity` {_q(vid)} SET "
            f"wiki_page_title = {_q(title)};"
        )


def build_wiki_graph_ops(store: Any) -> WikiGraphOps:
    return NebulaWikiGraphOps(store)
