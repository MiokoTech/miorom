import struct
from typing import Optional, Tuple


class SNESRom:
    """
    Super Nintendo Entertainment System (SNES/SFC) ROM handler.
    Supports LoROM, HiROM, ExHiROM auto-detection, SMC header stripping/adding,
    and internal checksum calculation & fixing.
    """

    SMC_HEADER_SIZE = 512

    def __init__(self, data: bytes):
        self.data = bytearray(data)
        self.has_smc = (len(self.data) % 1024) == self.SMC_HEADER_SIZE
        self.header_offset = self._detect_header_offset()

    @classmethod
    def from_file(cls, path: str) -> "SNESRom":
        with open(path, "rb") as f:
            return cls(f.read())

    def strip_smc_header(self) -> bool:
        """Removes the 512-byte copier header if present. Returns True if removed."""
        if self.has_smc:
            self.data = self.data[self.SMC_HEADER_SIZE:]
            self.has_smc = False
            self.header_offset = self._detect_header_offset()
            return True
        return False

    def add_smc_header(self) -> bool:
        """Prepends a 512-byte zeroed copier header if not already present."""
        if not self.has_smc:
            self.data = bytearray(self.SMC_HEADER_SIZE) + self.data
            self.has_smc = True
            self.header_offset = self._detect_header_offset()
            return True
        return False

    def _score_header(self, offset: int) -> int:
        if offset + 0x30 > len(self.data):
            return -1

        score = 0
        comp, chk = struct.unpack_from("<HH", self.data, offset + 0x1C)
        if (comp ^ chk) == 0xFFFF and chk != 0:
            score += 100

        # Title printable characters check (offset to offset + 21)
        title_bytes = self.data[offset : offset + 21]
        printable = sum(1 for b in title_bytes if 0x20 <= b <= 0x7E)
        score += printable

        # Valid map modes (0x20, 0x21, 0x25, 0x30, 0x31, 0x35)
        map_mode = self.data[offset + 0x15] & 0xEF  # ignore FastROM bit
        if map_mode in (0x20, 0x21, 0x25, 0x30, 0x31, 0x35):
            score += 20

        # Valid ROM sizes (0x07 = 128KB to 0x0D = 8MB)
        rom_size = self.data[offset + 0x17]
        if 0x07 <= rom_size <= 0x0E:
            score += 10

        return score

    def _detect_header_offset(self) -> int:
        base = self.SMC_HEADER_SIZE if self.has_smc else 0
        lorom_off = base + 0x7FC0
        hirom_off = base + 0xFFC0
        exhirom_off = base + 0x40FFC0

        scores = [
            (lorom_off, self._score_header(lorom_off)),
            (hirom_off, self._score_header(hirom_off)),
            (exhirom_off, self._score_header(exhirom_off)),
        ]
        best_off, best_score = max(scores, key=lambda x: x[1])
        if best_score <= 0:
            # Default to LoROM
            return lorom_off
        return best_off

    @property
    def mapping_type(self) -> str:
        base = self.SMC_HEADER_SIZE if self.has_smc else 0
        rel_off = self.header_offset - base
        if rel_off == 0x7FC0:
            return "LoROM"
        elif rel_off == 0xFFC0:
            return "HiROM"
        elif rel_off == 0x40FFC0:
            return "ExHiROM"
        return "Unknown"

    @property
    def title(self) -> str:
        raw = self.data[self.header_offset : self.header_offset + 21]
        return raw.decode("latin1", errors="replace").strip()

    @title.setter
    def title(self, value: str):
        encoded = value.encode("latin1", errors="replace")[:21].ljust(21, b" ")
        self.data[self.header_offset : self.header_offset + 21] = encoded

    @property
    def rom_checksum(self) -> int:
        return struct.unpack_from("<H", self.data, self.header_offset + 0x1E)[0]

    @property
    def checksum_complement(self) -> int:
        return struct.unpack_from("<H", self.data, self.header_offset + 0x1C)[0]

    def is_checksum_valid(self) -> bool:
        comp, chk = self.checksum_complement, self.rom_checksum
        return (comp ^ chk) == 0xFFFF and chk == self.calculate_checksum()

    def calculate_checksum(self) -> int:
        """
        Calculates 16-bit SNES ROM checksum.
        Mirroring non-power-of-two ROM sizes (e.g. 24Mbit).
        Note: The complement and checksum fields in header always sum to 0x1FE.
        """
        rom_data = bytearray(self.data[self.SMC_HEADER_SIZE:] if self.has_smc else self.data)
        size = len(rom_data)
        if size == 0:
            return 0

        # Temporarily zero out complement and checksum bytes in calculation
        base_off = self.header_offset - (self.SMC_HEADER_SIZE if self.has_smc else 0)
        if base_off + 0x20 <= size:
            rom_data[base_off + 0x1C : base_off + 0x20] = b"\x00\x00\x00\x00"

        # Find closest power of 2
        p2 = 1
        while p2 * 2 <= size:
            p2 *= 2

        chk = sum(rom_data[:p2])

        # If remainder exists, mirror it
        remainder = size - p2
        if remainder > 0:
            rem_data = rom_data[p2:size]
            mult = p2 // remainder
            chk += sum(rem_data) * mult

        # Add invariant 0x1FE (sum of 4 bytes: complement_lo + complement_hi + checksum_lo + checksum_hi)
        return (chk + 0x1FE) & 0xFFFF

    def fix_checksum(self):
        """Calculates and writes the correct checksum and complement into the ROM header."""
        chk = self.calculate_checksum()
        comp = chk ^ 0xFFFF
        struct.pack_into("<HH", self.data, self.header_offset + 0x1C, comp, chk)

    def to_bytes(self) -> bytes:
        return bytes(self.data)
