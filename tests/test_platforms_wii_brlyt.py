import pytest

from miorom.errors import ParseError
from miorom.platforms.wii.brlyt import (
    BRLYTFile,
    BRLYTHeaderStruct,
    BRLYTLyt1Struct,
    BRLYTPaneStruct,
    BRLYTPic1Struct,
    BRLYTSectionHeaderStruct,
    BRLYTTxt1Struct,
    Pane,
    PicturePane,
    TextBoxPane,
    build_resource_list,
    find_pane,
    parse_brlyt_sections,
    parse_resource_list,
    rebuild_brlyt,
    update_pane,
)


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


def test_find_pane_nul_padded_matching():
    pan1_sec = BRLYTSectionHeaderStruct(magic=b"pan1", size=76).to_bytes() + BRLYTPaneStruct(name="HUD_HP\x00\x00", width=100.0, height=50.0).to_bytes()
    sections = [("pan1", pan1_sec)]
    # Search without trailing NUL
    found = find_pane(sections, "HUD_HP")
    assert found is not None
    assert found[2].name.rstrip("\x00") == "HUD_HP"
    # Search with trailing NUL
    found2 = find_pane(sections, "HUD_HP\x00\x00\x00")
    assert found2 is not None


def test_brlyt_txt1_struct_properties():
    txt = BRLYTTxt1Struct(
        flag=1,
        name="LabelMsg",
        width=200.0,
        height=30.0,
        str_buf_len=64,
        str_len=14,
        font_idx=2,
        font_size_x=28.0,
        font_size_y=28.0,
    )
    raw = txt.to_bytes()
    assert len(raw) == 108
    unpacked = BRLYTTxt1Struct.from_bytes(raw)
    assert unpacked.name == "LabelMsg"
    assert unpacked.str_buf_len == 64
    assert unpacked.str_len == 14
    assert unpacked.font_idx == 2
    assert unpacked.font_size_x == 28.0
    assert unpacked.font_size_y == 28.0


def test_brlyt_resource_list_roundtrip():
    names = ["font_title.brfnt", "font_body.brfnt", "font_symbol.brfnt"]
    raw_fnl1 = build_resource_list(b"fnl1", names)
    assert raw_fnl1.startswith(b"fnl1")
    parsed_names = parse_resource_list(raw_fnl1)
    assert parsed_names == names


def test_brlyt_high_level_tree_parse_and_roundtrip():
    layout = BRLYTFile(
        textures=["banner.tpl", "icon.tpl"],
        fonts=["kart_font_kana.brfnt", "kart_font_latin.brfnt"],
    )
    root = Pane(name="RootPane", width=640.0, height=480.0)
    layout.root_pane = root

    pic = PicturePane(name="BannerPic", width=300.0, height=100.0, material_idx=0)
    txt = TextBoxPane(
        name="TitleText",
        width=250.0,
        height=40.0,
        text="Grand Prix",
        font_idx=0,
        str_buf_len=32,
    )
    sub_pane = Pane(name="SubUnderline", width=250.0, height=4.0)

    root.add_child(pic)
    root.add_child(txt)
    txt.add_child(sub_pane)

    raw_bytes = layout.to_bytes()
    reparsed = BRLYTFile.from_bytes(raw_bytes)

    assert reparsed.textures == ["banner.tpl", "icon.tpl"]
    assert reparsed.fonts == ["kart_font_kana.brfnt", "kart_font_latin.brfnt"]
    assert reparsed.root_pane is not None
    assert reparsed.root_pane.name == "RootPane"
    assert len(reparsed.root_pane.children) == 2

    reparsed_pic = reparsed.find_pane("BannerPic")
    assert isinstance(reparsed_pic, PicturePane)
    assert reparsed_pic.width == 300.0

    reparsed_txt = reparsed.find_pane("TitleText")
    assert isinstance(reparsed_txt, TextBoxPane)
    assert reparsed_txt.text == "Grand Prix"
    assert reparsed_txt.font_name == "kart_font_kana.brfnt"
    assert len(reparsed_txt.children) == 1
    assert reparsed_txt.children[0].name == "SubUnderline"


