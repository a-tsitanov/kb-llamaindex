import pytest

from scripts import smoke_graph_isolation as S


async def test_wait_for_returns_first_truthy():
    calls = iter([None, None, {"status": "ready"}])

    async def probe():
        return next(calls)

    assert await S.wait_for(probe, timeout_s=5, interval_s=0) == {"status": "ready"}


async def test_wait_for_times_out():
    async def probe():
        return None

    with pytest.raises(TimeoutError):
        await S.wait_for(probe, timeout_s=0.05, interval_s=0.01)
