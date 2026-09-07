import os
import struct
from dataclasses import dataclass
from typing import Optional, Tuple


def is_smd(data: bytes) -> bool:
    """Check if binary data is in Super Magic Drive (.smd) interleaved format."""
    if len(data) < 512:
        return False
    # SMD header has block count and magic bytes 0xAA 0xBB at offset 8, 9
    return data[8] == 0xAA and data[9] == 0xBB and ((len(data) - 512) % 16384 == 0)


def deinterleave_smd(data: bytes) -> bytes:
    """
    De-interleave a Super Magic Drive (.smd) format ROM into standard flat binary (.bin/.md).
    Strips the 512-byte header and merges even/odd 8KB blocks.
    """
    payload = data[512:] if is_smd(data) else data
    block_size = 16384
    half_block = 8192
    num_blocks = len(payload) // block_size

    out = bytearray(len(payload))

    for b in range(num_blocks):
        src_offset = b * block_size
        dst_offset = b * block_size

        first_half = payload[src_offset:src_offset + half_block]
        second_half = payload[src_offset + half_block:src_offset + block_size]

        # In SMD format, first 8K is even bytes, second 8K is odd bytes
        out[dst_offset:dst_offset + block_size:2] = first_half
        out[dst_offset + 1:dst_offset + block_size:2] = second_half

    return bytes(out)


def interleave_smd(data: bytes) -> bytes:
    """Interleave flat ROM binary into Super Magic Drive (.smd) format with 512-byte header."""
    block_size = 16384
    half_block = 8192
    aligned_len = len(data) - (len(data) % block_size)
    num_blocks = aligned_len // block_size

    smd_header = bytearray(512)
    smd_header[0] = num_blocks & 0xFF
    smd_header[1] = (num_blocks >> 8) & 0xFF
    smd_header[8] = 0xAA
    smd_header[9] = 0xBB

    out = bytearray(smd_header)

    for b in range(num_blocks):
        src_offset = b * block_size
        chunk = data[src_offset:src_offset + block_size]

        even_bytes = chunk[0::2]
        odd_bytes = chunk[1::2]

        out.extend(even_bytes)
        out.extend(odd_bytes)

    return bytes(out)


def calculate_md_checksum(rom_bytes: bytes) -> int:
    """
    Calculate the Sega Mega Drive / Genesis 16-bit header checksum.
    The checksum is the 16-bit big-endian sum of all 16-bit words from offset 0x0200
    to the end of the ROM.
    """
    if len(rom_bytes) <= 0x0200:
        return 0
    aligned_len = len(rom_bytes) - (len(rom_bytes) % 2)
    words_count = (aligned_len - 0x0200) // 2
    words = struct.unpack_from(f">{words_count}H", rom_bytes, 0x0200)
    return sum(words) & 0xFFFF


def verify_md_checksum(rom_bytes: bytes) -> bool:
    """Verify ROM header checksum at offset 0x018E against calculated value."""
    if len(rom_bytes) < 0x0190:
        return False
    expected = struct.unpack_from(">H", rom_bytes, 0x018E)[0]
    actual = calculate_md_checksum(rom_bytes)
    return expected == actual


def fix_md_checksum(rom_bytes: bytes) -> bytes:
    """Recalculate Mega Drive checksum and patch offset 0x018E..0x0190."""
    checksum = calculate_md_checksum(rom_bytes)
    ba = bytearray(rom_bytes)
    struct.pack_into(">H", ba, 0x018E, checksum)
    return bytes(ba)


