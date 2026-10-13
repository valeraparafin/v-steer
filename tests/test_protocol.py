import pytest

from vs200steer.events import Tap
from vs200steer.zwift import protocol as P


def test_dpad_frames_match_the_spike():
    assert P.keypad_frame(Tap.LEFT).hex() == "2308feffffff0f"
    assert P.keypad_frame(Tap.RIGHT).hex() == "2308fbffffff0f"
    assert P.RELEASED_FRAME.hex() == "2308ffffffff0f"
    assert P.keypad_frame(None) == P.RELEASED_FRAME


@pytest.mark.parametrize("payload,expected", [
    ("000800", 0),
    ("000810", 16),
    ("00088008", 1024),
    ("00088306", 771),
])
def test_parse_get_reads_data_object_id(payload, expected):
    assert P.parse_get(bytes.fromhex(payload)) == expected


@pytest.mark.parametrize("payload", ["", "526964654f6e", "2308ffffffff0f", "00", "001000"])
def test_parse_get_rejects_non_get_or_missing_id(payload):
    assert P.parse_get(bytes.fromhex(payload)) is None


def test_get_replies_golden_bytes():
    assert P.GET_REPLIES[0].hex() == (
        "3c080012460a440883041204000001011a0b5a7769667420436c69636b320f30422d3538443135414242343336333a"
        "03422e304204080210014801500b5a0c353844313541424234333633"
    )
    assert P.GET_REPLIES[16].hex() == "3c081012020800"
    assert P.GET_REPLIES[1024].hex() == "3c088008120508ff231000"
    assert P.GET_REPLIES[771].hex() == "3c08830612080800106418002000"


def test_mdns_txt_matches_what_zwift_accepted():
    assert P.MDNS_TXT == {
        "ble-service-uuids": b"FC82",
        "mac-address": b"50-50-25-6C-66-9C",
        "serial-number": b"244700181",
        "manufacturer-data": b"094A0BAAAA",
    }
    assert P.MDNS_SERVICE_TYPE == "_wahoo-fitness-tnp._tcp.local."
