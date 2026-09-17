"""
miorom.platforms.psx.rom
~~~~~~~~~~~~~~~~~~~~~~~~
Unified Sony PlayStation 1 (PS1 / PS-X) ROM & Disc Manager.
Supports 2048-byte/sector Mode 1 ISO disc images and 2352-byte/sector
Mode 2 Form 1 raw CD-ROM BIN images with automated EDC checksum recalculation,
SYSTEM.CNF parsing, executable management, and multi-media asset discovery.
"""

from __future__ import annotations

import os
import re
from enum import Enum
from typing import Dict, List, Optional, Tuple, Union

from miorom.audio.vag import VAGHeader
from miorom.core.schema import (
    U8,
    BinaryStruct,
    pack_into,
)
from miorom.errors import ParseError
from miorom.platforms.cdrom.cue import lba_to_msf
from miorom.platforms.cdrom.disc import (
    SYNC_PATTERN,
    _to_bcd,
    calculate_cdrom_edc,
)
from miorom.platforms.iso.builder import ISOBuilder
from miorom.platforms.iso.iso9660 import ISO9660
from miorom.platforms.psx.exe import PSXExe
from miorom.platforms.psx.str import StrDemuxer
from miorom.platforms.psx.tim import TIMImage

# Standard ISO 9660 PVD Magic
ISO_PVD_MAGIC = b"\x01CD001"


class PSXFormat(str, Enum):
    """Container disc format for PlayStation 1 game images."""

    ISO = "iso"  # 2048 bytes/sector Mode 1 ISO 9660 disc image
    BIN = "bin"  # 2352 bytes/sector Mode 2 Form 1 raw CD-ROM sector image
    BIN_MODE1 = "bin_mode1"  # 2352 bytes/sector Mode 1 raw CD-ROM sector image


class CdSectorHeaderStruct(BinaryStruct):
    """CD-ROM 4-byte sector header (MSF address + Mode)."""

    min = U8()  # BCD Minute
    sec = U8()  # BCD Second
    frame = U8()  # BCD Frame (75 frames/sec)
    mode = U8()  # 0x01 (Mode 1), 0x02 (Mode 2)


class CdSubHeaderStruct(BinaryStruct):
    """CD-ROM XA 8-byte subheader (Mode 2 Form 1/2)."""

    file_num = U8()
    channel = U8()
    submode = U8()  # 0x08 = Form 1, 0x28 = Form 2
    coding = U8()
    file_num_rep = U8()
    channel_rep = U8()
    submode_rep = U8()
    coding_rep = U8()


def resolve_psx_region(game_id: str) -> str:
    """
    Resolves the regional distribution territory from a Sony PlayStation 1 product code prefix.
    """
    clean_id = game_id.upper().replace("-", "").replace("_", "").replace(".", "")
    if clean_id.startswith(("SLUS", "SCUS")):
        return "USA"
    elif clean_id.startswith(("SLES", "SCES")):
        return "EUR"
    elif clean_id.startswith(("SLPS", "SLPM", "SCPS")):
        return "JPN"
    elif clean_id.startswith("SLAJ"):
        return "ASIA"
    return "UNKNOWN"


def _bin_to_iso_bytes(bin_data: bytes) -> bytes:
    """
    Extract 2048-byte sector payloads from a 2352-byte raw BIN image,
    producing a clean ISO 9660 virtual filesystem image.
    Supports both Mode 1 (user data at offset 16) and Mode 2 Form 1 (user data at offset 24).
    """
    num_sectors = len(bin_data) // 2352
    out = bytearray(num_sectors * 2048)
    for i in range(num_sectors):
        sec = bin_data[i * 2352 : (i + 1) * 2352]
        mode = sec[15] if len(sec) > 15 else 0x02
        if mode == 0x01:
            out[i * 2048 : (i + 1) * 2048] = sec[16:2064]
        else:
            out[i * 2048 : (i + 1) * 2048] = sec[24:2072]
    return bytes(out)


