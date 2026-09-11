import os
import pytest
from miorom.platforms.psp.sfo import SFOFile, SFO_MAGIC
from miorom.platforms.psp.pbp import PBPFile, PBP_MAGIC, PBP_SECTION_NAMES
from miorom.errors import ParseError


def test_sfo_file_creation_and_accessors():
    sfo = SFOFile()
    sfo["TITLE"] = "Test Game"
    sfo["DISC_ID"] = "ULES00123"
    sfo["CATEGORY"] = "UG"
    sfo["PARENTAL_LEVEL"] = 3

    assert sfo.title == "Test Game"
    assert sfo.disc_id == "ULES00123"
    assert sfo.category == "UG"
    assert sfo["PARENTAL_LEVEL"] == 3
    assert "TITLE" in sfo
    assert "NONEXISTENT" not in sfo
    assert sfo.get("MISSING", 42) == 42


def test_sfo_file_serialization_roundtrip():
    initial = {
        "TITLE": "Final Fantasy Tactics",
        "DISC_ID": "ULUS10297",
        "CATEGORY": "UG",
        "BOOTABLE": 1,
        "APP_VER": "01.00",
    }
    sfo = SFOFile(initial)
    raw_sfo = sfo.to_bytes()

    assert len(raw_sfo) >= 20
    assert raw_sfo[:4] == SFO_MAGIC

    loaded = SFOFile.from_bytes(raw_sfo)
    assert loaded.title == "Final Fantasy Tactics"
    assert loaded.disc_id == "ULUS10297"
    assert loaded.category == "UG"
    assert loaded["BOOTABLE"] == 1
    assert loaded["APP_VER"] == "01.00"


def test_sfo_save_and_from_file(tmp_path):
    path = str(tmp_path / "PARAM.SFO")
    sfo = SFOFile({"TITLE": "Chrono Trigger", "DISC_VERSION": "1.00"})
    sfo.save(path)

    loaded = SFOFile.from_file(path)
    assert loaded["TITLE"] == "Chrono Trigger"
    assert loaded["DISC_VERSION"] == "1.00"


def test_sfo_error_handling():
    with pytest.raises(ParseError):
        SFOFile.from_bytes(b"SHORT")

    with pytest.raises(ParseError):
        SFOFile.from_bytes(b"BADM" + b"\x00" * 30)


def test_pbp_file_construction_and_sections():
    pbp = PBPFile()
    assert all(name in pbp.sections for name in PBP_SECTION_NAMES)

    icon_data = b"\x89PNG\r\n\x1a\nFakePNG"
    psp_data = b"\x7fELFfake_executable"

    pbp.set_section("ICON0.PNG", icon_data)
    pbp.set_section("DATA.PSP", psp_data)

    assert pbp.get_section("icon0.png") == icon_data
    assert pbp.get_section("DATA.PSP") == psp_data
    assert pbp.get_section("PIC1.PNG") == b""


def test_pbp_serialization_and_sfo_property():
    sfo = SFOFile({"TITLE": "Crisis Core", "DISC_ID": "ULUS10336"})
    sfo_bytes = sfo.to_bytes()
    psp_binary = b"ELF_DATA" * 64

    pbp = PBPFile({
        "PARAM.SFO": sfo_bytes,
        "DATA.PSP": psp_binary,
    })

    raw_pbp = pbp.to_bytes()
    assert len(raw_pbp) >= 40
    assert raw_pbp[:4] == PBP_MAGIC

    loaded_pbp = PBPFile.from_bytes(raw_pbp)
    assert loaded_pbp.get_section("DATA.PSP") == psp_binary
    assert loaded_pbp.get_section("PARAM.SFO") == sfo_bytes

    assert loaded_pbp.sfo is not None
    assert loaded_pbp.sfo.title == "Crisis Core"
    assert loaded_pbp.sfo.disc_id == "ULUS10336"


def test_pbp_extract_all_and_save(tmp_path):
    pbp_path = str(tmp_path / "EBOOT.PBP")
    extract_dir = str(tmp_path / "extracted")

    pbp = PBPFile({
        "PARAM.SFO": b"\x00PSFdummy",
        "ICON0.PNG": b"PNG_TEST",
    })
    pbp.save(pbp_path)

    loaded = PBPFile.from_file(pbp_path)
    loaded.extract_all(extract_dir)

    assert os.path.exists(os.path.join(extract_dir, "PARAM.SFO"))
    assert os.path.exists(os.path.join(extract_dir, "ICON0.PNG"))
    assert not os.path.exists(os.path.join(extract_dir, "DATA.PSP"))


def test_pbp_error_handling():
    with pytest.raises(ParseError):
        PBPFile.from_bytes(b"TINY")

    with pytest.raises(ParseError):
        PBPFile.from_bytes(b"BADM" + b"\x00" * 40)
