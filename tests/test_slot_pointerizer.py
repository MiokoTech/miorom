import struct
import pytest
from miorom.patch.pointerizer import (
    SlotToHeapPointerizer,
    PascalStringManager,
    SlotConversionReport,
)


def test_slot_to_heap_pointerizer():
    # Table of 3 records, 16 bytes stride
    # Format: [u16 id][u16 icon][char[8] name][u32 price]
    buf = bytearray(0x100)
    stride = 16
    slot_off = 4
    slot_sz = 8

    # Record 0
    struct.pack_into("<H", buf, 0, 1)
    buf[4:12] = b"Herb\x00\x00\x00\x00"
    struct.pack_into("<I", buf, 12, 50)

    # Record 1
    struct.pack_into("<H", buf, 16, 2)
    buf[20:28] = b"Ring\x00\x00\x00\x00"
    struct.pack_into("<I", buf, 28, 500)

    # Extract original fixed-width texts
    extracted = SlotToHeapPointerizer.extract_fixed_slots(
        buffer=bytes(buf),
        table_offset=0,
        record_count=2,
        record_stride=stride,
        slot_offset_in_record=slot_off,
        slot_size=slot_sz,
    )
    assert extracted[0] == (0, "Herb")
    assert extracted[1] == (1, "Ring")

    # Translate with long strings that overflow 8 bytes
    translations = {
        0: "Herbal Penyembuh Luka Parah",
        1: "Cincin Kekuatan Mistis Naga",
    }

    # Run pointerization starting heap at 0x80
    report = SlotToHeapPointerizer.pointerize_table(
        buffer=buf,
        table_offset=0,
        record_count=2,
        record_stride=stride,
        slot_offset_in_record=slot_off,
        slot_size=slot_sz,
        translations=translations,
        heap_offset=0x80,
        pointer_size=4,
        endian="<",
    )

    assert report.total_records == 2
    assert report.heap_start_offset == 0x80
    assert report.heap_total_bytes > 0

    # Read pointers from slots
    ptr0 = struct.unpack_from("<I", buf, 0 + slot_off)[0]
    ptr1 = struct.unpack_from("<I", buf, 16 + slot_off)[0]

    assert ptr0 == 0x80
    assert ptr1 > 0x80

    # Verify strings in heap at pointers
    str0 = buf[ptr0 : buf.find(b"\x00", ptr0)].decode("utf-8")
    str1 = buf[ptr1 : buf.find(b"\x00", ptr1)].decode("utf-8")

    assert str0 == "Herbal Penyembuh Luka Parah"
    assert str1 == "Cincin Kekuatan Mistis Naga"


def test_pascal_string_manager():
    buf = bytearray(64)
    # Write Pascal string with 1-byte length
    written = PascalStringManager.write_pascal_string(buf, 0x10, "Ksatria", length_size=1)
    assert written == 1 + len("Ksatria")
    assert buf[0x10] == len("Ksatria")

    # Read back
    text, consumed = PascalStringManager.read_pascal_string(bytes(buf), 0x10, length_size=1)
    assert text == "Ksatria"
    assert consumed == written
