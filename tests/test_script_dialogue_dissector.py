from typing import Tuple
import struct
import pytest

from miorom.script.dialogue_dissector import (
    DialogueDissector,
    DialogueBlock,
    DialogueEntry,
    DissectionPatchReport,
)
from miorom.text.po_handler import PoHandler


def _create_synthetic_rom() -> Tuple[bytearray, int, int]:
    """
    Creates a synthetic ROM with a 4-entry pointer table (32-bit LE)
    and null-terminated strings.
    """
    rom = bytearray(0x2000)

    # Put strings at 0x200
    strings = [
        b"Halo, selamat datang!\x00",
        b"Ksatria pemberani.\x00",
        b"Apakah kamu siap?\x00",
        b"Ayo berangkat sekarang!\x00",
    ]

    str_offsets = []
    curr = 0x200
    for s in strings:
        rom[curr : curr + len(s)] = s
        str_offsets.append(curr)
        curr += len(s)

    # Pointer table at 0x50 (4 pointers @ 4 bytes = 16 bytes)
    table_offset = 0x50
    for i, off in enumerate(str_offsets):
        rom[table_offset + i * 4 : table_offset + (i + 1) * 4] = struct.pack("<I", off)

    return rom, table_offset, len(strings)


def test_extract_from_explicit_table():
    rom, table_offset, count = _create_synthetic_rom()

    block = DialogueDissector.extract_from_table(
        data=bytes(rom),
        table_offset=table_offset,
        pointer_count=count,
        pointer_size=4,
        endian="<",
        base_address=0,
        encoding="utf-8",
        block_id="main_dialogue",
    )

    assert block.block_id == "main_dialogue"
    assert block.pointer_count == 4
    assert len(block.entries) == 4

    assert block.entries[0].text == "Halo, selamat datang!"
    assert block.entries[1].text == "Ksatria pemberani."
    assert block.entries[2].text == "Apakah kamu siap?"
    assert block.entries[3].text == "Ayo berangkat sekarang!"


def test_auto_discover_dialogue_blocks():
    rom, table_offset, _ = _create_synthetic_rom()

    blocks = DialogueDissector.auto_discover(
        data=bytes(rom),
        encoding="utf-8",
        min_entries=4,
        pointer_sizes=(4,),
        endians=("<",),
        base_addresses=(0,),
    )

    assert len(blocks) >= 1
    found = [b for b in blocks if b.table_offset == table_offset]
    assert len(found) == 1
    block = found[0]
    assert block.pointer_count == 4
    assert block.entries[0].text == "Halo, selamat datang!"


def test_dump_to_po_and_json():
    rom, table_offset, count = _create_synthetic_rom()

    block = DialogueDissector.extract_from_table(
        data=bytes(rom),
        table_offset=table_offset,
        pointer_count=count,
        pointer_size=4,
        endian="<",
        base_address=0,
        encoding="utf-8",
        block_id="dialogue_01",
    )

    # PO Export
    po_text = block.to_po()
    assert "MioROM Dialogue Dissector" in po_text
    assert 'msgctxt "dialogue_01:0"' in po_text
    assert 'msgid "Halo, selamat datang!"' in po_text

    # JSON Export
    json_text = block.to_json()
    assert '"block_id": "dialogue_01"' in json_text
    assert '"text": "Halo, selamat datang!"' in json_text


def test_inject_translations_inplace():
    rom, table_offset, count = _create_synthetic_rom()

    block = DialogueDissector.extract_from_table(
        data=bytes(rom),
        table_offset=table_offset,
        pointer_count=count,
        pointer_size=4,
        endian="<",
        base_address=0,
        encoding="utf-8",
        block_id="dialogue_01",
    )

    # Shorter string (fits in-place)
    trans = {0: "Hai!"}
    report = DialogueDissector.inject_translations(
        data=rom,
        block=block,
        translations=trans,
        encoding="utf-8",
    )

    assert report.modified_entries == 1
    assert report.relocated_entries == 0

    # Re-extract
    re_block = DialogueDissector.extract_from_table(
        data=bytes(rom),
        table_offset=table_offset,
        pointer_count=count,
        pointer_size=4,
        endian="<",
        base_address=0,
        encoding="utf-8",
        block_id="dialogue_01",
    )
    assert re_block.entries[0].text == "Hai!"


def test_inject_translations_with_relocation():
    rom, table_offset, count = _create_synthetic_rom()

    block = DialogueDissector.extract_from_table(
        data=bytes(rom),
        table_offset=table_offset,
        pointer_count=count,
        pointer_size=4,
        endian="<",
        base_address=0,
        encoding="utf-8",
        block_id="dialogue_01",
    )

    # Much longer translation that exceeds original 18-byte slot
    long_translation = "Wahai ksatria pemberani dari kerajaan matahari terbit yang sangat perkasa!"
    trans = {1: long_translation}

    # Free space pool at 0x1000..0x1500
    report = DialogueDissector.inject_translations(
        data=rom,
        block=block,
        translations=trans,
        encoding="utf-8",
        free_space_ranges=[(0x1000, 0x1500)],
    )

    assert report.modified_entries == 1
    assert report.relocated_entries == 1
    assert len(report.pointer_updates) == 1

    # Check updated pointer in table
    ptr_off, old_target, new_target = report.pointer_updates[0]
    assert new_target == 0x1000
    updated_ptr_val = struct.unpack_from("<I", rom, ptr_off)[0]
    assert updated_ptr_val == 0x1000

    # Re-extract from table and verify the new long text is intact
    re_block = DialogueDissector.extract_from_table(
        data=bytes(rom),
        table_offset=table_offset,
        pointer_count=count,
        pointer_size=4,
        endian="<",
        base_address=0,
        encoding="utf-8",
        block_id="dialogue_01",
    )
    assert re_block.entries[1].text == long_translation


def test_inject_from_po_file():
    rom, table_offset, count = _create_synthetic_rom()

    block = DialogueDissector.extract_from_table(
        data=bytes(rom),
        table_offset=table_offset,
        pointer_count=count,
        pointer_size=4,
        endian="<",
        base_address=0,
        encoding="utf-8",
        block_id="block_po",
    )

    po_content = """
msgid ""
msgstr ""
"Content-Type: text/plain; charset=UTF-8\\n"

msgctxt "block_po:2"
msgid "Apakah kamu siap?"
msgstr "Siapkah engkau melangkah?"
"""
    report = DialogueDissector.inject_translations(
        data=rom,
        block=block,
        translations=po_content,
        encoding="utf-8",
        free_space_ranges=[(0x1200, 0x1800)],
    )

    assert report.modified_entries == 1
    re_block = DialogueDissector.extract_from_table(
        data=bytes(rom),
        table_offset=table_offset,
        pointer_count=count,
        pointer_size=4,
        endian="<",
        base_address=0,
        encoding="utf-8",
        block_id="block_po",
    )
    assert re_block.entries[2].text == "Siapkah engkau melangkah?"
