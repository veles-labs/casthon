"""Independent test-side bytesrepr fixtures; never import the contract SDK."""


def u32(value):
    return value.to_bytes(4, "little")


def text(value):
    data = value.encode("utf-8")
    return u32(len(data)) + data


def payload(kind, value):
    if kind == "Bool":
        assert type(value) is bool
        return bytes([value])
    if kind == "Key":
        assert key_length(value) == len(value)
        return value
    if kind == "U8":
        return bytes([value])
    if kind == "U32":
        return u32(value)
    if kind == "U256":
        assert 0 <= value < 1 << 256
        data = value.to_bytes((value.bit_length() + 7) // 8, "little")
        return bytes([len(data)]) + data
    if kind == "String":
        return text(value)
    raise ValueError("Unsupported test codec " + kind)


def envelope(kind, value=None):
    data = b"" if kind == "Unit" else payload(kind, value)
    return u32(len(data)) + data + bytes([{"U8": 3, "U32": 4, "U256": 7,
                                          "String": 10, "Unit": 9, "Bool": 0, "Key": 11}[kind]])


def unwrap(data):
    size = int.from_bytes(data[:4], "little")
    assert size <= len(data) - 5  # Recursive CLTypes can occupy several bytes.
    return data[4:4 + size]


def key_length(data, offset=0):
    tag = data[offset]
    if tag == 2:
        return 34
    if tag == 5:
        return 9
    if tag == 15:
        sub = data[offset + 1]
        return 34 if sub in (0, 1, 9) else 42 if sub == 4 else 66
    if tag in (17, 24):
        return 34
    if tag == 18:
        return 2 if data[offset + 1] == 0 else 34
    if tag == 19:
        return 71 if data[offset + 66] else 67
    if tag == 20:
        return 66
    if tag == 22:
        return 42
    if tag == 23:
        return 67
    assert tag <= 24
    return 33
