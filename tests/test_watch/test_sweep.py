"""Entity-watch sweep: pure detectors + the cursor-driven runner."""
from __future__ import annotations

from datetime import date

from src.graph.nebula_store import entity_vid
from src.watch.sweep import (
    detect_contradictions,
    detect_edges,
    detect_mentions,
    run_watch_sweep,
)

DOC = "d0c5e6a0-0000-0000-0000-000000000001"
BL = entity_vid("Блинов")
PH = entity_vid("+79161234567")
SA = entity_vid("Самойлов")
WATCHED = {BL: "Блинов"}


def _mention(i, vid, name, *, backfill=False, mc=4, doc=DOC):
    return {"id": i, "entity_vid": vid, "entity_name": name, "label": "Person",
            "doc_id": doc, "doc_date": date(2024, 3, 12), "mention_count": mc,
            "backfill": backfill}


def _edge(i, src, tgt, tgt_label, rel, *, src_label="Person", backfill=False):
    return {"id": i, "src_vid": entity_vid(src), "src_name": src, "src_label": src_label,
            "tgt_vid": entity_vid(tgt), "tgt_name": tgt, "tgt_label": tgt_label,
            "rel": rel, "doc_id": DOC, "doc_date": None, "backfill": backfill}


# ── detectors ────────────────────────────────────────────────────────


def test_new_mention_only_for_watched_and_not_backfill():
    ev = detect_mentions(
        [_mention(1, BL, "Блинов"), _mention(2, SA, "Самойлов"),
         _mention(3, BL, "Блинов", backfill=True)],
        WATCHED,
    )
    assert len(ev) == 1
    e = ev[0]
    assert e["kind"] == "new_mention" and e["entity_vid"] == BL
    assert e["dedup_key"] == f"new_mention:{BL}:{DOC}"
    assert e["doc_id"] == DOC and e["source_table"] == "entity_mention" and e["source_id"] == 1
    assert e["detail"]["mention_count"] == 4


def test_identifier_vs_connection_by_the_other_side_label():
    ev = detect_edges(
        [_edge(7, "Блинов", "+79161234567", "PhoneNumber", "PHONE"),
         _edge(8, "Блинов", "Самойлов", "Person", "TRANSFERRED_TO")],
        WATCHED,
    )
    kinds = {e["kind"]: e for e in ev}
    assert set(kinds) == {"new_identifier", "new_connection"}
    assert kinds["new_identifier"]["dedup_key"] == f"new_identifier:{BL}:{PH}"
    assert kinds["new_identifier"]["detail"]["other"] == "+79161234567"
    assert kinds["new_connection"]["detail"]["rel"] == "TRANSFERRED_TO"


def test_event_participation_is_new_event_and_document_bookkeeping_is_dropped():
    ev = detect_edges(
        [_edge(1, "Блинов", "передал 45 000 рублей", "EventOrAction", "PARTICIPATED_IN"),
         _edge(2, "10 октября 2026 года", "Блинов", "Person", "PAYMENT", src_label="DocumentDate"),
         _edge(3, "Протокол допроса", "Блинов", "Person", "TESTIMONY", src_label="Document"),
         _edge(4, "Блинов", "кража", "Concept", "RELATED"),
         _edge(5, "45 000 рублей", "Блинов", "Person", "PAYMENT_AMOUNT", src_label="Amount")],
        WATCHED,
    )
    assert [(e["kind"], e["detail"]["other"]) for e in ev] == [
        ("new_event", "передал 45 000 рублей"),
        ("new_connection", "45 000 рублей"),
    ]


def test_edge_detected_from_either_end():
    """Watched entity on the TARGET side: the other side is the source."""
    ev = detect_edges([_edge(9, "Самойлов", "Блинов", "Person", "KNOWS")], WATCHED)
    assert len(ev) == 1
    assert ev[0]["entity_vid"] == BL
    assert ev[0]["detail"]["other"] == "Самойлов"
    assert ev[0]["detail"]["direction"] == "in"


def test_edge_between_two_watched_entities_raises_one_event_each():
    both = {BL: "Блинов", SA: "Самойлов"}
    ev = detect_edges([_edge(9, "Самойлов", "Блинов", "Person", "KNOWS")], both)
    assert {e["entity_vid"] for e in ev} == {BL, SA}


def test_backfill_edges_raise_nothing():
    assert detect_edges([_edge(9, "Блинов", "X", "Person", "R", backfill=True)], WATCHED) == []


def test_contradiction_from_fact_supersede_by_name():
    row = {"id": 12, "src": "Блинов", "rel": "ADDRESS", "tgt": "ул. Лесная, 118",
           "stored_polarity": "affirmed", "new_polarity": "negated",
           "stored_trust": 0.9, "new_trust": 0.5, "stored_doc_id": "old",
           "new_doc_id": DOC, "winner": "stored"}
    ev = detect_contradictions([row], WATCHED)
    assert len(ev) == 1
    e = ev[0]
    assert e["kind"] == "contradiction" and e["dedup_key"] == f"contradiction:{BL}:12"
    assert e["doc_id"] == DOC
    assert e["detail"]["winner"] == "stored"


def test_contradiction_with_a_non_uuid_doc_keeps_no_doc_link():
    row = {"id": 13, "src": "Блинов", "rel": "R", "tgt": "T", "new_doc_id": "doc-x"}
    assert detect_contradictions([row], WATCHED)[0]["doc_id"] is None


def test_duplicate_keys_within_a_batch_collapse():
    ev = detect_mentions([_mention(1, BL, "Блинов"), _mention(2, BL, "Блинов")], WATCHED)
    assert len(ev) == 1


def test_nothing_watched_nothing_detected():
    assert detect_mentions([_mention(1, BL, "Блинов")], {}) == []


# ── runner ───────────────────────────────────────────────────────────


class _Repo:
    def __init__(self, journals, watched):
        self.journals = journals
        self.cursors: dict[str, int] = {}
        self._watched = watched
        self.saved: list[tuple[str, list, int]] = []

    async def watched(self):
        return self._watched

    async def cursor(self, name):
        return self.cursors.get(name, 0)

    async def read_journal(self, name, *, after_id, limit):
        rows = [r for r in self.journals.get(name, []) if r["id"] > after_id]
        return rows[:limit]

    async def save_events(self, journal, events, *, last_id):
        self.saved.append((journal, events, last_id))
        self.cursors[journal] = last_id


async def test_runner_advances_every_cursor_in_batches():
    repo = _Repo(
        {"entity_mention": [_mention(i, BL, "Блинов", doc=f"{DOC[:-1]}{i}") for i in (1, 2, 3)],
         "edge_new": [_edge(5, "Блинов", "+79161234567", "PhoneNumber", "PHONE")],
         "fact_supersede": []},
        WATCHED,
    )
    out = await run_watch_sweep(repo, batch=2)
    assert repo.cursors == {"entity_mention": 3, "edge_new": 5}
    assert out == {"new_mention": 3, "new_identifier": 1}
    # second run: nothing new past the cursors
    assert await run_watch_sweep(repo, batch=2) == {}


async def test_runner_moves_cursors_even_when_nobody_watches():
    repo = _Repo({"entity_mention": [_mention(1, BL, "Блинов")]}, {})
    assert await run_watch_sweep(repo) == {}
    assert repo.cursors == {"entity_mention": 1}
    assert repo.saved[0][1] == []
