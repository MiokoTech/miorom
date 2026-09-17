"""
miorom.platforms.psp.rom
~~~~~~~~~~~~~~~~~~~~~~~~
Unified Sony PlayStation Portable (PSP) ROM, Disc & Package Manager.
Provides a uniform abstraction across UMD Optical Disc images (ISO 9660),
Compressed ISOs (CSO / CISO), and digital packages (EBOOT.PBP).

Pure Python implementation using MioROM declarative primitives with zero external dependencies.
"""

from __future__ import annotations

import os
from enum import Enum
from typing import List, Optional, Tuple, Union

from miorom.errors import ParseError
from miorom.platforms.iso.builder import ISOBuilder
from miorom.platforms.iso.cso import CSOCompressor, CSOImage
from miorom.platforms.iso.iso9660 import ISO9660
from miorom.platforms.psp.at3 import AT3Audio, AT3Codec
from miorom.platforms.psp.pbp import GIM_MAGIC, GIMImage, PBPFile
from miorom.platforms.psp.prx import PRXModule
from miorom.platforms.psp.sfo import SFOFile


class PSPFormat(str, Enum):
    """Container format for PSP game images."""

    ISO = "iso"  # Standard UMD ISO 9660 disc image
    CSO = "cso"  # Compressed ISO (CISO)
    PBP = "pbp"  # Sony EBOOT.PBP digital package


def resolve_psp_region(game_id: str) -> str:
    """
    Resolves the regional distribution territory from a Sony 4-character product code prefix.
    """
    if not game_id:
        return "Unknown"
    prefix = game_id.strip().upper()[:4]
    if prefix in ("ULUS", "UCUS", "NPUH", "NPUG", "NPUZ", "NPUX"):
        return "USA"
    if prefix in ("ULES", "UCES", "NPEH", "NPEG", "NPEZ", "NPEX"):
        return "EUR"
    if prefix in ("ULJM", "ULJS", "UCJM", "UCJS", "NPJH", "NPJG", "NPJZ", "NPJX"):
        return "JPN"
    if prefix in ("ULAS", "UCAS", "NPAH", "NPAG", "NPAZ"):
        return "ASIA"
    if prefix in ("ULKS", "UCKS", "NPKH", "NPKG", "NPKZ"):
        return "KOR"
    return "Global"


