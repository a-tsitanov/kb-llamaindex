"""Активность свипа наблюдения: журналы и рост риска.

Тестов дуги `:Alert` здесь больше нет — она выведена вместе с P2
(спека `docs/superpowers/specs/2026-10-20-watch-contour-design.md` §4).
Из неё сохранён один детектор, рост риска, и ровно он проверяется ниже:
чтение идёт ПО СПИСКУ ПОДПИСОК, а не по графовому флагу `watched`,
иначе свип возвращал бы сущности, на которые никто не подписан.
"""

from __future__ import annotations

import pytest

# ── entity-watch sweep activity ──────────────────────────────────────


async def _default_only():
    from src.tenancy.context import default_graph_context

    return [default_graph_context()]


class _NoWatches:
    """Репозиторий без подписок: журнальная часть свипа подменена, а
    риск без подписок и так не читается."""

    async def watched(self):
        return {}

    async def insert_events(self, events):
        raise AssertionError("нечего записывать")


@pytest.mark.asyncio
async def test_sweep_watch_tallies_events(monkeypatch):
    import src.watch.activities as acts

    async def _run(repo, **kw):
        return {"new_mention": 2, "new_identifier": 1}

    monkeypatch.setattr(acts, "run_watch_sweep", _run)
    monkeypatch.setattr(acts, "WatchRepository", lambda *, graph: _NoWatches())
    monkeypatch.setattr(acts, "_watch_graphs", _default_only)
    out = await acts.sweep_watch()
    assert out.events == 3 and out.by_kind == {"new_mention": 2, "new_identifier": 1}
    assert out.error == ""


@pytest.mark.asyncio
async def test_sweep_watch_never_raises(monkeypatch):
    import src.watch.activities as acts

    async def _boom(repo, **kw):
        raise RuntimeError("pg down")

    monkeypatch.setattr(acts, "run_watch_sweep", _boom)
    monkeypatch.setattr(acts, "WatchRepository", lambda *, graph: _NoWatches())
    monkeypatch.setattr(acts, "_watch_graphs", _default_only)
    out = await acts.sweep_watch()
    assert out.events == 0 and "pg down" in out.error


# ── рост риска ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_risk_rise_lands_in_the_same_event_stream(monkeypatch):
    """Рост риска — событие в `watch_event`, а не узел графа.

    Подписчик видит один поток: журнальные виды и риск приходят одним
    ``by_kind``, а не двумя разными счётчиками, как было при двух дугах.
    """
    import src.watch.activities as acts

    inserted: list[list[dict]] = []

    class _Repo:
        async def watched(self):
            return {"vid1": "Акме"}

        async def insert_events(self, events):
            inserted.append(events)

    async def _run(repo, **kw):
        return {"new_mention": 1}

    monkeypatch.setattr(acts, "run_watch_sweep", _run)
    monkeypatch.setattr(acts, "WatchRepository", lambda *, graph: _Repo())
    monkeypatch.setattr(acts, "_watch_graphs", _default_only)
    monkeypatch.setattr(acts, "build_graph_store", lambda g: object())
    monkeypatch.setattr(
        acts, "_read_risk_scores",
        lambda store, vids: [{"vid": "vid1", "name": "Акме", "score": 0.8, "prev": 0.2}],
    )

    out = await acts.sweep_watch()

    assert out.by_kind == {"new_mention": 1, "risk_rise": 1}
    assert out.events == 2
    event = inserted[0][0]
    assert event["kind"] == "risk_rise"
    assert event["dedup_key"] == "risk_rise:vid1:0.80"
    # Журнала у риска нет, поэтому и курсора нет: запись идёт отдельным
    # методом, а не save_events с фиктивным курсором.
    assert event["source_table"] == "entity.risk_score"


@pytest.mark.asyncio
async def test_risk_is_read_for_subscribed_entities_only(monkeypatch):
    import src.watch.activities as acts

    asked: list[list[str]] = []

    class _Repo:
        async def watched(self):
            return {"vid1": "Акме", "vid2": "Бета"}

        async def insert_events(self, events):
            pass

    async def _run(repo, **kw):
        return {}

    monkeypatch.setattr(acts, "run_watch_sweep", _run)
    monkeypatch.setattr(acts, "WatchRepository", lambda *, graph: _Repo())
    monkeypatch.setattr(acts, "_watch_graphs", _default_only)
    monkeypatch.setattr(acts, "build_graph_store", lambda g: object())

    def _read(store, vids):
        asked.append(sorted(vids))
        return []

    monkeypatch.setattr(acts, "_read_risk_scores", _read)
    await acts.sweep_watch()

    assert asked == [["vid1", "vid2"]]


@pytest.mark.asyncio
async def test_no_subscriptions_means_no_graph_read(monkeypatch):
    """Пустая подписка — не повод открывать соединение с графом."""
    import src.watch.activities as acts

    class _Repo:
        async def watched(self):
            return {}

        async def insert_events(self, events):
            raise AssertionError("нечего записывать")

    async def _run(repo, **kw):
        return {}

    def _boom(g):
        raise AssertionError("граф читать незачем")

    monkeypatch.setattr(acts, "run_watch_sweep", _run)
    monkeypatch.setattr(acts, "WatchRepository", lambda *, graph: _Repo())
    monkeypatch.setattr(acts, "_watch_graphs", _default_only)
    monkeypatch.setattr(acts, "build_graph_store", _boom)

    out = await acts.sweep_watch()
    assert out.events == 0 and out.error == ""
