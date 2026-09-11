import struct
import pytest
from miorom.asm.trampoline import TrampolineHook
from miorom.errors import RelocationError


def test_6502_trampoline_hook():
    hook_addr = 0x8000
    cave_addr = 0x9500
    # Original 3 bytes: LDA #$01, NOP
    orig = b"\xA9\x01\xEA"
    payload = b"\xAD\x00\x03"  # LDA $0300

    hook_bytes, cave_bytes = TrampolineHook.create_6502_hook(
        hook_ram_addr=hook_addr,
        original_instr_bytes=orig,
        custom_payload_bytes=payload,
        cave_ram_addr=cave_addr,
    )

    # Hook bytes should be JMP $9500 (0x4C 0x00 0x95)
    assert len(hook_bytes) == 3
    assert hook_bytes[0] == 0x4C
    assert struct.unpack_from("<H", hook_bytes, 1)[0] == cave_addr

    # Cave bytes: payload (3B) + orig (3B) + return JMP $8003 (3B) = 9B
    assert len(cave_bytes) == 9
    assert cave_bytes[:3] == payload
    assert cave_bytes[3:6] == orig
    assert cave_bytes[6] == 0x4C
    assert struct.unpack_from("<H", cave_bytes, 7)[0] == hook_addr + 3


def test_6502_hook_size_validation():
    with pytest.raises(RelocationError):
        TrampolineHook.create_6502_hook(0x8000, b"\xEA\xEA", b"", 0x9000)


def test_snes_trampoline_jml_and_jsl():
    hook_addr = 0xC08000
    cave_addr = 0xC12000
    orig = b"\xAD\x00\x21\xEA"  # LDA $2100, NOP (4 bytes)
    payload = b"\x20\x00\x10"      # JSR $1000

    # JML mode
    hook_jml, cave_jml = TrampolineHook.create_snes_hook(
        hook_ram_addr=hook_addr,
        original_instr_bytes=orig,
        custom_payload_bytes=payload,
        cave_ram_addr=cave_addr,
        mode="jml",
    )
    assert len(hook_jml) == 4
    assert hook_jml[0] == 0x5C  # JML
    assert struct.unpack_from("<I", hook_jml[1:] + b"\x00")[0] == cave_addr

    # Cave JML: payload + orig + JML $C08004
    assert cave_jml[:3] == payload
    assert cave_jml[3:7] == orig
    assert cave_jml[7] == 0x5C
    assert struct.unpack_from("<I", cave_jml[8:] + b"\x00")[0] == hook_addr + 4

    # JSL mode (returns via RTL 0x6B)
    hook_jsl, cave_jsl = TrampolineHook.create_snes_hook(
        hook_ram_addr=hook_addr,
        original_instr_bytes=orig,
        custom_payload_bytes=payload,
        cave_ram_addr=cave_addr,
        mode="jsl",
    )
    assert hook_jsl[0] == 0x22  # JSL
    assert cave_jsl[-1] == 0x6B  # RTL


def test_trampoline_unified_dispatcher():
    # Dispatch 6502
    h6502, _ = TrampolineHook.create_hook("6502", 0x8000, b"\xEA" * 4, b"", 0x9000)
    assert h6502[0] == 0x4C

    # Dispatch SNES
    hsnes, _ = TrampolineHook.create_hook("snes", 0xC08000, b"\xEA" * 4, b"", 0xC09000)
    assert hsnes[0] == 0x5C
