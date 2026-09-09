import struct

from miorom.platforms.nds.narc import NARCArchive
from miorom.platforms.psx.exe import PSXExe, PSXExeHeaderStruct
from miorom.platforms.wii.u8 import U8Archive, U8HeaderStruct, U8NodeStruct, Yaz0HeaderStruct
from miorom.platforms.gba.rom import GBAHeaderStruct, GBARom
from miorom.platforms.n64.rom import N64HeaderStruct
from miorom.platforms.snes.rom import SNESHeaderStruct
from miorom.platforms.nds.rom import (
    NDSFatEntryStruct,
    NDSFntDirectoryEntryStruct,
    NDSHeaderCrcStruct,
    NDSHeaderStruct,
    NDSRom,
)
from miorom.platforms.psx.tim import (
    TIMColorStruct,
    TIMHeaderStruct,
    TIMSectionHeaderStruct,
)
from miorom.platforms.wii.tpl import (
    TPLColorStruct,
    TPLHeaderStruct,
    TPLImageHeaderStruct,
    TPLImageTableEntryStruct,
)
from miorom.platforms.gc.disc import GCHeaderStruct, GCFstEntryStruct
from miorom.platforms.gb.rom import GBCoreHeaderStruct
from miorom.platforms.md.rom import MDChecksumStruct, MDHeaderStruct, MDSmdHeaderStruct


def test_nds_header_struct_matches_actual_header_layout():
    raw = bytearray(0x400)
    raw[0:12] = b"TEST_GAME\x00\x00\x00"
    raw[12:16] = b"TEST"
    raw[16:18] = b"01"
    raw[18] = 1
    struct.pack_into("<I", raw, 0x20, 0x200)
    struct.pack_into("<I", raw, 0x28, 0x02000800)
    struct.pack_into("<I", raw, 0x48, 0x280)
    struct.pack_into("<I", raw, 0x4C, 8)
    struct.pack_into("<II", raw, 0x280, 0x300, 0x30B)
    raw[0x300:0x310] = b"PAYLOAD1234"

    assert NDSHeaderStruct.sizeof() == 0x160

    rom = NDSRom(bytes(raw))
    assert rom.title == "TEST_GAME"
    assert rom.arm9_offset == 0x200
    assert rom.arm9_ram_addr == 0x02000800
    assert rom.fat_offset == 0x280
    assert rom.get_file(0) == b"PAYLOAD1234"


def test_gba_header_struct_roundtrip_preserves_header_and_checksum():
    raw = bytearray(0xC0)
    raw[0:4] = b"\x2E\x00\x00\xEA"
    raw[0x04:0xA0] = GBARom.NINTENDO_LOGO
    raw[0xA0:0xAC] = b"TEST_GAME\x00\x00\x00\x00"
    raw[0xAC:0xB0] = b"TSTG"
    raw[0xB0:0xB2] = b"01"

    struct_bytes = GBAHeaderStruct.from_bytes(raw).to_bytes()
    assert struct_bytes.find(b"TEST_GAME") == 0xA0

    rom = GBARom(bytes(raw))
    original_len = len(rom.data)
    rom.title = "CHANGED"
    rom.game_code = "NEW!"
    rom.fix_header_checksum()

    assert len(rom.data) == original_len
    assert rom.title == "CHANGED"
    assert rom.game_code == "NEW!"
    assert rom.is_header_checksum_valid()
    assert rom.is_logo_valid()


def test_n64_header_struct_layout():
    assert N64HeaderStruct.sizeof() == 0x40
    assert N64HeaderStruct.offset_of("title") == 0x20


def test_snes_header_struct_layout():
    assert SNESHeaderStruct.sizeof() == 0x30
    assert SNESHeaderStruct.offset_of("checksum_complement") == 0x1C


def test_narc_binary_struct_layouts():
    assert NARCArchive._Header.sizeof() == 0x10
    assert NARCArchive._SectionHeader.sizeof() == 8
    assert NARCArchive._FatEntry.sizeof() == 8


def test_nds_auxiliary_binary_struct_layouts():
    assert NDSFatEntryStruct.sizeof() == 8
    assert NDSFntDirectoryEntryStruct.sizeof() == 8
    assert NDSHeaderCrcStruct.sizeof() == 2
    assert NDSHeaderCrcStruct.offset_of("checksum") == 0


def test_yaz0_binary_struct_layout():
    assert Yaz0HeaderStruct.sizeof() == 8


def test_psx_header_struct_preserves_full_2048_byte_header():
    assert PSXExeHeaderStruct.sizeof() == PSXExe.HEADER_SIZE
    assert PSXExeHeaderStruct.offset_of("_reserved_0x34") == 0x34


def test_u8_binary_struct_layouts():
    assert U8HeaderStruct.sizeof() == 0x20
    assert U8NodeStruct.sizeof() == 12
    assert U8Archive._parse_archive.__qualname__ == "U8Archive._parse_archive"


def test_tim_binary_struct_layouts():
    assert TIMHeaderStruct.sizeof() == 8
    assert TIMSectionHeaderStruct.sizeof() == 12
    assert TIMColorStruct.sizeof() == 2


def test_tpl_binary_struct_layouts():
    assert TPLHeaderStruct.sizeof() == 12
    assert TPLImageTableEntryStruct.sizeof() == 8
    assert TPLImageHeaderStruct.sizeof() == 28
    assert TPLColorStruct.sizeof() == 2
    assert TPLImageHeaderStruct.offset_of("data_offset") == 8


def test_gamecube_binary_struct_layouts():
    assert GCHeaderStruct.sizeof() == 0x440
    assert GCHeaderStruct.offset_of("magic") == 0x1C
    assert GCHeaderStruct.offset_of("dol_offset") == 0x420
    assert GCFstEntryStruct.sizeof() == 12


def test_gameboy_binary_struct_layout():
    assert GBCoreHeaderStruct.sizeof() == 0x1C
    assert GBCoreHeaderStruct.offset_of("header_checksum") == 0x19
    assert GBCoreHeaderStruct.offset_of("global_checksum") == 0x1A


def test_megadrive_binary_struct_layouts():
    assert MDHeaderStruct.sizeof() == 0x100
    assert MDHeaderStruct.offset_of("checksum") == 0x8E
    assert MDChecksumStruct.sizeof() == 0x190
    assert MDSmdHeaderStruct.sizeof() == 10
