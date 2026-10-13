import asyncio
from types import SimpleNamespace
from typing import ClassVar

from vs200steer.events import Tap
from vs200steer.vs200 import FEA1_UUID, InputState, Vs200Input, parse_packet, pick_remote


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
                    client_factory=FakeClient, retry_s=0.01, max_retry_s=0.02)
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
                    retry_s=0.01, max_retry_s=0.02)
    task = asyncio.create_task(vs.run())
    await until(lambda: vs.state is InputState.CONNECTED)
    FakeClient.instances[0].drop()
    await until(lambda: len(FakeClient.instances) == 2 and vs.state is InputState.CONNECTED)
    FakeClient.instances[0].drop()  # Windows reports the old link's disconnect again, late
    await asyncio.sleep(0.1)
    assert len(FakeClient.instances) == 2 and vs.state is InputState.CONNECTED
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
