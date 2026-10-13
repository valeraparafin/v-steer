import pytest

from vsteer.update import check_for_update, newer_version


@pytest.mark.parametrize(
    ("latest", "current", "expected"),
    [
        ("v0.2.0", "0.1.0", "v0.2.0"),
        ("v0.1.10", "0.1.9", "v0.1.10"),  # numeric, not text, comparison
        ("v1.0", "0.9.9", "v1.0"),
        ("v0.1.0", "0.1.0", None),
        ("v0.0.9", "0.1.0", None),
        ("nightly", "0.1.0", None),
        ("", "0.1.0", None),
    ],
)
def test_newer_version(latest, current, expected):
    assert newer_version(latest, current) == expected


async def test_reports_a_newer_release():
    assert await check_for_update("0.1.0", fetch=lambda: "v0.2.0") == "v0.2.0"


async def test_stays_quiet_when_up_to_date():
    assert await check_for_update("0.1.0", fetch=lambda: "v0.1.0") is None


async def test_stays_quiet_offline():
    def offline():
        raise OSError("no network")

    assert await check_for_update("0.1.0", fetch=offline) is None


def test_exit_does_not_wait_for_a_slow_network():
    import asyncio
    import time

    def slow():
        time.sleep(2)
        return "v9.9.9"

    async def ride_then_stop():
        task = asyncio.create_task(check_for_update("0.1.0", fetch=slow))
        await asyncio.sleep(0.05)
        task.cancel()

    started = time.monotonic()
    asyncio.run(ride_then_stop())
    assert time.monotonic() - started < 1
