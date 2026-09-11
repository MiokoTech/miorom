from miorom.result import MioRomResult
import struct
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


from miorom.errors import ParseError, RelocationError
class RomExpander:
    """
    ROM Capacity Expander for Retro Systems.
    Safely enlarges ROM binaries, updates cartridge header size descriptors,
    and recalculates system checksums for SNES, Game Boy, and GBA.
    """

    @staticmethod
    def expand_snes(rom: bytearray, target_size_bytes: int) -> bytearray:
        """
        Expand Super Nintendo ROM to target_size_bytes (e.g. 2MB = 0x200000, 4MB = 0x400000).
        Automatically locates LoROM or HiROM internal header, updates ROM size exponent,
        and recalculates the 16-bit complement checksum.
        """
        if target_size_bytes <= len(rom):
            return rom

        # Pad with 0x00 or 0xFF
        rom.extend(b"\x00" * (target_size_bytes - len(rom)))

        # Determine LoROM vs HiROM header offset
        header_off = 0x7FC0
        if len(rom) >= 0xFFE0:
            csum_hi, comp_hi = struct.unpack_from("<HH", rom, 0xFFDC)
            if (csum_hi + comp_hi) == 0xFFFF and csum_hi > 0:
                header_off = 0xFFC0

        # Calculate size code: 2^N KB
        kb = target_size_bytes // 1024
        size_code = 7
        while (1 << size_code) < kb:
            size_code += 1

        rom[header_off + 0x17] = size_code

        # Recalculate 16-bit checksum
        total_sum = sum(rom)
        # Exclude old checksum and complement bytes
        old_csum = struct.unpack_from("<H", rom, header_off + 0x1E)[0]
        old_comp = struct.unpack_from("<H", rom, header_off + 0x1C)[0]
        total_sum -= (old_csum & 0xFF) + (old_csum >> 8) + (old_comp & 0xFF) + (old_comp >> 8)

        new_csum = total_sum & 0xFFFF
        new_comp = (~new_csum) & 0xFFFF
        struct.pack_into("<HH", rom, header_off + 0x1C, new_comp, new_csum)

        return rom

    @staticmethod
    def expand_gb(rom: bytearray, target_size_bytes: int) -> bytearray:
        """
        Expand Game Boy / Color ROM to target_size_bytes (e.g. 1MB, 2MB, 4MB).
        Updates ROM size indicator at 0x0148, and recalculates header and global checksums.
        """
        if target_size_bytes <= len(rom):
            return rom

        rom.extend(b"\x00" * (target_size_bytes - len(rom)))

        # ROM size mapping (32KB << N)
        size_code = 0
        sz = 32 * 1024
        while sz < target_size_bytes:
            sz <<= 1
            size_code += 1

        rom[0x0148] = size_code

        # Header checksum at 0x014D: -(sum(0x0134..0x014C) + 1)
        h_csum = 0
        for b in rom[0x0134:0x014D]:
            h_csum = (h_csum - b - 1) & 0xFF
        rom[0x014D] = h_csum

        # Global 16-bit checksum at 0x014E..0x014F
        rom[0x014E] = 0
        rom[0x014F] = 0
        g_csum = sum(rom) & 0xFFFF
        struct.pack_into(">H", rom, 0x014E, g_csum)

        return rom

    @staticmethod
    def expand_gba(rom: bytearray, target_size_bytes: int) -> bytearray:
        """
        Expand Game Boy Advance ROM up to 32MB (0x02000000), padding with 0xFF.
        """
        if target_size_bytes <= len(rom):
            return rom

        rom.extend(b"\xFF" * (target_size_bytes - len(rom)))
        return rom


@dataclass
class AllocatedItem(MioRomResult):
    key: Any
    bank: int
    offset_in_bank: int
    pointer_bytes: bytes
    size: int


class FarPointerRelocator:
    """
    Multi-Bank Far-Pointer and Script Relocation Engine.
    Allocates expanded text and binary payloads across multiple banking boundaries
    (SNES 24-bit bank:offset, GB MBC banking, GBA linear 32-bit), preventing bank overflows
    and generating ready-to-write pointer tables.
    """

    def __init__(
        self,
        bank_size: int = 0x8000,
        base_bank: int = 0,
        bank_ram_base: int = 0x8000,
        pointer_format: str = "snes_24",
    ):
        self.bank_size = bank_size
        self.base_bank = base_bank
        self.bank_ram_base = bank_ram_base
        self.pointer_format = pointer_format.lower()

    def allocate(
        self,
        items: List[Tuple[Any, bytes]],
    ) -> List[AllocatedItem]:
        """
        Pack items into consecutive banks without crossing bank boundaries.
        Returns list of AllocatedItem.
        """
        allocated: List[AllocatedItem] = []
        current_bank = self.base_bank
        current_offset = 0

        for key, data in items:
            item_len = len(data)
            if item_len > self.bank_size:
                raise ParseError(
                    f"Item '{key}' with size {item_len} bytes exceeds maximum bank size {self.bank_size}."
                )

            # Check if item fits in current bank
            if current_offset + item_len > self.bank_size:
                current_bank += 1
                current_offset = 0

            # Compute pointer bytes
            ptr_bytes = self._format_pointer(current_bank, current_offset)

            allocated.append(
                AllocatedItem(
                    key=key,
                    bank=current_bank,
                    offset_in_bank=current_offset,
                    pointer_bytes=ptr_bytes,
                    size=item_len,
                )
            )

            current_offset += item_len

        return allocated

    def _format_pointer(self, bank: int, offset_in_bank: int) -> bytes:
        ram_addr = self.bank_ram_base + offset_in_bank

        if self.pointer_format == "snes_24":
            # 3 bytes Little-Endian: (ram_addr & 0xFFFF) | (bank << 16)
            low_word = ram_addr & 0xFFFF
            return struct.pack("<HB", low_word, bank & 0xFF)

        elif self.pointer_format == "linear_32":
            # 4 bytes Little-Endian
            linear_addr = ram_addr + (bank * self.bank_size)
            return struct.pack("<I", linear_addr)

        elif self.pointer_format == "offset_16":
            # 2 bytes Little-Endian
            return struct.pack("<H", ram_addr & 0xFFFF)

        elif self.pointer_format == "gb_bank":
            # 1 byte bank, 2 bytes offset LE
            return struct.pack("<BH", bank & 0xFF, ram_addr & 0xFFFF)

        else:
            raise RelocationError(f"Unknown pointer format: '{self.pointer_format}'")

    def build_bank_buffers(
        self,
        items: List[Tuple[Any, bytes]],
    ) -> Tuple[bytes, Dict[int, bytearray]]:
        """
        Allocate items, return pointer table binary and dictionary of {bank_number: bank_bytes}.
        """
        allocated = self.allocate(items)
        pointer_table = bytearray()
        bank_buffers: Dict[int, bytearray] = {}

        for alloc, (_, data) in zip(allocated, items):
            pointer_table.extend(alloc.pointer_bytes)

            if alloc.bank not in bank_buffers:
                bank_buffers[alloc.bank] = bytearray(self.bank_size)

            b_buf = bank_buffers[alloc.bank]
            b_buf[alloc.offset_in_bank:alloc.offset_in_bank + len(data)] = data

        return bytes(pointer_table), bank_buffers
