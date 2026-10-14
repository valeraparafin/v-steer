import asyncio

import pytest

from vsteer.events import Tap
from vsteer.zwift import dircon
from vsteer.zwift import protocol as P
from vsteer.zwift import ride as ride_module
from vsteer.zwift.ride import EmulatorState, RideEmulator

DISCOVER_CHARACTERISTICS_GOLDEN = (
    "0102010000430000fc8200001000800000805f9b34fb0000000319ca465186e5fa29dcdd09d1020000000219ca465186e5"
    "fa29dcdd09d1040000000419ca465186e5fa29dcdd09d104"
)


class FakeZwift:
    """A TCP client that speaks DirCon the way Zwift did in the 2026-10-13 spike."""

    def __init__(self, reader, writer):
        self.reader, self.writer, self.seq, self.buffer = reader, writer, 0, b""

    @classmethod
    async def connect(cls, port):
        return cls(*await asyncio.open_connection("127.0.0.1", port))

    async def send(self, identifier, payload=b""):
        self.writer.write(dircon.Packet(identifier, self.seq, 0, payload).encode())
        self.seq = (self.seq + 1) % 256
        await self.writer.drain()

    async def recv(self, timeout=1.0):
        while True:
            pkt, self.buffer = dircon.decode(self.buffer)
            if pkt is not None:
                return pkt
            chunk = await asyncio.wait_for(self.reader.read(4096), timeout)
            if not chunk:
                raise ConnectionError("server closed")
            self.buffer += chunk

    async def drain_packets(self, quiet=0.2):
        packets = []
        while True:
            try:
                packets.append(await self.recv(timeout=quiet))
            except TimeoutError:
                return packets

    async def session(self):
        """DISCOVER_SERVICES, DISCOVER_CHARACTERISTICS, ENABLE ASYNC, ENABLE SYNC_TX."""
        await self.send(dircon.MSG_DISCOVER_SERVICES)
        services = await self.recv()
        await self.send(dircon.MSG_DISCOVER_CHARACTERISTICS, dircon.uuid_bytes(P.RIDE_SERVICE_UUID))
        characteristics = await self.recv()
        for uuid in (P.ASYNC_CHAR_UUID, P.SYNC_TX_CHAR_UUID):
            await self.send(dircon.MSG_ENABLE_NOTIFICATIONS, dircon.uuid_bytes(uuid) + b"\x01")
            await self.recv()
        return services, characteristics

    async def write_sync_rx(self, value):
        await self.send(dircon.MSG_WRITE_CHARACTERISTIC, dircon.uuid_bytes(P.SYNC_RX_CHAR_UUID) + value)

    async def close(self):
        self.writer.close()


def frames(packets):
    """ASYNC notification values, consecutive duplicates collapsed."""
    out = []
    for p in packets:
        if p.identifier == dircon.MSG_CHARACTERISTIC_NOTIFICATION and p.payload[:16] == dircon.uuid_bytes(
            P.ASYNC_CHAR_UUID
        ):
            value = p.payload[16:]
            if not out or out[-1] != value:
                out.append(value)
    return out


