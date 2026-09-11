"""
miorom.platforms.sega_disc
~~~~~~~~~~~~~~~~~~~~~~~~~~
Sega Saturn and Sega Dreamcast optical disc bootstrap headers and GDI descriptor parser.

Supports Saturn 512-byte security boot sectors, Dreamcast IP.BIN bootstrap headers,
region-free unlocking, and GD-ROM GDI multi-track sheet descriptors.
"""

from __future__ import annotations

import io
import os
import struct
from dataclasses import dataclass
from typing import List, Optional, Union

from miorom.errors import ParseError
from miorom.result import MioRomResult


SATURN_MAGIC = b"SEGA SEGASATURN "
DREAMCAST_MAGIC = b"SEGA SEGAKATANA "


class SaturnDiscHeader(MioRomResult):
    """
    Sega Saturn disc bootstrap security header (Sector 0, 512 bytes).
    Controls system initialization, hardware verification, area symbols, and boot filename.
    """

    def __init__(
        self,
        hardware_id: str = "SEGA SEGASATURN ",
        maker_id: str = "SEGA ENTERPRISES",
        device_info: str = "CD-1/1",
        area_symbols: str = "JUE",
        peripherals: str = "JTKB",
        title: str = "UNTITLED SATURN GAME",
        product_number: str = "GS-9000",
        version: str = "V1.000",
        release_date: str = "19950101",
        boot_file: str = "0.BIN",
        software_code: str = "",
        raw_header: Optional[bytes] = None,
    ):
        self.hardware_id = hardware_id
        self.maker_id = maker_id
        self.device_info = device_info
        self.area_symbols = area_symbols
        self.peripherals = peripherals
        self.title = title
        self.product_number = product_number
        self.version = version
        self.release_date = release_date
        self.boot_file = boot_file
        self.software_code = software_code
        self._raw_tail = raw_header[0x100:512] if raw_header and len(raw_header) >= 512 else (b"\x00" * 256)

    @classmethod
    def from_bytes(cls, data: bytes) -> "SaturnDiscHeader":
        """Parses Saturn 512-byte disc header."""
        if len(data) < 256:
            raise ParseError("Data too small for Sega Saturn disc header (minimum 256 bytes).")

        magic = data[:16]
        if magic != SATURN_MAGIC:
            raise ParseError(f"Invalid Sega Saturn header magic: {magic!r}, expected {SATURN_MAGIC!r}")

        def get_ascii(start: int, length: int) -> str:
            return data[start : start + length].decode("latin-1", errors="replace").strip("\x00 ").strip()

        return cls(
            hardware_id=data[0:16].decode("latin-1", errors="replace"),
            maker_id=get_ascii(0x10, 16),
            device_info=get_ascii(0x20, 16),
            area_symbols=get_ascii(0x30, 10),
            peripherals=get_ascii(0x40, 10),
            title=get_ascii(0x50, 112),
            product_number=get_ascii(0xC0, 10),
            version=get_ascii(0xCA, 6),
            release_date=get_ascii(0xD0, 8),
            boot_file=get_ascii(0xD8, 16),
            software_code=get_ascii(0xE8, 24),
            raw_header=data,
        )

    @classmethod
    def from_file(cls, path: str) -> "SaturnDiscHeader":
        with open(path, "rb") as f:
            return cls.from_bytes(f.read(512))

    @property
    def is_region_free(self) -> bool:
        """Returns True if the disc permits execution across Japan, US, and European hardware."""
        symbols = self.area_symbols.upper()
        return ("J" in symbols) and ("U" in symbols) and ("E" in symbols)

    def make_region_free(self):
        """Unlocks all worldwide region symbols (JTUEKABL)."""
        self.area_symbols = "JTUEKABL"

    def to_bytes(self) -> bytes:
        """Serializes header to standard 512-byte Saturn bootstrap sector."""
        buf = bytearray(512)

        def put_str(start: int, length: int, val: str):
            encoded = val.encode("latin-1", errors="replace")[:length]
            padded = encoded.ljust(length, b" ")
            buf[start : start + length] = padded

        buf[0:16] = SATURN_MAGIC
        put_str(0x10, 16, self.maker_id)
        put_str(0x20, 16, self.device_info)
        put_str(0x30, 10, self.area_symbols)
        put_str(0x40, 10, self.peripherals)
        put_str(0x50, 112, self.title)
        put_str(0xC0, 10, self.product_number)
        put_str(0xCA, 6, self.version)
        put_str(0xD0, 8, self.release_date)
        put_str(0xD8, 16, self.boot_file)
        put_str(0xE8, 24, self.software_code)

        buf[0x100:512] = self._raw_tail
        return bytes(buf)


