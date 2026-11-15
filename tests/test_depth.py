"""A capture's depth (#203), without Kit: the sensor's metres made stage units, nothing hit told by the segmentation or
by the value, the grey image linear in inverse distance, the raw file, and each prim's nearest distance."""

import io
import struct
import zlib

import numpy as np
import pytest

from ovmcp.core import capture
from ovmcp.core.depth import GREY_FAR, GREY_NEAR, depth_image, npy_bytes, stage_distances

INF = np.inf


def _grey(png: bytes) -> np.ndarray:
    """The pixels of a grey PNG encode_png wrote: its one IDAT, each row after its filter byte."""
    width, height = struct.unpack(">II", png[16:24])
    start = png.index(b"IDAT") + 4
    length = struct.unpack(">I", png[start - 8 : start - 4])[0]
    raw = zlib.decompress(png[start : start + length])
    return np.frombuffer(raw, dtype=np.uint8).reshape(height, width + 1)[:, 1:]


def test_metres_become_stage_units():
    # A centimetre stage: 2.5 m is 250 units.
    distances = stage_distances(np.array([[2.5, 1.0]], dtype=np.float32), 0.01)
    assert distances[0].tolist() == pytest.approx([250.0, 100.0])


def test_the_sensor_s_extra_axis_is_dropped():
    distances = stage_distances(np.full((2, 3, 1), 4.0, dtype=np.float32), 1.0)
    assert distances.shape == (2, 3)


def test_segmentation_tells_what_was_hit():
    # The sky reads large and finite; segmentation id 0 says it is nothing, whatever its value.
    metres = np.array([[3.0, 10000.0], [0.5, 2.0]], dtype=np.float32)
    ids = np.array([[4, 0], [4, 0]], dtype=np.uint32)
    distances = stage_distances(metres, 1.0, ids=ids)
    assert distances.tolist() == [[3.0, INF], [0.5, INF]]


@pytest.mark.parametrize("sky", [INF, -INF, np.nan, 0.0, -1.0, 1e7])
def test_without_segmentation_the_value_tells_what_was_hit(sky: float):
    distances = stage_distances(np.array([[2.0, sky]], dtype=np.float32), 1.0, far_clip=1e7)
    assert distances[0, 0] == 2.0
    assert distances[0, 1] == INF


def test_a_segmentation_of_another_size_is_not_used():
    distances = stage_distances(np.array([[2.0, INF]], dtype=np.float32), 1.0, ids=np.zeros((4, 4), dtype=np.uint32))
    assert distances.tolist() == [[2.0, INF]]


def test_metres_per_unit_must_be_positive():
    with pytest.raises(ValueError, match="metersPerUnit"):
        stage_distances(np.ones((1, 1)), 0.0)


def test_the_grey_is_linear_in_inverse_distance_with_nothing_hit_black():
    # Near 1, far 4: 1/2 sits two thirds of the way from 1/4 to 1/1, so its grey two thirds of the way up.
    distances = np.array([[1.0, 2.0, 4.0, INF]], dtype=np.float32)
    depth = depth_image(distances)
    expected_middle = round(GREY_FAR + (0.5 - 0.25) / (1 - 0.25) * (GREY_NEAR - GREY_FAR))
    assert _grey(depth.png).tolist() == [[GREY_NEAR, expected_middle, GREY_FAR, 0]]
    assert (depth.near, depth.far) == (1.0, 4.0)
    assert depth.nothing_hit == 0.25


def test_one_distance_is_white():
    depth = depth_image(np.array([[3.0, 3.0], [INF, 3.0]], dtype=np.float32))
    assert _grey(depth.png).tolist() == [[GREY_NEAR, GREY_NEAR], [0, GREY_NEAR]]
    assert (depth.near, depth.far) == (3.0, 3.0)


def test_nothing_hit_is_black_with_no_range():
    depth = depth_image(np.full((2, 2), INF, dtype=np.float32))
    assert not _grey(depth.png).any()
    assert (depth.near, depth.far, depth.nothing_hit) == (None, None, 1.0)


def test_the_raw_file_loads_as_the_distances():
    distances = np.array([[1.5, INF]], dtype=np.float32)
    loaded = np.load(io.BytesIO(npy_bytes(distances)))
    assert loaded.dtype == np.float32
    assert loaded.tolist() == [[1.5, INF]]


def test_each_prim_s_nearest_distance_is_the_minimum_over_its_ids():
    ids = np.array([[0, 7, 7], [9, 3, 0]], dtype=np.uint32)
    distances = np.array([[INF, 5.0, 4.0], [2.0, 6.0, INF]], dtype=np.float32)
    names = {3: "/World/A", 7: "/World/B", 9: "/World/B"}  # two ids, one prim
    _image, legend, nearest = capture.colour_instances(ids, names.__getitem__, distances)
    assert nearest == {"/World/A": 6.0, "/World/B": 2.0}
    assert list(legend) == ["/World/A", "/World/B"]
