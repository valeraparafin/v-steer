import asyncio
from types import SimpleNamespace
from typing import ClassVar

from vsteer.events import Tap
from vsteer.vs200 import FEA1_UUID, InputState, Vs200Input, parse_packet, pick_remote


class FakeClient:
    instances: ClassVar[list["FakeClient"]] = []

    def __init__(self, device, disconnected_callback):
        self.device, self.on_disconnect, self.handler = device, disconnected_callback, None
        FakeClient.instances.append(self)

    async def connect(self):
        pass

    async def start_notify(self, uuid, handler):
        assert uuid == FEA1_UUID
        self.handler = handler

    async def disconnect(self):
        pass

    def press(self, hex_packet):
        self.handler(None, bytearray.fromhex(hex_packet))

    def drop(self):
        self.on_disconnect(self)


async def until(condition, timeout=1.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not condition():
        if loop.time() > end:
            raise AssertionError("condition not met")
        await asyncio.sleep(0.005)


def test_parse_packet():
    assert parse_packet(bytes.fromhex("f3050301fc")) is Tap.RIGHT
    assert parse_packet(bytes.fromhex("f3050300fb")) is Tap.LEFT
    assert parse_packet(bytes.fromhex("f3050302fd")) is None
    assert parse_packet(b"") is None


async def test_reconnects_after_sleep_and_drop():
    FakeClient.instances = []
    lookups = iter([None, None, SimpleNamespace(address="AA"), SimpleNamespace(address="AA")])
    taps, states = [], []

    async def find_device(address, timeout):
        return next(lookups)

    vs = Vs200Input("AA", taps.append, states.append, find_device=find_device,
                    client_factory=FakeClient, retry_s=0.01)
    task = asyncio.create_task(vs.run())
    await until(lambda: vs.state is InputState.CONNECTED)
    FakeClient.instances[0].press("f3050301fc")
    FakeClient.instances[0].drop()
    await until(lambda: len(FakeClient.instances) == 2 and vs.state is InputState.CONNECTED)
    FakeClient.instances[1].press("f3050300fb")
    FakeClient.instances[1].press("ffff")  # unknown packet: ignored
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert taps == [Tap.RIGHT, Tap.LEFT]
    assert states == [InputState.SEARCHING, InputState.CONNECTED, InputState.SEARCHING, InputState.CONNECTED]


async def test_pick_remote_returns_the_remote_that_was_pressed():
    FakeClient.instances = []
    devices = [SimpleNamespace(name="Think VS01-1", address="A1"), SimpleNamespace(name="Think VS01-2", address="B2")]

    async def scan(timeout):
        return devices

    task = asyncio.create_task(pick_remote(5.0, scan=scan, client_factory=FakeClient))
    await until(lambda: len(FakeClient.instances) == 2 and all(c.handler for c in FakeClient.instances))
    FakeClient.instances[1].press("f3050300fb")
    assert await asyncio.wait_for(task, 3.0) == "B2"


async def test_pick_remote_times_out_without_remotes():
    async def scan(timeout):
        await asyncio.sleep(0.01)
        return []

    assert await pick_remote(0.1, scan=scan, client_factory=FakeClient) is None


async def test_late_disconnect_of_old_link_does_not_drop_the_new_one():
    FakeClient.instances = []

    async def find_device(address, timeout):
        return SimpleNamespace(address="AA")

    vs = Vs200Input("AA", lambda tap: None, find_device=find_device, client_factory=FakeClient,
                    retry_s=0.01)
    task = asyncio.create_task(vs.run())
    await until(lambda: vs.state is InputState.CONNECTED)
    FakeClient.instances[0].drop()
    await until(lambda: len(FakeClient.instances) == 2 and vs.state is InputState.CONNECTED)
    FakeClient.instances[0].drop()  # Windows reports the old link's disconnect again, late
    await asyncio.sleep(0.1)
    assert len(FakeClient.instances) == 2 and vs.state is InputState.CONNECTED
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_scanner_errors_are_retried_not_fatal():
    from bleak.exc import BleakError

    FakeClient.instances = []
    calls = {"n": 0}

    async def find_device(address, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise BleakError("Failed to start scanner. Is Bluetooth turned on?")
        return SimpleNamespace(address="AA")

    taps = []
    vs = Vs200Input("AA", taps.append, find_device=find_device, client_factory=FakeClient,
                    retry_s=0.01)
    task = asyncio.create_task(vs.run())
    await until(lambda: vs.state is InputState.CONNECTED)
    FakeClient.instances[0].press("f3050301fc")
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert taps == [Tap.RIGHT]


async def test_pick_remote_survives_a_scanner_error():
    from bleak.exc import BleakError

    FakeClient.instances = []
    calls = {"n": 0}

    async def scan(timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise BleakError("Bluetooth adapter not available")
        return [SimpleNamespace(name="Think VS01-1", address="A1")]

    task = asyncio.create_task(pick_remote(5.0, scan=scan, client_factory=FakeClient))
    await until(lambda: FakeClient.instances and FakeClient.instances[0].handler, timeout=3.0)
    FakeClient.instances[0].press("f3050301fc")
    assert await asyncio.wait_for(task, 3.0) == "A1"


async def test_search_interval_stays_short_while_the_remote_sleeps(monkeypatch):
    """#3: a press that wakes the remote must be picked up within seconds, not after a long backoff."""
    from vsteer import vs200 as vs200_module

    delays = []
    real_sleep = asyncio.sleep

    async def record(delay):
        delays.append(delay)
        if len(delays) >= 8:
            raise asyncio.CancelledError
        await real_sleep(0)

    async def asleep(address, timeout):
        return None

    monkeypatch.setattr(vs200_module.asyncio, "sleep", record)
    vs = Vs200Input("AA", lambda tap: None, find_device=asleep, client_factory=FakeClient)
    try:
        await vs.run()
    except asyncio.CancelledError:
        pass
    assert len(delays) == 8 and max(delays) <= 3.0


async def test_pick_remote_disconnects_a_remote_it_could_not_listen_to():
    """#7: connect() worked but start_notify() failed: that remote must not stay connected to the PC."""
    disconnected = []

    class DeafClient(FakeClient):
        async def start_notify(self, uuid, handler):
            raise OSError("notify failed")

        async def disconnect(self):
            disconnected.append(self.device.address)

    async def scan(timeout):
        return [SimpleNamespace(name="Think VS01-1", address="A1")]

    assert await pick_remote(0.3, scan=scan, client_factory=DeafClient) is None
    assert "A1" in disconnected


async def test_pick_remote_disconnects_after_any_error():
    """Review of #7: a non-BLE error type must not leave the remote attached or crash the first run."""
    disconnected = []

    class OddClient(FakeClient):
        async def start_notify(self, uuid, handler):
            raise RuntimeError("winrt said no")

        async def disconnect(self):
            disconnected.append(self.device.address)

    async def scan(timeout):
        return [SimpleNamespace(name="Think VS01-1", address="A1")]

    assert await pick_remote(0.3, scan=scan, client_factory=OddClient) is None
    assert "A1" in disconnected


async def test_search_scans_in_short_bursts():
    """Review of #3: a sleeping remote is searched often, so each scan must be short (adapter time)."""
    timeouts = []

    async def find_device(address, timeout):
        timeouts.append(timeout)
        raise asyncio.CancelledError

    vs = Vs200Input("AA", lambda tap: None, find_device=find_device, client_factory=FakeClient)
    try:
        await vs.run()
    except asyncio.CancelledError:
        pass
    assert timeouts and timeouts[0] <= 5.0