def _iso_to_bin_mode1_bytes(iso_data: bytes, start_lba: int = 0) -> bytes:
    """
    Package a 2048-byte/sector ISO image into a fully compliant 2352-byte/sector
    Mode 1 CD-ROM disc image with sync patterns, BCD MSF headers,
    and recalculated 32-bit EDC checksums.
    """
    chunk_size = 2048
    num_sectors = (len(iso_data) + chunk_size - 1) // chunk_size
    packed = bytearray(num_sectors * 2352)

    for i in range(num_sectors):
        chunk = iso_data[i * chunk_size : (i + 1) * chunk_size]
        if len(chunk) < chunk_size:
            chunk = chunk + b"\x00" * (chunk_size - len(chunk))

        lba = start_lba + i + 150  # CD standard 2-second pregap (150 frames)
        m, s, f = lba_to_msf(lba)

        sec_offset = i * 2352
        # 1. Sync pattern (12 bytes)
        packed[sec_offset : sec_offset + 12] = SYNC_PATTERN
        # 2. Header (4 bytes: min, sec, frame in BCD, mode 0x01)
        packed[sec_offset + 12 : sec_offset + 16] = bytes(
            [_to_bcd(m), _to_bcd(s), _to_bcd(f), 0x01]
        )
        # 3. User data (2048 bytes starting at offset 16)
        packed[sec_offset + 16 : sec_offset + 2064] = chunk
        # 4. EDC checksum (4 bytes calculated over header + user data: bytes 0..2064)
        edc = calculate_cdrom_edc(packed[sec_offset : sec_offset + 2064])
        pack_into("<I", packed, sec_offset + 2064, edc)
        # 5. ECC parity blocks (276 bytes remain 0x00 for standard burning/emulators)

    return bytes(packed)


def _iso_to_bin_bytes(iso_data: bytes, start_lba: int = 0) -> bytes:
    """
    Package a 2048-byte/sector ISO image into a fully compliant 2352-byte/sector
    Mode 2 Form 1 CD-ROM disc image with sync patterns, BCD MSF headers,
    subheaders, and recalculated 32-bit EDC checksums.
    """
    chunk_size = 2048
    num_sectors = (len(iso_data) + chunk_size - 1) // chunk_size
    packed = bytearray(num_sectors * 2352)

    for i in range(num_sectors):
        chunk = iso_data[i * chunk_size : (i + 1) * chunk_size]
        if len(chunk) < chunk_size:
            chunk = chunk + b"\x00" * (chunk_size - len(chunk))

        lba = start_lba + i + 150  # CD standard 2-second pregap (150 frames)
        m, s, f = lba_to_msf(lba)

        sec_offset = i * 2352
        # 1. Sync pattern (12 bytes)
        packed[sec_offset : sec_offset + 12] = SYNC_PATTERN
        # 2. Header (4 bytes: min, sec, frame in BCD, mode 0x02)
        packed[sec_offset + 12 : sec_offset + 16] = bytes(
            [_to_bcd(m), _to_bcd(s), _to_bcd(f), 0x02]
        )
        # 3. Subheader (8 bytes: Form 1 data flags)
        packed[sec_offset + 16 : sec_offset + 24] = b"\x00\x00\x08\x00\x00\x00\x08\x00"
        # 4. User data (2048 bytes)
        packed[sec_offset + 24 : sec_offset + 2072] = chunk
        # 5. EDC checksum (4 bytes calculated over subheader + user data: 2056 bytes)
        edc = calculate_cdrom_edc(packed[sec_offset + 16 : sec_offset + 2072])
        pack_into("<I", packed, sec_offset + 2072, edc)
        # 6. ECC parity blocks (276 bytes remain 0x00 for standard burning/emulators)

    return bytes(packed)


