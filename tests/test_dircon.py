from vs200steer.zwift import dircon

ASYNC = "00000002-19ca-4651-86e5-fa29dcdd09d1"


def test_packet_roundtrip_keeps_trailing_bytes():
    data = dircon.Packet(dircon.MSG_WRITE_CHARACTERISTIC, 7, 0, b"\x01\x02").encode()
    assert data.hex() == "010407000002" + "0102"
    pkt, rest = dircon.decode(data + b"\x01")
    assert (pkt.identifier, pkt.sequence, pkt.payload, rest) == (4, 7, b"\x01\x02", b"\x01")


def test_decode_waits_for_a_complete_packet():
    data = dircon.Packet(dircon.MSG_WRITE_CHARACTERISTIC, 1, 0, b"\x01\x02").encode()
    pkt, rest = dircon.decode(data[:-1])
    assert pkt is None and rest == data[:-1]


def test_notification_is_uuid_then_value():
    pkt = dircon.notification(ASYNC, b"\x23")
    assert pkt.encode().hex() == "010600000011" + "0000000219ca465186e5fa29dcdd09d1" + "23"
