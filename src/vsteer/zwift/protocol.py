"""Zwift Ride controller protocol as Zwift expects it over DirCon.

Every constant here was verified against Zwift on 2026-10-13 (see the design spec).
"""

from __future__ import annotations

from ..events import Tap

RIDE_SERVICE_UUID = "0000fc82-0000-1000-8000-00805f9b34fb"
ASYNC_CHAR_UUID = "00000002-19ca-4651-86e5-fa29dcdd09d1"    # notify: button state
SYNC_RX_CHAR_UUID = "00000003-19ca-4651-86e5-fa29dcdd09d1"  # write: commands from Zwift
SYNC_TX_CHAR_UUID = "00000004-19ca-4651-86e5-fa29dcdd09d1"  # notify: replies to Zwift

# DirCon's own property bits. GATT bits (write 0x08, notify 0x10) make Zwift
# subscribe to SYNC_RX only, and nothing works.
DIRCON_PROP_WRITE = 0x02
DIRCON_PROP_NOTIFY = 0x04

MDNS_SERVICE_TYPE = "_wahoo-fitness-tnp._tcp.local."
DEFAULT_DEVICE_NAME = "KICKR BIKE PRO 1337"
# Without manufacturer-data (Zwift Inc 0x094A, type 0x0B) Zwift does not list the device.
MDNS_TXT = {
    "ble-service-uuids": b"FC82",
    "mac-address": b"50-50-25-6C-66-9C",
    "serial-number": b"244700181",
    "manufacturer-data": b"094A0BAAAA",
}

RIDE_ON = b"RideOn"
RIDE_ON_REPLY = b"RideOn\x01\x03"

OP_GET = 0x00
OP_GET_RESPONSE = 0x3C
OP_RIDE_KEYPAD = 0x23
OP_BATTERY_NOTIF = 0x19

# D-pad bits in the Ride button map; buttons are active low (bit clear = pressed).
_DPAD_MASKS = {Tap.LEFT: 0x01, Tap.RIGHT: 0x04}


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | 0x80 if value else byte)
        if not value:
            return bytes(out)


def _read_varint(buf: bytes, i: int) -> tuple[int, int]:
    value, shift = 0, 0
    while True:
        if i >= len(buf):
            raise ValueError("truncated varint")
        byte = buf[i]
        i += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, i
        shift += 7


def _pb_uint(field: int, value: int) -> bytes:
    return _varint(field << 3) + _varint(value)


def _pb_bytes(field: int, value: bytes) -> bytes:
    return _varint((field << 3) | 2) + _varint(len(value)) + value


def keypad_frame(direction: Tap | None) -> bytes:
    """RideKeyPadStatus {1: buttonMap} with the D-pad bit for `direction` cleared."""
    button_map = 0xFFFFFFFF
    if direction is not None:
        button_map &= ~_DPAD_MASKS[direction]
    return bytes([OP_RIDE_KEYPAD]) + _pb_uint(1, button_map)


RELEASED_FRAME = keypad_frame(None)


def battery_notification(level: int) -> bytes:
    """BatteryNotification {1: newPercLevel}, as a Zwift Ride sends it when its level changes."""
    return bytes([OP_BATTERY_NOTIF]) + _pb_uint(1, level)


def battery_state_reply(level: int) -> bytes:
    """GET reply for BATTERY_STATE {chgState: IDLE, percLevel, timeToEmpty: 0, timeToFull: 0}."""
    return _get_response(771, _pb_uint(1, 0) + _pb_uint(2, level) + _pb_uint(3, 0) + _pb_uint(4, 0))


def parse_get(value: bytes) -> int | None:
    """dataObjectId of a GET (opcode 0x00, protobuf {1: id}), or None if not a GET."""
    if len(value) < 2 or value[0] != OP_GET:
        return None
    i = 1
    try:
        while i < len(value):
            key, i = _read_varint(value, i)
            if key & 0x07 != 0:
                return None
            field_value, i = _read_varint(value, i)
            if key >> 3 == 1:
                return field_value
    except ValueError:
        return None
    return None


def _get_response(object_id: int, data: bytes) -> bytes:
    return bytes([OP_GET_RESPONSE]) + _pb_uint(1, object_id) + _pb_bytes(2, data)


GET_REPLIES: dict[int, bytes] = {
    # PAGE_DEV_INFO: BikeControl's captured "Zwift Click2" page, verified with Zwift.
    0: bytes.fromhex(
        "3c080012460a440883041204000001011a0b5a7769667420436c69636b320f30422d3538443135414242343336333a"
        "03422e304204080210014801500b5a0c353844313541424234333633"
    ),
    # PAGE_CLIENT_SERVER_CONFIGURATION {notifications: 0}
    16: _get_response(16, _pb_uint(1, 0)),
    # PAGE_CONTROLLER_INPUT_CONFIG {supportedDigitalInputs: 4607, supportedAnalogInputs: 0}
    1024: _get_response(1024, _pb_uint(1, 4607) + _pb_uint(2, 0)),
    # BATTERY_STATE while the remote's level is unknown; the emulator serves the real one (#36)
    771: battery_state_reply(100),
}
