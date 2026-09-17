"""
Unit tests for Nintendo BMG and MSBT dialogue format containers.
"""

import pytest
from miorom.text.bmg import BMGFile, BMGMessage
from miorom.text.msbt import MSBTFile, MSBTEntry
from miorom.errors import ParseError


def test_bmg_roundtrip():
    m1 = BMGMessage(text="Hello, hero of Hyrule!", message_id=1001)
    m2 = BMGMessage(text="Be careful in the dungeon.", message_id=1002)

    bmg = BMGFile(messages=[m1, m2], encoding=2)
    raw = bmg.to_bytes()
    assert raw[:8] == b"MESGbmg1"

    reloaded = BMGFile.from_bytes(raw)
    assert len(reloaded.messages) == 2
    assert reloaded.messages[0].text == "Hello, hero of Hyrule!"
    assert reloaded.messages[0].message_id == 1001
    assert reloaded.messages[1].text == "Be careful in the dungeon."
    assert reloaded.messages[1].message_id == 1002


def test_bmg_invalid():
    with pytest.raises(ParseError):
        BMGFile.from_bytes(b"BAD_HEADER_DATA_12345678901234567890")


def test_bmg_escape_sequences():
    # 1. UTF-16BE with escape sequence containing 0x0000 arg:
    # 0x001A (escape), len 0x06, cmd 0x01, arg 0x00 0x00
    # Must NOT be prematurely truncated at 0x0000!
    esc_utf16 = b"\x00\x1a\x06\x01\x00\x00"
    raw_dat = (
        b"\x00\x00"
        + "Hello, ".encode("utf-16-be")
        + esc_utf16
        + "Hero of Time!".encode("utf-16-be")
        + b"\x00\x00"
    )
    # Wrap in valid minimal BMG
    from miorom.core.binary import BinaryWriter
    from miorom.text.bmg import BMGHeaderStruct, BMGSectionHeaderStruct, BMGINF1HeaderStruct

    inf_w = BinaryWriter(endian=">")
    inf_w.write_bytes(BMGINF1HeaderStruct(entry_count=1, entry_size=8, file_id=0, default_color=0).to_bytes())
    inf_w.write_u32(2)  # offset 2
    inf_w.write_u32(0)
    inf_bytes = inf_w.to_bytes()
    inf_sec = BinaryWriter(endian=">")
    inf_sec.write_bytes(BMGSectionHeaderStruct(magic=b"INF1", size=8 + len(inf_bytes)).to_bytes())
    inf_sec.write_bytes(inf_bytes)
    inf_sec.align(32)

    dat_sec = BinaryWriter(endian=">")
    dat_sec.write_bytes(BMGSectionHeaderStruct(magic=b"DAT1", size=8 + len(raw_dat)).to_bytes())
    dat_sec.write_bytes(raw_dat)
    dat_sec.align(32)

    inf_chunk = inf_sec.to_bytes()
    dat_chunk = dat_sec.to_bytes()
    total_sz = 32 + len(inf_chunk) + len(dat_chunk)

    hdr = BMGHeaderStruct(magic=b"MESGbmg1", file_size=total_sz, section_count=2, encoding=2)
    bmg_data = hdr.to_bytes() + inf_chunk + dat_chunk

    loaded = BMGFile.from_bytes(bmg_data)
    assert len(loaded.messages) == 1
    assert "Hero of Time!" in loaded.messages[0].text
    assert "Hello, " in loaded.messages[0].text

    # 2. 8-bit CP1252 with escape sequence containing 0x00:
    # 0x1A, len 0x06, cmd 0x01, args \x00\x00\x02
    esc_8 = b"\x1a\x06\x01\x00\x00\x02"
    raw_dat_8 = b"\x00" + b"Score: " + esc_8 + b" 100 points!" + b"\x00"

    inf_w8 = BinaryWriter(endian=">")
    inf_w8.write_bytes(BMGINF1HeaderStruct(entry_count=1, entry_size=8, file_id=0, default_color=0).to_bytes())
    inf_w8.write_u32(1)
    inf_w8.write_u32(0)
    inf_b8 = inf_w8.to_bytes()
    inf_sec8 = BinaryWriter(endian=">")
    inf_sec8.write_bytes(BMGSectionHeaderStruct(magic=b"INF1", size=8 + len(inf_b8)).to_bytes())
    inf_sec8.write_bytes(inf_b8)
    inf_sec8.align(32)

    dat_sec8 = BinaryWriter(endian=">")
    dat_sec8.write_bytes(BMGSectionHeaderStruct(magic=b"DAT1", size=8 + len(raw_dat_8)).to_bytes())
    dat_sec8.write_bytes(raw_dat_8)
    dat_sec8.align(32)

    inf_chunk8 = inf_sec8.to_bytes()
    dat_chunk8 = dat_sec8.to_bytes()
    total_sz8 = 32 + len(inf_chunk8) + len(dat_chunk8)

    hdr8 = BMGHeaderStruct(magic=b"MESGbmg1", file_size=total_sz8, section_count=2, encoding=1)
    bmg_data8 = hdr8.to_bytes() + inf_chunk8 + dat_chunk8

    loaded8 = BMGFile.from_bytes(bmg_data8)
    assert len(loaded8.messages) == 1
    assert "100 points!" in loaded8.messages[0].text
    assert "Score: " in loaded8.messages[0].text


