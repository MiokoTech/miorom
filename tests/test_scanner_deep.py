import os
import struct
import pytest
from miorom.scanner import (
    DeepScanner,
    calculate_entropy,
    calculate_block_entropy,
    BinaryFingerprint,
    DeepScanReport,
)


def test_entropy_calculation():
    # All zeroes -> entropy 0.0
    assert calculate_entropy(b"\x00" * 1000) == 0.0

    # Perfectly uniform distribution of 256 bytes -> entropy 8.0
    uniform = bytes(range(256)) * 10
    ent = calculate_entropy(uniform)
    assert abs(ent - 8.0) < 0.001

    # Text -> around 3.5 - 5.0
    text_data = b"The quick brown fox jumps over the lazy dog. A quick test of entropy!" * 10
    text_ent = calculate_entropy(text_data)
    assert 3.5 <= text_ent <= 5.5


def test_block_entropy_and_compressed_blocks():
    # 1024 bytes of 0x00 (entropy 0.0), then 1024 bytes of pseudo-random / all 256 bytes (entropy ~8.0)
    data = (b"\x00" * 1024) + (bytes(range(256)) * 4) + (b"\x00" * 1024)
    scanner = DeepScanner()

    blocks = calculate_block_entropy(data, block_size=1024)
    assert len(blocks) == 3
    assert blocks[0][1] == 0.0
    assert abs(blocks[1][1] - 8.0) < 0.01
    assert blocks[2][1] == 0.0

    comp_blocks = scanner.find_compressed_blocks(data, block_size=1024, entropy_threshold=7.0)
    assert len(comp_blocks) == 1
    start, length, avg_ent = comp_blocks[0]
    assert start == 1024
    assert length == 1024
    assert abs(avg_ent - 8.0) < 0.01


def test_scan_n64_and_gba():
    scanner = DeepScanner()

    # N64 Z64
    z64_data = b"\x80\x37\x12\x40" + b"\x00" * 64
    rep = scanner.scan(z64_data, scan_embedded=False)
    assert len(rep.fingerprints) == 1
    assert rep.fingerprints[0].format_name == "N64 (Z64)"
    assert rep.fingerprints[0].category == "rom"

    # N64 V64
    v64_data = b"\x37\x80\x40\x12" + b"\x00" * 64
    rep_v64 = scanner.scan(v64_data, scan_embedded=False)
    assert rep_v64.fingerprints[0].format_name == "N64 (V64)"

    # GBA ROM
    gba_data = bytearray(0x100)
    gba_logo = bytes([0x24, 0xFF, 0xAE, 0x51, 0x69, 0x9A, 0xA2, 0x21])
    gba_data[4:12] = gba_logo
    gba_data[0xA0:0xAC] = b"POKEMON EMER"
    gba_data[0xAC:0xB0] = b"BPEE"

    rep_gba = scanner.scan(bytes(gba_data), scan_embedded=False)
    assert len(rep_gba.fingerprints) == 1
    assert rep_gba.fingerprints[0].format_name == "GBA"
    assert rep_gba.fingerprints[0].metadata["title"] == "POKEMON EMER"
    assert rep_gba.fingerprints[0].metadata["game_code"] == "BPEE"


def test_scan_nds_and_gb():
    scanner = DeepScanner()

    # NDS ROM
    nds_data = bytearray(0x300)
    nds_data[0x00:0x04] = b"GAME"
    nds_data[0x0C:0x10] = b"NTRJ"
    struct.pack_into("<I", nds_data, 0x20, 0x200)  # arm9_off
    struct.pack_into("<I", nds_data, 0x30, 0x280)  # arm7_off

    rep_nds = scanner.scan(bytes(nds_data), scan_embedded=False)
    assert any(fp.format_name == "NDS" for fp in rep_nds.fingerprints)

    # GB / GBC ROM
    gb_data = bytearray(0x200)
    gb_logo = bytes([0xCE, 0xED, 0x66, 0x66, 0xCC, 0x0D, 0x00, 0x0B])
    gb_data[0x104:0x10C] = gb_logo
    gb_data[0x134:0x13C] = b"TETRIS\x00\x00"
    gb_data[0x143] = 0x80  # CGB
    gb_data[0x147] = 0x01  # MBC1

    rep_gb = scanner.scan(bytes(gb_data), scan_embedded=False)
    assert any(fp.format_name == "GBC" for fp in rep_gb.fingerprints)


