"""PNG encoding with the standard library and numpy, for the images the bridge makes itself (instance segmentation)."""

import struct
import zlib
from typing import Any

import numpy as np
from numpy.typing import NDArray

_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def encode_png(image: NDArray[Any]) -> bytes:
    """An 8-bit RGB PNG of an (height, width, channels) array; a fourth channel (alpha) is dropped.

    Anything that isn't three-dimensional gives b"", so a renderer's empty buffer reads as "no image".
    """
    if image.ndim != 3:
        return b""
    height, width, channels = image.shape
    pixels = image.astype(np.uint8)
    if channels == 4:
        pixels = pixels[:, :, :3]

    # Each row starts with its filter type: 0, none.
    raw = b"".join(b"\x00" + pixels[row].tobytes() for row in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8 bits per channel, colour type 2 (RGB)
    return _SIGNATURE + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(raw)) + _chunk(b"IEND", b"")


def _chunk(kind: bytes, data: bytes) -> bytes:
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
