from miorom.errors import ParseError
from miorom.core.schema import BinaryStruct, FixedString, RawBytes, U16, U8
from typing import Optional


class GBCoreHeaderStruct(BinaryStruct):
    _endian = ">"
    title = FixedString(15, pad=b"\x00")
    cgb_flag = U8()
    new_licensee_code = RawBytes(2)
    sgb_flag = U8()
    cartridge_type = U8()
    rom_size = U8()
    ram_size = U8()
    destination_code = U8()
    old_licensee_code = U8()
    mask_rom_version = U8()
    header_checksum = U8()
    global_checksum = U16()


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
            raise ParseError("Data too small for Game Boy ROM header (minimum 336 bytes).")
        self.data = bytearray(data)

    @classmethod
    def from_file(cls, path: str) -> "GBRom":
        with open(path, "rb") as f:
            return cls(f.read())

    def _core_header(self) -> GBCoreHeaderStruct:
        return GBCoreHeaderStruct.from_bytes(self.data, offset=0x134)

    @property
    def title(self) -> str:
        return self._core_header().title.strip()

    @title.setter
    def title(self, val: str):
        encoded = val.encode("ascii", errors="replace")[:15].ljust(15, b"\x00")
        self.data[0x134:0x143] = encoded

    @property
    def cgb_flag(self) -> int:
        return self._core_header().cgb_flag

    @property
    def is_cgb(self) -> bool:
        return self.cgb_flag in (0x80, 0xC0)

    @property
    def is_sgb(self) -> bool:
        return self._core_header().sgb_flag == 0x03

    @property
    def cartridge_type_code(self) -> int:
        return self._core_header().cartridge_type

    @property
    def cartridge_type(self) -> str:
        return self.CART_TYPES.get(self.cartridge_type_code, f"UNKNOWN (0x{self.cartridge_type_code:02X})")

    @property
    def rom_size_bytes(self) -> int:
        code = self._core_header().rom_size
        return 32768 << code

    @property
    def header_checksum(self) -> int:
        return self._core_header().header_checksum

    @property
    def global_checksum(self) -> int:
        return self._core_header().global_checksum

    def is_logo_valid(self) -> bool:
        return self.data[0x104:0x134] == self.NINTENDO_LOGO

    def calculate_header_checksum(self) -> int:
        chk = 0
        for byte in self.data[0x134:0x14D]:
            chk = (chk - byte - 1) & 0xFF
        return chk

    def is_header_checksum_valid(self) -> bool:
        return self.header_checksum == self.calculate_header_checksum()

    def fix_header_checksum(self):
        self.data[0x14D] = self.calculate_header_checksum()

    def calculate_global_checksum(self) -> int:
        total = sum(self.data[:0x14E]) + sum(self.data[0x150:])
        return total & 0xFFFF

    def is_global_checksum_valid(self) -> bool:
        return self.global_checksum == self.calculate_global_checksum()

    def fix_global_checksum(self):
        struct_data = self._core_header()
        struct_data.global_checksum = self.calculate_global_checksum()
        self.data[0x134:0x150] = struct_data.to_bytes()

    def resolve_bank_address(self, bank: int, addr: int) -> int:
        if addr < 0x4000:
            return addr
        elif 0x4000 <= addr <= 0x7FFF:
            effective_bank = max(1, bank)
            return (effective_bank * 0x4000) + (addr - 0x4000)
        else:
            raise ParseError(f"Invalid Game Boy ROM address: 0x{addr:04X} (must be $0000-$7FFF)")

    def to_bytes(self) -> bytes:
        return bytes(self.data)


def fix_gb_checksum(data: bytes) -> bytes:
    gb = GBRom(data)
    gb.fix_header_checksum()
    gb.fix_global_checksum()
    return gb.to_bytes()
