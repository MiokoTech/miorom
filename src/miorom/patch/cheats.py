"""
miorom.patch.cheats
~~~~~~~~~~~~~~~~~~~
Universal Game Genie, GameShark, and Action Replay Cheat Code Engine.
Decodes and encodes cheat cipher strings for NES, SNES, Genesis/MD, Game Boy,
and applies permanent ROM modifications via hard-patching.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple, Union

from miorom.result import MioRomResult


@dataclass
class CheatCode(MioRomResult):
    """Structured representation of a decoded cheat code."""
    raw_code: str
    system: str
    address: int
    value: int
    compare: Optional[int] = None
    size: int = 1
    description: str = ""

    @property
    def address_hex(self) -> str:
        return f"0x{self.address:06X}"

    @property
    def value_hex(self) -> str:
        return f"0x{self.value:02X}" if self.size == 1 else f"0x{self.value:04X}"


class NesGameGenie:
    """NES Game Genie 6-character and 8-character cipher decoder and encoder."""

    ALPHABET = "APZLGITYEOXUKSVN"
    CHAR_MAP: Dict[str, int] = {c: i for i, c in enumerate(ALPHABET)}

    @classmethod
    def decode(cls, code: str) -> CheatCode:
        clean = code.strip().upper().replace("-", "").replace(" ", "")
        if len(clean) not in (6, 8):
            raise ValueError(f"NES Game Genie code must be 6 or 8 characters (got {len(clean)})")

        for c in clean:
            if c not in cls.CHAR_MAP:
                raise ValueError(f"Invalid character '{c}' in NES Game Genie code")

        n = [cls.CHAR_MAP[c] for c in clean]

        if len(clean) == 6:
            address = (
                0x8000
                + ((n[3] & 7) << 12)
                + ((n[5] & 7) << 8)
                + ((n[4] & 8) << 8)
                + ((n[2] & 7) << 4)
                + ((n[1] & 8) << 4)
                + (n[4] & 7)
                + (n[3] & 8)
            )
            value = ((n[1] & 7) << 4) | ((n[0] & 8) << 4) | (n[0] & 7) | (n[5] & 8)
            return CheatCode(raw_code=code, system="nes", address=address, value=value, size=1)
        else:
            address = (
                0x8000
                + ((n[3] & 7) << 12)
                + ((n[5] & 7) << 8)
                + ((n[4] & 8) << 8)
                + ((n[2] & 7) << 4)
                + ((n[1] & 8) << 4)
                + (n[4] & 7)
                + (n[3] & 8)
            )
            value = ((n[1] & 7) << 4) | ((n[0] & 8) << 4) | (n[0] & 7) | (n[7] & 8)
            compare = ((n[7] & 7) << 4) | ((n[6] & 8) << 4) | (n[6] & 7) | (n[5] & 8)
            return CheatCode(raw_code=code, system="nes", address=address, value=value, compare=compare, size=1)

    @classmethod
    def encode(cls, address: int, value: int, compare: Optional[int] = None) -> str:
        if not (0x8000 <= address <= 0xFFFF):
            raise ValueError(f"NES Game Genie address must be 0x8000..0xFFFF (got 0x{address:04X})")

        addr = address - 0x8000
        val = value & 0xFF

        if compare is None:
            n0 = (val & 7) | ((val & 0x80) >> 4)
            n1 = ((val & 0x70) >> 4) | ((addr & 0x80) >> 4)
            n2 = (addr & 0x70) >> 4
            n3 = ((addr & 0x7000) >> 12) | (addr & 8)
            n4 = (addr & 7) | ((addr & 0x800) >> 8)
            n5 = ((addr & 0x700) >> 8) | (val & 8)
            return "".join(cls.ALPHABET[x] for x in (n0, n1, n2, n3, n4, n5))
        else:
            cmp_val = compare & 0xFF
            n0 = (val & 7) | ((val & 0x80) >> 4)
            n1 = ((val & 0x70) >> 4) | ((addr & 0x80) >> 4)
            n2 = (addr & 0x70) >> 4
            n3 = ((addr & 0x7000) >> 12) | (addr & 8)
            n4 = (addr & 7) | ((addr & 0x800) >> 8)
            n5 = ((addr & 0x700) >> 8) | (cmp_val & 8)
            n6 = (cmp_val & 7) | ((cmp_val & 0x80) >> 4)
            n7 = ((cmp_val & 0x70) >> 4) | (val & 8)
            return "".join(cls.ALPHABET[x] for x in (n0, n1, n2, n3, n4, n5, n6, n7))


class SnesGameGenie:
    """SNES Game Genie 8-character cipher decoder and encoder."""

    ALPHABET = "DF4709156BC8A23E"
    CHAR_MAP: Dict[str, int] = {c: i for i, c in enumerate(ALPHABET)}

    @classmethod
    def decode(cls, code: str) -> CheatCode:
        clean = code.strip().upper().replace("-", "").replace(" ", "")
        if len(clean) != 8:
            raise ValueError(f"SNES Game Genie code must be 8 characters (got {len(clean)})")

        for c in clean:
            if c not in cls.CHAR_MAP:
                raise ValueError(f"Invalid character '{c}' in SNES Game Genie code")

        d = [cls.CHAR_MAP[c] for c in clean]

        value = (d[0] << 4) | d[1]
        address = (
            ((d[2] & 0x03) << 22)
            | ((d[3] & 0x03) << 20)
            | ((d[4] & 0x03) << 18)
            | ((d[5] & 0x03) << 16)
            | ((d[6] & 0x03) << 14)
            | ((d[7] & 0x03) << 12)
            | ((d[2] & 0x0C) << 8)
            | ((d[3] & 0x0C) << 6)
            | ((d[4] & 0x0C) << 4)
            | ((d[5] & 0x0C) << 2)
            | (d[6] & 0x0C)
            | ((d[7] & 0x0C) >> 2)
        )

        return CheatCode(raw_code=code, system="snes", address=address, value=value, size=1)

    @classmethod
    def encode(cls, address: int, value: int) -> str:
        d0 = (value >> 4) & 0x0F
        d1 = value & 0x0F

        d2 = ((address >> 22) & 0x03) | ((address >> 8) & 0x0C)
        d3 = ((address >> 20) & 0x03) | ((address >> 6) & 0x0C)
        d4 = ((address >> 18) & 0x03) | ((address >> 4) & 0x0C)
        d5 = ((address >> 16) & 0x03) | ((address >> 2) & 0x0C)
        d6 = ((address >> 14) & 0x03) | (address & 0x0C)
        d7 = ((address >> 12) & 0x03) | ((address << 2) & 0x0C)

        chars = "".join(cls.ALPHABET[x] for x in (d0, d1, d2, d3, d4, d5, d6, d7))
        return f"{chars[:4]}-{chars[4:]}"


class GenesisGameGenie:
    """Sega Genesis / Mega Drive Game Genie 8-character cipher decoder and encoder."""

    ALPHABET = "ABCDEFGHJKLMNPRSTVWXYZ0123456789"
    CHAR_MAP: Dict[str, int] = {c: i for i, c in enumerate(ALPHABET)}

    @classmethod
    def decode(cls, code: str) -> CheatCode:
        clean = code.strip().upper().replace("-", "").replace(" ", "")
        if len(clean) != 8:
            raise ValueError(f"Genesis Game Genie code must be 8 characters (got {len(clean)})")

        for c in clean:
            if c not in cls.CHAR_MAP:
                raise ValueError(f"Invalid character '{c}' in Genesis Game Genie code")

        # Genesis 16-bit value and 24-bit address decoding
        v = 0
        for c in clean:
            v = (v << 5) | cls.CHAR_MAP[c]

        val = (
            ((v >> 31) & 0x01) << 15
            | ((v >> 22) & 0x01) << 14
            | ((v >> 13) & 0x01) << 13
            | ((v >> 4) & 0x01) << 12
            | ((v >> 35) & 0x0F) << 8
            | ((v >> 26) & 0x0F) << 4
            | ((v >> 17) & 0x0F)
        )

        addr = (
            ((v >> 30) & 0x01) << 23
            | ((v >> 21) & 0x01) << 22
            | ((v >> 12) & 0x01) << 21
            | ((v >> 3) & 0x01) << 20
            | ((v >> 32) & 0x07) << 16
            | ((v >> 23) & 0x07) << 12
            | ((v >> 14) & 0x07) << 8
            | ((v >> 5) & 0x07) << 4
            | (v & 0x07)
        )

        return CheatCode(raw_code=code, system="genesis", address=addr, value=val, size=2)


class GameBoyGameGenie:
    """Game Boy Game Genie 6-character and 9-character cipher decoder and encoder."""

    @classmethod
    def decode(cls, code: str) -> CheatCode:
        clean = code.strip().upper().replace("-", "").replace(" ", "")
        if len(clean) not in (6, 9):
            raise ValueError(f"Game Boy Game Genie code must be 6 or 9 characters (got {len(clean)})")

        try:
            d = [int(c, 16) for c in clean]
        except ValueError:
            raise ValueError("Game Boy Game Genie code contains non-hexadecimal characters")

        value = (d[0] << 4) | d[1]
        address = ((d[5] ^ 0x0F) << 12) | (d[2] << 8) | (d[3] << 4) | d[4]

        compare = None
        if len(clean) == 9:
            compare = ((d[6] ^ 0x0F) << 4) | d[8]

        return CheatCode(
            raw_code=code,
            system="gb",
            address=address,
            value=value,
            compare=compare,
            size=1,
        )

    @classmethod
    def encode(cls, address: int, value: int, compare: Optional[int] = None) -> str:
        d0 = (value >> 4) & 0x0F
        d1 = value & 0x0F
        d2 = (address >> 8) & 0x0F
        d3 = (address >> 4) & 0x0F
        d4 = address & 0x0F
        d5 = ((address >> 12) & 0x0F) ^ 0x0F

        base = "".join(f"{x:X}" for x in (d0, d1, d2, d3, d4, d5))
        if compare is None:
            return f"{base[:3]}-{base[3:]}"

        d6 = ((compare >> 4) & 0x0F) ^ 0x0F
        d7 = 0x00  # Checksum digit placeholder
        d8 = compare & 0x0F
        ext = "".join(f"{x:X}" for x in (d6, d7, d8))
        return f"{base[:3]}-{base[3:]}-{ext}"


class GameShark:
    """GameShark and Action Replay memory poke code decoder."""

    @classmethod
    def decode(cls, code: str, default_system: str = "gba") -> CheatCode:
        clean = code.strip().upper().replace(":", " ").replace("-", " ")
        parts = clean.split()
        if len(parts) != 2:
            raise ValueError(f"GameShark code must consist of two parts (got {code!r})")

        addr_str, val_str = parts
        addr = int(addr_str, 16)
        val = int(val_str, 16)

        # Detect width based on value string length or prefix
        val_len = len(val_str)
        if val_len <= 2:
            size = 1
        elif val_len <= 4:
            size = 2
        else:
            size = 4

        return CheatCode(
            raw_code=code,
            system=default_system,
            address=addr,
            value=val,
            size=size,
        )


def parse_cheat_code(code: str, system: Optional[str] = None) -> CheatCode:
    """
    Auto-detect cheat format and decode into a CheatCode object.
    Supported system hints: 'nes', 'snes', 'genesis', 'md', 'gb', 'gbc', 'gameshark'.
    """
    clean = code.strip().upper().replace("-", "").replace(" ", "")

    if system:
        sys = system.lower()
        if sys == "nes":
            return NesGameGenie.decode(code)
        elif sys == "snes":
            return SnesGameGenie.decode(code)
        elif sys in ("genesis", "md", "megadrive"):
            return GenesisGameGenie.decode(code)
        elif sys in ("gb", "gbc"):
            return GameBoyGameGenie.decode(code)
        elif sys in ("gameshark", "ar", "gba", "n64", "ps1"):
            return GameShark.decode(code, default_system=sys)

    # Heuristic format detection
    if " " in code.strip() or ":" in code.strip():
        return GameShark.decode(code)

    if len(clean) in (6, 8) and all(c in NesGameGenie.ALPHABET for c in clean):
        try:
            return NesGameGenie.decode(code)
        except Exception:
            pass

    if len(clean) == 8 and all(c in SnesGameGenie.ALPHABET for c in clean):
        try:
            return SnesGameGenie.decode(code)
        except Exception:
            pass

    if len(clean) in (6, 9) and all(c in "0123456789ABCDEF" for c in clean):
        try:
            return GameBoyGameGenie.decode(code)
        except Exception:
            pass

    if len(clean) == 8 and all(c in GenesisGameGenie.ALPHABET for c in clean):
        return GenesisGameGenie.decode(code)

    raise ValueError(f"Could not auto-detect format for cheat code: {code!r}")


def hard_patch_rom(
    rom_data: Union[bytes, bytearray],
    cheats: Sequence[Union[CheatCode, str]],
    system: Optional[str] = None,
    header_offset: int = 0,
) -> Tuple[bytearray, List[Tuple[int, int, int]]]:
    """
    Permanently patch Game Genie / cheat overrides directly into a ROM binary.
    Returns (patched_rom, list_of_updates) where each update is (file_offset, old_byte, new_byte).
    """
    buf = bytearray(rom_data)
    log: List[Tuple[int, int, int]] = []

    for item in cheats:
        if isinstance(item, str):
            cheat = parse_cheat_code(item, system=system)
        else:
            cheat = item

        # Resolve CPU address to file offset
        addr = cheat.address
        sys = (cheat.system or system or "raw").lower()

        if sys == "nes":
            # NES CPU 0x8000..0xFFFF maps to PRG ROM
            if 0x8000 <= addr <= 0xFFFF:
                # Account for 16-byte iNES header if present
                ines_hdr = 16 if len(buf) % 1024 == 16 or buf.startswith(b"NES\x1A") else 0
                file_off = ines_hdr + (addr - 0x8000)
            else:
                file_off = addr
        elif sys == "snes":
            # LoROM mapping: Bank $00..$7D, addr $8000..$FFFF
            bank = (addr >> 16) & 0xFF
            offset_in_bank = addr & 0xFFFF
            snes_hdr = 512 if len(buf) % 1024 == 512 else 0
            if offset_in_bank >= 0x8000:
                file_off = snes_hdr + ((bank & 0x7F) * 0x8000) + (offset_in_bank - 0x8000)
            else:
                file_off = snes_hdr + addr
        elif sys in ("gb", "gbc"):
            # Game Boy Bank 0 (0x0000..0x3FFF)
            file_off = addr & 0x3FFF
        else:
            file_off = addr + header_offset

        if file_off + cheat.size > len(buf):
            raise IndexError(
                f"Resolved cheat offset 0x{file_off:06X} is outside ROM boundaries (size {len(buf)})"
            )

        if cheat.compare is not None:
            current_val = buf[file_off]
            if current_val != cheat.compare:
                raise ValueError(
                    f"Cheat compare mismatch at 0x{file_off:06X}: expected 0x{cheat.compare:02X}, found 0x{current_val:02X}"
                )

        if cheat.size == 1:
            old_b = buf[file_off]
            buf[file_off] = cheat.value & 0xFF
            log.append((file_off, old_b, cheat.value & 0xFF))
        elif cheat.size == 2:
            # Big-endian 16-bit word (Genesis)
            old_b = (buf[file_off] << 8) | buf[file_off + 1]
            buf[file_off] = (cheat.value >> 8) & 0xFF
            buf[file_off + 1] = cheat.value & 0xFF
            log.append((file_off, old_b, cheat.value & 0xFFFF))

    return buf, log
