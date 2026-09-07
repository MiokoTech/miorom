import struct
import pytest
from miorom.patch.relocator import (
    AutoRelocationManager,
    RelocatablePointer,
    RelocationRecord,
    RelocationSummary,
)
from miorom.patch.slack import SlackSpaceManager


def test_in_place_relocation():
    buf = bytearray(256)
    # Write pointer at 0x10 pointing to 0x40
    struct.pack_into("<I", buf, 0x10, 0x40)
    # Write old string at 0x40 (20 bytes)
    buf[0x40:0x54] = b"Original Text Data!!"

    manager = AutoRelocationManager(buf)
    new_data = b"Shorter"  # 7 bytes <= 20 bytes

    rec = manager.relocate_item(
        item_id=0,
        old_offset=0x40,
        old_size=20,
        new_payload=new_data,
        pointers=[0x10],
    )

    assert rec.overflowed is False
    assert rec.new_offset == 0x40
    assert buf[0x40:0x47] == b"Shorter"
    # Remainder should be padded with 0
    assert buf[0x47:0x54] == b"\x00" * (20 - 7)
    # Pointer unchanged
    assert struct.unpack_from("<I", buf, 0x10)[0] == 0x40


def test_overflow_spillover_relocation():
    buf = bytearray(256)
    # Pointer at 0x08 pointing to 0x20
    struct.pack_into("<I", buf, 0x08, 0x20)
    # Old item at 0x20 of size 10
    buf[0x20:0x2A] = b"Short text"

    manager = AutoRelocationManager(buf)
    new_data = b"This is a much longer translated dialogue text that overflows original bounds!"

    rec = manager.relocate_item(
        item_id="dialogue_01",
        old_offset=0x20,
        old_size=10,
        new_payload=new_data,
        pointers=[0x08],
        allow_eof_growth=True,
    )

    assert rec.overflowed is True
    assert rec.new_offset > 0x20
    # Old location zeroed
    assert buf[0x20:0x2A] == b"\x00" * 10
    # New location contains new payload
    assert buf[rec.new_offset : rec.new_offset + len(new_data)] == new_data
    # Pointer at 0x08 updated to new_offset
    updated_ptr = struct.unpack_from("<I", buf, 0x08)[0]
    assert updated_ptr == rec.new_offset


def test_multiple_pointers_with_base_address():
    buf = bytearray(256)
    gba_base = 0x08000000
    target_offset = 0x80

    # Pointer 1 at 0x04 (GBA absolute ROM address: 0x08000080)
    struct.pack_into("<I", buf, 0x04, gba_base + target_offset)
    # Pointer 2 at 0x08
    struct.pack_into("<I", buf, 0x08, gba_base + target_offset)

    manager = AutoRelocationManager(buf)
    ptr1 = RelocatablePointer(pointer_offset=0x04, base_address=gba_base)
    ptr2 = RelocatablePointer(pointer_offset=0x08, base_address=gba_base)

    new_data = b"Expanded GBA String Content" * 5  # Overflows size 16
    rec = manager.relocate_item(
        item_id=1,
        old_offset=target_offset,
        old_size=16,
        new_payload=new_data,
        pointers=[ptr1, ptr2],
    )

    assert rec.overflowed is True
    assert len(rec.pointers_updated) == 2
    # Check that both pointers were updated to new_offset + gba_base
    assert struct.unpack_from("<I", buf, 0x04)[0] == gba_base + rec.new_offset
    assert struct.unpack_from("<I", buf, 0x08)[0] == gba_base + rec.new_offset


def test_relocate_pointer_table_batch():
    # Build a pointer table with 4 items
    buf = bytearray(512)
    offsets = [0x40, 0x60, 0x80, 0xA0]
    sizes = [16, 16, 16, 16]

    for i, off in enumerate(offsets):
        struct.pack_into("<I", buf, i * 4, off)
        buf[off : off + sizes[i]] = f"OldString_{i}____".encode("ascii")

    manager = AutoRelocationManager(buf)

    # Payloads: item 0 fits in-place, item 1 overflows, item 2 fits, item 3 overflows
    new_payloads = [
        b"Fit 0",                                  # fits
        b"Overflow 1 - very long new translation",  # overflows
        b"Fit 2",                                  # fits
        b"Overflow 3 - another long translation",   # overflows
    ]

    summary = manager.relocate_pointer_table(
        table_offset=0,
        entry_count=4,
        item_sizes=sizes,
        new_payloads=new_payloads,
    )

    assert summary.total_items == 4
    assert summary.in_place_count == 2
    assert summary.relocated_count == 2

    # Verify each item in buffer
    for i in range(4):
        ptr_val = struct.unpack_from("<I", buf, i * 4)[0]
        data_len = len(new_payloads[i])
        assert buf[ptr_val : ptr_val + data_len] == new_payloads[i]
