import pytest
from miorom.platforms.wii.brlyt import (
    BRLYTHeaderStruct,
    BRLYTSectionHeaderStruct,
    BRLYTLyt1Struct,
    BRLYTPaneStruct,
    BRLYTPic1Struct,
    parse_brlyt_sections,
    rebuild_brlyt,
    find_pane,
    update_pane,
)
from miorom.errors import ParseError


def test_brlyt_header_pack_unpack():
    hdr = BRLYTHeaderStruct(
        magic=b"RLYT",
        bom=0xFEFF,
        version=0x000A,
        file_size=1024,
        header_size=16,
        section_count=4,
    )
    raw = hdr.to_bytes()
    assert len(raw) == 16
    unpacked = BRLYTHeaderStruct.from_bytes(raw)
    assert unpacked.magic == b"RLYT"
    assert unpacked.bom == 0xFEFF
    assert unpacked.version == 0x000A
    assert unpacked.file_size == 1024
    assert unpacked.section_count == 4


def test_brlyt_pane_struct_properties():
    pane = BRLYTPaneStruct(
        flag=1,
        origin=4,
        alpha=255,
        name="TestPane",
        width=120.0,
        height=40.0,
    )
    assert pane.name == "TestPane"
    assert pane.width == 120.0
    assert pane.height == 40.0

    raw = pane.to_bytes()
    assert len(raw) == 68
    unpacked = BRLYTPaneStruct.from_bytes(raw)
    assert unpacked.name == "TestPane"
    assert unpacked.width == 120.0
    assert unpacked.height == 40.0


def test_brlyt_synthetic_roundtrip():
    # Construct a minimal valid BRLYT binary
    lyt1_sec = BRLYTSectionHeaderStruct(magic=b"lyt1", size=20).to_bytes() + BRLYTLyt1Struct(width=640.0, height=480.0).to_bytes()
    pan1_sec = BRLYTSectionHeaderStruct(magic=b"pan1", size=76).to_bytes() + BRLYTPaneStruct(name="RootPane", width=640.0, height=480.0).to_bytes()
    pic1_sec = BRLYTSectionHeaderStruct(magic=b"pic1", size=128).to_bytes() + BRLYTPic1Struct(name="IconPic", width=64.0, height=64.0).to_bytes()

    sections = [
        ("lyt1", lyt1_sec),
        ("pan1", pan1_sec),
        ("pic1", pic1_sec),
    ]
    hdr = BRLYTHeaderStruct(
        magic=b"RLYT",
        bom=0xFEFF,
        version=0x000A,
        file_size=16 + len(lyt1_sec) + len(pan1_sec) + len(pic1_sec),
        header_size=16,
        section_count=3,
    )
    raw_brlyt = rebuild_brlyt(hdr, sections)
    assert len(raw_brlyt) == 16 + 20 + 76 + 128

    parsed_hdr, parsed_sections = parse_brlyt_sections(raw_brlyt)
    assert parsed_hdr.section_count == 3
    assert len(parsed_sections) == 3

    # Find pane
    found = find_pane(parsed_sections, "IconPic")
    assert found is not None
    idx, magic, pic = found
    assert idx == 2
    assert magic == "pic1"
    assert pic.name == "IconPic"
    assert pic.width == 64.0

    # Update pane
    pic.width = 128.0
    pic.height = 32.0
    updated_sections = update_pane(parsed_sections, idx, pic)
    rebuilt_brlyt = rebuild_brlyt(parsed_hdr, updated_sections)

    _, reparsed_sections = parse_brlyt_sections(rebuilt_brlyt)
    _, _, updated_pic = find_pane(reparsed_sections, "IconPic")
    assert updated_pic.width == 128.0
    assert updated_pic.height == 32.0


def test_brlyt_invalid_magic():
    with pytest.raises(ParseError):
        parse_brlyt_sections(b"INVALID_HEADER_BYTES_123456789")
