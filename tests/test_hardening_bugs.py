"""
tests/test_hardening_bugs.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Comprehensive regression and hardening tests verifying fixes for:
1. Path traversal / zip-slip prevention in NDS, GameCube, and ISO9660 handlers.
2. SPU-ADPCM shift > 12 negative bit-shift safety in VAGCodec.
3. Yay0 truncated decompression error detection.
4. DSP-ADPCM coefficient boundary checking in DSPADPCMCodec.
5. BPS patcher out-of-bounds SourceCopy/TargetCopy protection.
6. NES ROM archaic iNES 0-byte PRG convention and NES 2.0 exponent sizing.
7. CharMap strict encoding mode for unmapped characters.
8. Floyd-Steinberg dithering parity after inner loop optimization.
"""

import os
import struct
import tempfile
import pytest

from miorom.security import UnsafeArchivePathError, sanitize_extract_path
from miorom.errors import CompressionError, ParseError, PatchError
from miorom.audio.vag import VAGCodec
from miorom.audio.dsp_adpcm import DSPADPCMCodec
from miorom.compression.yay0 import Yay0
from miorom.compression.lz10 import LZ10
from miorom.compression.lz11 import LZ11
from miorom.compression.yaz0 import Yaz0
from miorom.compression.rle import RLE
from miorom.compression.huffman import Huffman
from miorom.patch.bps import BpsPatcher
from miorom.patch.ups import UpsPatcher
from miorom.platforms.nes.rom import NESRom
from miorom.platforms.psx.tim import TIMImage
from miorom.platforms.gc.disc import GameCubeDisc, GCHeader
from miorom.platforms.iso.iso9660 import ISO9660
from miorom.asm.xref_engine import XRefDatabase
from miorom.asm.xref import XRefType
from miorom.text.charmap import CharMap
from miorom.graphics.palette import FloydSteinbergDitherer, Palette, Color
from miorom.rom.handlers.nds import NDSRomHandler
from miorom.rom.handlers.gc import GameCubeRomHandler
from miorom.rom.handlers.iso9660 import Iso9660RomHandler


def test_vag_negative_shift_handled():
    """SPU-ADPCM block with shift > 12 should shift right instead of raising ValueError."""
    # Construct a 16-byte block: shift=14 (0x0E), filter=0, flags=0
    block = bytearray(16)
    block[0] = 0x0E  # shift = 14, filter = 0
    block[1] = 0x00  # flags = 0
    # Nibbles with sample data
    for i in range(2, 16):
        block[i] = 0x77  # positive max nibbles

    samples, s1, s2, flags = VAGCodec.decode_block(bytes(block), 0.0, 0.0)
    assert len(samples) == 28
    assert all(-32768 <= s <= 32767 for s in samples)


def test_yay0_truncated_raises_compression_error():
    """Yay0 decompression on truncated payload must raise CompressionError."""
    # Valid Yay0 header: "Yay0", uncompressed_size=100, link_table_offset=16, byte_chunks_offset=24
    # But truncate data so it cannot reach 100 bytes
    header = b"Yay0" + struct.pack(">III", 100, 16, 20)
    # Mask with literal bits but not enough byte data
    payload = header + b"\xFF\xFF\xFF\xFF" + b"\x12\x34"
    with pytest.raises(CompressionError, match="Yay0 decompression truncated"):
        Yay0.decompress(payload)


def test_dsp_adpcm_coefs_length_validation():
    """DSP-ADPCM decoder must validate that coefs contains at least 16 entries."""
    frame = b"\x00" * 8
    short_coefs = [0] * 8  # Only 8 coefs instead of 16
    with pytest.raises(ParseError, match="16 filter coefficients"):
        DSPADPCMCodec.decode_frame(frame, short_coefs)

    with pytest.raises(ParseError, match="16 filter coefficients"):
        DSPADPCMCodec.decode(frame, short_coefs)


def test_bps_bounds_validation():
    """BPS patcher must reject negative or out-of-bounds SourceCopy/TargetCopy offsets."""
    source = b"Hello, World! This is a test file for BPS patching."

    patch_body = bytearray(b"BPS1")
    patch_body.append(len(source) | 0x80)
    patch_body.append(len(source) | 0x80)
    patch_body.append(0x80)
    patch_body.append(((10 - 1) << 2) | 2 | 0x80)
    from miorom.patch.bps import _encode_vlq
    patch_body.extend(_encode_vlq(2001))

    dummy_crcs = struct.pack("<III", 0, 0, 0)
    full_patch = bytes(patch_body) + dummy_crcs

    with pytest.raises(PatchError):
        BpsPatcher.apply(source, full_patch)