def test_bmg_attributes_and_metadata_roundtrip():
    # Test custom file_id, default_color, inf_entry_size (e.g. 12 bytes = 8 bytes attributes)
    attrs1 = b"\x01\x02\x03\x04\xAA\xBB\xCC\xDD"
    attrs2 = b"\x10\x20\x30\x40\x50\x60\x70\x80"
    m1 = BMGMessage(text="First line", message_id=501, attributes=attrs1)
    m2 = BMGMessage(text="Second line", message_id=502, attributes=attrs2)

    bmg = BMGFile(
        messages=[m1, m2],
        encoding=2,
        file_id=0x5A5A,
        default_color=7,
        inf_entry_size=12,
    )
    raw = bmg.to_bytes()

    reloaded = BMGFile.from_bytes(raw)
    assert reloaded.file_id == 0x5A5A
    assert reloaded.default_color == 7
    assert reloaded.inf_entry_size == 12
    assert len(reloaded.messages) == 2
    assert reloaded.messages[0].text == "First line"
    assert reloaded.messages[0].attributes == attrs1
    assert reloaded.messages[0].message_id == 501
    assert reloaded.messages[1].text == "Second line"
    assert reloaded.messages[1].attributes == attrs2
    assert reloaded.messages[1].message_id == 502

    # Also test entry_size=4 (no attributes)
    m_no_attr = [BMGMessage(text="No attrs")]
    bmg4 = BMGFile(messages=m_no_attr, encoding=2, inf_entry_size=4)
    raw4 = bmg4.to_bytes()
    reloaded4 = BMGFile.from_bytes(raw4)
    assert reloaded4.inf_entry_size == 4
    assert reloaded4.messages[0].attributes == b""


def test_msbt_roundtrip():
    e1 = MSBTEntry(label="TUTORIAL_01", text="Press A to jump.")
    e2 = MSBTEntry(label="TUTORIAL_02", text="Collect coins for extra lives!")

    msbt = MSBTFile(entries=[e1, e2], encoding="utf-16", endian="<")
    raw = msbt.to_bytes()
    assert raw[:8] == b"MsgStdBn"

    reloaded = MSBTFile.from_bytes(raw)
    assert len(reloaded.entries) == 2
    assert reloaded.get_text("TUTORIAL_01") == "Press A to jump."
    assert reloaded.get_text("TUTORIAL_02") == "Collect coins for extra lives!"


def test_msbt_invalid():
    with pytest.raises(ParseError):
        MSBTFile.from_bytes(b"INVALID_MSBT_STRING_123456789012")


def test_msbt_utf8_control_tags_with_nulls():
    # Tag: \x0e + group(2B=0x0000) + type(2B=0x0001) + arg_len(2B=0x0002) + args(\x00\x05)
    # Total tag has multiple 0x00 bytes that must not prematurely terminate the string!
    tag = "\x0e\x00\x00\x01\x00\x02\x00\x00\x05"
    full_text = f"Welcome, {tag}Hero of Hyrule!"
    e1 = MSBTEntry(label="MSG_01", text=full_text)

    msbt = MSBTFile(entries=[e1], encoding="utf-8", endian="<")
    raw = msbt.to_bytes()

    reloaded = MSBTFile.from_bytes(raw)
    assert len(reloaded.entries) == 1
    assert reloaded.entries[0].label == "MSG_01"
    assert "Hero of Hyrule!" in reloaded.entries[0].text
    assert reloaded.entries[0].text == full_text


def test_msbt_atr1_attributes_roundtrip():
    attr1 = b"\x01\x00\xAA\xBB"
    attr2 = b"\x02\x00\xCC\xDD"
    e1 = MSBTEntry(label="ITEM_01", text="Master Sword", attributes=attr1)
    e2 = MSBTEntry(label="ITEM_02", text="Hylian Shield", attributes=attr2)

    msbt = MSBTFile(entries=[e1, e2], encoding="utf-16", endian=">", attribute_size=4)
    raw = msbt.to_bytes()
    assert b"ATR1" in raw

    reloaded = MSBTFile.from_bytes(raw)
    assert len(reloaded.entries) == 2
    assert reloaded.attribute_size == 4
    assert reloaded.entries[0].attributes == attr1
    assert reloaded.entries[1].attributes == attr2
    assert reloaded.get_text("ITEM_01") == "Master Sword"
    assert reloaded.get_text("ITEM_02") == "Hylian Shield"


def test_msbt_unlabelled_strings_and_other_sections():
    # Build MSBT with extra sections (TSY1) and test unlabelled strings
    e1 = MSBTEntry(label="LABEL_A", text="First string")
    e2 = MSBTEntry(label="STR_1", text="Second unlabelled string")

    msbt = MSBTFile(
        entries=[e1, e2],
        encoding="utf-16",
        endian="<",
        other_sections=[(b"TSY1", b"STYLE_DATA_12345678")],
    )
    raw = msbt.to_bytes()
    assert b"TSY1" in raw

    reloaded = MSBTFile.from_bytes(raw)
    assert len(reloaded.entries) == 2
    assert reloaded.entries[0].text == "First string"
    assert reloaded.entries[1].text == "Second unlabelled string"
    assert len(reloaded.other_sections) == 1
    assert reloaded.other_sections[0][0] == b"TSY1"
    assert reloaded.other_sections[0][1] == b"STYLE_DATA_12345678"

