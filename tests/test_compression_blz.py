import pytest

from miorom.compression.blz import BLZ, BLZTrailerStruct
from miorom.core.checksum import RetroChecksum
from miorom.errors import CompressionError
from miorom.platforms.nds.overlay import NDSOverlayCompressor
from miorom.platforms.nds.rom import NDSHeaderStruct, NDSRom


def test_blz_roundtrip_simple():
    # Simple repetitive pattern that compresses well
    raw = b"Nintendo DS ARM9 binary code. Hello world! Repetition 123456789 123456789 123456789. " * 30
    assert not BLZ.is_compressed(raw)

    compressed = BLZ.compress(raw)
    assert BLZ.is_compressed(compressed)
    assert len(compressed) < len(raw)

    decompressed = BLZ.decompress(compressed)
    assert decompressed == raw


def test_blz_roundtrip_large():
    # Larger 64KB synthetic buffer with mixed text and binary opcodes
    chunk = (
        b"\x00\x00\xA0\xE3\x01\x10\xA0\xE3\x02\x20\xA0\xE3"  # ARM opcodes
        + b"DIALOGUE_STRING_POKEMON_PLATINUM_VERSION_MIO_ROM"
        + b"\xFF\xFE\xFD\xFC" * 16
    )
    raw = chunk * 50
    compressed = BLZ.compress(raw, mode="normal")
    assert BLZ.is_compressed(compressed)
    assert len(compressed) < len(raw)

    decompressed = BLZ.decompress(compressed)
    assert decompressed == raw


def test_blz_best_mode():
    raw = (b"Best mode test pattern ABCDEFGHIJKLMNOPQRSTUVWXYZ" * 20) + (b"\x12\x34\x56\x78" * 50)
    compressed = BLZ.compress(raw, mode="best")
    assert BLZ.is_compressed(compressed)

    decompressed = BLZ.decompress(compressed)
    assert decompressed == raw


def test_blz_arm9_secure_area():
    # 20KB ARM9 mock binary
    arm9_mock = bytearray(0x5000)
    # Valid Nintendo DS Decrypted Secure Area Signature
    arm9_mock[0:4] = b"\xff\xde\xff\xe7"
    arm9_mock[4:8] = b"\xff\xde\xff\xe7"
    arm9_mock[8:12] = b"\xff\xde\xff\xe7"
    arm9_mock[12:14] = b"\xff\xde"
    # Fill 2KB secure area (0x10..0x7FE)
    arm9_mock[0x10:0x7FE] = b"\xAA\xBB\xCC\xDD" * 507 + b"\xAA\xBB"
    arm9_mock[0x7FE:0x800] = b"\x00\x00"
    # Payload after 0x4000
    payload = b"Code section compressed portion repeats repeats repeats " * 20
    arm9_mock[0x4000 : 0x4000 + len(payload)] = payload

    compressed = BLZ.compress(bytes(arm9_mock), is_arm9=True)
    assert BLZ.is_compressed(compressed)
    assert len(compressed) < len(arm9_mock)

    decompressed = BLZ.decompress(compressed)
    assert len(decompressed) == len(arm9_mock)

    # Verify Secure Area 2KB CRC16 was calculated and written to 0x0E
    expected_crc = RetroChecksum.crc16_modbus(arm9_mock[0x10:0x800])
    assert decompressed[0x0E] == (expected_crc & 0xFF)
    assert decompressed[0x0F] == ((expected_crc >> 8) & 0xFF)

    # Verify 16KB uncompressed prefix is identical (except CRC at 0x0E..0x10)
    assert decompressed[:0x0E] == arm9_mock[:0x0E]
    assert decompressed[0x10:0x4000] == arm9_mock[0x10:0x4000]
    # Verify decompressed payload matches original payload
    assert decompressed[0x4000 : 0x4000 + len(payload)] == payload


def test_blz_uncompressible_fallback():
    # Data that doesn't compress (random-like distinct bytes)
    raw = bytes([i % 251 for i in range(300)])
    compressed = BLZ.compress(raw)
    # In CUE BLZ, uncompressible data falls back to raw data with 4 zero trailer bytes
    decompressed = BLZ.decompress(compressed)
    assert decompressed == raw


def test_blz_empty_buffer():
    compressed = BLZ.compress(b"")
    assert compressed == b"\x00\x00\x00\x00"
    decompressed = BLZ.decompress(compressed)
    assert decompressed == b""