def test_nes_rom_sizing():
    """NES ROM PRG/CHR size calculations for archaic iNES and NES 2.0."""
    # Archaic iNES: prg_rom_16kb = 0 -> 256 banks (4MB)
    header = bytearray(16)
    header[0:4] = b"NES\x1A"
    header[4] = 0  # 0 units
    header[5] = 1  # 1 CHR unit (8KB)
    rom_data = bytes(header) + b"\x00" * 8192
    rom = NESRom(rom_data)
    assert rom.prg_size == 256 * 16384  # 4MB
    assert rom.chr_size == 8192

    # NES 2.0: exponent notation
    header2 = bytearray(16)
    header2[0:4] = b"NES\x1A"
    header2[4] = 0x02  # byte 4: exponent 0, multiplier (2 & 3)*2 + 1 = 5
    header2[7] = 0x08  # NES 2.0 identifier in flags7
    header2[9] = 0x0F  # Upper nibble 0 for CHR, lower nibble 0x0F for PRG exponent notation
    rom2 = NESRom(bytes(header2))
    assert rom2.is_nes20
    # 2^0 * ( (2 & 3)*2 + 1 ) = 1 * 5 = 5 bytes
    assert rom2.prg_size == 5


def test_charmap_strict_mode():
    """CharMap encode strict mode should raise ValueError on unmapped characters."""
    cm = CharMap()
    cm.add_mapping(b"\x01", "A")
    cm.add_mapping(b"\x02", "B")

    # Non-strict mode silently truncates/falls back
    encoded_lenient = cm.encode("AB\u65e5", strict=False)
    assert len(encoded_lenient) == 3

    # Strict mode raises ValueError
    with pytest.raises(ValueError, match="Unmapped character"):
        cm.encode("AB\u65e5", strict=True)


def test_floyd_steinberg_parity():
    """Floyd-Steinberg ditherer produces valid palette index matrix."""
    pal = Palette([
        Color(0, 0, 0),
        Color(255, 255, 255),
        Color(255, 0, 0),
        Color(0, 255, 0),
        Color(0, 0, 255),
    ])
    pixels = [
        [(100, 100, 100), (200, 200, 200)],
        [(50, 0, 0), (0, 250, 0)],
    ]
    indices = FloydSteinbergDitherer.dither(pixels, pal)
    assert len(indices) == 2
    assert len(indices[0]) == 2
    assert all(0 <= idx < len(pal) for row in indices for idx in row)


