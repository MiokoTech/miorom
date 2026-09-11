import pytest
from miorom.core.delta import (
    cumulative_offsets,
    offsets_to_lengths,
    delta_decode,
    delta_encode,
    relative_to_absolute,
    absolute_to_relative,
)


def test_cumulative_offsets():
    lengths = [100, 200, 300]
    # Without include_end
    starts = cumulative_offsets(lengths, base_offset=0x1000, include_end=False)
    assert starts == [0x1000, 0x1000 + 100, 0x1000 + 300]

    # With include_end
    starts_with_end = cumulative_offsets(lengths, base_offset=0x1000, include_end=True)
    assert starts_with_end == [0x1000, 0x1000 + 100, 0x1000 + 300, 0x1000 + 600]


def test_offsets_to_lengths():
    offsets = [0, 100, 250, 400]
    lengths = offsets_to_lengths(offsets, total_size=500)
    assert lengths == [100, 150, 150, 100]

    # Decreasing offset error
    with pytest.raises(ValueError):
        offsets_to_lengths([100, 50])


def test_delta_roundtrip():
    values = [100, 105, 107, 120, 150, 145]
    deltas = delta_encode(values, initial=100)
    assert deltas == [0, 5, 2, 13, 30, -5]

    decoded = delta_decode(deltas, initial=100)
    assert decoded == values


def test_relative_absolute_conversion():
    base = 0x8000
    relatives = [0, 16, 32, 64]
    absolutes = relative_to_absolute(relatives, base)
    assert absolutes == [0x8000, 0x8010, 0x8020, 0x8040]

    re_relatives = absolute_to_relative(absolutes, base)
    assert re_relatives == relatives
