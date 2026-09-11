import pytest
from miorom.patch.cheats import (
    CheatCode,
    GameBoyGameGenie,
    GameShark,
    GenesisGameGenie,
    NesGameGenie,
    SnesGameGenie,
    hard_patch_rom,
    parse_cheat_code,
)


def test_nes_game_genie_6char_roundtrip():
    # Test address in $8000..$FFFF
    addr = 0x9123
    val = 0x42
    encoded = NesGameGenie.encode(addr, val)
    assert len(encoded) == 6

    decoded = NesGameGenie.decode(encoded)
    assert decoded.system == "nes"
    assert decoded.address == addr
    assert decoded.value == val
    assert decoded.compare is None


def test_nes_game_genie_8char_roundtrip():
    addr = 0xC5A0
    val = 0x99
    cmp_val = 0x12
    encoded = NesGameGenie.encode(addr, val, compare=cmp_val)
    assert len(encoded) == 8

    decoded = NesGameGenie.decode(encoded)
    assert decoded.system == "nes"
    assert decoded.address == addr
    assert decoded.value == val
    assert decoded.compare == cmp_val


def test_nes_game_genie_invalid_codes():
    with pytest.raises(ValueError):
        NesGameGenie.decode("TOOLONGCODE")

    with pytest.raises(ValueError):
        NesGameGenie.decode("QQQQQQ")  # Q is not in NES alphabet
    with pytest.raises(ValueError):
        NesGameGenie.decode("123456")  # 1 is not in NES alphabet


def test_snes_game_genie_roundtrip():
    addr = 0x008000
    val = 0xA9
    encoded = SnesGameGenie.encode(addr, val)
    assert len(encoded.replace("-", "")) == 8

    decoded = SnesGameGenie.decode(encoded)
    assert decoded.system == "snes"
    assert decoded.address == addr
    assert decoded.value == val


def test_genesis_game_genie_decode():
    # Standard Genesis code: 8 characters from base32 alphabet
    code = "ATBT-AA32"
    decoded = GenesisGameGenie.decode(code)
    assert decoded.system == "genesis"
    assert decoded.size == 2
    assert isinstance(decoded.address, int)
    assert isinstance(decoded.value, int)


def test_gb_game_genie_roundtrip():
    addr = 0x1234
    val = 0xFE
    cmp_val = 0x55

    # 6-char
    code6 = GameBoyGameGenie.encode(addr, val)
    dec6 = GameBoyGameGenie.decode(code6)
    assert dec6.system == "gb"
    assert dec6.address == addr
    assert dec6.value == val
    assert dec6.compare is None

    # 9-char
    code9 = GameBoyGameGenie.encode(addr, val, compare=cmp_val)
    dec9 = GameBoyGameGenie.decode(code9)
    assert dec9.address == addr
    assert dec9.value == val
    assert dec9.compare == cmp_val


def test_gameshark_decode():
    code = "010512D0 0003"
    decoded = GameShark.decode(code, default_system="gba")
    assert decoded.system == "gba"
    assert decoded.address == 0x010512D0
    assert decoded.value == 0x0003


def test_parse_cheat_code_autodetect():
    c_gs = parse_cheat_code("80012345 0001")
    assert c_gs.address == 0x80012345

    c_gb = parse_cheat_code("001-234-DEF")
    assert c_gb.system == "gb"


def test_hard_patch_rom():
    # Build 32KB test ROM with 16-byte iNES header
    rom = bytearray(b"NES\x1A" + (b"\x00" * 12) + (b"\xEA" * 0x8000))

    # NOP at $8000 (offset 16)
    cheat = CheatCode(raw_code="TEST", system="nes", address=0x8000, value=0x60, compare=0xEA)
    patched, log = hard_patch_rom(rom, [cheat])

    assert patched[16] == 0x60
    assert len(log) == 1
    assert log[0] == (16, 0xEA, 0x60)

    # Compare mismatch raises ValueError
    bad_cheat = CheatCode(raw_code="TEST", system="nes", address=0x8000, value=0x00, compare=0xFF)
    with pytest.raises(ValueError):
        hard_patch_rom(rom, [bad_cheat])

    # Out of bounds raises IndexError
    oob_cheat = CheatCode(raw_code="OOB", system="nes", address=0xFFFF, value=0x00)
    small_rom = bytearray(0x100)
    with pytest.raises(IndexError):
        hard_patch_rom(small_rom, [oob_cheat])
