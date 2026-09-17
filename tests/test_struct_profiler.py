import struct

import pytest

from miorom.core.struct_profiler import FieldType, StructProfiler


def test_autodetect_stride_and_field_profiling():
    record_count = 12
    stride = 16
    buf = bytearray(record_count * stride)

    for i in range(record_count):
        off = i * stride
        # Field 1: u16 ID (0x00)
        struct.pack_into("<H", buf, off + 0, 100 + i)
        # Field 2: u16 HP (0x02)
        struct.pack_into("<H", buf, off + 2, 500 + i * 10)
        # Field 3: u32 pointer (0x04) in 0x08000000 range
        struct.pack_into("<I", buf, off + 4, 0x08001000 + i * 32)
        # Field 4: u32 flags (0x08)
        struct.pack_into("<I", buf, off + 8, 0x00010000 | i)
        # Field 5: u32 zero padding (0x0C)
        struct.pack_into("<I", buf, off + 12, 0)

    # Autodetect Stride
    candidates = StructProfiler.autodetect_stride(bytes(buf), min_stride=4, max_stride=32)
    assert len(candidates) > 0
    # Top candidate should be 16
    assert candidates[0].stride == 16

    # Profile Struct
    profile = StructProfiler.profile_struct(
        data=bytes(buf),
        stride=16,
        pointer_range=(0x08000000, 0x08FFFFFF),
    )

    assert profile.stride == 16
    assert profile.record_count == record_count
    assert profile.total_bytes == record_count * stride
    assert len(profile.fields) >= 4

    # Verify pointer field detected at offset 4
    ptr_field = next(f for f in profile.fields if f.offset == 4)
    assert ptr_field.field_type == FieldType.POINTER_LE
    assert ptr_field.size == 4

    # Verify padding field detected at offset 12
    pad_field = next(f for f in profile.fields if f.offset == 12)
    assert pad_field.field_type == FieldType.PADDING
    assert pad_field.is_constant is True

    # Export to C struct
    c_code = profile.to_c_struct(struct_name="MonsterStats")
    assert "typedef struct {" in c_code
    assert "MonsterStats;" in c_code
    assert "void* ptr_04;" in c_code
    assert "pad_0C" in c_code

    # Export to JSON schema
    schema = profile.to_json_schema()
    assert schema["stride"] == 16
    assert schema["record_count"] == 12
    assert len(schema["fields"]) >= 4


def test_profile_struct_field_boundaries_small_u32_and_u16():
    """
    Regression test for Masalah 1:
    Small 32-bit fields (e.g. id=0..19) must not be falsely demoted to 16-bit fields
    and desynchronize subsequent field offsets.
    Struct layout: <IHHI (u32 id, u16 hp, u16 mp, u32 flags) = 12 bytes/record.
    """
    record_count = 20
    records = bytearray()
    for i in range(record_count):
        records += struct.pack("<IHHI", i, 100 + i, 50 + i, 0xABCD0000 + i)

    profile = StructProfiler.profile_struct(bytes(records), stride=12)
    assert profile.stride == 12
    assert profile.record_count == record_count
    assert len(profile.fields) == 4

    # Assert exact offsets and sizes
    offsets = [f.offset for f in profile.fields]
    sizes = [f.size for f in profile.fields]
    types = [f.field_type for f in profile.fields]

    assert offsets == [0, 4, 6, 8]
    assert sizes == [4, 2, 2, 4]
    assert types == [
        FieldType.UINT32_LE,
        FieldType.UINT16_LE,
        FieldType.UINT16_LE,
        FieldType.UINT32_LE,
    ]

    # Big-endian test (>IHHI)
    be_records = bytearray()
    for i in range(record_count):
        be_records += struct.pack(">IHHI", i, 100 + i, 50 + i, 0xABCD0000 + i)

    be_profile = StructProfiler.profile_struct(bytes(be_records), stride=12, endian=">")
    assert [f.offset for f in be_profile.fields] == [0, 4, 6, 8]
    assert [f.size for f in be_profile.fields] == [4, 2, 2, 4]
    assert [f.field_type for f in be_profile.fields] == [
        FieldType.UINT32_BE,
        FieldType.UINT16_BE,
        FieldType.UINT16_BE,
        FieldType.UINT32_BE,
    ]


def test_profile_struct_stride_composability():
    """
    Regression test for Masalah 2:
    autodetect_stride() output (List[StrideCandidate]) or single StrideCandidate
    can be passed directly to profile_struct() without TypeError.
    """
    record_count = 20
    records = bytearray()
    for i in range(record_count):
        records += struct.pack("<IHHI", i, 100 + i, 50 + i, 0xABCD0000 + i)

    candidates = StructProfiler.autodetect_stride(bytes(records), min_stride=4, max_stride=24)
    assert len(candidates) > 0
    top_stride = candidates[0].stride
    assert top_stride == 12

    # 1. Pass List[StrideCandidate] directly
    profile_from_list = StructProfiler.profile_struct(bytes(records), candidates)
    assert profile_from_list.stride == 12
    assert len(profile_from_list.fields) == 4

    # 2. Pass single StrideCandidate
    profile_from_single = StructProfiler.profile_struct(bytes(records), candidates[0])
    assert profile_from_single.stride == 12
    assert len(profile_from_single.fields) == 4

    # 3. Pass int directly (backward compatibility)
    profile_from_int = StructProfiler.profile_struct(bytes(records), 12)
    assert profile_from_int.stride == 12
    assert len(profile_from_int.fields) == 4

    # 4. Error validation: empty list
    with pytest.raises(ValueError, match="stride candidate list is empty"):
        StructProfiler.profile_struct(bytes(records), [])

    # 5. Error validation: invalid type
    with pytest.raises(TypeError, match="stride must be int, StrideCandidate, or List\\[StrideCandidate\\]"):
        StructProfiler.profile_struct(bytes(records), "invalid_stride")  # type: ignore

    # 6. Error validation: non-positive int
    with pytest.raises(ValueError, match="stride must be a positive integer"):
        StructProfiler.profile_struct(bytes(records), 0)