class PSXRom:
    """
    Unified Sony PlayStation 1 (PS1) CD-ROM Disc Manager.
    Provides seamless virtual filesystem operations, SYSTEM.CNF configuration,
    executable modification, and multi-format ISO/BIN serialization.
    """

    def __init__(self, raw_data: bytes):
        if len(raw_data) < 2048 * 17:
            raise ParseError(
                f"Data too small for a PlayStation 1 disc image: {len(raw_data)} bytes"
            )

        self.original_data = raw_data
        self.sector_size, self.bin_mode = self._detect_sector_size_and_mode(raw_data)
        self.original_format = (
            (PSXFormat.BIN_MODE1 if self.bin_mode == 1 else PSXFormat.BIN)
            if self.sector_size == 2352
            else PSXFormat.ISO
        )

        if self.sector_size == 2352:
            iso_data = _bin_to_iso_bytes(raw_data)
        else:
            iso_data = raw_data

        try:
            self._iso = ISO9660(iso_data)
        except Exception as e:
            raise ParseError(
                f"Failed to mount PlayStation 1 ISO 9660 filesystem: {e}"
            ) from e

        self.system_cnf: Dict[str, str] = {}
        self.boot_path: Optional[str] = None
        self.game_id: Optional[str] = None
        self.region: str = "UNKNOWN"

        self._parse_system_cnf()

    @classmethod
    def from_bytes(cls, data: bytes) -> "PSXRom":
        """Load a PlayStation 1 ROM from raw binary bytes."""
        return cls(data)

    @classmethod
    def from_file(cls, path: Union[str, os.PathLike]) -> "PSXRom":
        """Load a PlayStation 1 ROM from an ISO or BIN disc image file."""
        with open(path, "rb") as f:
            return cls(f.read())

    @staticmethod
    def _detect_sector_size_and_mode(data: bytes) -> Tuple[int, int]:
        """
        Detect whether the image is 2352 bytes/sector (BIN) or 2048 bytes/sector (ISO),
        and if BIN, whether it is Mode 1 or Mode 2 Form 1.
        Returns (sector_size, bin_mode).
        """
        # Check 2352-byte BIN signature at sector 16
        if len(data) >= 17 * 2352:
            sec16_off = 16 * 2352
            if data[sec16_off : sec16_off + 12] == SYNC_PATTERN:
                # Mode 2 Form 1 has PVD at offset 24
                if data[sec16_off + 24 : sec16_off + 30] == ISO_PVD_MAGIC:
                    return 2352, 2
                # Mode 1 has PVD at offset 16
                if data[sec16_off + 16 : sec16_off + 22] == ISO_PVD_MAGIC:
                    return 2352, 1
                sec_mode = data[sec16_off + 15] if len(data) > sec16_off + 15 else 2
                return 2352, sec_mode if sec_mode in (1, 2) else 2

        # Check 2048-byte ISO signature at sector 16 (0x8000)
        if len(data) >= 17 * 2048:
            if data[0x8000 : 0x8006] == ISO_PVD_MAGIC:
                return 2048, 1

        # Fallback heuristic: check if buffer starts with CD sync pattern
        if len(data) >= 2352 and data[:12] == SYNC_PATTERN:
            sec_mode = data[15] if len(data) > 15 and data[15] in (1, 2) else 2
            return 2352, sec_mode

        return 2048, 1

    @classmethod
    def _detect_sector_size(cls, data: bytes) -> int:
        """Detect whether the image is 2352 bytes/sector (BIN) or 2048 bytes/sector (ISO)."""
        return cls._detect_sector_size_and_mode(data)[0]

    def _parse_system_cnf(self):
        """Parse /SYSTEM.CNF to determine boot executable, game ID, and region."""
        cnf_path = self._find_disc_file("SYSTEM.CNF")
        if not cnf_path:
            return

        raw_cnf = self.get_file(cnf_path)
        text = raw_cnf.decode("ascii", errors="replace")

        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                self.system_cnf[k.strip().upper()] = v.strip()

        boot_str = self.system_cnf.get("BOOT", "")
        if boot_str:
            # e.g., 'cdrom:\SLUS_000.01;1' -> 'SLUS_000.01'
            m = re.search(r"\\([A-Za-z0-9_.]+(?:;\d+)?)", boot_str)
            if m:
                clean_path = m.group(1).split(";")[0]
            else:
                clean_path = boot_str.split(":")[-1].strip("\\/").split(";")[0]
            self.boot_path = clean_path

            # Extract Game ID (e.g. SLUS-00001 or SLUS_000.01)
            id_m = re.search(r"([A-Z]{4})[_-]?(\d{3})\.?(\d{2})", clean_path.upper())
            if id_m:
                prefix, num1, num2 = id_m.groups()
                self.game_id = f"{prefix}-{num1}{num2}"
                self.region = resolve_psx_region(self.game_id)
            else:
                self.game_id = clean_path
                self.region = resolve_psx_region(clean_path)

    @property
    def title(self) -> str:
        """Volume identifier string parsed from the primary ISO descriptor."""
        return self._iso.volume_id.strip()

    @property
    def format(self) -> PSXFormat:
        """Container format of the original loaded disc image."""
        return self.original_format

    @property
    def license_text(self) -> str:
        """
        Extract the PlayStation 1 boot license banner string from Sector 4 if present.
        (e.g., 'Licensed by Sony Computer Entertainment Inc.')
        """
        if self.sector_size == 2352:
            sec4_off = 4 * 2352 + 24
        else:
            sec4_off = 4 * 2048

        if len(self.original_data) >= sec4_off + 2048:
            sec4 = self.original_data[sec4_off : sec4_off + 2048]
            for marker in (b"Licensed by", b"Sony Computer Entertainment"):
                if marker in sec4:
                    start = sec4.find(b"Licensed by") if b"Licensed by" in sec4 else sec4.find(marker)
                    end = sec4.find(b"\x00", start)
                    if end == -1:
                        end = start + 80
                    try:
                        return sec4[start:end].decode("ascii", errors="ignore").strip()
                    except Exception:
                        pass
        return ""

    def _find_disc_file(self, filename: str) -> Optional[str]:
        """Case-insensitive file search across the virtual ISO filesystem."""
        target = filename.strip("/").upper()
        for f in self._iso.list_files():
            if f.strip("/").upper() == target or f.strip("/").upper().endswith(
                "/" + target
            ):
                return f
        return None

    # =========================================================================
    # Filesystem Operations
    # =========================================================================

    def list_files(self, prefix: Optional[str] = None) -> List[str]:
        """List all file paths present in the disc image."""
        files = self._iso.list_files()
        if prefix:
            norm_p = prefix.strip("/").upper()
            return [f for f in files if f.strip("/").upper().startswith(norm_p)]
        return files

    def has_file(self, path: str) -> bool:
        """Check if a file path exists within the disc image."""
        return self._find_disc_file(path) is not None

    def get_file(self, path: str) -> bytes:
        """Read and return the raw byte contents of a file from the disc image."""
        p = self._find_disc_file(path)
        if not p:
            raise FileNotFoundError(
                f"File '{path}' not found in PlayStation 1 disc image."
            )
        return self._iso.read_file(p)

    def replace_file(self, path: str, new_content: bytes) -> None:
        """
        Replace a file within the disc image.
        If new_content exceeds the original sector count, automatically reallocates
        disc extent sectors and updates ISO directory descriptors.
        """
        p = self._find_disc_file(path)
        if not p:
            raise FileNotFoundError(
                f"File '{path}' not found in PlayStation 1 disc image."
            )
        self._iso.replace_file(p, new_content)
        if "SYSTEM.CNF" in p.upper():
            self._parse_system_cnf()

    def extract_all(self, dest_dir: Union[str, os.PathLike]) -> None:
        """Extract all files and folder hierarchies from the disc image to local disk."""
        os.makedirs(dest_dir, exist_ok=True)
        for fpath in self.list_files():
            content = self.get_file(fpath)
            out_file = os.path.join(str(dest_dir), fpath.replace("/", os.sep))
            os.makedirs(os.path.dirname(out_file), exist_ok=True)
            with open(out_file, "wb") as f:
                f.write(content)

    # =========================================================================
    # Executable Helpers
    # =========================================================================

    def get_main_exe(self) -> Optional[PSXExe]:
        """
        Parse and return the primary boot executable identified in SYSTEM.CNF
        as an inspectable PSXExe object.
        """
        target_name = self.boot_path
        if not target_name:
            # Fallback scan for any file starting with PS-X EXE
            for fpath in self.list_files():
                data = self.get_file(fpath)
                if len(data) >= 8 and data[:8] == PSXExe.MAGIC:
                    return PSXExe(data)
            return None

        p = self._find_disc_file(target_name)
        if not p:
            return None

        exe_data = self.get_file(p)
        if len(exe_data) >= 8 and exe_data[:8] == PSXExe.MAGIC:
            return PSXExe(exe_data)
        return None

    def replace_main_exe(self, exe: PSXExe) -> None:
        """Serialize and inject a modified PSXExe back into the primary boot file."""
        target_name = self.boot_path
        if not target_name:
            # Find file with matching magic
            for fpath in self.list_files():
                data = self.get_file(fpath)
                if len(data) >= 8 and data[:8] == PSXExe.MAGIC:
                    target_name = fpath
                    break

        if not target_name:
            raise FileNotFoundError("Cannot locate primary boot executable on disc.")

        self.replace_file(target_name, exe.to_bytes())

    # =========================================================================
    # Multi-Media Discovery
    # =========================================================================

    def find_textures(self) -> List[Tuple[str, int, TIMImage]]:
        """
        Deep scan disc files for embedded Sony TIM texture images (magic 0x10).
        Returns a list of (file_path, byte_offset, TIMImage).
        """
        results: List[Tuple[str, int, TIMImage]] = []
        sig = b"\x10\x00\x00\x00"

        for fpath in self.list_files():
            try:
                data = self.get_file(fpath)
            except Exception:
                continue

            if len(data) < 16:
                continue

            offset = 0
            while offset < len(data):
                idx = data.find(sig, offset)
                if idx == -1:
                    break
                try:
                    tim = TIMImage(data[idx:])
                    results.append((fpath, idx, tim))
                    offset = idx + max(16, len(tim.pixel_data))
                except Exception:
                    offset = idx + 4

        return results

    def find_audio(self) -> List[Tuple[str, int, VAGHeader]]:
        """
        Deep scan disc files for embedded Sony SPU-ADPCM VAG audio streams (VAGp / VAGi).
        Returns a list of (file_path, byte_offset, VAGHeader).
        """
        results: List[Tuple[str, int, VAGHeader]] = []
        sigs = [b"VAGp", b"VAGi"]

        for fpath in self.list_files():
            try:
                data = self.get_file(fpath)
            except Exception:
                continue

            if len(data) < 48:
                continue

            for sig in sigs:
                offset = 0
                while offset < len(data):
                    idx = data.find(sig, offset)
                    if idx == -1:
                        break
                    try:
                        hdr = VAGHeader.from_bytes(data[idx:])
                        results.append((fpath, idx, hdr))
                        offset = idx + max(48, hdr.data_size + 48)
                    except Exception:
                        offset = idx + 4

        return results

    def find_videos(self) -> List[Tuple[str, int, StrDemuxer]]:
        """
        Scan disc files for embedded PlayStation 1 STR cutscene movie streams.
        Returns a list of (file_path, byte_offset, StrDemuxer).
        """
        results: List[Tuple[str, int, StrDemuxer]] = []

        for fpath in self.list_files():
            if fpath.upper().endswith(".STR"):
                try:
                    data = self.get_file(fpath)
                    demuxer = StrDemuxer(data)
                    if len(demuxer.sectors) > 0:
                        results.append((fpath, 0, demuxer))
                except Exception:
                    pass

        return results

    # =========================================================================
    # Serialization & Repacking
    # =========================================================================

    def to_bytes(self, fmt: Optional[Union[str, PSXFormat]] = None) -> bytes:
        """
        Serialize the disc back into binary image bytes.
        Supports export as standard 2048-byte ISO or 2352-byte Mode 2 Form 1 BIN.
        """
        if fmt is None:
            target_fmt = self.original_format
        elif isinstance(fmt, str):
            target_fmt = PSXFormat(fmt.lower())
        else:
            target_fmt = fmt

        iso_bytes = self._iso.to_bytes()

        if target_fmt == PSXFormat.BIN_MODE1:
            return _iso_to_bin_mode1_bytes(iso_bytes)
        elif target_fmt == PSXFormat.BIN:
            return _iso_to_bin_bytes(iso_bytes)
        return bytes(iso_bytes)

    def generate_cue(self, bin_filename: Optional[str] = None) -> str:
        """
        Generate a standard PlayStation 1 CUE sheet string.
        Compatible with DuckStation, Mednafen, PCSX-Redux, and disc burning tools.
        """
        filename = bin_filename or f"{self.game_id or 'GAME'}.bin"
        track_mode = (
            "MODE1/2352"
            if self.original_format == PSXFormat.BIN_MODE1
            else "MODE2/2352"
        )
        return (
            f'FILE "{filename}" BINARY\n'
            f"  TRACK 01 {track_mode}\n"
            f"    INDEX 01 00:00:00\n"
        )

    def save(
        self,
        path: Union[str, os.PathLike],
        fmt: Optional[Union[str, PSXFormat]] = None,
        create_cue: bool = False,
    ) -> None:
        """Save the PlayStation 1 disc image to a file with optional CUE sheet generation."""
        if fmt is None:
            ext = os.path.splitext(str(path))[1].lower()
            if ext in (".bin", ".img"):
                fmt = (
                    PSXFormat.BIN_MODE1
                    if self.original_format == PSXFormat.BIN_MODE1
                    else PSXFormat.BIN
                )
            elif ext == ".iso":
                fmt = PSXFormat.ISO

        data = self.to_bytes(fmt=fmt)
        with open(path, "wb") as f:
            f.write(data)

        if create_cue or (
            (fmt in (PSXFormat.BIN, PSXFormat.BIN_MODE1))
            and str(path).lower().endswith(".bin")
        ):
            cue_path = os.path.splitext(str(path))[0] + ".cue"
            bin_name = os.path.basename(str(path))
            with open(cue_path, "w", encoding="utf-8") as f:
                f.write(self.generate_cue(bin_name))