def test_scan_snes_and_md():
    scanner = DeepScanner()

    # SNES HiROM
    snes_data = bytearray(0x10000)
    snes_off = 0xFFC0
    title = b"SUPER MARIO WORLD    "
    snes_data[snes_off:snes_off + len(title)] = title
    csum = 0x1234
    comp = 0xEDCB  # 0x1234 + 0xEDCB == 0xFFFF
    struct.pack_into("<HH", snes_data, snes_off + 0x1C, csum, comp)

    rep_snes = scanner.scan(bytes(snes_data), scan_embedded=False)
    assert any("SNES" in fp.format_name for fp in rep_snes.fingerprints)

    # SMD Interleaved
    smd_data = bytearray(1024)
    smd_data[8] = 0xAA
    smd_data[9] = 0xBB
    rep_smd = scanner.scan(bytes(smd_data), scan_embedded=False)
    assert any(fp.format_name == "SMD" for fp in rep_smd.fingerprints)

    # MegaDrive Raw
    md_data = bytearray(1024)
    md_data[0x100:0x110] = b"SEGA MEGA DRIVE "
    rep_md = scanner.scan(bytes(md_data), scan_embedded=False)
    assert any(fp.format_name == "MegaDrive" for fp in rep_md.fingerprints)


def test_scan_psx_and_iso():
    scanner = DeepScanner()

    # PS-X EXE
    psx_data = bytearray(2048)
    psx_data[:8] = b"PS-X EXE"
    struct.pack_into("<IIII", psx_data, 0x10, 0x80010000, 0, 0x80010000, 1024)
    rep_psx = scanner.scan(bytes(psx_data), scan_embedded=False)
    assert rep_psx.fingerprints[0].format_name == "PS-X EXE"

    # ISO9660 CD001 at 0x8000
    iso_data = bytearray(0x9000)
    iso_data[0x8000:0x8006] = b"\x01CD001"
    iso_data[0x8008:0x8028] = b"PLAYSTATION                     "
    iso_data[0x8028:0x8048] = b"FINAL_FANTASY_VII               "
    rep_iso = scanner.scan(bytes(iso_data), scan_embedded=False)
    assert any(fp.format_name == "ISO9660" for fp in rep_iso.fingerprints)


def test_scan_embedded_containers():
    scanner = DeepScanner(alignment=4)

    # Create dummy buffer with embedded assets:
    # 0x00: NARC archive
    # 0x40: Yaz0 stream
    # 0x80: TPL texture
    # 0xC0: SDAT sound
    # 0x100: WAV file
    buf = bytearray(512)

    # NARC at 0x20
    buf[0x20:0x24] = b"NARC"
    struct.pack_into("<H", buf, 0x24, 0xFFFE)
    struct.pack_into("<I", buf, 0x28, 0x100)

    # Yaz0 at 0x60
    buf[0x60:0x64] = b"Yaz0"
    struct.pack_into(">I", buf, 0x64, 4096)

    # TPL at 0x80
    buf[0x80:0x84] = b"\x00\x20\xAF\x30"

    # SDAT at 0xC0
    buf[0xC0:0xC4] = b"SDAT"
    struct.pack_into("<I", buf, 0xC8, 2048)

    # WAV at 0x100
    buf[0x100:0x104] = b"RIFF"
    struct.pack_into("<I", buf, 0x104, 100)
    buf[0x108:0x10C] = b"WAVE"

    rep = scanner.scan(bytes(buf), scan_embedded=True)
    detected_formats = {fp.format_name for fp in rep.fingerprints}

    assert "NARC" in detected_formats
    assert "Yaz0" in detected_formats
    assert "TPL" in detected_formats
    assert "SDAT" in detected_formats
    assert "WAV" in detected_formats

    summary = rep.summary()
    assert "DEEP BINARY INSPECTOR REPORT" in summary
    assert "NARC" in summary
    assert "Yaz0" in summary