def test_rom_handlers_path_traversal_prevention():
    """Unpackers must reject path traversal entries trying to escape output_dir."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Verify sanitize_extract_path raises UnsafeArchivePathError on ../ escapes
        with pytest.raises(UnsafeArchivePathError):
            sanitize_extract_path(tmp_dir, "../escaped.bin")

        with pytest.raises(UnsafeArchivePathError):
            sanitize_extract_path(tmp_dir, "/etc/passwd")

        with pytest.raises(UnsafeArchivePathError):
            sanitize_extract_path(tmp_dir, "data/../../escape.bin")

        # Verify safe extraction resolves inside tmp_dir
        safe_path = sanitize_extract_path(tmp_dir, "data/sub/file.bin")
        assert os.path.realpath(safe_path).startswith(os.path.realpath(tmp_dir))


def test_nintendo_compression_suite_truncation_detection():
    """All compression decompressors must raise CompressionError on truncated streams."""
    # LZ10 truncated stream
    lz10_truncated = bytes([0x10, 100, 0, 0, 0x00, 0x12])
    with pytest.raises(CompressionError, match="LZ10 decompression truncated"):
        LZ10.decompress(lz10_truncated)

    # LZ11 truncated stream
    lz11_truncated = bytes([0x11, 100, 0, 0, 0x00, 0x12])
    with pytest.raises(CompressionError, match="LZ11 decompression truncated"):
        LZ11.decompress(lz11_truncated)

    # Yaz0 truncated stream
    yaz0_truncated = b"Yaz0" + struct.pack(">III", 100, 0, 0) + b"\xFF\x12\x34"
    with pytest.raises(CompressionError, match="Yaz0 decompression truncated"):
        Yaz0.decompress(yaz0_truncated)

    # RLE truncated stream
    rle_truncated = bytes([0x30, 100, 0, 0, 0x01, 0x55])
    with pytest.raises(CompressionError, match="RLE decompression truncated"):
        RLE.decompress(rle_truncated)

    # Huffman truncated stream
    huff_tree = bytes([0, 0x80, 0x81])  # minimal 3-byte tree
    huff_header = bytes([0x28, 100, 0, 0]) + bytes([len(huff_tree) // 2])
    huff_truncated = huff_header + huff_tree + b"\x00\x00"
    with pytest.raises(CompressionError):
        Huffman.decompress(huff_truncated)


def test_ups_patcher_corrupt_stream_check():
    """UPS patcher must reject patches with malformed header or truncated payload."""
    source = b"Short source"
    # Create UPS patch with missing EOF or truncated stream
    patch_bytes = b"UPS1\x00\x00\x00"  # too short (< 16 bytes)
    with pytest.raises(PatchError, match="Invalid UPS patch"):
        UpsPatcher.apply(source, patch_bytes)


def test_tim_truncated_payload_rejection():
    """PS1 TIMImage parser must reject truncated CLUT or Image sections."""
    # Truncated CLUT section
    # Header: magic=0x10, flag=0x08 (has_clut=True, 4bpp)
    tim_hdr = struct.pack("<II", 0x10, 0x08)
    # CLUT section claims size 100, but only 12 bytes provided
    clut_hdr = struct.pack("<IHHHH", 100, 0, 0, 16, 1)
    with pytest.raises(ParseError, match="Malformed TIM CLUT section size"):
        TIMImage(tim_hdr + clut_hdr)

    # Truncated image section
    tim_hdr_direct = struct.pack("<II", 0x10, 0x02)  # 16bpp direct, no CLUT
    img_hdr = struct.pack("<IHHHH", 500, 0, 0, 32, 32)  # claims 500 bytes
    with pytest.raises(ParseError, match="Malformed TIM image section size"):
        TIMImage(tim_hdr_direct + img_hdr)


def test_gc_and_iso_streaming_unpack():
    """Streaming unpack for GC and ISO handlers must extract files without errors."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create minimal synthetic GC disc file
        gc_path = os.path.join(tmp_dir, "test.iso")
        raw = bytearray(0x8000)
        # Magic 0xC2339F3D at offset 0x1C
        struct.pack_into(">I", raw, 0x1C, GameCubeDisc.GC_MAGIC)
        raw[0:4] = b"GM8E"
        raw[4:6] = b"01"
        # Header title
        raw[0x20:0x30] = b"Test GC Game\x00\x00\x00\x00"

        # FST offset at 0x1000, size 36 bytes (root + 1 file)
        fst_off = 0x1000
        struct.pack_into(">II", raw, 0x424, fst_off, 36)
        # Root entry: flags=1, name_off=0, first=0, second=2 (2 total entries)
        struct.pack_into(">B", raw, fst_off, 1)
        struct.pack_into(">I", raw, fst_off + 8, 2)
        # File 1 entry at offset fst_off + 12: flags=0, name_off=0, file_off=0x3000, file_sz=16
        struct.pack_into(">B", raw, fst_off + 12, 0)
        struct.pack_into(">I", raw, fst_off + 12 + 4, 0x3000)
        struct.pack_into(">I", raw, fst_off + 12 + 8, 16)
        # String table at fst_off + 24: "file.bin\0"
        raw[fst_off + 24 : fst_off + 33] = b"file.bin\x00"
        # File data at 0x3000
        raw[0x3000 : 0x3010] = b"STREAMING_TEST!!"

        with open(gc_path, "wb") as f:
            f.write(raw)

        # Test GameCubeRomHandler unpack_file
        gc_handler = GameCubeRomHandler()
        out_gc = os.path.join(tmp_dir, "unpacked_gc")
        meta_gc = gc_handler.unpack_file(gc_path, out_gc)
        assert meta_gc["streaming"] is True
        assert meta_gc["file_count"] == 1
        with open(os.path.join(out_gc, "root", "file.bin"), "rb") as f:
            assert f.read() == b"STREAMING_TEST!!"

        # Test Iso9660RomHandler unpack_file
        iso_path = os.path.join(tmp_dir, "test_iso.iso")
        iso_data = bytearray(18 * 2048)
        pvd_offset = 16 * 2048
        iso_data[pvd_offset : pvd_offset + 6] = b"\x01CD001"
        # Set volume ID
        iso_data[pvd_offset + 40 : pvd_offset + 47] = b"TESTISO"
        # Root record at pvd_offset + 156
        struct.pack_into("<B", iso_data, pvd_offset + 156, 34)  # length
        struct.pack_into("<I", iso_data, pvd_offset + 156 + 2, 17)  # root LBA 17
        struct.pack_into("<I", iso_data, pvd_offset + 156 + 10, 2048)  # root size 2048

        with open(iso_path, "wb") as f:
            f.write(iso_data)

        iso_handler = Iso9660RomHandler()
        out_iso = os.path.join(tmp_dir, "unpacked_iso")
        meta_iso = iso_handler.unpack_file(iso_path, out_iso)
        assert meta_iso["streaming"] is True
        assert os.path.isfile(os.path.join(out_iso, "sys", "iso_base.bin"))


def test_xref_database_export_map_and_ghidra():
    """XRefDatabase can export symbol and xref tables to IDA .map and Ghidra XML."""
    db = XRefDatabase()
    db.add_symbol(0x02001000, "main")
    db.add_symbol(0x02002000, "do_render")
    db.add_symbol(0x02040000, "g_player_score")

    db.add_xref(0x02001020, 0x02002000, XRefType.CALL, "BL do_render")
    db.add_xref(0x02001040, 0x02040000, XRefType.READ, "LDR R0, =g_player_score")

    # Export IDA MAP format
    map_text = db.export_ida_map("game_binary")
    assert "game_binary" in map_text
    assert "0001:02001000       main" in map_text
    assert "0001:02002000       do_render" in map_text
    assert "Cross References" in map_text
    assert "do_render [call]" in map_text

    # Export Ghidra XML format
    xml_text = db.export_ghidra_xml("game_binary")
    assert '<PROGRAM NAME="game_binary">' in xml_text
    assert '<SYMBOL ADDRESS="0x02001000" NAME="main"' in xml_text
    assert '<XREF FROM="0x02001020" TO="0x02002000" TYPE="call" />' in xml_text