def create_synthetic_psx_iso(
    game_id: str = "SLUS-00001",
    title: str = "SYNTHETIC PS1 GAME",
    with_main_exe: bool = True,
    with_tim: bool = True,
    with_str: bool = False,
) -> bytes:
    """
    Synthesize a valid 2048-byte/sector Mode 1 ISO 9660 PlayStation 1 disc image for testing.
    Includes SYSTEM.CNF, boot executable (PS-X EXE), optional TIM texture, and optional STR video.
    """
    # Normalize Game ID for filename (e.g. SLUS-00001 -> SLUS_000.01)
    clean = game_id.upper().replace("-", "").replace("_", "").replace(".", "")
    if len(clean) >= 9:
        exe_filename = f"{clean[:4]}_{clean[4:7]}.{clean[7:9]}"
    else:
        exe_filename = "SLUS_000.01"

    builder = ISOBuilder(volume_id=title[:32].upper())

    # 0. System Area & License Banner (Sector 4)
    sys_area = bytearray(16 * 2048)
    license_banner = b"Licensed by Sony Computer Entertainment Inc."
    sys_area[4 * 2048 : 4 * 2048 + len(license_banner)] = license_banner
    builder.set_system_area(bytes(sys_area))

    # 1. SYSTEM.CNF
    cnf_content = (
        f"BOOT = cdrom:\\{exe_filename};1\r\n"
        f"TCB = 4\r\n"
        f"EVENT = 16\r\n"
        f"STACK = 801FFFF0\r\n"
    ).encode("ascii")
    builder.add_file("SYSTEM.CNF", cnf_content)

    # 2. Main Executable (PS-X EXE)
    if with_main_exe:
        exe_header = bytearray(2048)
        exe_header[:8] = PSXExe.MAGIC
        # Initial PC = 0x80010000, GP = 0x80080000, Text RAM = 0x80010000, Text Size = 2048, SP = 0x801FFFF0
        pack_into("<IIII", exe_header, 16, 0x80010000, 0x80080000, 0x80010000, 2048)
        pack_into("<I", exe_header, 48, 0x801FFFF0)
        # Dummy MIPS instructions (.text payload: 2048 bytes)
        dummy_text = b"\x08\x00\xe0\x03\x00\x00\x00\x00" * 256
        builder.add_file(exe_filename, bytes(exe_header + dummy_text))

    # 3. Dummy TIM texture
    if with_tim:
        # Create minimal valid 16bpp TIM
        tim_data = bytearray()
        tim_data.extend((0x10).to_bytes(4, "little"))  # magic
        tim_data.extend((0x02).to_bytes(4, "little"))  # 16bpp direct
        # Image header
        tim_data.extend((12 + 16 * 16 * 2).to_bytes(4, "little"))  # total size
        tim_data.extend((0).to_bytes(2, "little"))  # dx
        tim_data.extend((0).to_bytes(2, "little"))  # dy
        tim_data.extend((16).to_bytes(2, "little"))  # width
        tim_data.extend((16).to_bytes(2, "little"))  # height
        tim_data.extend(b"\x00\x7C" * (16 * 16))  # 16x16 red pixels
        builder.add_file("TEXTURES/ICON.TIM", bytes(tim_data))

    # 4. Dummy STR cutscene movie
    if with_str:
        str_sector = bytearray(2352)
        str_sector[:12] = SYNC_PATTERN
        str_sector[12:16] = bytes([1, 0, 0, 2])
        # Subheader: submode = 0x64 (video/data Form 2)
        str_sector[16:24] = b"\x01\x01\x64\x00\x01\x01\x64\x00"
        builder.add_file("MOVIES/INTRO.STR", bytes(str_sector))

    return builder.build()


def create_synthetic_psx_bin(
    game_id: str = "SLUS-00001",
    title: str = "SYNTHETIC PS1 GAME",
    with_main_exe: bool = True,
    with_tim: bool = True,
    with_str: bool = False,
    mode: int = 2,
) -> bytes:
    """
    Synthesize a valid 2352-byte/sector Mode 1 or Mode 2 Form 1 raw CD-ROM BIN image for testing.
    """
    iso_data = create_synthetic_psx_iso(
        game_id=game_id,
        title=title,
        with_main_exe=with_main_exe,
        with_tim=with_tim,
        with_str=with_str,
    )
    if mode == 1:
        return _iso_to_bin_mode1_bytes(iso_data)
    return _iso_to_bin_bytes(iso_data)
