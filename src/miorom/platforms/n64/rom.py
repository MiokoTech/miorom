from miorom.result import MioRomResult
import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple, Union

from miorom.core.schema import BinaryStruct, FixedString, RawBytes, U32, U8
from miorom.platforms.n64.checksum import (
    N64CIC,
    calculate_n64_checksum,
    detect_cic,
    fix_n64_checksum,
    verify_n64_checksum,
)


class N64HeaderStruct(BinaryStruct):
    _endian = ">"
    magic = RawBytes(4)
    clock_rate = U32()
    entrypoint = U32()
    release_addr = U32()
    crc1 = U32()
    crc2 = U32()
    _reserved_0x18 = RawBytes(8)
    title = FixedString(20, pad=b" ")
    _reserved_0x34 = RawBytes(7)
    media_format_code = U8()
    game_code = FixedString(2, pad=b" ")
    country_code = FixedString(1)
    version = U8()


class N64ByteOrder(Enum):
    BIG_ENDIAN = "z64"       # Native N64 (0x80371240)
    BYTE_SWAPPED = "v64"     # Doctor V64 (0x37804012)
    LITTLE_ENDIAN = "n64"    # CD64 / PC (0x40123780)
    UNKNOWN = "unknown"


def detect_byte_order(data: bytes) -> N64ByteOrder:
    """Detect the byte ordering format of an N64 ROM image."""
    if len(data) < 4:
        return N64ByteOrder.UNKNOWN
    magic = data[:4]
    if magic == b"\x80\x37\x12\x40":
        return N64ByteOrder.BIG_ENDIAN
    elif magic == b"\x37\x80\x40\x12":
        return N64ByteOrder.BYTE_SWAPPED
    elif magic == b"\x40\x12\x37\x80":
        return N64ByteOrder.LITTLE_ENDIAN
    return N64ByteOrder.UNKNOWN


def swap_to_big_endian(data: bytes, source_order: Optional[N64ByteOrder] = None) -> bytes:
    """Convert ROM bytes from any endianness format to native Big-Endian (.z64)."""
    if source_order is None:
        source_order = detect_byte_order(data)

    if source_order == N64ByteOrder.BIG_ENDIAN:
        return data

    if source_order == N64ByteOrder.BYTE_SWAPPED:
        # 16-bit word byte-swap
        aligned_len = len(data) - (len(data) % 2)
        ba = bytearray(aligned_len)
        ba[0::2] = data[1:aligned_len:2]
        ba[1::2] = data[0:aligned_len:2]
        if len(data) > aligned_len:
            ba.extend(data[aligned_len:])
        return bytes(ba)

    elif source_order == N64ByteOrder.LITTLE_ENDIAN:
        # 32-bit dword byte-swap
        aligned_len = len(data) - (len(data) % 4)
        ba = bytearray(aligned_len)
        ba[0::4] = data[3:aligned_len:4]
        ba[1::4] = data[2:aligned_len:4]
        ba[2::4] = data[1:aligned_len:4]
        ba[3::4] = data[0:aligned_len:4]
        if len(data) > aligned_len:
            ba.extend(data[aligned_len:])
        return bytes(ba)

    return data


def swap_from_big_endian(data: bytes, target_order: N64ByteOrder) -> bytes:
    """Convert Big-Endian (.z64) ROM bytes to target byte order format."""
    if target_order == N64ByteOrder.BIG_ENDIAN:
        return data

    if target_order == N64ByteOrder.BYTE_SWAPPED:
        aligned_len = len(data) - (len(data) % 2)
        ba = bytearray(aligned_len)
        ba[0::2] = data[1:aligned_len:2]
        ba[1::2] = data[0:aligned_len:2]
        if len(data) > aligned_len:
            ba.extend(data[aligned_len:])
        return bytes(ba)

    elif target_order == N64ByteOrder.LITTLE_ENDIAN:
        aligned_len = len(data) - (len(data) % 4)
        ba = bytearray(aligned_len)
        ba[0::4] = data[3:aligned_len:4]
        ba[1::4] = data[2:aligned_len:4]
        ba[2::4] = data[1:aligned_len:4]
        ba[3::4] = data[0:aligned_len:4]
        if len(data) > aligned_len:
            ba.extend(data[aligned_len:])
        return bytes(ba)

    return data


