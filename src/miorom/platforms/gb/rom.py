import struct
from typing import Optional


class GBRom:
    """
    Game Boy (DMG) and Game Boy Color (CGB) ROM header inspector,
    checksum calculator/fixer, and MBC memory bank resolver.
    """

    NINTENDO_LOGO = bytes([
        0xCE, 0xED, 0x66, 0x66, 0xCC, 0x0D, 0x00, 0x0B, 0x03, 0x73, 0x00, 0x83, 0x00, 0x0C, 0x00, 0x0D,
        0x00, 0x08, 0x11, 0x1F, 0x88, 0x89, 0x00, 0x0E, 0xDC, 0xCC, 0x6E, 0xE6, 0xDD, 0xDD, 0xD9, 0x99,
        0xBB, 0xBB, 0x67, 0x63, 0x6E, 0x0E, 0xEC, 0xCC, 0xDD, 0xDC, 0x99, 0x9F, 0xBB, 0xB9, 0x33, 0x3E,
    ])

    CART_TYPES = {
        0x00: "ROM ONLY",
        0x01: "MBC1",
        0x02: "MBC1+RAM",
        0x03: "MBC1+RAM+BATTERY",
        0x05: "MBC2",
        0x06: "MBC2+BATTERY",
        0x08: "ROM+RAM",
        0x09: "ROM+RAM+BATTERY",
        0x0F: "MBC3+TIMER+BATTERY",
        0x10: "MBC3+TIMER+RAM+BATTERY",
        0x11: "MBC3",
        0x12: "MBC3+RAM",
        0x13: "MBC3+RAM+BATTERY",
        0x19: "MBC5",
        0x1A: "MBC5+RAM",
        0x1B: "MBC5+RAM+BATTERY",
        0x1C: "MBC5+RUMBLE",
        0x1D: "MBC5+RUMBLE+RAM",
        0x1E: "MBC5+RUMBLE+RAM+BATTERY",
    }

    def __init__(self, data: bytes):
        if len(data) < 0x150:
            raise ValueError("Data too small for Game Boy ROM header (minimum 336 bytes).")
        self.data = bytearray(data)

    @classmethod
    def from_file(cls, path: str) -> "GBRom":
        with open(path, "rb") as f:
            return cls(f.read())

    @property
    def title(self) -> str:
        # Title can be up to 16 characters (or 11/15 in CGB)
        raw = self.data[0x134:0x143]
        return raw.split(b"\x00")[0].decode("ascii", errors="replace").strip()

    @title.setter
    def title(self, val: str):
        encoded = val.encode("ascii", errors="replace")[:15].ljust(15, b"\x00")
        self.data[0x134:0x143] = encoded

    @property
    def cgb_flag(self) -> int:
        return self.data[0x143]

    @property
    def is_cgb(self) -> bool:
        return self.cgb_flag in (0x80, 0xC0)

    @property
    def is_sgb(self) -> bool:
        return self.data[0x146] == 0x03

    @property
    def cartridge_type_code(self) -> int:
        return self.data[0x147]

    @property
    def cartridge_type(self) -> str:
        return self.CART_TYPES.get(self.cartridge_type_code, f"UNKNOWN (0x{self.cartridge_type_code:02X})")

    @property
    def rom_size_bytes(self) -> int:
        code = self.data[0x148]
        return 32768 << code

    @property
    def header_checksum(self) -> int:
        return self.data[0x14D]

    @property
    def global_checksum(self) -> int:
        return struct.unpack_from(">H", self.data, 0x14E)[0]

    def is_logo_valid(self) -> bool:
        return self.data[0x104:0x134] == self.NINTENDO_LOGO

    def calculate_header_checksum(self) -> int:
        """
        Game Boy header checksum:
        x = 0
        FOR i = 0x134 TO 0x14C: x = x - [i] - 1
        return x & 0xFF
        """
        chk = 0
        for b in self.data[0x134:0x14D]:
            chk = (chk - b - 1) & 0xFF
        return chk

    def is_header_checksum_valid(self) -> bool:
        return self.header_checksum == self.calculate_header_checksum()

    def fix_header_checksum(self):
        """Calculates and writes the correct header checksum at byte 0x14D."""
        self.data[0x14D] = self.calculate_header_checksum()

    def calculate_global_checksum(self) -> int:
        """
        16-bit big-endian sum of all bytes in the ROM except the two global checksum bytes.
        """
        total = sum(self.data[:0x14E]) + sum(self.data[0x150:])
        return total & 0xFFFF

    def is_global_checksum_valid(self) -> bool:
        return self.global_checksum == self.calculate_global_checksum()

    def fix_global_checksum(self):
        """Calculates and writes the 16-bit global checksum at bytes 0x14E..0x14F."""
        chk = self.calculate_global_checksum()
        struct.pack_into(">H", self.data, 0x14E, chk)

    def resolve_bank_address(self, bank: int, addr: int) -> int:
        """
        Translates a Game Boy banked CPU address ($4000-$7FFF) or fixed address ($0000-$3FFF)
        into a raw ROM file offset.
        """
        if addr < 0x4000:
            # Fixed bank 0
            return addr
        elif 0x4000 <= addr <= 0x7FFF:
            effective_bank = max(1, bank)
            return (effective_bank * 0x4000) + (addr - 0x4000)
        else:
            raise ValueError(f"Invalid Game Boy ROM address: 0x{addr:04X} (must be $0000-$7FFF)")

    def to_bytes(self) -> bytes:
        return bytes(self.data)


def fix_gb_checksum(data: bytes) -> bytes:
    """Helper to fix both header checksum and global checksum of a Game Boy ROM."""
    gb = GBRom(data)
    gb.fix_header_checksum()
    gb.fix_global_checksum()
    return gb.to_bytes()