def test_blz_is_compressed_detection():
    assert not BLZ.is_compressed(b"")
    assert not BLZ.is_compressed(b"short")
    assert not BLZ.is_compressed(b"12345678")

    # Valid compression
    raw = b"Repetitive text string for detection testing " * 20
    comp = BLZ.compress(raw)
    assert BLZ.is_compressed(comp)

    # Corrupt trailer inc_len to 0
    corrupt = bytearray(comp)
    corrupt[-4:] = b"\x00\x00\x00\x00"
    assert not BLZ.is_compressed(bytes(corrupt))

    # Corrupt hdr_len to invalid value (e.g. 0x20)
    corrupt2 = bytearray(comp)
    corrupt2[-5] = 0x20
    assert not BLZ.is_compressed(bytes(corrupt2))


def test_blz_error_handling():
    # Data too short
    with pytest.raises(CompressionError, match="too short"):
        BLZ.decompress(b"1234")

    # Invalid header length
    raw = b"Repetitive text string for error testing " * 20
    comp = bytearray(BLZ.compress(raw))
    comp[-5] = 0x05  # < 0x08
    with pytest.raises(CompressionError, match="Invalid BLZ header length"):
        BLZ.decompress(bytes(comp))

    # Encoded length exceeds file size
    comp2 = bytearray(BLZ.compress(raw))
    # Modify enc_and_hdr so enc_len is huge (0x00FFFFFF)
    trailer = BLZTrailerStruct(enc_and_hdr=(0x08 << 24) | 0x007FFFFF, inc_len_hdr=100)
    comp2[-8:] = trailer.to_bytes()
    with pytest.raises(CompressionError, match="exceeds total buffer length"):
        BLZ.decompress(bytes(comp2))


def test_blz_ndrom_integration():
    # Construct a synthetic NDS ROM with an ARM9 binary
    arm9_raw = b"ARM9_MAIN_EXECUTABLE_CODE_BLOCK_TEST_ROUTINES_1234567890" * 40
    comp_arm9 = BLZ.compress(arm9_raw)

    rom_buf = bytearray(0x8000)
    # Header fields
    hdr = NDSHeaderStruct(
        game_title="BLZTEST",
        game_code="NTRX",
        maker_code="01",
        unit_code=0,
        arm9_offset=0x1000,
        arm9_entry_address=0x02000000,
        arm9_ram_address=0x02000000,
        arm9_size=len(comp_arm9),
        arm7_offset=0x3000,
        arm7_entry_address=0x02380000,
        arm7_ram_address=0x02380000,
        arm7_size=0x100,
        fnt_offset=0x3500,
        fnt_size=0x100,
        fat_offset=0x3700,
        fat_size=0x100,
        arm9_overlay_offset=0,
        arm9_overlay_size=0,
        arm7_overlay_offset=0,
        arm7_overlay_size=0,
        banner_offset=0,
        header_crc=0,
    )
    rom_buf[0:len(hdr.to_bytes())] = hdr.to_bytes()
    rom_buf[0x1000 : 0x1000 + len(comp_arm9)] = comp_arm9

    rom = NDSRom(bytes(rom_buf))
    assert rom.is_arm9_compressed()

    decomp_arm9 = rom.decompress_arm9()
    assert decomp_arm9 == arm9_raw

    # Test set_arm9_binary with compression
    new_code = b"MODIFIED_ARM9_TRANSLATED_ENGLISH_DIALOGUE_TEXT_REPLACEMENT" * 30
    rom.set_arm9_binary(new_code, compress=True)
    assert rom.is_arm9_compressed()
    assert rom.decompress_arm9() == new_code


def test_blz_overlay_compressor_integration():
    raw_overlay = b"OVERLAY_0001_BATTLE_SYSTEM_LOGIC_DATA_TABLE" * 25

    # Test compression with BLZ
    blz_overlay = NDSOverlayCompressor.compress(raw_overlay, codec="blz")
    assert BLZ.is_compressed(blz_overlay)
    assert NDSOverlayCompressor.is_compressed(blz_overlay)

    # Decompress through NDSOverlayCompressor
    decomp = NDSOverlayCompressor.decompress(blz_overlay)
    assert decomp == raw_overlay
