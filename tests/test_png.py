"""The bridge's PNG writer gives a file any PNG reader takes: valid chunks, and the pixels it was given."""

import builtins
import importlib
import struct
import zlib

import numpy as np

from ovmcp.core.png import encode_png, is_complete_png

PNG = encode_png(np.zeros((2, 2, 3), dtype=np.uint8))


def _read_png(data: bytes) -> tuple[dict[str, int], bytes]:
    """IHDR's fields and the decompressed image data, checking the signature and every chunk's CRC."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, chunks = 8, []
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind, body = data[pos + 4 : pos + 8], data[pos + 8 : pos + 8 + length]
        (crc,) = struct.unpack(">I", data[pos + 8 + length : pos + 12 + length])
        assert crc == zlib.crc32(kind + body) & 0xFFFFFFFF, kind
        chunks.append((kind, body))
        pos += 12 + length
    assert [kind for kind, _ in chunks] == [b"IHDR", b"IDAT", b"IEND"]
    width, height, depth, colour, compression, filtering, interlace = struct.unpack(">IIBBBBB", chunks[0][1])
    header = {"width": width, "height": height, "depth": depth, "colour": colour, "interlace": interlace}
    assert (compression, filtering) == (0, 0)
    return header, zlib.decompress(chunks[1][1])


def test_an_rgb_image_round_trips():
    image = np.arange(2 * 3 * 3, dtype=np.uint8).reshape(2, 3, 3)

    header, raw = _read_png(encode_png(image))

    assert header == {"width": 3, "height": 2, "depth": 8, "colour": 2, "interlace": 0}
    # Each row: filter type 0, then the row's RGB bytes.
    assert raw == b"\x00" + image[0].tobytes() + b"\x00" + image[1].tobytes()


def test_alpha_is_dropped():
    image = np.zeros((1, 2, 4), dtype=np.uint8)
    image[0, 0] = [10, 20, 30, 255]
    image[0, 1] = [40, 50, 60, 0]

    _, raw = _read_png(encode_png(image))

    assert raw == bytes([0, 10, 20, 30, 40, 50, 60])


def test_other_dtypes_are_cast_to_bytes():
    image = np.full((1, 1, 3), 200, dtype=np.int32)

    _, raw = _read_png(encode_png(image))

    assert raw == bytes([0, 200, 200, 200])


def test_an_array_that_is_not_an_image_gives_nothing():
    assert encode_png(np.zeros((4, 4), dtype=np.uint8)) == b""
    assert encode_png(np.zeros(0, dtype=np.uint8)) == b""


def test_a_whole_png_is_complete_and_a_partly_written_one_is_not():
    # Kit writes a capture's file after it says the capture is done; the bridge reads it only once it is whole (#32).
    data = encode_png(np.zeros((4, 6, 3), dtype=np.uint8))
    assert is_complete_png(data)
    for cut in (0, 8, len(data) // 2, len(data) - 1):
        assert not is_complete_png(data[:cut])
    assert not is_complete_png(b"not a png" + data[8:])


def test_the_module_loads_without_numpy(monkeypatch):
    # Every capture imports it, and the bridge must load in a Kit app without numpy; only encode_png needs it.
    real = builtins.__import__

    def refuse_numpy(name, *args, **kwargs):
        if name.split(".")[0] == "numpy":
            raise ImportError(name)
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse_numpy)
    module = importlib.reload(importlib.import_module("ovmcp.core.png"))
    assert module.is_complete_png(PNG)