class DreamcastIpBin(MioRomResult):
    """
    Sega Dreamcast IP.BIN initial bootstrap sector (Sector 0, 32KB / 0x8000 bytes).
    Contains hardware identifier, country code, peripheral mask, boot filename (1ST_READ.BIN), and CRC16.
    """

    def __init__(
        self,
        hardware_id: str = "SEGA SEGAKATANA ",
        maker_id: str = "SEGA ENTERPRISES",
        device_info: str = "GD-ROM1/1",
        area_symbols: str = "JUE",
        peripherals: str = "0000000",
        product_number: str = "HDR-0001",
        version: str = "V1.000",
        release_date: str = "19990101",
        boot_file: str = "1ST_READ.BIN",
        software_company: str = "SEGA ENTERPRISES",
        title: str = "UNTITLED DREAMCAST GAME",
        crc: int = 0,
        raw_payload: Optional[bytes] = None,
    ):
        self.hardware_id = hardware_id
        self.maker_id = maker_id
        self.device_info = device_info
        self.area_symbols = area_symbols
        self.peripherals = peripherals
        self.product_number = product_number
        self.version = version
        self.release_date = release_date
        self.boot_file = boot_file
        self.software_company = software_company
        self.title = title
        self.crc = crc
        self._raw_tail = raw_payload[0x100:0x8000] if raw_payload and len(raw_payload) >= 0x8000 else (b"\x00" * 0x7F00)

    @classmethod
    def from_bytes(cls, data: bytes) -> "DreamcastIpBin":
        """Parses Dreamcast IP.BIN bootstrap sector."""
        if len(data) < 256:
            raise ParseError("Data too small for Dreamcast IP.BIN header (minimum 256 bytes).")

        magic = data[:16]
        if magic != DREAMCAST_MAGIC:
            raise ParseError(f"Invalid Dreamcast IP.BIN magic: {magic!r}, expected {DREAMCAST_MAGIC!r}")

        def get_ascii(start: int, length: int) -> str:
            return data[start : start + length].decode("latin-1", errors="replace").strip("\x00 ").strip()

        crc = struct.unpack_from("<H", data, 0x20)[0]

        return cls(
            hardware_id=data[0:16].decode("latin-1", errors="replace"),
            maker_id=get_ascii(0x10, 16),
            crc=crc,
            device_info=get_ascii(0x22, 6),
            area_symbols=get_ascii(0x28, 8),
            peripherals=get_ascii(0x30, 8),
            product_number=get_ascii(0x40, 10),
            version=get_ascii(0x4A, 6),
            release_date=get_ascii(0x50, 8),
            boot_file=get_ascii(0x60, 16),
            software_company=get_ascii(0x70, 32),
            title=get_ascii(0x80, 128),
            raw_payload=data,
        )

    @classmethod
    def from_file(cls, path: str) -> "DreamcastIpBin":
        with open(path, "rb") as f:
            return cls.from_bytes(f.read(0x8000))

    @property
    def is_region_free(self) -> bool:
        symbols = self.area_symbols.upper()
        return ("J" in symbols) and ("U" in symbols) and ("E" in symbols)

    def make_region_free(self):
        """Sets area symbols to worldwide region free (JUE)."""
        self.area_symbols = "JUE"

    def calculate_crc(self) -> int:
        """Calculates standard 16-bit CRC checksum over IP.BIN header."""
        buf = self.to_bytes()
        crc = 0xFFFF
        for i in range(0x40, 0x100):
            byte = buf[i]
            crc ^= (byte << 8)
            for _ in range(8):
                if crc & 0x8000:
                    crc = ((crc << 1) ^ 0x1021) & 0xFFFF
                else:
                    crc = (crc << 1) & 0xFFFF
        return crc

    def to_bytes(self) -> bytes:
        """Serializes IP.BIN to standard 32KB (0x8000) binary sector."""
        buf = bytearray(0x8000)

        def put_str(start: int, length: int, val: str):
            encoded = val.encode("latin-1", errors="replace")[:length]
            padded = encoded.ljust(length, b" ")
            buf[start : start + length] = padded

        buf[0:16] = DREAMCAST_MAGIC
        put_str(0x10, 16, self.maker_id)
        struct.pack_into("<H", buf, 0x20, self.crc)
        put_str(0x22, 6, self.device_info)
        put_str(0x28, 8, self.area_symbols)
        put_str(0x30, 8, self.peripherals)
        put_str(0x40, 10, self.product_number)
        put_str(0x4A, 6, self.version)
        put_str(0x50, 8, self.release_date)
        put_str(0x60, 16, self.boot_file)
        put_str(0x70, 32, self.software_company)
        put_str(0x80, 128, self.title)

        buf[0x100:0x8000] = self._raw_tail
        return bytes(buf)