def test_brlyt_textbox_query_and_mutation():
    layout = BRLYTFile(fonts=["main_font.brfnt"])
    root = Pane(name="Root")
    layout.root_pane = root

    txt_pane = TextBoxPane(
        name="Dialog1",
        text="Ayo Mulai",
        str_buf_len=20,  # 20 bytes capacity
    )
    root.add_child(txt_pane)

    assert layout.get_text("Dialog1") == "Ayo Mulai"
    assert len(layout.find_text_boxes()) == 1

    # Short mutation
    layout.set_text("Dialog1", "Siap?")
    assert layout.get_text("Dialog1") == "Siap?"
    assert txt_pane.str_len == len("Siap?".encode("utf-16-be"))

    # Long mutation with expand_buffer=False should raise ValueError
    long_msg = "Ini adalah teks dialog yang sangat panjang melebihi kapasitas memori"
    with pytest.raises(ValueError, match="exceeds allocated buffer capacity"):
        layout.set_text("Dialog1", long_msg, expand_buffer=False)

    # Long mutation with expand_buffer=True should succeed
    layout.set_text("Dialog1", long_msg, expand_buffer=True)
    assert layout.get_text("Dialog1") == long_msg
    assert txt_pane.str_buf_len >= len(long_msg.encode("utf-16-be")) + 2

    # Roundtrip to verify binary integrity after expansion
    raw_data = layout.to_bytes()
    reparsed = BRLYTFile.from_bytes(raw_data)
    assert reparsed.get_text("Dialog1") == long_msg


def test_brlyt_export_and_import_strings():
    layout = BRLYTFile(fonts=["font.brfnt"])
    root = Pane(name="Menu")
    layout.root_pane = root

    root.add_child(TextBoxPane(name="BtnStart", text="Start Game"))
    root.add_child(TextBoxPane(name="BtnOptions", text="Options"))
    root.add_child(TextBoxPane(name="BtnQuit", text="Quit"))

    exported = layout.export_strings()
    assert exported == {
        "BtnStart": "Start Game",
        "BtnOptions": "Options",
        "BtnQuit": "Quit",
    }

    # Translate / modify
    localized = {
        "BtnStart": "Mulai Permainan",
        "BtnOptions": "Pengaturan",
        "BtnQuit": "Keluar",
    }
    updated_count = layout.import_strings(localized)
    assert updated_count == 3
    assert layout.get_text("BtnStart") == "Mulai Permainan"
    assert layout.get_text("BtnOptions") == "Pengaturan"
    assert layout.get_text("BtnQuit") == "Keluar"


def test_brlyt_font_remapping():
    layout = BRLYTFile(fonts=["kart_font_jp.brfnt"])
    root = Pane(name="HUD")
    layout.root_pane = root

    tb1 = TextBoxPane(name="Txt1", text="Kiri", font_idx=0, font_name="kart_font_jp.brfnt")
    tb2 = TextBoxPane(name="Txt2", text="Kanan", font_idx=0, font_name="kart_font_jp.brfnt")
    root.add_child(tb1)
    root.add_child(tb2)

    count = layout.remap_font("kart_font_jp.brfnt", "custom_latin.brfnt")
    assert count == 2
    assert "custom_latin.brfnt" in layout.fonts
    assert tb1.font_name == "custom_latin.brfnt"
    assert tb2.font_name == "custom_latin.brfnt"
    assert tb1.font_idx == tb2.font_idx

    # Roundtrip binary verification
    reparsed = BRLYTFile.from_bytes(layout.to_bytes())
    assert reparsed.find_pane("Txt1").font_name == "custom_latin.brfnt"
    assert reparsed.find_pane("Txt2").font_name == "custom_latin.brfnt"


def test_brlyt_hierarchy_error_handling(tmp_path):
    layout = BRLYTFile()
    root = Pane(name="Root")
    layout.root_pane = root
    root.add_child(PicturePane(name="Pic"))

    with pytest.raises(KeyError, match="not found"):
        layout.get_text("NonExistent")

    with pytest.raises(ValueError, match="is not a TextBoxPane"):
        layout.get_text("Pic")

    # Unmatched pae1 parsing error
    sec_pan = BRLYTSectionHeaderStruct(magic=b"pan1", size=76).to_bytes() + BRLYTPaneStruct().to_bytes()
    sec_pae = BRLYTSectionHeaderStruct(magic=b"pae1", size=8).to_bytes()
    bad_bytes = rebuild_brlyt(
        BRLYTHeaderStruct(file_size=16 + 76 + 8, section_count=2),
        [("pan1", sec_pan), ("pae1", sec_pae)],
    )
    with pytest.raises(ParseError, match="unmatched pae1"):
        BRLYTFile.from_bytes(bad_bytes)

    # File IO test
    out_file = tmp_path / "hud.brlyt"
    layout.save(out_file)
    assert out_file.exists()
    loaded = BRLYTFile.from_file(out_file)
    assert loaded.find_pane("Pic") is not None

