"""
Unit tests for miorom.core.pointer_analyzer.
"""

import pytest

from miorom.core.pointer_analyzer import (
    PointerSequenceMetrics,
    PointerTableCandidate,
    unpack_pointer,
    pack_pointer,
    unpack_pointers,
    pack_pointers,
    verify_stride_monotonicity,
    calculate_monotonicity_ratio,
    analyze_pointer_sequence,
    remap_pointers,
    find_pointer_tables,
)


def test_pack_unpack_pointer_16bit():
    raw_le = pack_pointer(0x8020, stride=2, endian="<")
    assert raw_le == b"\x20\x80"
    assert unpack_pointer(raw_le, 0, stride=2, endian="<") == 0x8020

    raw_be = pack_pointer(0x8020, stride=2, endian=">")
    assert raw_be == b"\x80\x20"
    assert unpack_pointer(raw_be, 0, stride=2, endian=">") == 0x8020


def test_pack_unpack_pointer_24bit():
    raw_le = pack_pointer(0xC18234, stride=3, endian="<")
    assert raw_le == b"\x34\x82\xC1"
    assert unpack_pointer(raw_le, 0, stride=3, endian="<") == 0xC18234

    raw_be = pack_pointer(0xC18234, stride=3, endian=">")
    assert raw_be == b"\xC1\x82\x34"
    assert unpack_pointer(raw_be, 0, stride=3, endian=">") == 0xC18234


def test_pack_unpack_pointer_32bit():
    raw_le = pack_pointer(0x08012345, stride=4, endian="<")
    assert raw_le == b"\x45\x23\x01\x08"
    assert unpack_pointer(raw_le, 0, stride=4, endian="<") == 0x08012345

    raw_be = pack_pointer(0x80045678, stride=4, endian=">")
    assert raw_be == b"\x80\x04\x56\x78"
    assert unpack_pointer(raw_be, 0, stride=4, endian=">") == 0x80045678


def test_pack_unpack_pointer_errors():
    with pytest.raises(ValueError):
        pack_pointer(0x10000, stride=2)
    with pytest.raises(ValueError):
        pack_pointer(0x1000000, stride=3)
    with pytest.raises(ValueError):
        pack_pointer(10, stride=5)
    with pytest.raises(ValueError):
        pack_pointer(10, stride=2, endian="=")

    with pytest.raises(ValueError):
        unpack_pointer(b"\x00\x00", 1, stride=2)
    with pytest.raises(ValueError):
        unpack_pointer(b"\x00\x00", 0, stride=5)
    with pytest.raises(ValueError):
        unpack_pointer(b"\x00\x00", 0, stride=2, endian="=")


def test_unpack_pack_pointers_sequence():
    targets = [0x1000, 0x1024, 0x1080, 0x1100]
    data = pack_pointers(targets, stride=2, endian="<")
    assert len(data) == 8
    unpacked = unpack_pointers(data, offset=0, count=4, stride=2, endian="<")
    assert unpacked == targets

    auto_unpacked = unpack_pointers(data, stride=2, endian="<")
    assert auto_unpacked == targets

    with pytest.raises(ValueError):
        unpack_pointers(data, offset=0, count=5, stride=2, endian="<")


def test_monotonicity_verification():
    assert verify_stride_monotonicity([]) is True
    assert verify_stride_monotonicity([100]) is True
    assert verify_stride_monotonicity([100, 120, 140, 160]) is True
    assert verify_stride_monotonicity([100, 120, 120, 160], allow_duplicates=True) is True
    assert verify_stride_monotonicity([100, 120, 120, 160], allow_duplicates=False) is False
    assert verify_stride_monotonicity([100, 120, 110, 160]) is False

    ratio = calculate_monotonicity_ratio([100, 120, 110, 130])
    assert ratio == pytest.approx(2 / 3)