async def wait_state(emu, state, timeout=1.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while emu.state is not state:
        if loop.time() > end:
            raise AssertionError(f"state {emu.state} != {state}")
        await asyncio.sleep(0.01)


@pytest.fixture
async def emu():
    emulator = RideEmulator("127.0.0.1", port=0, advertise=False, keepalive_s=3600)
    await emulator.start()
    yield emulator
    await emulator.stop()


async def test_session_replies_match_zwift_expectations(emu):
    z = await FakeZwift.connect(emu.bound_port)
    services, characteristics = await z.session()
    assert services.payload == dircon.uuid_bytes(P.RIDE_SERVICE_UUID)
    assert characteristics.encode().hex() == DISCOVER_CHARACTERISTICS_GOLDEN
    assert emu.state is EmulatorState.READY
    await z.close()


async def test_ride_on_is_answered_on_sync_tx(emu):
    z = await FakeZwift.connect(emu.bound_port)
    await z.session()
    await z.write_sync_rx(P.RIDE_ON)
    response = await z.recv()
    reply = await z.recv()
    assert response.identifier == dircon.MSG_WRITE_CHARACTERISTIC
    assert reply.identifier == dircon.MSG_CHARACTERISTIC_NOTIFICATION
    assert reply.payload == dircon.uuid_bytes(P.SYNC_TX_CHAR_UUID) + P.RIDE_ON_REPLY
    await z.close()


@pytest.mark.parametrize("request_hex,object_id", [
    ("000800", 0), ("000810", 16), ("00088008", 1024), ("00088306", 771),
])
async def test_get_requests_are_answered(emu, request_hex, object_id):
    z = await FakeZwift.connect(emu.bound_port)
    await z.session()
    await z.write_sync_rx(bytes.fromhex(request_hex))
    await z.recv()  # write response
    reply = await z.recv()
    assert reply.payload == dircon.uuid_bytes(P.SYNC_TX_CHAR_UUID) + P.GET_REPLIES[object_id]
    await z.close()


async def test_unknown_get_gets_no_reply(emu):
    z = await FakeZwift.connect(emu.bound_port)
    await z.session()
    await z.write_sync_rx(bytes.fromhex("00088010"))  # id 2048, not served
    await z.recv()  # write response
    assert await z.drain_packets() == []
    await z.close()


async def test_pulse_sends_pressed_then_released(emu):
    z = await FakeZwift.connect(emu.bound_port)
    await z.session()
    assert await emu.pulse(Tap.LEFT, 120) is True
    packets = await z.drain_packets()
    pressed = [p for p in packets if p.payload[16:] == P.keypad_frame(Tap.LEFT)]
    assert len(pressed) == 3  # re-sent every 50 ms for 120 ms
    assert frames(packets) == [P.keypad_frame(Tap.LEFT), P.RELEASED_FRAME]
    await z.close()


@pytest.mark.parametrize("ms,expected_sends", [(120, 3), (200, 4), (50, 1), (60, 2)])
async def test_pulse_frame_count_does_not_depend_on_timer_resolution(emu, monkeypatch, ms, expected_sends):
    """Windows' ~15 ms timer makes short sleeps return at once; a pulse must not then flood Zwift."""
    z = await FakeZwift.connect(emu.bound_port)
    await z.session()

    async def instant_sleep(_delay):
        return None

    with monkeypatch.context() as m:
        m.setattr(ride_module.asyncio, "sleep", instant_sleep)
        assert await asyncio.wait_for(emu.pulse(Tap.LEFT, ms), 2.0) is True
    pressed = [p for p in await z.drain_packets() if p.payload[16:] == P.keypad_frame(Tap.LEFT)]
    assert len(pressed) == expected_sends  # one send per started 50 ms of the pulse
    await z.close()


async def test_pulse_without_ready_client_returns_false(emu):
    assert emu.state is EmulatorState.ADVERTISING
    assert await emu.pulse(Tap.RIGHT, 50) is False
    z = await FakeZwift.connect(emu.bound_port)
    await z.session()
    assert await emu.pulse(Tap.RIGHT, 50) is True
    await z.close()


async def test_rapid_taps_are_serialized(emu):
    z = await FakeZwift.connect(emu.bound_port)
    await z.session()
    results = await asyncio.gather(emu.pulse(Tap.LEFT, 60), emu.pulse(Tap.RIGHT, 60), emu.pulse(Tap.RIGHT, 60))
    assert results == [True, True, True]
    assert frames(await z.drain_packets()) == [
        P.keypad_frame(Tap.LEFT), P.RELEASED_FRAME,
        P.keypad_frame(Tap.RIGHT), P.RELEASED_FRAME,
        P.keypad_frame(Tap.RIGHT), P.RELEASED_FRAME,
    ]
    await z.close()


async def test_pulses_reach_a_reconnected_client(emu):
    z1 = await FakeZwift.connect(emu.bound_port)
    await z1.session()
    await z1.close()
    await wait_state(emu, EmulatorState.ADVERTISING)
    z2 = await FakeZwift.connect(emu.bound_port)
    await z2.session()
    assert await emu.pulse(Tap.RIGHT, 50) is True
    assert frames(await z2.drain_packets()) == [P.keypad_frame(Tap.RIGHT), P.RELEASED_FRAME]
    await z2.close()


async def test_write_failure_does_not_raise(emu, monkeypatch):
    z = await FakeZwift.connect(emu.bound_port)
    await z.session()

    async def broken_notify(char_uuid, value):
        raise ConnectionAbortedError(10053, "aborted by the host")

    monkeypatch.setattr(emu.dircon, "notify", broken_notify)
    assert await emu.pulse(Tap.LEFT, 50) is False  # nothing reached Zwift; no exception escapes
    await z.close()


async def test_state_changes_are_reported():
    seen = []
    emulator = RideEmulator("127.0.0.1", port=0, advertise=False, keepalive_s=3600)
    emulator.on_state_change = seen.append
    await emulator.start()
    z = await FakeZwift.connect(emulator.bound_port)
    await z.session()
    await z.close()
    await wait_state(emulator, EmulatorState.ADVERTISING)
    await emulator.stop()
    assert seen == [
        EmulatorState.ADVERTISING, EmulatorState.CONNECTED, EmulatorState.READY,
        EmulatorState.ADVERTISING, EmulatorState.STOPPED,
    ]


async def test_keepalive_sends_released_frame_when_idle():
    emulator = RideEmulator("127.0.0.1", port=0, advertise=False, keepalive_s=0.1)
    await emulator.start()
    z = await FakeZwift.connect(emulator.bound_port)
    await z.session()
    seen_released = False
    for _ in range(10):  # keepalives never go quiet, so read a bounded number of packets
        pkt = await z.recv(timeout=0.5)
        if pkt.payload[16:] == P.RELEASED_FRAME:
            seen_released = True
            break
    assert seen_released
    await z.close()
    await emulator.stop()


async def test_failed_start_cleans_up():
    emulator = RideEmulator("999.1.1.1", port=0, advertise=True, keepalive_s=3600)
    with pytest.raises(OSError):
        await emulator.start()
    assert emulator.state is EmulatorState.STOPPED
    assert emulator._zeroconf is None and emulator._server is None


def test_default_keepalive_beats_zwifts_idle_timeout():
    # Live probe 2026-10-13: Zwift drops an idle DirCon controller after ~20 s; with a 20 s keepalive it
    # reconnected every 20 s, with 5 s (BikeControl's interval) one session held for 75 s.
    assert RideEmulator("127.0.0.1").keepalive_s <= 5.0


async def test_pulse_reports_false_when_no_frame_reached_zwift(emu, monkeypatch):
    """#4: the link dropped mid-pulse, so 'steer' must not be logged as delivered."""
    z = await FakeZwift.connect(emu.bound_port)
    await z.session()

    async def nobody_listening(char_uuid, value):
        return 0

    monkeypatch.setattr(emu.dircon, "notify", nobody_listening)
    assert await emu.pulse(Tap.LEFT, 50) is False
    await z.close()


async def test_stop_survives_a_crashed_keepalive():
    """#6: a keepalive that died with an unexpected error must not stop the cleanup (mDNS, port)."""
    emulator = RideEmulator("127.0.0.1", port=0, advertise=False, keepalive_s=3600)
    await emulator.start()

    async def crashed():
        raise RuntimeError("keepalive bug")

    emulator._keepalive_task.cancel()
    emulator._keepalive_task = asyncio.create_task(crashed())
    await asyncio.sleep(0)
    await emulator.stop()
    assert emulator.state is EmulatorState.STOPPED and emulator._server is None


class _Writer:
    def __init__(self, fail=None):
        self.fail, self.data, self.closed = fail, b"", False

    def write(self, data):
        self.data += data

    async def drain(self):
        if self.fail:
            raise self.fail

    def close(self):
        self.closed = True

    def get_extra_info(self, name):
        return ("127.0.0.1", 1)


async def test_notify_reaches_the_new_client_when_the_old_one_aborted():
    """#5: Windows' ConnectionAbortedError on a dying link must not stop the frame reaching the new link."""
    server = dircon.DirconServer(dircon.Service(P.RIDE_SERVICE_UUID, []))
    old, new = _Writer(ConnectionAbortedError(10053, "aborted")), _Writer()
    for w in (old, new):
        server.clients.add(w)
        server.subscriptions[w] = {P.ASYNC_CHAR_UUID}
    assert await server.notify(P.ASYNC_CHAR_UUID, P.RELEASED_FRAME) == 1
    assert new.data and old not in server.clients


async def test_an_aborted_connection_ends_the_client_quietly():
    """#5: the client handler must end cleanly, not leave 'Task exception was never retrieved'."""
    class AbortingReader:
        async def read(self, n):
            raise ConnectionAbortedError(10053, "aborted")

    server = dircon.DirconServer(dircon.Service(P.RIDE_SERVICE_UUID, []))
    writer = _Writer()
    await server.handle_client(AbortingReader(), writer)
    assert writer.closed and writer not in server.clients
