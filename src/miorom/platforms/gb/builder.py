"""
miorom.platforms.gb.builder
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Game Boy and Game Boy Color ROM image builder, MBC cartridge layout manager,
and header/checksum recalculator.
"""

from dataclasses import dataclass
from typing import Dict, Optional, Union

from miorom.result import MioRomResult

NINTENDO_LOGO = bytes([
    0xCE, 0xED, 0x66, 0x66, 0xCC, 0x0D, 0x00, 0x0B, 0x03, 0x73, 0x00, 0x83, 0x00, 0x0C, 0x00, 0x0D,
    0x00, 0x08, 0x11, 0x1F, 0x88, 0x89, 0x00, 0x0E, 0xDC, 0xCC, 0x6E, 0xE6, 0xDD, 0xDD, 0xD9, 0x99,
    0xBB, 0xBB, 0x67, 0x63, 0x6E, 0x0E, 0xEC, 0xCC, 0xDD, 0xDC, 0x99, 0x9F, 0xBB, 0xB9, 0x33, 0x3E,
])


def calculate_header_checksum(rom: Union[bytes, bytearray]) -> int:
    """Compute standard Game Boy header checksum for bytes 0x134 through 0x14C."""
    if len(rom) < 0x14D:
        raise ValueError(f"ROM buffer too small for header checksum ({len(rom)} < 0x14D)")
    chk = 0
    for b in rom[0x134:0x14D]:
        chk = (chk - b - 1) & 0xFF
    return chk


def calculate_global_checksum(rom: Union[bytes, bytearray]) -> int:
    """Compute 16-bit big-endian global checksum across ROM excluding header checksum bytes."""
    if len(rom) < 0x150:
        raise ValueError(f"ROM buffer too small for global checksum ({len(rom)} < 0x150)")
    total = sum(rom[:0x14E]) + sum(rom[0x150:])
    return total & 0xFFFF


@dataclass
class GBHeader(MioRomResult):
    """Cartridge header definition for Game Boy and Game Boy Color ROM images."""
    title: str
    mbc_type: int
    rom_size_code: int
    ram_size_code: int
    destination: int
    licensee: int
    version: int
    header_checksum: int
    global_checksum: int
    is_cgb: bool
    is_sgb: bool

    @classmethod
    def parse(cls, rom: Union[bytes, bytearray]) -> "GBHeader":
        """Parse cartridge header from 0x100..0x14F of a Game Boy ROM."""
        if len(rom) < 0x150:
            raise ValueError(f"ROM buffer too small for Game Boy header ({len(rom)} < 0x150 bytes)")

        title_raw = bytes(rom[0x134:0x144])
        # Title length (15 if CGB, else 16)
        cgb_flag = rom[0x143]
        is_cgb = cgb_flag in (0x80, 0xC0)
        if is_cgb:
            title_clean = title_raw[:15].decode("ascii", errors="replace").rstrip("\x00").strip()
        else:
            title_clean = title_raw[:16].decode("ascii", errors="replace").rstrip("\x00").strip()

        is_sgb = rom[0x146] == 0x03
        mbc_type = rom[0x147]
        rom_size_code = rom[0x148]
        ram_size_code = rom[0x149]
        destination = rom[0x14A]
        old_licensee = rom[0x14B]
        version = rom[0x14C]
        header_checksum = rom[0x14D]
        global_checksum = (rom[0x14E] << 8) | rom[0x14F]

        return cls(
            title=title_clean,
            mbc_type=mbc_type,
            rom_size_code=rom_size_code,
            ram_size_code=ram_size_code,
            destination=destination,
            licensee=old_licensee,
            version=version,
            header_checksum=header_checksum,
            global_checksum=global_checksum,
            is_cgb=is_cgb,
            is_sgb=is_sgb,
        )

    def pack(self, rom: Optional[Union[bytes, bytearray]] = None) -> bytearray:
        """Write header fields into ROM buffer and return the updated bytearray."""
        if rom is None:
            buf = bytearray(0x150)
        else:
            buf = bytearray(rom)

        if len(buf) < 0x150:
            buf.extend(b"\x00" * (0x150 - len(buf)))

        # Entry point NOP ; JP 0x0150
        buf[0x100:0x104] = b"\x00\xC3\x50\x01"

        # Boot logo
        buf[0x104:0x134] = NINTENDO_LOGO

        # Title and flags
        title_bytes = self.title.encode("ascii", errors="replace")
        if self.is_cgb:
            buf[0x134:0x143] = title_bytes[:15].ljust(15, b"\x00")
            buf[0x143] = 0x80
        else:
            buf[0x134:0x144] = title_bytes[:16].ljust(16, b"\x00")

        buf[0x144:0x146] = b"01"
        buf[0x146] = 0x03 if self.is_sgb else 0x00
        buf[0x147] = self.mbc_type & 0xFF
        buf[0x148] = self.rom_size_code & 0xFF
        buf[0x149] = self.ram_size_code & 0xFF
        buf[0x14A] = self.destination & 0xFF
        buf[0x14B] = self.licensee & 0xFF
        buf[0x14C] = self.version & 0xFF

        chk = calculate_header_checksum(buf)
        buf[0x14D] = chk

        glob = calculate_global_checksum(buf)
        buf[0x14E] = (glob >> 8) & 0xFF
        buf[0x14F] = glob & 0xFF

        return buf