def test_analyze_pointer_sequence_metrics():
    targets = [0x8000, 0x8010, 0x8025, 0x8040]
    metrics = analyze_pointer_sequence(targets, min_target=0x8000, max_target=0x8100)
    assert metrics.count == 4
    assert metrics.min_target == 0x8000
    assert metrics.max_target == 0x8040
    assert metrics.span == 0x40
    assert metrics.monotonic_ratio == 1.0
    assert metrics.strictly_monotonic_ratio == 1.0
    assert metrics.duplicate_ratio == 0.0
    assert metrics.confidence > 0.7

    empty_metrics = analyze_pointer_sequence([])
    assert empty_metrics.count == 0
    assert empty_metrics.confidence == 0.0

    zeros = [0x0000, 0x0000, 0x0000, 0x0000]
    zero_metrics = analyze_pointer_sequence(zeros, min_target=0, max_target=0xFFFF)
    assert zero_metrics.confidence == 0.0


def test_remap_pointers_and_candidate():
    targets = [0x1000, 0x1020, 0x1050]
    remapped = remap_pointers(targets, default_delta=0x200)
    assert remapped == [0x1200, 0x1220, 0x1250]

    custom_map = {0x1000: 0x2000, 0x1020: 0x2050}
    mapped = remap_pointers(targets, offset_map=custom_map, default_delta=0x10)
    assert mapped == [0x2000, 0x2050, 0x1060]

    candidate = PointerTableCandidate(
        table_offset=0x50,
        entry_count=3,
        stride=2,
        endian="<",
        base_offset=0,
        min_target=0x1000,
        max_target=0x1050,
        confidence=0.85,
        is_monotonic=True,
        targets=targets,
    )
    new_candidate = candidate.remap(default_delta=0x100)
    assert new_candidate.targets == [0x1100, 0x1120, 0x1150]
    assert new_candidate.min_target == 0x1100
    assert new_candidate.max_target == 0x1150

    as_dict = new_candidate.to_dict()
    assert as_dict["entry_count"] == 3
    assert as_dict["targets"] == [0x1100, 0x1120, 0x1150]
    assert new_candidate.to_bytes() == pack_pointers(new_candidate.targets, stride=2, endian="<")


def test_find_pointer_tables_scanning():
    # Build synthetic ROM buffer
    rom = bytearray(512)

    # 16-bit little-endian table at offset 0x20 (NES style text table)
    nes_targets = [0x8000, 0x8020, 0x8045, 0x8070, 0x80A0]
    rom[0x20 : 0x20 + 10] = pack_pointers(nes_targets, stride=2, endian="<")

    # 24-bit little-endian table at offset 0x80 (SNES style asset table)
    snes_targets = [0xC10000, 0xC10400, 0xC10800, 0xC10C00, 0xC11000]
    rom[0x80 : 0x80 + 15] = pack_pointers(snes_targets, stride=3, endian="<")

    # Discover 16-bit tables in $8000..$8FFF
    nes_cands = find_pointer_tables(
        bytes(rom),
        min_target=0x8000,
        max_target=0x8FFF,
        strides=(2,),
        endian="<",
        min_entries=4,
    )
    assert len(nes_cands) >= 1
    c = nes_cands[0]
    assert c.table_offset == 0x20
    assert c.stride == 2
    assert c.endian == "<"
    assert c.entry_count == 5
    assert c.targets == nes_targets
    assert c.is_monotonic is True
    assert c.confidence > 0.7

    # Discover 24-bit SNES tables
    snes_cands = find_pointer_tables(
        bytes(rom),
        min_target=0xC10000,
        max_target=0xC20000,
        strides=(3,),
        endian="<",
        min_entries=4,
    )
    assert len(snes_cands) >= 1
    sc = snes_cands[0]
    assert sc.table_offset == 0x80
    assert sc.stride == 3
    assert sc.endian == "<"
    assert sc.entry_count == 5
    assert sc.targets == snes_targets
