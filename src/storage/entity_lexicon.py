"""Postgres lookups for the KB name resolver (``src/graph/name_resolution.py``).

Pure query builders (asserted in tests, no live DB) + a thin async repository over the
process pool. All lookups take an already normalized name (``norm_name`` / ``translit_key``)
and read the ``entity`` mirror / ``entity_alias`` table; the graph stays canonical — the
resolver re-checks every hit against it (liveness), so a stale mirror row never wins.
"""

from __future__ import annotations

from typing import Any

from psycopg.rows import dict_row

from src.storage.pg_pool import get_pg_pool

_ENTITY = "name, label, description, mention_count"
_LIVE = "alive IS NOT FALSE"


def _like_prefix(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def q_norm(norm: str, limit: int) -> tuple[str, list[Any]]:
    return (f"SELECT {_ENTITY}, name AS matched_text FROM entity "
            f"WHERE name_norm = %s AND {_LIVE} ORDER BY mention_count DESC LIMIT %s",
            [norm, limit])


def q_alias(norm: str, limit: int) -> tuple[str, list[Any]]:
    return ("SELECT canonical_name AS name, alias AS matched_text, confidence, source "
            "FROM entity_alias WHERE alias_norm = %s ORDER BY confidence DESC LIMIT %s",
            [norm, limit])


def q_translit(key: str, limit: int) -> tuple[str, list[Any]]:
    return (f"(SELECT {_ENTITY}, name AS matched_text, 1.0::real AS confidence FROM entity "
            f"WHERE name_translit = %s AND {_LIVE} ORDER BY mention_count DESC LIMIT %s) "
            "UNION ALL "
            "(SELECT canonical_name, '', '', 0, alias, confidence FROM entity_alias "
            "WHERE alias_translit = %s ORDER BY confidence DESC LIMIT %s)",
            [key, limit, key, limit])


def q_word(norm: str, limit: int) -> tuple[str, list[Any]]:
    # the query is a word (or words) of the name: a surname inside "Имя Фамилия"
    return (f"SELECT {_ENTITY}, name AS matched_text, word_similarity(%s, name_norm) AS sim "
            f"FROM entity WHERE %s <%% name_norm AND {_LIVE} "
            "ORDER BY sim DESC, mention_count DESC LIMIT %s",
            [norm, norm, limit])


def q_prefix(norm: str, limit: int) -> tuple[str, list[Any]]:
    return (f"SELECT {_ENTITY}, name AS matched_text FROM entity "
            f"WHERE name_norm LIKE %s AND {_LIVE} ORDER BY mention_count DESC LIMIT %s",
            [_like_prefix(norm), limit])


def q_trigram(norm: str, limit: int) -> tuple[str, list[Any]]:
    return (f"SELECT {_ENTITY}, name AS matched_text, similarity(name_norm, %s) AS sim "
            f"FROM entity WHERE name_norm %% %s AND {_LIVE} "
            "ORDER BY sim DESC, mention_count DESC LIMIT %s",
            [norm, norm, limit])


class EntityLexicon:
    """The resolver's Postgres side. Every method returns row dicts; errors propagate (the
    resolver decides what a failed step means)."""

    async def _rows(self, built: tuple[str, list[Any]]) -> list[dict[str, Any]]:
        sql, params = built
        pool = await get_pg_pool()
        async with pool.connection(timeout=1) as conn, \
                conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return list(await cur.fetchall())

    async def by_norm(self, norm: str, limit: int) -> list[dict[str, Any]]:
        return await self._rows(q_norm(norm, limit))

    async def by_alias(self, norm: str, limit: int) -> list[dict[str, Any]]:
        return await self._rows(q_alias(norm, limit))

    async def by_translit(self, key: str, limit: int) -> list[dict[str, Any]]:
        return await self._rows(q_translit(key, limit))

    async def by_word(self, norm: str, limit: int) -> list[dict[str, Any]]:
        return await self._rows(q_word(norm, limit))

    async def by_prefix(self, norm: str, limit: int) -> list[dict[str, Any]]:
        return await self._rows(q_prefix(norm, limit))

    async def by_trigram(self, norm: str, limit: int) -> list[dict[str, Any]]:
        return await self._rows(q_trigram(norm, limit))


__all__ = ["EntityLexicon"]
