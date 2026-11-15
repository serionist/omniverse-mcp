"""PNG with the standard library: writing the images the bridge makes itself (instance segmentation), with numpy, and
telling a whole PNG from one Kit is still writing (every capture).
"""

import struct
import zlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from numpy.typing import NDArray

_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Every PNG ends with this chunk, empty: its length, its type and its CRC.
_IEND = b"\x00\x00\x00\x00IEND\xaeB`\x82"


def encode_png(image: "NDArray[Any]") -> bytes:
    """An 8-bit PNG: RGB of an (height, width, channels) array, a fourth channel (alpha) dropped; grey of an
    (height, width) one, a third of RGB's size and compression for a depth image (#203).

    Anything else gives b"", so a renderer's empty buffer reads as "no image".
    """
    # Here, not at the top: every capture uses this module, and the bridge must load in a Kit app without numpy.
    import numpy as np

    if image.ndim == 2:
        height, width = image.shape
        pixels = image.astype(np.uint8)
        colour_type = 0  # grey
    elif image.ndim == 3:
        height, width, channels = image.shape
        pixels = image.astype(np.uint8)
        if channels == 4:
            pixels = pixels[:, :, :3]
        colour_type = 2  # RGB
    else:
        return b""

    # Each row starts with its filter type: 0, none.
    raw = b"".join(b"\x00" + pixels[row].tobytes() for row in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, colour_type, 0, 0, 0)  # 8 bits per channel
    return _SIGNATURE + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(raw)) + _chunk(b"IEND", b"")


def png_size(data: bytes) -> tuple[int, int] | None:
    """A PNG's width and height, from its header chunk; None for anything that doesn't start as a PNG does."""
    if len(data) < 24 or not data.startswith(_SIGNATURE) or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def is_complete_png(data: bytes) -> bool:
    """Whether data is a whole PNG, from its signature to its IEND chunk: a file still being written is not."""
    return data.startswith(_SIGNATURE) and data.endswith(_IEND)


def _chunk(kind: bytes, data: bytes) -> bytes:
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
