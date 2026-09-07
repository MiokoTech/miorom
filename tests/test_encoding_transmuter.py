import struct
import pytest
from miorom.text.transmuter import EncodingTransmuter


def test_compress_utf16_and_expand_latin1():
    text = "Ksatria Petualang 123"
    utf16_bytes = EncodingTransmuter.expand_latin1_to_utf16(text, endian="<")
    assert len(utf16_bytes) == len(text) * 2

    compressed = EncodingTransmuter.compress_utf16_to_latin1(utf16_bytes, endian="<")
    assert compressed == text.encode("latin-1")
    assert len(compressed) == len(text)


def test_patch_arm_ldrh_to_ldrb():
    # LDRH r0, [r1, #4]
    # cond=0xE, P=1, U=1, W=0, L=1 -> 0x1D
    # Rn=1, Rd=0, imm_hi=0, 0xB, imm_lo=4
    # Hex: 0xE1D100B4
    ldrh_opcode = 0xE1D100B4
    code = bytearray(struct.pack("<I", ldrh_opcode))

    patched = EncodingTransmuter.patch_arm_ldrh_to_ldrb(code, instruction_offset=0, endian="<")
    assert patched is True

    # Check new opcode
    new_word = struct.unpack_from("<I", code, 0)[0]
    # LDRB r0, [r1, #4]:
    # cond=0xE, 0101 (0x5), U=1, 1 0 1 (B=1, L=1 -> 0xD) -> 0xE5D10004
    assert new_word == 0xE5D10004


def test_patch_arm_ldrh_non_matching():
    # An instruction that is NOT LDRH (e.g. NOP / MOV r0, r0 -> 0xE1A00000)
    code = bytearray(struct.pack("<I", 0xE1A00000))
    patched = EncodingTransmuter.patch_arm_ldrh_to_ldrb(code, instruction_offset=0)
    assert patched is False
