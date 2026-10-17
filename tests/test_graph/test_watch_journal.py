"""Journal rows the ingest writes for entity watch (pure + fail-open)."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from src.graph.nebula_store import entity_vid
from src.graph.watch_journal import (
    edge_rows,
    epoch_days_to_date,
    mention_rows,
    record_watch_journals,
)

DOC = "d0c5e6a0-0000-0000-0000-000000000001"


def _ent(name, label="Person", mc=1):
    return SimpleNamespace(name=name, label=label, properties={"mention_count": mc})


def _rel(src, tgt, label):
    return SimpleNamespace(source_id=src, target_id=tgt, label=label, properties={})


def test_epoch_days_to_date():
    assert epoch_days_to_date(None) is None
    assert epoch_days_to_date(0) == date(1970, 1, 1)
    assert epoch_days_to_date(19794) == date(2024, 3, 12)


def test_one_mention_row_per_entity_keyed_by_vid():
    rows = mention_rows(
        [_ent("Блинов", mc=4), _ent("Блинов", mc=1), _ent(""), _ent("ООО Ромашка", "Organization")],
        doc_id=DOC, doc_date=date(2024, 3, 12), backfill=False,
    )
    assert [r["entity_name"] for r in rows] == ["Блинов", "ООО Ромашка"]
    assert rows[0] == {
        "entity_vid": entity_vid("Блинов"), "doc_id": DOC, "entity_name": "Блинов",
        "label": "Person", "doc_date": date(2024, 3, 12), "mention_count": 4,
        "backfill": False,
    }


def test_edge_rows_only_for_created_pairs_with_both_labels():
    ents = [_ent("Блинов"), _ent("+79161234567", "PhoneNumber"), _ent("Самойлов")]
    rels = [_rel("Блинов", "+79161234567", "PHONE"), _rel("Блинов", "Самойлов", "KNOWS")]
    created = [(entity_vid("Блинов"), entity_vid("+79161234567"))]
    rows = edge_rows(rels, created, ents, doc_id=DOC, doc_date=None, backfill=True)
    assert rows == [{
        "src_vid": entity_vid("Блинов"), "src_name": "Блинов", "src_label": "Person",
        "tgt_vid": entity_vid("+79161234567"), "tgt_name": "+79161234567",
        "tgt_label": "PhoneNumber", "rel": "PHONE", "doc_id": DOC, "doc_date": None,
        "backfill": True,
    }]


def test_edge_rows_first_relation_wins_for_a_pair():
    ents = [_ent("A"), _ent("B")]
    rels = [_rel("A", "B", "X"), _rel("A", "B", "Y")]
    rows = edge_rows(rels, [(entity_vid("A"), entity_vid("B"))], ents,
                     doc_id=DOC, doc_date=None, backfill=False)
    assert [r["rel"] for r in rows] == ["X"]


def test_edge_rows_tolerate_a_non_list_created_value():
    """Non-nebula stores return None (or a mock) from upsert_relations."""
    assert edge_rows([_rel("A", "B", "X")], None, [], doc_id=DOC, doc_date=None,
                     backfill=False) == []


class _Repo:
    def __init__(self, fail=False):
        self.fail = fail
        self.mentions = None
        self.edges = None

    async def record_mentions(self, rows):
        if self.fail:
            raise RuntimeError("pg down")
        self.mentions = rows

    async def record_new_edges(self, rows):
        self.edges = rows


async def test_record_watch_journals_writes_both_journals():
    repo = _Repo()
    await record_watch_journals(
        repo, [_ent("A"), _ent("B")], [_rel("A", "B", "X")],
        [(entity_vid("A"), entity_vid("B"))],
        doc_id=DOC, doc_date_epoch=19794, backfill=False,
    )
    assert len(repo.mentions) == 2
    assert repo.mentions[0]["doc_date"] == date(2024, 3, 12)
    assert len(repo.edges) == 1


async def test_record_watch_journals_never_raises():
    await record_watch_journals(
        _Repo(fail=True), [_ent("A")], [], [], doc_id=DOC, doc_date_epoch=None,
        backfill=False,
    )


async def test_record_watch_journals_skips_non_uuid_doc_ids():
    """Legacy / test doc ids that are not UUIDs cannot go into the uuid column."""
    repo = _Repo()
    await record_watch_journals(repo, [_ent("A")], [], [], doc_id="d",
                                doc_date_epoch=None, backfill=False)
    assert repo.mentions is None
