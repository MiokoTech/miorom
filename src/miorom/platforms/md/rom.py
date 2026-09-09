from miorom.result import MioRomResult
import os
from dataclasses import dataclass
from miorom.core.schema import BinaryStruct, FixedString, RawBytes, U8, U16, U32
from typing import Optional, Tuple


class MDChecksumStruct(BinaryStruct):
    _endian = ">"
    _prefix = RawBytes(0x018E)
    checksum = U16()


class MDSmdHeaderStruct(BinaryStruct):
    _endian = "<"
    block_count_low = U8()
    block_count_high = U8()
    _reserved = RawBytes(6)
    magic = RawBytes(2)


def is_smd(data: bytes) -> bool:
    """Check if binary data is in Super Magic Drive (.smd) interleaved format."""
    if len(data) < 512:
        return False
    # SMD header has block count and magic bytes 0xAA 0xBB at offset 8, 9
    if len(data) < MDSmdHeaderStruct.sizeof():
        return False
    magic = MDSmdHeaderStruct.from_bytes(data).magic
    return magic == b"\xAA\xBB" and ((len(data) - 512) % 16384 == 0)


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
    checksum = 0
    for offset in range(0x0200, aligned_len, 2):
        checksum += U16(default=0, endian=">").unpack(rom_bytes, offset, ">")[0]
    return checksum & 0xFFFF


def verify_md_checksum(rom_bytes: bytes) -> bool:
    """Verify ROM header checksum at offset 0x018E against calculated value."""
    if len(rom_bytes) < 0x0190:
        return False
    expected = MDChecksumStruct.from_bytes(rom_bytes, offset=0).checksum
    actual = calculate_md_checksum(rom_bytes)
    return expected == actual


def fix_md_checksum(rom_bytes: bytes) -> bytes:
    """Recalculate Mega Drive checksum and patch offset 0x018E..0x0190."""
    checksum = calculate_md_checksum(rom_bytes)
    ba = bytearray(rom_bytes)
    ba[0x018E:0x0190] = MDChecksumStruct(checksum=checksum).to_bytes()[0x018E:]
    return bytes(ba)


class MDHeaderStruct(BinaryStruct):
    _endian = ">"
    system_type = FixedString(16, pad=b" ")
    copyright = FixedString(16, pad=b" ")
    domestic_title = FixedString(48, encoding="shift-jis", pad=b" ")
    overseas_title = FixedString(48, pad=b" ")
    serial_number = FixedString(14, pad=b" ")
    checksum = U16()
    io_support = FixedString(16, pad=b" ")
    rom_start = U32()
    rom_end = U32()
    ram_start = U32()
    ram_end = U32()
    _reserved_0xB0 = RawBytes(0x40)
    region = FixedString(16, pad=b" ")


@dataclass
class MDHeader(MioRomResult):
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
        if len(header_bytes) < 0x0100:
            header_bytes = header_bytes.ljust(0x0100, b"\x00")
        parsed = MDHeaderStruct.from_bytes(header_bytes, offset=0)
        return cls(
            system_type=parsed.system_type.strip(),
            copyright=parsed.copyright.strip(),
            domestic_title=parsed.domestic_title.strip(),
            overseas_title=parsed.overseas_title.strip(),
            serial_number=parsed.serial_number.strip(),
            checksum=parsed.checksum,
            io_support=parsed.io_support.strip(),
            rom_start=parsed.rom_start,
            rom_end=parsed.rom_end,
            ram_start=parsed.ram_start,
            ram_end=parsed.ram_end,
            sram_support=parsed._reserved_0xB0[:2] == b"RA",
            region=parsed.region.strip(),
        )

    def pack(self) -> bytes:
        reserved = bytearray(0x40)
        if self.sram_support:
            reserved[:2] = b"RA"
        return MDHeaderStruct(
            system_type=self.system_type,
            copyright=self.copyright,
            domestic_title=self.domestic_title,
            overseas_title=self.overseas_title,
            serial_number=self.serial_number,
            checksum=self.checksum,
            io_support=self.io_support,
            rom_start=self.rom_start,
            rom_end=self.rom_end,
            ram_start=self.ram_start,
            ram_end=self.ram_end,
            _reserved_0xB0=bytes(reserved),
            region=self.region,
        ).to_bytes()


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
        self.data[0x018E:0x0190] = MDChecksumStruct(checksum=checksum).to_bytes()[0x018E:]
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
