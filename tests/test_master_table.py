import struct
import pytest
from miorom.archive import MasterTableArchive
from miorom.core.mapper import ByteOffsetMapper


def test_master_table_archive_cascade():
    # 5 entries, 8 bytes each (size: u32, offset: u32)
    header_size = 5 * 8
    payloads = [
        b"Entry 0 data",
        b"Entry 1 data here",
        b"Entry 2",
        b"Entry 3 long data block",
        b"Entry 4 end",
    ]

    buf = bytearray(header_size)
    cur = header_size
    for i, p in enumerate(payloads):
        struct.pack_into("<II", buf, i * 8, len(p), cur)
        buf.extend(p)
        cur += len(p)

    archive = MasterTableArchive(bytes(buf), table_entries=5, record_format="<II")
    assert len(archive.table) == 5
    assert archive.table[0] == [len(payloads[0]), header_size]

    # Replace entry 1 with longer data (+10 bytes)
    e1_start = archive.table[1][1]
    e1_end = e1_start + archive.table[1][0]
    new_e1 = payloads[1] + b" [EXTENDED]"
    delta = archive.replace_slice(e1_start, e1_end, new_e1)
    assert delta == len(b" [EXTENDED]")

    # Update entry 1 size and cascade subsequent entries
    archive.table[1][0] += delta
    archive.cascade_offset(from_index=2, delta=delta, offset_field_idx=1)

    # Re-serialize
    out_bytes = archive.to_bytes()
    reloaded = MasterTableArchive(out_bytes, table_entries=5, record_format="<II")
    assert reloaded.table[1][0] == len(new_e1)
    assert reloaded.table[2][1] == archive.get_pristine_record(2)[1] + delta
    assert reloaded.table[3][1] == archive.get_pristine_record(3)[1] + delta


def test_update_footer_anchored_fields():
    old_data = b"\x00" * 4 + struct.pack("<H", 100) + b"\x00" * 20
    new_data = bytearray(b"\x00" * 4 + struct.pack("<H", 100) + b"\x00" * 30)  # +10 bytes

    results = ByteOffsetMapper.update_footer_anchored_fields(
        new_data, old_data, offsets=[4], endian="<", field_size=2
    )
    assert results[4] == 110
    assert struct.unpack_from("<H", new_data, 4)[0] == 110
