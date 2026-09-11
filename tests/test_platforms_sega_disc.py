import os
import pytest
from miorom.platforms.sega_disc import (
    SaturnDiscHeader,
    DreamcastIpBin,
    GDISheet,
    GDITrack,
    SATURN_MAGIC,
    DREAMCAST_MAGIC,
)
from miorom.errors import ParseError


def test_saturn_disc_header_roundtrip():
    hdr = SaturnDiscHeader(
        hardware_id="SEGA SEGASATURN ",
        maker_id="SEGA ENTERPRISES",
        device_info="CD-1/1",
        area_symbols="J",
        peripherals="JTKB",
        title="SHINING FORCE III",
        product_number="GS-9176",
        version="V1.002",
        release_date="19971211",
        boot_file="0.BIN",
    )

    assert hdr.is_region_free is False
    raw_bytes = hdr.to_bytes()
    assert len(raw_bytes) == 512
    assert raw_bytes[:16] == SATURN_MAGIC

    parsed = SaturnDiscHeader.from_bytes(raw_bytes)
    assert parsed.title == "SHINING FORCE III"
    assert parsed.maker_id == "SEGA ENTERPRISES"
    assert parsed.product_number == "GS-9176"
    assert parsed.boot_file == "0.BIN"
    assert parsed.version == "V1.002"

    parsed.make_region_free()
    assert parsed.is_region_free is True
    reencoded = parsed.to_bytes()
    reparsed = SaturnDiscHeader.from_bytes(reencoded)
    assert reparsed.is_region_free is True


def test_saturn_header_error_handling():
    with pytest.raises(ParseError):
        SaturnDiscHeader.from_bytes(b"SHORT")

    with pytest.raises(ParseError):
        SaturnDiscHeader.from_bytes(b"NOT_A_SATURN_HDR" + b"\x00" * 300)


def test_dreamcast_ip_bin_roundtrip():
    ip = DreamcastIpBin(
        hardware_id="SEGA SEGAKATANA ",
        maker_id="SEGA ENTERPRISES",
        device_info="GD-ROM1/1",
        area_symbols="J",
        title="SHENMUE",
        product_number="HDR-0012",
        version="V1.000",
        boot_file="1ST_READ.BIN",
    )

    assert ip.is_region_free is False
    crc = ip.calculate_crc()
    ip.crc = crc

    raw_bytes = ip.to_bytes()
    assert len(raw_bytes) == 0x8000
    assert raw_bytes[:16] == DREAMCAST_MAGIC

    parsed = DreamcastIpBin.from_bytes(raw_bytes)
    assert parsed.title == "SHENMUE"
    assert parsed.boot_file == "1ST_READ.BIN"
    assert parsed.crc == crc

    parsed.make_region_free()
    assert parsed.is_region_free is True
    assert "U" in parsed.area_symbols and "E" in parsed.area_symbols


def test_dreamcast_ip_bin_error_handling():
    with pytest.raises(ParseError):
        DreamcastIpBin.from_bytes(b"SHORT")

    with pytest.raises(ParseError):
        DreamcastIpBin.from_bytes(b"NOT_A_DREAMCAST!" + b"\x00" * 300)


def test_gdi_sheet_parsing_and_formatting(tmp_path):
    gdi_text = """3
1 0 4 2352 track01.bin 0
2 600 0 2352 track02.raw 0
3 45000 4 2048 track03.bin 0
"""
    sheet = GDISheet.from_text(gdi_text)
    assert len(sheet.tracks) == 3

    assert sheet.tracks[0].track_number == 1
    assert sheet.tracks[0].start_lba == 0
    assert sheet.tracks[0].filename == "track01.bin"

    hd_track = sheet.high_density_track
    assert hd_track is not None
    assert hd_track.track_number == 3
    assert hd_track.start_lba == 45000
    assert hd_track.sector_size == 2048

    formatted = sheet.to_text()
    assert formatted.strip() == gdi_text.strip()

    file_path = str(tmp_path / "disc.gdi")
    sheet.save(file_path)

    loaded = GDISheet.from_file(file_path)
    assert len(loaded.tracks) == 3
    assert loaded.high_density_track.filename == "track03.bin"


def test_gdi_sheet_error_handling():
    with pytest.raises(ParseError):
        GDISheet.from_text("")

    with pytest.raises(ParseError):
        GDISheet.from_text("NOT_A_NUMBER")
