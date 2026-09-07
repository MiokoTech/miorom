import struct
import pytest
from miorom.patch.pointer_remapper import (
    RelativePointerTable,
    MultiPointerRemapper,
)


def test_relative_pointer_table():
    buf = bytearray(0x80)
    # 3 targets at absolute offsets 0x30, 0x45, 0x60
    # Relative to base_offset = 0x20
    # Stored relative offsets should be: 0x10, 0x25, 0x40
    targets = [0x30, 0x45, 0x60]
    base_offset = 0x20

    RelativePointerTable.write(
        buffer=buf,
        table_offset=0x00,
        targets=targets,
        base_offset=base_offset,
        pointer_size=2,
        endian="<",
    )

    # Read back raw values
    raw0 = struct.unpack_from("<H", buf, 0x00)[0]
    raw1 = struct.unpack_from("<H", buf, 0x02)[0]
    raw2 = struct.unpack_from("<H", buf, 0x04)[0]
    assert raw0 == 0x10
    assert raw1 == 0x25
    assert raw2 == 0x40

    # Read using RelativePointerTable
    resolved = RelativePointerTable.read(
        data=bytes(buf),
        table_offset=0x00,
        count=3,
        base_offset=base_offset,
        pointer_size=2,
        endian="<",
    )
    assert resolved == targets


def test_multi_pointer_remapper():
    buf = bytearray(0x100)
    # Three pointers in table pointing to target 0x50 (1-to-many relationship)
    # Pointers located at 0x00, 0x08, 0x14
    struct.pack_into("<I", buf, 0x00, 0x50)
    struct.pack_into("<I", buf, 0x08, 0x50)
    struct.pack_into("<I", buf, 0x14, 0x50)
    # Another pointer at 0x20 pointing to 0x70
    struct.pack_into("<I", buf, 0x20, 0x70)

    ptr_locations = [0x00, 0x08, 0x14, 0x20]
    ref_map = MultiPointerRemapper.scan_references(bytes(buf), ptr_locations, pointer_size=4)

    assert 0x50 in ref_map
    assert len(ref_map[0x50]) == 3
    assert set(ref_map[0x50]) == {0x00, 0x08, 0x14}

    # Remap 0x50 -> 0x120, and 0x70 -> 0x150
    updated_cnt = MultiPointerRemapper.remap(
        buffer=buf,
        old_to_new={0x50: 0x120, 0x70: 0x150},
        ref_map=ref_map,
        pointer_size=4,
    )

    assert updated_cnt == 4
    # Check that all locations now point to new targets
    assert struct.unpack_from("<I", buf, 0x00)[0] == 0x120
    assert struct.unpack_from("<I", buf, 0x08)[0] == 0x120
    assert struct.unpack_from("<I", buf, 0x14)[0] == 0x120
    assert struct.unpack_from("<I", buf, 0x20)[0] == 0x150
