import struct
import pytest
from miorom.platforms.gba import GBASwiResolver, GBAMultiboot
from miorom.errors import ParseError


def test_gba_swi_resolver_lookup():
    entry_lz77 = GBASwiResolver.resolve(0x11)
    assert entry_lz77 is not None
    assert entry_lz77[0] == "LZ77UnCompWram"

    entry_cpuset = GBASwiResolver.resolve(0x0B)
    assert entry_cpuset is not None
    assert entry_cpuset[0] == "CpuSet"

    assert GBASwiResolver.resolve(0x99) is None


def test_gba_swi_instruction_annotations():
    # Thumb: 0xDF11 -> SWI 0x11 (LZ77UnCompWram)
    thumb_swi = 0xDF11
    ann = GBASwiResolver.annotate_thumb_instruction(thumb_swi)
    assert ann is not None
    assert "LZ77UnCompWram" in ann

    # Thumb non-SWI
    assert GBASwiResolver.annotate_thumb_instruction(0x46C0) is None  # NOP

    # ARM: 0xEF110000 -> SWI 0x11
    arm_swi = 0xEF110000
    arm_ann = GBASwiResolver.annotate_arm_instruction(arm_swi)
    assert arm_ann is not None
    assert "LZ77UnCompWram" in arm_ann

    # ARM non-SWI
    assert GBASwiResolver.annotate_arm_instruction(0xE1A00000) is None  # NOP


def test_gba_swi_scanner():
    # Synthetic Thumb binary containing 2 SWI calls
    thumb_code = bytearray()
    thumb_code.extend(struct.pack("<H", 0x46C0))  # NOP
    thumb_code.extend(struct.pack("<H", 0xDF01))  # SWI 0x01 (RegisterRamReset)
    thumb_code.extend(struct.pack("<H", 0x46C0))  # NOP
    thumb_code.extend(struct.pack("<H", 0xDF12))  # SWI 0x12 (LZ77UnCompVram)

    calls = GBASwiResolver.scan_swi_calls(bytes(thumb_code), thumb_mode=True, base_addr=0x08000000)
    assert len(calls) == 2
    assert calls[0]["address"] == 0x08000002
    assert calls[0]["name"] == "RegisterRamReset"
    assert calls[1]["address"] == 0x08000006
    assert calls[1]["name"] == "LZ77UnCompVram"

    # Synthetic ARM binary
    arm_code = bytearray()
    arm_code.extend(struct.pack("<I", 0xE1A00000))  # NOP
    arm_code.extend(struct.pack("<I", 0xEF0B0000))  # SWI 0x0B (CpuSet)

    arm_calls = GBASwiResolver.scan_swi_calls(bytes(arm_code), thumb_mode=False, base_addr=0x08000000)
    assert len(arm_calls) == 1
    assert arm_calls[0]["address"] == 0x08000004
    assert arm_calls[0]["name"] == "CpuSet"


def test_gba_multiboot_creation_and_verification():
    payload_code = b"\x70\x47\x00\x00" * 32  # 128 bytes dummy routine
    mb_bytes = GBAMultiboot.create_payload(
        code_bytes=payload_code,
        title="POKEMON_MB",
        game_code="PKMB",
        maker_code="01",
    )

    assert len(mb_bytes) == 0xE0 + len(payload_code)
    # Check ARM entry branch at offset 0
    assert struct.unpack_from("<I", mb_bytes, 0)[0] == 0xEA000036
    # Check fixed magic 0x96
    assert mb_bytes[0xB2] == 0x96

    assert GBAMultiboot.verify(mb_bytes) is True

    parsed = GBAMultiboot.parse(mb_bytes)
    assert parsed["title"] == "POKEMON_MB"
    assert parsed["game_code"] == "PKMB"
    assert parsed["maker_code"] == "01"
    assert parsed["is_valid_checksum"] is True
    assert parsed["payload_size"] == len(payload_code)
    assert parsed["entry_point"] == 0x020000E0


def test_gba_multiboot_corrupted_checksum():
    mb_bytes = bytearray(GBAMultiboot.create_payload(b"\x00" * 64))
    # Corrupt complement checksum
    mb_bytes[0xBD] ^= 0xFF
    assert GBAMultiboot.verify(bytes(mb_bytes)) is False

    with pytest.raises(ParseError):
        GBAMultiboot.parse(b"SHORT")


def test_gba_multiboot_size_limit():
    huge_payload = b"\x00" * (256 * 1024)
    with pytest.raises(ValueError):
        GBAMultiboot.create_payload(huge_payload)
