# Message statistics

## What it does
Processed-message counts (per channel, per group, and over time) come from
the `documents` table's `source_channel` / `source_group` columns. These are
populated by `tg_ingest` via the `/ingest` endpoint's `channel` + `group` form
fields at ingest time. Two read-only surfaces expose the same aggregation
logic (`IntakeRepository.status_counts_by` / `timeline_counts` in
`src/intake/repository.py`): an HTTP API for dashboards/tooling, and a CLI
for direct DB queries without going through the API.

## HTTP endpoints
Both require the `X-API-Key` header (same key as the rest of `/api/v1`).

- `GET /api/v1/stats/messages?group_by=channel|group[&since=YYYY-MM-DD][&until=YYYY-MM-DD]`
  → per-channel/group counts by status (`pending`/`processing`/`completed`/`vector_only`/`failed`/`skipped`, plus `total`),
  plus `versions` — see "What counts as a document" below.
- `GET /api/v1/stats/timeline?date_field=created_at|doc_date[&group_by=channel|group][&channel=][&group=][&since=][&until=]`
  → daily message counts, optionally broken out by channel/group and filtered
  to a single channel/group.

Example:

    curl -s -H "X-API-Key: $KEY" \
      "http://localhost:8000/api/v1/stats/messages?group_by=channel&since=2026-07-01" | jq

    curl -s -H "X-API-Key: $KEY" \
      "http://localhost:8000/api/v1/stats/timeline?date_field=doc_date&group_by=channel&channel=somechannel" | jq

## CLI
Direct DB access, no API/key needed — reads straight from Postgres using
`settings.postgres.dsn`:

    python -m scripts.message_stats channels [--since 2026-07-01] [--until 2026-07-23]
    python -m scripts.message_stats groups
    python -m scripts.message_stats timeline [--date-field doc_date] [--group-by channel] [--channel somechannel] [--group somegroup]

`channels`/`groups` print an aligned status-count table; `timeline` prints one
`day  [key]  count` line per bucket.

## What counts as a document

`total` and the per-status breakdown count **accepted documents** — rows with
`duplicate_of IS NULL`. A row with `duplicate_of` set is created by the
`on_duplicate=version` policy, which the documented re-upload paths send
(`backfill=true`, `deploy/offline/loadtest/loader.py`) along with a manual
`scripts/tg_ingest.py --reingest`. Without that predicate `total` would mean
"rows uploaded" rather than "documents accepted", and would stop matching the
pre-split numbers.

A version is nonetheless a full pipeline document: its own chunks, its own
graph nodes, its own outcome. So its outcome is reported in the **additive**
`versions` field — `{status: count}`, zeros omitted:

    "rows": [{"key": "somechannel", "total": 120, "completed": 118,
              "failed": 2, …, "versions": {"failed": 3, "completed": 7}}]

In the CLI this is a separate `versions` column rendered as `failed:3`. A
channel whose window contains only versions (its canonical row predates
`since`) comes back with `total=0` and a non-empty `versions`.

`timeline` has no `versions` field: it never reports a status, and a version
does not add another message to a day. A **sighting** (see below) does: it is
a separate message of a separate channel, so `timeline` counts it even though
`total` does not.

The diagnostic `python -m scripts.check_ingestion` deliberately does NOT apply
the predicate: it answers "what is in Postgres", not "how many documents were
accepted", and counts versions as separate rows. The two surfaces are not
required to agree.

## Dedup, cross-posts and sightings

The intake dedup key is the sha256 of the **body**, scoped to the graph; the
channel is not part of the key. A verbatim cross-post present in two watched
channels therefore does NOT become a second document: the second POST gets a
`409`, nothing is uploaded, nothing is queued, and the graph keeps exactly one
copy of that body. That part is the point of the dedup, not a shortcoming.

What the `409` does leave behind is a **sighting** — one lightweight row with
`intake_status='duplicate'`, `duplicate_of` pointing at the body's owner, and
the same MinIO path as the owner (one object, not two). It carries the
receiving channel and group, has **no `doc_processing` row** (nothing was
processed and nothing ever will be), and its effective status is reported as
`duplicate`. So the receiving channel keeps its numbers:

* `messages` — the sighting shows up in that channel's `versions` dict as
  `{"duplicate": N}`; `total` and the per-status breakdown stay "documents
  accepted" and do not move.
* `timeline` — counted as a message of its day.
* `check_ingestion` — appears in its own `duplicate` bucket.

A sighting is written only when the request carries a channel or a group:
both reporting dimensions are keyed on those, so an unattributed repeat (a
second run of `scripts/ingest_medical.py`, a manual re-upload of the same
file) would add a row that no surface could show. Those stay a plain `409`
with nothing written.

Not recoverable retroactively: cross-posts rejected before this shipped left
no trace, so there is nothing to backfill them from.

Under `on_duplicate=version` no sighting is written — that policy creates a
real second document (its own chunks, its own graph nodes) and reports itself
through `versions` as described above.

## Graph-wide reconciliation

This runbook is about per-channel and per-group numbers. The question
"why does the graph hold fewer documents than we uploaded" is a different
cut — graph-wide, rows with no channel included — and has its own surface:
`GET /api/v1/intake/stats`, see `docs/runbook/intake-stats.md`.

## Historical-data caveat
`source_group` is empty for documents ingested before this feature shipped —
`group` was not persisted historically, so there is nothing to backfill.
`source_channel` was backfilled from the filename in `path` for Telegram rows
only (via `scripts/setup_db.py`); non-Telegram historical documents have no
`source_channel` either.