class PSPRom:
    """
    Unified manager for Sony PlayStation Portable (PSP) games.
    Provides polymorphic filesystem access, metadata inspection, executable management,
    and GIM texture discovery across ISO, CSO, and PBP containers.
    """

    def __init__(
        self,
        source: Union[str, bytes, bytearray],
        fmt: Optional[Union[str, PSPFormat]] = None,
    ):
        raw_bytes: bytearray
        if isinstance(source, str):
            with open(source, "rb") as f:
                raw_bytes = bytearray(f.read())
        else:
            raw_bytes = bytearray(source)

        self.raw_data: bytearray = raw_bytes
        self.format: PSPFormat
        self.original_format: PSPFormat
        self._iso: Optional[ISO9660] = None
        self._pbp: Optional[PBPFile] = None

        detected_fmt = self._detect_format(self.raw_data, fmt)
        self.format = detected_fmt
        self.original_format = detected_fmt

        if self.format == PSPFormat.PBP:
            self._pbp = PBPFile.from_bytes(self.raw_data)
            psar_data = self._pbp.get_section("DATA.PSAR")
            pvd_offset = 16 * 2048
            if len(psar_data) >= pvd_offset + 6 and psar_data[pvd_offset : pvd_offset + 6] == b"\x01CD001":
                try:
                    self._iso = ISO9660(psar_data)
                except Exception:
                    self._iso = None
        elif self.format == PSPFormat.CSO:
            cso = CSOImage(self.raw_data)
            iso_bytes = cso.to_iso_bytes()
            self._iso = ISO9660(iso_bytes)
            self.format = PSPFormat.ISO
        elif self.format == PSPFormat.ISO:
            self._iso = ISO9660(self.raw_data)

    @classmethod
    def from_file(cls, path: str) -> PSPRom:
        """Loads a PSP ROM from a file path."""
        return cls(path)

    @classmethod
    def from_bytes(cls, data: bytes) -> PSPRom:
        """Loads a PSP ROM from a byte buffer."""
        return cls(data)

    @staticmethod
    def _detect_format(data: bytearray, explicit_fmt: Optional[Union[str, PSPFormat]] = None) -> PSPFormat:
        if explicit_fmt is not None:
            if isinstance(explicit_fmt, PSPFormat):
                return explicit_fmt
            fmt_str = explicit_fmt.lower().strip()
            for pf in PSPFormat:
                if pf.value == fmt_str:
                    return pf

        if len(data) >= 4 and data[:4] == b"\x00PBP":
            return PSPFormat.PBP
        if len(data) >= 4 and data[:4] == b"CISO":
            return PSPFormat.CSO

        # Check ISO 9660 Primary Volume Descriptor at sector 16 (offset 0x8000)
        pvd_offset = 16 * 2048
        if len(data) >= pvd_offset + 6 and data[pvd_offset : pvd_offset + 6] == b"\x01CD001":
            return PSPFormat.ISO

        raise ParseError(
            "Unsupported or unrecognized PSP image format (must be ISO 9660, CSO, or EBOOT.PBP)."
        )

    # =========================================================================
    # Metadata & Identity Properties
    # =========================================================================

    @property
    def sfo(self) -> Optional[SFOFile]:
        """Returns the parsed PARAM.SFO metadata instance."""
        if self._pbp is not None:
            return self._pbp.sfo
        if self._iso is not None:
            sfo_path = self._find_iso_file("PARAM.SFO")
            if sfo_path:
                try:
                    sfo_bytes = self._iso.read_file(sfo_path)
                    return SFOFile.from_bytes(sfo_bytes)
                except Exception:
                    return None
        return None

    @property
    def game_id(self) -> str:
        """Returns the game product code / disc ID (e.g. 'ULUS10001')."""
        s = self.sfo
        if s is not None:
            val = s.get("DISC_ID") or s.get("TITLE_ID")
            if val:
                return str(val).strip()
        return ""

    @property
    def title(self) -> str:
        """Returns the human-readable game title."""
        s = self.sfo
        if s is not None:
            val = s.get("TITLE")
            if val:
                return str(val).strip()
        if self._iso is not None:
            return self._iso.volume_id
        return ""

    @property
    def version(self) -> str:
        """Returns the game software version string (e.g. '1.00')."""
        s = self.sfo
        if s is not None:
            val = s.get("DISC_VERSION") or s.get("APP_VER")
            if val:
                return str(val).strip()
        return "1.00"

    @property
    def category(self) -> str:
        """Returns the Sony package category code ('UG'=UMD Game, 'EG'=EBOOT Game)."""
        s = self.sfo
        if s is not None:
            val = s.get("CATEGORY")
            if val:
                return str(val).strip()
        return "UG" if self._iso is not None else "EG"

    @property
    def region(self) -> str:
        """Returns the regional release territory (USA, EUR, JPN, ASIA, KOR, Global)."""
        return resolve_psp_region(self.game_id)

    @property
    def icon_bytes(self) -> Optional[bytes]:
        """Returns the raw bytes of ICON0.PNG (144x80 icon)."""
        if self._pbp is not None:
            sec = self._pbp.get_section("ICON0.PNG")
            return sec if sec else None
        if self._iso is not None:
            p = self._find_iso_file("ICON0.PNG")
            if p:
                return self._iso.read_file(p)
        return None

    @property
    def background_bytes(self) -> Optional[bytes]:
        """Returns the raw bytes of PIC1.PNG (480x272 background artwork)."""
        if self._pbp is not None:
            sec = self._pbp.get_section("PIC1.PNG")
            return sec if sec else None
        if self._iso is not None:
            p = self._find_iso_file("PIC1.PNG")
            if p:
                return self._iso.read_file(p)
        return None

    @property
    def boot_audio_bytes(self) -> Optional[bytes]:
        """Returns the raw bytes of SND0.AT3 (preview audio)."""
        if self._pbp is not None:
            sec = self._pbp.get_section("SND0.AT3")
            return sec if sec else None
        if self._iso is not None:
            p = self._find_iso_file("SND0.AT3")
            if p:
                return self._iso.read_file(p)
        return None

    def set_title(self, new_title: str) -> None:
        """Updates the game title in PARAM.SFO and saves it back into the container."""
        s = self.sfo
        if s is None:
            s = SFOFile({"TITLE": new_title, "DISC_ID": self.game_id or "ULUS00000"})
        else:
            s["TITLE"] = new_title

        sfo_bytes = s.to_bytes()
        if self._pbp is not None:
            self._pbp.set_section("PARAM.SFO", sfo_bytes)
        if self._iso is not None:
            p = self._find_iso_file("PARAM.SFO") or "PSP_GAME/PARAM.SFO"
            if self._iso.get_entry(p) is not None:
                self._iso.replace_file(p, sfo_bytes)
                if self._pbp is not None:
                    self._pbp.set_section("DATA.PSAR", self._iso.to_bytes())

    def set_icon(self, image_bytes: bytes) -> None:
        """Sets the ICON0.PNG icon image."""
        if self._pbp is not None:
            self._pbp.set_section("ICON0.PNG", image_bytes)
        if self._iso is not None:
            p = self._find_iso_file("ICON0.PNG") or "PSP_GAME/ICON0.PNG"
            if self._iso.get_entry(p) is not None:
                self._iso.replace_file(p, image_bytes)
                if self._pbp is not None:
                    self._pbp.set_section("DATA.PSAR", self._iso.to_bytes())

    def set_background(self, image_bytes: bytes) -> None:
        """Sets the PIC1.PNG background image."""
        if self._pbp is not None:
            self._pbp.set_section("PIC1.PNG", image_bytes)
        if self._iso is not None:
            p = self._find_iso_file("PIC1.PNG") or "PSP_GAME/PIC1.PNG"
            if self._iso.get_entry(p) is not None:
                self._iso.replace_file(p, image_bytes)
                if self._pbp is not None:
                    self._pbp.set_section("DATA.PSAR", self._iso.to_bytes())

    def set_boot_audio(self, audio_bytes: bytes) -> None:
        """Sets the SND0.AT3 boot preview audio."""
        if self._pbp is not None:
            self._pbp.set_section("SND0.AT3", audio_bytes)
        if self._iso is not None:
            p = self._find_iso_file("SND0.AT3") or "PSP_GAME/SND0.AT3"
            if self._iso.get_entry(p) is not None:
                self.replace_file(p, audio_bytes)
                if self._pbp is not None:
                    self._pbp.set_section("DATA.PSAR", self._iso.to_bytes())

    def get_boot_audio_at3(self) -> Optional[AT3Audio]:
        """Parses SND0.AT3 as an AT3Audio object, or None if missing/invalid."""
        raw = self.boot_audio_bytes
        if not raw:
            return None
        try:
            return AT3Audio.from_bytes(raw)
        except Exception:
            return None

    def set_boot_audio_at3(self, at3: AT3Audio) -> None:
        """Sets the SND0.AT3 boot audio from an AT3Audio object."""
        self.set_boot_audio(at3.to_bytes())

    # =========================================================================
    # Filesystem Operations
    # =========================================================================

    def list_files(self, prefix: Optional[str] = None) -> List[str]:
        """
        Lists all file paths contained within the ROM.
        If prefix is specified, only files matching the prefix directory are returned.
        """
        if self._iso is not None:
            files = self._iso.list_files()
            if prefix:
                norm_p = prefix.strip("/").upper()
                return [f for f in files if f.strip("/").upper().startswith(norm_p)]
            return files
        if self._pbp is not None:
            secs = [k for k, v in self._pbp.sections.items() if len(v) > 0]
            if prefix:
                norm_p = prefix.strip("/").upper()
                return [s for s in secs if s.upper().startswith(norm_p)]
            return secs
        return []

    def has_file(self, path: str) -> bool:
        """Returns True if the specified file exists in the container."""
        if self._iso is not None and self._iso.get_entry(path) is not None:
            return True
        if self._pbp is not None:
            return path.upper() in self._pbp.sections and len(self._pbp.sections[path.upper()]) > 0
        return False

    def get_file(self, path: str) -> bytes:
        """Reads and returns the byte content of the specified file."""
        if self._iso is not None and self._iso.get_entry(path) is not None:
            return self._iso.read_file(path)
        if self._pbp is not None:
            sec = self._pbp.get_section(path)
            if sec:
                return sec
        if self._iso is not None:
            return self._iso.read_file(path)
        raise ParseError("No active container filesystem.")

    def replace_file(self, path: str, new_content: bytes) -> None:
        """
        Replaces a file within the container.
        On ISO containers, automatically expands disc extents and updates LBA records
        if new_content exceeds the original sector allocation.
        """
        if self._iso is not None and self._iso.get_entry(path) is not None:
            self._iso.replace_file(path, new_content)
            if self._pbp is not None:
                self._pbp.set_section("DATA.PSAR", self._iso.to_bytes())
        elif self._pbp is not None and path.upper() in self._pbp.sections:
            self._pbp.set_section(path, new_content)
        elif self._iso is not None:
            self._iso.replace_file(path, new_content)
            if self._pbp is not None:
                self._pbp.set_section("DATA.PSAR", self._iso.to_bytes())
        else:
            raise ParseError("No active container filesystem.")

    def extract_all(self, dest_dir: str) -> None:
        """Dumps all game files and directory structures to a local directory on disk."""
        os.makedirs(dest_dir, exist_ok=True)
        for fpath in self.list_files():
            content = self.get_file(fpath)
            out_file = os.path.join(dest_dir, fpath.replace("/", os.sep))
            os.makedirs(os.path.dirname(out_file), exist_ok=True)
            with open(out_file, "wb") as f:
                f.write(content)

    def _find_iso_file(self, filename: str) -> Optional[str]:
        """Locates an ISO file matching filename regardless of folder depth."""
        if self._iso is None:
            return None
        target = filename.strip("/").upper()
        for f in self._iso.list_files():
            clean_f = f.strip("/").upper()
            if clean_f == target or clean_f.endswith("/" + target):
                return f
        return None

    # =========================================================================
    # Executable Helpers
    # =========================================================================

    def get_boot_bin(self) -> Optional[bytes]:
        """Retrieves PSP_GAME/SYSDIR/BOOT.BIN (unencrypted executable)."""
        p = self._find_iso_file("BOOT.BIN")
        if p and self._iso is not None:
            return self._iso.read_file(p)
        return None

    def get_eboot_bin(self) -> Optional[bytes]:
        """Retrieves PSP_GAME/SYSDIR/EBOOT.BIN (ISO) or DATA.PSP (PBP)."""
        if self._iso is not None:
            p = self._find_iso_file("EBOOT.BIN")
            if p:
                return self._iso.read_file(p)
        elif self._pbp is not None:
            sec = self._pbp.get_section("DATA.PSP")
            return sec if sec else None
        return None

    def replace_boot_bin(self, new_data: bytes) -> None:
        """Replaces PSP_GAME/SYSDIR/BOOT.BIN."""
        p = self._find_iso_file("BOOT.BIN") or "PSP_GAME/SYSDIR/BOOT.BIN"
        self.replace_file(p, new_data)

    def replace_eboot_bin(self, new_data: bytes) -> None:
        """Replaces PSP_GAME/SYSDIR/EBOOT.BIN (ISO) or DATA.PSP (PBP)."""
        if self._iso is not None:
            p = self._find_iso_file("EBOOT.BIN") or "PSP_GAME/SYSDIR/EBOOT.BIN"
            self.replace_file(p, new_data)
        elif self._pbp is not None:
            self._pbp.set_section("DATA.PSP", new_data)

    def get_boot_prx(self) -> Optional[PRXModule]:
        """
        Parses and returns PSP_GAME/SYSDIR/BOOT.BIN as an inspectable PRXModule.
        Returns None if BOOT.BIN is not present in the ROM.
        """
        data = self.get_boot_bin()
        if data is None:
            return None
        return PRXModule.from_bytes(data)

    def replace_boot_prx(self, prx: PRXModule) -> None:
        """Serializes and replaces PSP_GAME/SYSDIR/BOOT.BIN with the modified PRXModule."""
        self.replace_boot_bin(prx.to_bytes())

    def get_eboot_prx(self) -> Optional[PRXModule]:
        """
        Parses and returns PSP_GAME/SYSDIR/EBOOT.BIN (ISO) or DATA.PSP (PBP) as a PRXModule.
        Returns None if not present.
        Raises ParseError if the EBOOT is encrypted (~PSP header).
        """
        data = self.get_eboot_bin()
        if data is None:
            return None
        return PRXModule.from_bytes(data)

    def replace_eboot_prx(self, prx: PRXModule) -> None:
        """Serializes and replaces PSP_GAME/SYSDIR/EBOOT.BIN (ISO) or DATA.PSP (PBP) with the modified PRXModule."""
        self.replace_eboot_bin(prx.to_bytes())

    # =========================================================================
    # Texture Discovery
    # =========================================================================

    def find_textures(self) -> List[Tuple[str, int, GIMImage]]:
        """
        Scans game files in USRDIR (or PBP sections) for embedded Sony GIM textures.
        Returns a list of (file_path, byte_offset, GIMImage).
        """
        results: List[Tuple[str, int, GIMImage]] = []
        sig = GIM_MAGIC[:12]

        # Scan either USRDIR on ISO or all sections on PBP
        files_to_scan = self.list_files("PSP_GAME/USRDIR") if self._iso else self.list_files()
        if not files_to_scan and self._iso:
            files_to_scan = self.list_files()

        for fpath in files_to_scan:
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
                    gim = GIMImage.from_bytes(data[idx:])
                    results.append((fpath, idx, gim))
                    offset = idx + max(16, len(gim.pixel_data))
                except Exception:
                    offset = idx + 4

        return results

    def find_audio_streams(self) -> List[Tuple[str, int, AT3Audio]]:
        """
        Scans game files in USRDIR (or PBP sections) for embedded Sony ATRAC3 / ATRAC3plus audio streams.
        Returns a list of (file_path, byte_offset, AT3Audio).
        """
        results: List[Tuple[str, int, AT3Audio]] = []
        sig = b"RIFF"

        files_to_scan = self.list_files("PSP_GAME/USRDIR") if self._iso else self.list_files()
        if not files_to_scan and self._iso:
            files_to_scan = self.list_files()

        for fpath in files_to_scan:
            try:
                data = self.get_file(fpath)
            except Exception:
                continue

            if len(data) < 44:
                continue

            offset = 0
            while offset < len(data):
                idx = data.find(sig, offset)
                if idx == -1 or idx + 12 > len(data):
                    break
                if data[idx + 8 : idx + 12] == b"WAVE":
                    try:
                        at3 = AT3Audio.from_bytes(data[idx:])
                        if at3.codec != AT3Codec.UNKNOWN:
                            results.append((fpath, idx, at3))
                            offset = idx + len(at3.raw_data)
                            continue
                    except Exception:
                        pass
                offset = idx + 4

        return results

    # =========================================================================
    # Serialization & Repacking
    # =========================================================================

    def _build_iso_from_pbp(self) -> bytes:
        """Constructs or extracts an ISO 9660 disc image from PBP sections."""
        if self._pbp is None:
            return b""
        psar_data = self._pbp.get_section("DATA.PSAR")
        pvd_offset = 16 * 2048
        if len(psar_data) >= pvd_offset + 6 and psar_data[pvd_offset : pvd_offset + 6] == b"\x01CD001":
            return psar_data

        # Homebrew PBP conversion to ISO 9660 disc image
        builder = ISOBuilder(volume_id=(self.game_id or "PSP_GAME")[:16])
        sfo = self._pbp.get_section("PARAM.SFO")
        if sfo:
            builder.add_file("PSP_GAME/PARAM.SFO", sfo)
        data_psp = self._pbp.get_section("DATA.PSP")
        if data_psp:
            builder.add_file("PSP_GAME/SYSDIR/EBOOT.BIN", data_psp)
            if data_psp.startswith(b"\x7fELF"):
                builder.add_file("PSP_GAME/SYSDIR/BOOT.BIN", data_psp)
        icon = self._pbp.get_section("ICON0.PNG")
        if icon:
            builder.add_file("PSP_GAME/ICON0.PNG", icon)
        pic1 = self._pbp.get_section("PIC1.PNG")
        if pic1:
            builder.add_file("PSP_GAME/PIC1.PNG", pic1)
        snd0 = self._pbp.get_section("SND0.AT3")
        if snd0:
            builder.add_file("PSP_GAME/SND0.AT3", snd0)
        return builder.build()

    def to_bytes(self, fmt: Optional[Union[str, PSPFormat]] = None) -> bytes:
        """
        Serializes the ROM back into binary data.
        Supports exporting as ISO, CSO, or PBP.
        """
        target_fmt = self.original_format if fmt is None else self._detect_format(bytearray(), fmt)

        if target_fmt == PSPFormat.PBP:
            if self._pbp is not None:
                if self._iso is not None:
                    self._pbp.set_section("DATA.PSAR", self._iso.to_bytes())
                return self._pbp.to_bytes()
            # If converting ISO to PBP: wrap in DATA.PSAR
            sfo_data = self.sfo.to_bytes() if self.sfo else b""
            icon = self.icon_bytes or b""
            pbp = PBPFile(
                sections={
                    "PARAM.SFO": sfo_data,
                    "ICON0.PNG": icon,
                    "DATA.PSAR": self._iso.to_bytes() if self._iso else b"",
                }
            )
            return pbp.to_bytes()

        # ISO or CSO requires an ISO image
        if self._iso is not None:
            iso_data = self._iso.to_bytes()
        elif self._pbp is not None:
            iso_data = self._build_iso_from_pbp()
        else:
            iso_data = b""

        if target_fmt == PSPFormat.CSO:
            return CSOCompressor.compress_bytes(iso_data)

        return iso_data

    def save(self, path: str, fmt: Optional[Union[str, PSPFormat]] = None) -> None:
        """
        Saves the ROM to disk, inferring format from file extension or original format.
        """
        if fmt is None:
            ext = os.path.splitext(path)[1].lower()
            if ext == ".cso":
                fmt = PSPFormat.CSO
            elif ext == ".pbp":
                fmt = PSPFormat.PBP
            elif ext == ".iso":
                fmt = PSPFormat.ISO
            else:
                fmt = self.original_format

        data = self.to_bytes(fmt=fmt)
        with open(path, "wb") as f:
            f.write(data)


