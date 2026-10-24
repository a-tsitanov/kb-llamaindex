"""Единый ключ канала: по нему реестр, доверие и отчёт сравнивают слаги.

Слаг приходит в трёх видах: ``@Five`` (так его отдают ``sources_search`` и
``sources_resolve``), ``Five`` (так фидер кладёт его в ``documents.source_channel``
— без «@») и пустой (у канала без username).  Без общего правила реестр
хранил бы одно, документы — другое, и доверие канала не доходило бы ни до
одного документа.
"""

from __future__ import annotations


def normalize_slug(slug: str) -> str:
    """Слаг без ведущего «@» и в нижнем регистре; пустой остаётся пустым."""
    return slug.lstrip("@").casefold()


def channel_key(slug: str, peer_id: int) -> str:
    """Ключ канала для ``source_slug`` и поиска по документам.

    Канал без username (пустой слаг) фидер называет его ``peer_id`` — тем же
    ключом он и записывается.
    """
    return normalize_slug(slug) or str(peer_id)


__all__ = ["channel_key", "normalize_slug"]