class GBRomBuilder:
    """
    Game Boy / Game Boy Color cartridge ROM assembler.
    Assembles memory banks (16KB each), configures MBC mapper headers,
    recalculates checksums, and expands ROM images to higher capacities.
    """

    BANK_SIZE = 0x4000

    def __init__(
        self,
        mbc_type: int = 0x01,
        ram_size_code: int = 0x00,
        destination: int = 0x01,
        is_cgb: bool = False,
        is_sgb: bool = False,
    ):
        self.mbc_type = mbc_type
        self.ram_size_code = ram_size_code
        self.destination = destination
        self.is_cgb = is_cgb
        self.is_sgb = is_sgb
        self._banks: Dict[int, bytearray] = {}

    def set_bank_data(self, bank: int, data: Union[bytes, bytearray]) -> None:
        """Store binary payload for a specific 16KB bank."""
        if bank < 0:
            raise ValueError(f"Invalid bank number {bank} (must be >= 0)")
        bank_buf = bytearray(self.BANK_SIZE)
        copy_len = min(len(data), self.BANK_SIZE)
        bank_buf[:copy_len] = data[:copy_len]
        self._banks[bank] = bank_buf

    def get_bank(self, bank: int) -> bytearray:
        """Retrieve the bytearray for a specific bank, creating an empty bank if uninitialized."""
        if bank not in self._banks:
            self._banks[bank] = bytearray([0xFF] * self.BANK_SIZE)
        return self._banks[bank]

    def recalculate_checksums(self, rom: bytearray) -> bytearray:
        """Recalculate header and global checksums and write them into the ROM buffer."""
        if len(rom) < 0x150:
            raise ValueError("ROM size too small to compute checksums")
        h_chk = calculate_header_checksum(rom)
        rom[0x14D] = h_chk
        g_chk = calculate_global_checksum(rom)
        rom[0x14E] = (g_chk >> 8) & 0xFF
        rom[0x14F] = g_chk & 0xFF
        return rom

    def expand(self, rom: Union[bytes, bytearray], target_banks: int) -> bytearray:
        """
        Expand ROM buffer to target_banks (power of 2), padding with 0xFF.
        Updates the ROM size code at 0x148 and recalculates checksums.
        """
        if target_banks < 2 or (target_banks & (target_banks - 1)) != 0:
            raise ValueError(f"Target banks must be a power of two >= 2 (got {target_banks})")

        target_size = target_banks * self.BANK_SIZE
        if len(rom) > target_size:
            raise ValueError(f"ROM size ({len(rom)}) already exceeds target size ({target_size})")

        expanded = bytearray(target_size)
        expanded[:len(rom)] = rom
        if len(rom) < target_size:
            expanded[len(rom):] = bytes([0xFF] * (target_size - len(rom)))

        # rom_size_code = log2(target_banks) - 1
        code = (target_banks.bit_length() - 1) - 1
        expanded[0x148] = code & 0xFF

        return self.recalculate_checksums(expanded)

    def build(self, title: str = "MIOROM") -> bytes:
        """
        Assemble all configured banks into a valid, bootable Game Boy ROM byte string.
        Ensures a minimum of 2 banks (32KB).
        """
        max_bank = max(self._banks.keys(), default=1)
        # Round up to next power of 2, minimum 2 banks
        num_banks = 2
        while num_banks <= max_bank:
            num_banks *= 2

        full_rom = bytearray(num_banks * self.BANK_SIZE)
        for i in range(num_banks):
            bank_content = self.get_bank(i)
            offset = i * self.BANK_SIZE
            full_rom[offset:offset + self.BANK_SIZE] = bank_content

        rom_size_code = (num_banks.bit_length() - 1) - 1

        header = GBHeader(
            title=title,
            mbc_type=self.mbc_type,
            rom_size_code=rom_size_code,
            ram_size_code=self.ram_size_code,
            destination=self.destination,
            licensee=0x01,
            version=0x00,
            header_checksum=0,
            global_checksum=0,
            is_cgb=self.is_cgb,
            is_sgb=self.is_sgb,
        )

        header_rom = header.pack(full_rom)
        return bytes(header_rom)
