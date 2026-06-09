"""Pure broadlink-IR <-> pulse-tick codec. No I/O, no hardware.

A broadlink IR packet: byte0=0x26 (IR), byte1=repeat, bytes2-3=little-endian
payload length, then the pulse stream (1 byte per pulse, or 0x00 + 2 big-endian
bytes for pulses > 255), then a 0x00 0x0d 0x05 trailer. One tick is 2**-15 s.
"""
import base64

TICK_US = 1_000_000 / 32768  # ~30.5176 microseconds per tick


def decode_broadlink_bytes(data: bytes) -> list[int]:
    if len(data) < 4:
        raise ValueError(f"packet too short ({len(data)} bytes)")
    if data[0] != 0x26:
        raise ValueError(f"not a broadlink IR packet (byte0={data[:1].hex()})")
    length = data[2] | (data[3] << 8)
    i, end, pulses = 4, 4 + length, []
    try:
        while i < end:
            b = data[i]
            if b == 0:
                pulses.append((data[i + 1] << 8) | data[i + 2])
                i += 3
            else:
                pulses.append(b)
                i += 1
    except IndexError as exc:
        raise ValueError(f"truncated payload at offset {i}") from exc
    return pulses


def decode_broadlink_b64(b64: str) -> list[int]:
    try:
        data = base64.b64decode(b64)
    except Exception as exc:
        raise ValueError(f"invalid base64: {exc}") from exc
    return decode_broadlink_bytes(data)


def encode_broadlink(ticks: list[int]) -> bytes:
    body = bytearray()
    for v in ticks:
        if v <= 0:
            continue  # 0/negative tick is a no-op pulse; 0x00 would break the escape protocol
        if v > 255:
            body += bytes([0x00, (v >> 8) & 0xFF, v & 0xFF])
        else:
            body.append(v & 0xFF)
    header = bytes([0x26, 0x00, len(body) & 0xFF, (len(body) >> 8) & 0xFF])
    return bytes(header) + bytes(body) + b"\x00\x0d\x05"


def raw_to_ticks(raw) -> list[int]:
    tokens = raw.split() if isinstance(raw, str) else raw
    return [round(abs(int(x)) / TICK_US) for x in tokens]


def b64_to_bytes(b64: str) -> bytes:
    return base64.b64decode(b64)
