import struct
import pytest
from miorom.text.pipeline import StringTablePipeline, ExtractedString
from miorom.text.charmap import CharMap
from miorom.text.po_handler import PoHandler
from miorom.core.integrity import RomIntegrityManager
from miorom.platforms.gba.rom import GBARom


def test_string_pipeline_extract_strings():
    buf = bytearray(256)

    # Place strings at 0x80, 0x90, 0xA0
    buf[0x80:0x86] = b"Hello\x00"
    buf[0x90:0x96] = b"World\x00"
    buf[0xA0:0xA7] = b"MioROM\x00"

    # Pointer table at 0x20: 3 32-bit little-endian pointers
    struct.pack_into("<I", buf, 0x20, 0x80)
    struct.pack_into("<I", buf, 0x24, 0x90)
    struct.pack_into("<I", buf, 0x28, 0xA0)

    extracted = StringTablePipeline.extract_strings(
        buffer=bytes(buf),
        table_offset=0x20,
        entry_count=3,
        pointer_size=4,
        endian="<",
    )

    assert len(extracted) == 3
    assert extracted[0].index == 0
    assert extracted[0].offset == 0x80
    assert extracted[0].decoded_text == "Hello"
    assert extracted[0].length == 5

    assert extracted[1].index == 1
    assert extracted[1].offset == 0x90
    assert extracted[1].decoded_text == "World"
    assert extracted[1].length == 5

    assert extracted[2].index == 2
    assert extracted[2].offset == 0xA0
    assert extracted[2].decoded_text == "MioROM"
    assert extracted[2].length == 6


def test_string_pipeline_extract_with_charmap():
    buf = bytearray(128)
    # Custom encoding: 0x01='H', 0x02='I', 0xFF=stop
    cmap = CharMap({b"\x01": "H", b"\x02": "I"})
    buf[0x40:0x43] = b"\x01\x02\xFF"

    struct.pack_into("<I", buf, 0x10, 0x40)

    extracted = StringTablePipeline.extract_strings(
        buffer=bytes(buf),
        table_offset=0x10,
        entry_count=1,
        charmap=cmap,
        stop_byte=b"\xFF",
    )

    assert len(extracted) == 1
    assert extracted[0].decoded_text == "HI"
    assert extracted[0].length == 2


def test_string_pipeline_dump_to_po(tmp_path):
    buf = bytearray(256)
    buf[0x50:0x56] = b"Sword\x00"
    buf[0x60:0x67] = b"Shield\x00"

    struct.pack_into("<I", buf, 0x10, 0x50)
    struct.pack_into("<I", buf, 0x14, 0x60)

    po_file = tmp_path / "items.po"

    po_handler = StringTablePipeline.dump_to_po(
        buffer=bytes(buf),
        table_offset=0x10,
        entry_count=2,
        output_path=str(po_file),
    )

    assert len(po_handler.entries) == 2
    assert po_handler.entries[0].msgid == "Sword"
    assert po_handler.entries[0].msgctxt == "entry_0000"
    assert po_handler.entries[1].msgid == "Shield"
    assert po_handler.entries[1].msgctxt == "entry_0001"

    # Verify file saved on disk
    assert po_file.exists()
    loaded_po = PoHandler.from_file(str(po_file))
    assert len(loaded_po.entries) == 2
    assert loaded_po.entries[0].msgid == "Sword"


def test_string_pipeline_inject_in_place():
    buf = bytearray(256)
    buf[0x50:0x56] = b"Apple\x00"
    buf[0x60:0x66] = b"Peach\x00"

    struct.pack_into("<I", buf, 0x10, 0x50)
    struct.pack_into("<I", buf, 0x14, 0x60)

    po_handler = StringTablePipeline.dump_to_po(bytes(buf), table_offset=0x10, entry_count=2)
    po_handler.entries[0].msgstr = "Pear"  # 4 bytes <= 5 bytes
    po_handler.entries[1].msgstr = "Plum"  # 4 bytes <= 5 bytes

    summary = StringTablePipeline.inject_from_po(
        buffer=buf,
        po_source=po_handler,
        table_offset=0x10,
        auto_fix_integrity=False,
    )

    assert summary.total_items == 2
    assert summary.total_overflowed == 0

    # Verify buffer updated in place
    assert buf[0x50:0x55] == b"Pear\x00"
    assert buf[0x60:0x65] == b"Plum\x00"
    # Pointers unchanged
    assert struct.unpack_from("<I", buf, 0x10)[0] == 0x50
    assert struct.unpack_from("<I", buf, 0x14)[0] == 0x60


def test_string_pipeline_inject_overflow_and_auto_relocate():
    buf = bytearray(256)
    buf[0x40:0x46] = b"Tiny\x00"
    struct.pack_into("<I", buf, 0x10, 0x40)

    po_handler = StringTablePipeline.dump_to_po(bytes(buf), table_offset=0x10, entry_count=1)
    po_handler.entries[0].msgstr = "This translated dialogue line is significantly longer than original!"

    summary = StringTablePipeline.inject_from_po(
        buffer=buf,
        po_source=po_handler,
        table_offset=0x10,
        auto_fix_integrity=False,
    )

    assert summary.total_items == 1
    assert summary.total_overflowed == 1

    # New offset should be relocated
    new_ptr = struct.unpack_from("<I", buf, 0x10)[0]
    assert new_ptr > 0x40

    # Re-extract and verify text matches translation
    re_extracted = StringTablePipeline.extract_strings(
        buffer=bytes(buf),
        table_offset=0x10,
        entry_count=1,
    )
    assert re_extracted[0].decoded_text == "This translated dialogue line is significantly longer than original!"


def test_string_pipeline_dte_compression_and_integrity():
    # Build minimal GBA ROM header (192 bytes)
    header = bytearray(0xC0)
    header[0:4] = b"\x2E\x00\x00\xEA"
    header[0x04:0xA0] = GBARom.NINTENDO_LOGO
    header[0xA0:0xAC] = b"TEST_GBA\x00\x00\x00\x00"
    header[0xAC:0xB0] = b"BPEE"
    header[0xB0:0xB2] = b"01"
    header[0xB2] = 0x96

    # Full ROM buffer
    rom = bytearray(header + b"\x00" * 256)

    # Pointer at 0xD0 pointing to 0xE0
    struct.pack_into("<I", rom, 0xD0, 0xE0)
    rom[0xE0:0xF0] = b"Short greeting\x00"

    po_handler = StringTablePipeline.dump_to_po(bytes(rom), table_offset=0xD0, entry_count=1)
    po_handler.entries[0].msgstr = "the thing that thrives"

    # DTE tokens
    dte_dict = {
        b"\x80": "th",
        b"\x81": "ing",
    }

    summary = StringTablePipeline.inject_from_po(
        buffer=rom,
        po_source=po_handler,
        table_offset=0xD0,
        dte_dict=dte_dict,
        auto_fix_integrity=True,
        platform="GBA",
    )

    assert summary.total_items == 1

    # Integrity verification must pass
    rep = RomIntegrityManager.verify(bytes(rom), platform="GBA")
    assert rep.is_valid is True