@dataclass
class GDITrack:
    """Descriptor for a single track within a Dreamcast GDI sheet."""
    track_number: int
    start_lba: int
    track_type: int
    sector_size: int
    filename: str
    offset: int = 0


class GDISheet(MioRomResult):
    """
    Parser and builder for Dreamcast GD-ROM descriptor sheets (disc.gdi).
    """

    def __init__(self, tracks: Optional[List[GDITrack]] = None):
        self.tracks: List[GDITrack] = list(tracks) if tracks else []

    @classmethod
    def from_text(cls, text: str) -> "GDISheet":
        """Parses GDI descriptor text."""
        lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
        if not lines:
            raise ParseError("Empty GDI sheet.")

        try:
            total_tracks = int(lines[0])
        except ValueError:
            raise ParseError(f"Invalid GDI track count header: {lines[0]!r}")

        tracks: List[GDITrack] = []
        for line in lines[1:]:
            parts = line.split()
            if len(parts) < 5:
                continue
            trk_num = int(parts[0])
            start_lba = int(parts[1])
            trk_type = int(parts[2])
            sec_size = int(parts[3])
            filename = parts[4].strip('"')
            offset = int(parts[5]) if len(parts) >= 6 else 0

            tracks.append(GDITrack(
                track_number=trk_num,
                start_lba=start_lba,
                track_type=trk_type,
                sector_size=sec_size,
                filename=filename,
                offset=offset,
            ))

        return cls(tracks)

    @classmethod
    def from_file(cls, path: str) -> "GDISheet":
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return cls.from_text(f.read())

    @property
    def high_density_track(self) -> Optional[GDITrack]:
        """Returns the primary high-density game data track (typically track 3 at LBA 45000)."""
        for trk in self.tracks:
            if trk.start_lba >= 45000:
                return trk
        return self.tracks[2] if len(self.tracks) >= 3 else None

    def to_text(self) -> str:
        """Formats tracks into standard GDI descriptor sheet string."""
        lines = [str(len(self.tracks))]
        for trk in self.tracks:
            lines.append(
                f"{trk.track_number} {trk.start_lba} {trk.track_type} {trk.sector_size} {trk.filename} {trk.offset}"
            )
        return "\n".join(lines) + "\n"

    def save(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_text())
