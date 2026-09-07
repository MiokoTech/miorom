import pytest
import struct
from miorom.platforms.snes.rom import SNESRom
from miorom.platforms.psx.tim import TIMImage
from miorom.platforms.psx.exe import PSXExe
from miorom.graphics.palette import Color, Palette


def test_snes_rom_detection_and_checksum():
    # Build minimal 512KB LoROM (0x80000 bytes)
    rom_data = bytearray(b"\x00" * 0x80000)
    header_off = 0x7FC0

    # Title
    rom_data[header_off : header_off + 21] = b"CHRONO TRIGGER       "
    # Map mode (0x20 = LoROM)
    rom_data[header_off + 0x15] = 0x20
    # Rom type (0x02 = ROM+RAM+Battery)
    rom_data[header_off + 0x16] = 0x02
    # Rom size (0x09 = 4MB, or 0x08 = 2MB)
    rom_data[header_off + 0x17] = 0x09

    # Pre-calculate checksum
    snes = SNESRom(bytes(rom_data))
    assert snes.mapping_type == "LoROM"
    assert snes.title == "CHRONO TRIGGER"
    assert snes.has_smc is False

    # Fix checksum
    snes.fix_checksum()
    assert snes.is_checksum_valid() is True

    # Test SMC copier header stripping & adding
    assert snes.add_smc_header() is True
    assert snes.has_smc is True
    assert len(snes.data) == 0x80000 + 512
    assert snes.strip_smc_header() is True
    assert snes.has_smc is False
    assert len(snes.data) == 0x80000


def test_psx_tim_image_roundtrip():
    # 4bpp TIM image with 16-color CLUT
    bpp_mode = 0 # 4bpp
    flag = bpp_mode | 0x08 # has clut

    header = struct.pack("<II", 0x10, flag)

    # CLUT: 16 colors (32 bytes) + 12 bytes header = 44 bytes
    clut_dx, clut_dy, clut_w, clut_h = 0, 480, 16, 1
    clut_header = struct.pack("<IHHHH", 12 + 32, clut_dx, clut_dy, clut_w, clut_h)
    colors = bytearray(32)
    # Set first color to white BGR555: 0x7FFF
    struct.pack_into("<H", colors, 0, 0x7FFF)

    # Image: 16x16 pixels in 4bpp.
    # 1 word = 4 pixels, so width in words = 16 // 4 = 4 words = 8 bytes per line.
    # 16 lines = 128 bytes of pixel data.
    img_dx, img_dy, img_w_words, img_h = 0, 0, 4, 16
    img_data = b"\x12\x34\x56\x78" * (4 * 16 // 4)
    img_header = struct.pack("<IHHHH", 12 + len(img_data), img_dx, img_dy, img_w_words, img_h)

    tim_raw = header + clut_header + bytes(colors) + img_header + img_data
    tim = TIMImage(tim_raw)

    assert tim.bpp == 4
    assert tim.has_clut is True
    assert tim.width == 16
    assert tim.height == 16
    assert tim.palette is not None
    assert len(tim.palette) == 16
    assert tim.palette[0].r == 255 and tim.palette[0].g == 255 and tim.palette[0].b == 255

    # Roundtrip serialization
    tim_out = tim.to_bytes()
    assert tim_out == tim_raw


def test_psx_exe_header():
    raw_exe = bytearray(2048 + 100)
    raw_exe[0:8] = b"PS-X EXE"
    struct.pack_into("<I", raw_exe, 0x10, 0x80010000) # PC
    struct.pack_into("<I", raw_exe, 0x18, 0x80010000) # text RAM
    struct.pack_into("<I", raw_exe, 0x1C, 100)        # text size
    struct.pack_into("<I", raw_exe, 0x30, 0x801FFFF0) # SP
    raw_exe[2048:] = b"TEXT PAYLOAD" * 8 + b"1234"

    exe = PSXExe(bytes(raw_exe))
    assert exe.initial_pc == 0x80010000
    assert exe.text_ram_address == 0x80010000
    assert exe.text_size == 100
    assert exe.initial_sp == 0x801FFFF0

    rebuilt = exe.to_bytes()
    assert rebuilt == bytes(raw_exe)
