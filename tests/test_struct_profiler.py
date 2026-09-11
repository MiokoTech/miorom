import struct
import pytest
from miorom.core.struct_profiler import StructProfiler, FieldType, StructProfile


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
