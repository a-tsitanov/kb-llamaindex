"""Entity-watch tables (journals, subscriptions, events) — DDL shape."""
from scripts.setup_db import _WATCH_DDL, _WATCH_INDEXES_DDL

_TABLES = (
    "watch", "entity_mention", "edge_new", "watch_event",
    "watch_seen", "monitor_cursor",
    "watch_digest", "watch_delivery",
)


def test_every_table_is_created_idempotently():
    for t in _TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {t} (" in _WATCH_DDL


def test_one_subscription_per_owner_and_entity():
    assert "UNIQUE (owner, entity_vid)" in _WATCH_DDL


def test_mention_is_keyed_by_entity_and_document_with_a_cursor_id():
    assert "PRIMARY KEY (entity_vid, doc_id)" in _WATCH_DDL
    assert "id            BIGSERIAL UNIQUE" in _WATCH_DDL


def test_edge_new_keeps_only_the_first_appearance_of_a_pair():
    assert "UNIQUE (src_vid, tgt_vid)" in _WATCH_DDL


def test_events_are_deduplicated():
    assert "dedup_key   TEXT NOT NULL UNIQUE" in _WATCH_DDL


def test_journals_carry_the_backfill_flag():
    assert _WATCH_DDL.count("backfill") == 2


def test_seen_is_per_owner_and_event():
    assert "PRIMARY KEY (owner, event_id)" in _WATCH_DDL


def test_indexes_back_the_cursor_reads_and_the_feed():
    for idx in ("entity_mention_doc_idx", "edge_new_src_idx", "edge_new_tgt_idx",
                "watch_event_entity_idx", "watch_entity_idx"):
        assert idx in _WATCH_INDEXES_DDL


def test_delivery_is_deduped_by_subscriber_and_event():
    """Ключ (owner, event_id) И ЕСТЬ дедуп доставки: одно событие одному
    подписчику уходит один раз, сколько бы раз свип ни перезапускался."""
    assert "PRIMARY KEY (owner, event_id)" in _WATCH_DDL


def test_subscription_carries_its_own_destination():
    """Адресат на подписке, а не один глобальный из env."""
    assert "ADD COLUMN IF NOT EXISTS webhook_url TEXT NOT NULL DEFAULT ''" in _WATCH_DDL
    assert "ADD COLUMN IF NOT EXISTS daily_push_limit INTEGER" in _WATCH_DDL
