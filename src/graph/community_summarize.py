"""Community SUMMARIZE I/O (context reads + report write).

`NebulaCommunitySummarize` implements the ops in nGQL. `report_vec` is NOT written to the nebula vertex (Milvus owns it,
via the already-dispatched community report-vector store).
"""
from __future__ import annotations

from typing import Any, Protocol


class CommunitySummarize(Protocol):
    def read_member_context(self, *, community_id: str, level: int) -> list[dict]: ...
    def read_child_reports(self, *, community_id: str, level: int) -> list[dict]: ...
    def write_report(self, *, community_id: str, level: int, report: str,
                     title: str, summary: str, report_vec: list[float] | None) -> None: ...


class NebulaCommunitySummarize:
    """nGQL community SUMMARIZE. UPDATE VERTEX is a partial update (preserves
    BUILD's member_count/members_hash); report_vec is never written (Milvus).
    The intra-community edge filter for member context is done in Python."""

    def __init__(self, store: Any):
        self._store = store

    def _exec(self, stmt: str) -> list[dict]:
        return list(self._store.structured_query(stmt) or [])

    def read_child_reports(self, *, community_id, level) -> list[dict]:
        from src.graph.community_writeback import community_vid
        from src.graph.nebula_store import _q
        cvid = community_vid(community_id, level)
        child_rows = self._exec(f'GO FROM {_q(cvid)} OVER `PARENT_OF` YIELD dst(edge) AS child;')
        cvids = [r["child"] for r in child_rows if r.get("child")]
        if not cvids:
            return []
        listed = ", ".join(_q(v) for v in cvids)
        props = self._exec(
            f"FETCH PROP ON `Community` {listed} YIELD "
            "`Community`.title AS title, `Community`.summary AS summary, "
            "`Community`.report AS report, `Community`.member_count AS mc;"
        )
        kept = [r for r in props if (r.get("report") or "").strip()]
        kept.sort(key=lambda r: r.get("mc") or 0, reverse=True)
        return [{"title": r.get("title") or "", "summary": r.get("summary") or ""} for r in kept]

    def read_member_context(self, *, community_id, level) -> list[dict]:
        from src.graph.community_writeback import community_vid
        from src.graph.nebula_store import _q
        cvid = community_vid(community_id, level)
        mrows = self._exec(f'GO FROM {_q(cvid)} OVER `IN_COMMUNITY` REVERSELY YIELD src(edge) AS m;')
        members = [r["m"] for r in mrows if r.get("m")]
        if not members:
            return []
        mset = set(members)
        listed = ", ".join(_q(v) for v in members)
        # YIELD id(vertex) so props can be keyed back to each member's VID.
        prop_rows = self._exec(
            f"FETCH PROP ON `Entity` {listed} YIELD id(vertex) AS vid, "
            "`Entity`.name AS name, `Entity`.description AS description;"
        )
        # Key props by each row's own vid (the FETCH YIELDs id(vertex) AS vid).
        # FETCH does NOT guarantee input order, so never pair positionally.
        props = {
            r["vid"]: (r.get("name") or "", r.get("description") or "")
            for r in prop_rows
        }
        edges = self._exec(
            f"GO FROM {listed} OVER `RELATED` BIDIRECT YIELD "
            "src(edge) AS s, dst(edge) AS d, `RELATED`.rel_type AS rt;"
        )
        rel: dict[str, list[str]] = {v: [] for v in members}
        for e in edges:
            s_, d_, rt = e.get("s"), e.get("d"), e.get("rt")
            if s_ in mset and d_ in mset and rt:      # intra-community only
                for endpoint in (s_, d_):
                    if rt not in rel[endpoint]:
                        rel[endpoint].append(rt)
        out = []
        for v in members:
            name, desc = props.get(v, ("", ""))
            out.append({"name": name, "description": desc, "rel_types": rel[v][:10]})
        out.sort(key=lambda r: r["name"])
        return out

    def write_report(self, *, community_id, level, report, title, summary, report_vec) -> None:
        import time

        from src.graph.community_writeback import community_vid
        from src.graph.nebula_store import _q
        cvid = community_vid(community_id, level)
        now = int(time.time() * 1000)
        # report_vec intentionally NOT written (Milvus owns it). UPDATE VERTEX
        # is a partial update, preserving member_count/members_hash from BUILD.
        self._exec(
            f'UPDATE VERTEX ON `Community` {_q(cvid)} SET '
            f"report = {_q(report)}, title = {_q(title)}, "
            f"summary = {_q(summary)}, summarized_at = {now};"
        )


def build_community_summarize(store: Any) -> CommunitySummarize:
    return NebulaCommunitySummarize(store)