@dataclass
class N64Header(MioRomResult):
    clock_rate: int
    entrypoint: int
    release_addr: int
    crc1: int
    crc2: int
    title: str
    media_format: str
    game_code: str
    country_code: str
    version: int

    @classmethod
    def parse(cls, header_bytes: bytes) -> "N64Header":
        """Parse 64-byte Big-Endian N64 ROM header."""
        if len(header_bytes) < 0x40:
            header_bytes = header_bytes.ljust(0x40, b"\x00")

        parsed = N64HeaderStruct.from_bytes(header_bytes)
        media_format = chr(parsed.media_format_code) if 32 <= parsed.media_format_code <= 126 else "?"
        country_code = parsed.country_code if parsed.country_code.isprintable() else "?"

        return cls(
            clock_rate=parsed.clock_rate,
            entrypoint=parsed.entrypoint,
            release_addr=parsed.release_addr,
            crc1=parsed.crc1,
            crc2=parsed.crc2,
            title=parsed.title.strip(),
            media_format=media_format,
            game_code=parsed.game_code.strip(),
            country_code=country_code,
            version=parsed.version,
        )

    def pack(self) -> bytes:
        """Serialize header into 64-byte big-endian buffer."""
        parsed = N64HeaderStruct(
            magic=b"\x80\x37\x12\x40",
            clock_rate=self.clock_rate,
            entrypoint=self.entrypoint,
            release_addr=self.release_addr,
            crc1=self.crc1,
            crc2=self.crc2,
            title=self.title,
            media_format_code=ord(self.media_format[0]) if self.media_format else ord("N"),
            game_code=self.game_code,
            country_code=self.country_code[0] if self.country_code else "E",
            version=self.version & 0xFF,
        )
        return parsed.to_bytes()


class N64Rom:
    """
    Nintendo 64 ROM file inspector, endianness converter, and checksum manipulator.
    Internally normalizes data to Big-Endian (.z64) format.
    """

    def __init__(self, data: bytes, filepath: Optional[str] = None):
        self.filepath = filepath
        self.original_byte_order = detect_byte_order(data)
        # Normalize internal buffer to native Big-Endian
        self.data: bytearray = bytearray(swap_to_big_endian(data, self.original_byte_order))
        self._header_struct = N64HeaderStruct.from_bytes(self.data, offset=0)
        self.header: N64Header = N64Header.parse(bytes(self.data[:0x40]))
        self.cic: Optional[N64CIC] = detect_cic(bytes(self.data))

    @classmethod
    def from_file(cls, filepath: str) -> "N64Rom":
        with open(filepath, "rb") as f:
            data = f.read()
        return cls(data, filepath=filepath)

    def verify_checksum(self) -> bool:
        """Verify ROM header checksum against IPL3 calculation."""
        return verify_n64_checksum(bytes(self.data), self.cic)

    def recalculate_checksum(self, preserve_database_crc: bool = False) -> Tuple[int, int]:
        """
        Recalculate checksum and update ROM header.
        If preserve_database_crc=True, preserves original header CRC for emulator database matching.
        """
        if preserve_database_crc:
            return self.header.crc1, self.header.crc2
        crc1, crc2 = calculate_n64_checksum(bytes(self.data), self.cic)
        self.header.crc1 = crc1
        self.header.crc2 = crc2
        self._header_struct.crc1 = crc1
        self._header_struct.crc2 = crc2
        self.data[0x10:0x18] = self._header_struct.to_bytes()[0x10:0x18]
        return crc1, crc2

    def to_bytes(self, target_order: N64ByteOrder = N64ByteOrder.BIG_ENDIAN) -> bytes:
        """Export ROM in requested byte order (.z64, .v64, .n64)."""
        # Ensure header changes are synchronized to data
        hdr_bytes = self.header.pack()
        self.data[:0x40] = hdr_bytes
        return swap_from_big_endian(bytes(self.data), target_order)

    def save(self, output_path: str, target_order: Optional[N64ByteOrder] = None):
        """Save ROM to disk with optional byte order conversion."""
        if target_order is None:
            ext = os.path.splitext(output_path)[1].lower()
            if ext == ".v64":
                target_order = N64ByteOrder.BYTE_SWAPPED
            elif ext == ".n64":
                target_order = N64ByteOrder.LITTLE_ENDIAN
            else:
                target_order = N64ByteOrder.BIG_ENDIAN

        out_data = self.to_bytes(target_order)
        with open(output_path, "wb") as f:
            f.write(out_data)