def create_synthetic_psp_iso(
    game_id: str = "ULUS10001",
    title: str = "Synthetic PSP Game",
    version: str = "1.00",
    category: str = "UG",
    with_boot_bin: bool = True,
    with_eboot_bin: bool = True,
    with_gim: bool = True,
    boot_bin_data: Optional[bytes] = None,
) -> bytes:
    """
    Synthesizes a 100% valid PSP UMD ISO 9660 disc image for testing and ROM analysis.
    """
    builder = ISOBuilder(volume_id=game_id[:16])

    # 1. PARAM.SFO
    sfo = SFOFile(
        {
            "DISC_ID": game_id,
            "TITLE": title,
            "DISC_VERSION": version,
            "CATEGORY": category,
        }
    )
    builder.add_file("PSP_GAME/PARAM.SFO", sfo.to_bytes())

    # 2. Executables
    if with_boot_bin:
        payload = (
            boot_bin_data
            if boot_bin_data is not None
            else b"\x7FELF_BOOT_DUMMY_EXEC_PAYLOAD"
        )
        builder.add_file("PSP_GAME/SYSDIR/BOOT.BIN", payload)
    if with_eboot_bin:
        builder.add_file("PSP_GAME/SYSDIR/EBOOT.BIN", b"~PSP_EBOOT_DUMMY_EXEC_PAYLOAD")

    # 3. Media
    builder.add_file("PSP_GAME/ICON0.PNG", b"\x89PNG\r\n\x1a\n_DUMMY_ICON")
    builder.add_file("PSP_GAME/PIC1.PNG", b"\x89PNG\r\n\x1a\n_DUMMY_BACKGROUND")
    builder.add_file("PSP_GAME/SND0.AT3", b"RIFF....WAVE_DUMMY_AT3")

    # 4. Data asset with GIM texture
    if with_gim:
        # Create valid 16x16 GIM texture
        from miorom.graphics.png_codec import PNGColorType, PNGImage
        from miorom.platforms.psp.pbp import GIMFormat

        raw_rgba = bytes([128, 64, 32, 255] * (16 * 16))
        png = PNGImage(width=16, height=16, color_type=PNGColorType.RGBA, bit_depth=8, pixels=raw_rgba)
        gim = GIMImage.from_image(png, format=GIMFormat.RGBA8888, swizzle=True)
        builder.add_file("PSP_GAME/USRDIR/ui.gim", gim.to_bytes())
        builder.add_file("PSP_GAME/USRDIR/data.bin", b"SAMPLE_GAME_ASSET_BYTES")

    return builder.build()


def create_synthetic_psp_pbp(
    game_id: str = "NPUH10002",
    title: str = "Synthetic PBP Game",
    version: str = "1.01",
) -> bytes:
    """
    Synthesizes a 100% valid Sony EBOOT.PBP digital package for unit testing.
    """
    sfo = SFOFile(
        {
            "DISC_ID": game_id,
            "TITLE": title,
            "APP_VER": version,
            "CATEGORY": "EG",
        }
    )
    pbp = PBPFile(
        sections={
            "PARAM.SFO": sfo.to_bytes(),
            "ICON0.PNG": b"\x89PNG\r\n\x1a\n_PBP_ICON",
            "DATA.PSP": b"\x7FELF_PBP_EXEC",
            "DATA.PSAR": b"PSAR_ARCHIVE_BYTES",
        }
    )
    return pbp.to_bytes()