@dataclass
class MDHeader:
    system_type: str
    copyright: str
    domestic_title: str
    overseas_title: str
    serial_number: str
    checksum: int
    io_support: str
    rom_start: int
    rom_end: int
    ram_start: int
    ram_end: int
    sram_support: bool
    region: str

    @classmethod
    def parse(cls, header_bytes: bytes) -> "MDHeader":
        """Parse 256-byte Mega Drive header at offset 0x0100..0x0200."""
        if len(header_bytes) < 0x0100:
            header_bytes = header_bytes.ljust(0x0100, b"\x00")

        system_type = header_bytes[0x00:0x10].decode("ascii", errors="replace").strip()
        copyright_str = header_bytes[0x10:0x20].decode("ascii", errors="replace").strip()
        domestic_title = header_bytes[0x20:0x50].decode("shift-jis", errors="replace").strip()
        overseas_title = header_bytes[0x50:0x80].decode("ascii", errors="replace").strip()
        serial_number = header_bytes[0x80:0x8E].decode("ascii", errors="replace").strip()
        checksum = struct.unpack_from(">H", header_bytes, 0x8E)[0]
        io_support = header_bytes[0x90:0xA0].decode("ascii", errors="replace").strip()

        rom_start, rom_end, ram_start, ram_end = struct.unpack_from(">IIII", header_bytes, 0xA0)
        sram_support = header_bytes[0xB0:0xB2] == b"RA"
        region = header_bytes[0xF0:0x100].decode("ascii", errors="replace").strip()

        return cls(
            system_type=system_type,
            copyright=copyright_str,
            domestic_title=domestic_title,
            overseas_title=overseas_title,
            serial_number=serial_number,
            checksum=checksum,
            io_support=io_support,
            rom_start=rom_start,
            rom_end=rom_end,
            ram_start=ram_start,
            ram_end=ram_end,
            sram_support=sram_support,
            region=region,
        )

    def pack(self) -> bytes:
        """Serialize header into 256-byte buffer."""
        out = bytearray(0x0100)
        out[0x00:0x10] = self.system_type.encode("ascii", errors="replace")[:16].ljust(16, b" ")
        out[0x10:0x20] = self.copyright.encode("ascii", errors="replace")[:16].ljust(16, b" ")
        out[0x20:0x50] = self.domestic_title.encode("shift-jis", errors="replace")[:48].ljust(48, b" ")
        out[0x50:0x80] = self.overseas_title.encode("ascii", errors="replace")[:48].ljust(48, b" ")
        out[0x80:0x8E] = self.serial_number.encode("ascii", errors="replace")[:14].ljust(14, b" ")
        struct.pack_into(">H", out, 0x8E, self.checksum)
        out[0x90:0xA0] = self.io_support.encode("ascii", errors="replace")[:16].ljust(16, b" ")
        struct.pack_into(">IIII", out, 0xA0, self.rom_start, self.rom_end, self.ram_start, self.ram_end)
        if self.sram_support:
            out[0xB0:0xB2] = b"RA"
        out[0xF0:0x100] = self.region.encode("ascii", errors="replace")[:16].ljust(16, b" ")
        return bytes(out)


class MDRom:
    """
    Sega Mega Drive / Genesis ROM inspector, SMD converter, and checksum fixer.
    """

    def __init__(self, data: bytes, filepath: Optional[str] = None):
        self.filepath = filepath
        self.was_smd = is_smd(data)
        # De-interleave if SMD
        self.data: bytearray = bytearray(deinterleave_smd(data) if self.was_smd else data)

        raw_header = self.data[0x0100:0x0200] if len(self.data) >= 0x0200 else bytes(0x0100)
        self.header: MDHeader = MDHeader.parse(raw_header)

    @classmethod
    def from_file(cls, filepath: str) -> "MDRom":
        with open(filepath, "rb") as f:
            data = f.read()
        return cls(data, filepath=filepath)

    def verify_checksum(self) -> bool:
        """Verify whether the header checksum matches calculated ROM word sum."""
        return verify_md_checksum(bytes(self.data))

    def recalculate_checksum(self) -> int:
        """Recalculate checksum, update header, and return new 16-bit checksum."""
        checksum = calculate_md_checksum(bytes(self.data))
        self.header.checksum = checksum
        struct.pack_into(">H", self.data, 0x018E, checksum)
        return checksum

    def to_bytes(self, smd_format: bool = False) -> bytes:
        """Export ROM as flat binary (.bin/.md) or interleaved SMD (.smd)."""
        hdr_bytes = self.header.pack()
        self.data[0x0100:0x0200] = hdr_bytes
        raw = bytes(self.data)
        return interleave_smd(raw) if smd_format else raw

    def save(self, output_path: str, smd_format: Optional[bool] = None):
        """Save ROM to disk, automatically selecting format based on extension if not specified."""
        if smd_format is None:
            smd_format = output_path.lower().endswith(".smd")
        out_bytes = self.to_bytes(smd_format=smd_format)
        with open(output_path, "wb") as f:
            f.write(out_bytes)
