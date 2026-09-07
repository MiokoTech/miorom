import math
import struct
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class BinaryFingerprint:
    """Represents an identified file format, container, or header inside binary data."""
    offset: int
    category: str  # "rom", "filesystem", "compression", "graphics", "audio", "archive", "code"
    format_name: str
    confidence: float  # 0.0 to 1.0
    description: str
    size: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


def calculate_entropy(data: bytes) -> float:
    """
    Calculate Shannon entropy of byte data (range: 0.0 to 8.0).
    0.0 = completely homogeneous (all identical bytes)
    8.0 = perfectly random / dense compressed or encrypted payload
    ~3.5 - 6.0 = executable machine code or natural text
    """
    if not data:
        return 0.0
    length = len(data)
    counts = Counter(data)
    return -sum((cnt / length) * math.log2(cnt / length) for cnt in counts.values())


def calculate_block_entropy(data: bytes, block_size: int = 1024) -> List[Tuple[int, float]]:
    """
    Compute Shannon entropy across sliding/chunked blocks of the binary data.
    Returns list of (offset, entropy).
    """
    blocks = []
    for offset in range(0, len(data), block_size):
        chunk = data[offset:offset + block_size]
        blocks.append((offset, calculate_entropy(chunk)))
    return blocks


class DeepScanner:
    """
    Deep Binary Inspector and Container Fingerprinter.
    Recursively scans binary data to detect console ROM headers, embedded archives,
    graphics containers, sound formats, compressed streams, and entropy distribution.
    """

    def __init__(self, alignment: int = 4):
        self.alignment = max(1, alignment)

    def scan(
        self,
        data: bytes,
        min_confidence: float = 0.5,
        scan_embedded: bool = True,
        block_size: int = 1024,
    ) -> "DeepScanReport":
        """
        Perform a comprehensive deep scan of the binary buffer.
        """
        fingerprints: List[BinaryFingerprint] = []

        # 1. Primary container / ROM header checks (at offset 0 or standard offsets)
        self._check_primary_rom_headers(data, fingerprints)

        # 2. Embedded asset / container signatures
        if scan_embedded and len(data) > 0:
            self._scan_embedded_signatures(data, fingerprints)

        # Filter by minimum confidence
        fingerprints = [fp for fp in fingerprints if fp.confidence >= min_confidence]
        # Sort by offset
        fingerprints.sort(key=lambda fp: fp.offset)

        # 3. Shannon entropy analysis
        overall_entropy = calculate_entropy(data)
        entropy_blocks = calculate_block_entropy(data, block_size=block_size)

        return DeepScanReport(
            total_size=len(data),
            overall_entropy=overall_entropy,
            fingerprints=fingerprints,
            entropy_blocks=entropy_blocks,
        )

    def find_compressed_blocks(
        self,
        data: bytes,
        block_size: int = 1024,
        entropy_threshold: float = 7.2,
    ) -> List[Tuple[int, int, float]]:
        """
        Identify high-entropy blocks likely containing compressed or encrypted data.
        Returns list of (start_offset, length, average_entropy).
        """
        blocks = calculate_block_entropy(data, block_size=block_size)
        high_entropy_regions = []
        current_start = None
        current_len = 0
        entropy_sum = 0.0

        for off, ent in blocks:
            if ent >= entropy_threshold:
                if current_start is None:
                    current_start = off
                    current_len = min(block_size, len(data) - off)
                    entropy_sum = ent
                else:
                    current_len += min(block_size, len(data) - off)
                    entropy_sum += ent
            else:
                if current_start is not None:
                    num_blocks = current_len // block_size or 1
                    high_entropy_regions.append(
                        (current_start, current_len, entropy_sum / num_blocks)
                    )
                    current_start = None
                    current_len = 0
                    entropy_sum = 0.0

        if current_start is not None:
            num_blocks = current_len // block_size or 1
            high_entropy_regions.append(
                (current_start, current_len, entropy_sum / num_blocks)
            )

        return high_entropy_regions

    def _check_primary_rom_headers(self, data: bytes, out: List[BinaryFingerprint]):
        sz = len(data)
        if sz < 16:
            return

        # N64
        if sz >= 4:
            magic4 = data[:4]
            if magic4 == b"\x80\x37\x12\x40":
                out.append(BinaryFingerprint(
                    offset=0, category="rom", format_name="N64 (Z64)",
                    confidence=1.0, description="Nintendo 64 ROM (Big-Endian .z64)",
                    metadata={"endian": "big"}
                ))
            elif magic4 == b"\x37\x80\x40\x12":
                out.append(BinaryFingerprint(
                    offset=0, category="rom", format_name="N64 (V64)",
                    confidence=1.0, description="Nintendo 64 ROM (Byte-Swapped .v64)",
                    metadata={"endian": "byteswapped"}
                ))
            elif magic4 == b"\x40\x12\x37\x80":
                out.append(BinaryFingerprint(
                    offset=0, category="rom", format_name="N64 (Little-Endian)",
                    confidence=1.0, description="Nintendo 64 ROM (Little-Endian .n64)",
                    metadata={"endian": "little"}
                ))

        # GBA
        if sz >= 0xC0 and len(data) >= 0xA0:
            # GBA Nintendo logo at 0x04..0x9F
            gba_logo_snippet = bytes([0x24, 0xFF, 0xAE, 0x51, 0x69, 0x9A, 0xA2, 0x21])
            if data[4:12] == gba_logo_snippet:
                title = data[0xA0:0xAC].decode("ascii", errors="replace").strip("\x00")
                game_code = data[0xAC:0xB0].decode("ascii", errors="replace").strip("\x00")
                out.append(BinaryFingerprint(
                    offset=0, category="rom", format_name="GBA",
                    confidence=1.0, description=f"Game Boy Advance ROM ('{title}', Code: {game_code})",
                    metadata={"title": title, "game_code": game_code}
                ))

        # NDS
        if sz >= 0x200:
            arm9_off, = struct.unpack_from("<I", data, 0x20)
            arm7_off, = struct.unpack_from("<I", data, 0x30)
            if 0x200 <= arm9_off < sz and 0x200 <= arm7_off < sz:
                title = data[0x00:0x0C].decode("ascii", errors="replace").strip("\x00")
                game_code = data[0x0C:0x10].decode("ascii", errors="replace").strip("\x00")
                out.append(BinaryFingerprint(
                    offset=0, category="rom", format_name="NDS",
                    confidence=0.95, description=f"Nintendo DS ROM ('{title}', Code: {game_code})",
                    metadata={"title": title, "game_code": game_code, "arm9_offset": arm9_off, "arm7_offset": arm7_off}
                ))

        # GB / GBC
        if sz >= 0x150:
            # Nintendo logo at 0x104
            gb_logo_snippet = bytes([0xCE, 0xED, 0x66, 0x66, 0xCC, 0x0D, 0x00, 0x0B])
            if data[0x104:0x10C] == gb_logo_snippet:
                title = data[0x134:0x143].decode("ascii", errors="replace").strip("\x00")
                cgb_flag = data[0x143]
                is_cgb = cgb_flag in (0x80, 0xC0)
                fmt = "GBC" if is_cgb else "GB"
                out.append(BinaryFingerprint(
                    offset=0, category="rom", format_name=fmt,
                    confidence=1.0, description=f"Game Boy {'Color ' if is_cgb else ''}ROM ('{title}')",
                    metadata={"title": title, "is_cgb": is_cgb, "cartridge_type": data[0x147]}
                ))

        # SNES (Check LoROM 0x7FB0 / 0x7FC0 or HiROM 0xFFB0 / 0xFFC0)
        for snes_off, name in [(0x7FC0, "SNES (LoROM)"), (0xFFC0, "SNES (HiROM)")]:
            if sz >= snes_off + 0x30:
                csum, comp = struct.unpack_from("<HH", data, snes_off + 0x1C)
                if (csum + comp) == 0xFFFF and csum > 0:
                    title = data[snes_off:snes_off + 21].decode("ascii", errors="replace").strip()
                    out.append(BinaryFingerprint(
                        offset=0, category="rom", format_name=name,
                        confidence=0.98, description=f"Super Nintendo ROM ('{title}')",
                        metadata={"title": title, "checksum": hex(csum)}
                    ))
                    break

        # Sega Mega Drive / Genesis
        if sz >= 512 and data[8] == 0xAA and data[9] == 0xBB:
            out.append(BinaryFingerprint(
                offset=0, category="rom", format_name="SMD",
                confidence=1.0, description="Sega Mega Drive Interleaved ROM (.smd)",
            ))
        elif sz >= 0x120:
            if data[0x100:0x104] == b"SEGA":
                sys_name = data[0x100:0x110].decode("ascii", errors="replace").strip()
                out.append(BinaryFingerprint(
                    offset=0, category="rom", format_name="MegaDrive",
                    confidence=1.0, description=f"Sega Genesis / Mega Drive ROM ({sys_name})",
                    metadata={"system": sys_name}
                ))

        # Sony PS-X EXE
        if data[:8] == b"PS-X EXE":
            pc0, gp0, t_addr, t_size = struct.unpack_from("<IIII", data, 0x10)
            out.append(BinaryFingerprint(
                offset=0, category="code", format_name="PS-X EXE",
                confidence=1.0, description="Sony PlayStation Executable (PS-X EXE)",
                size=sz, metadata={"pc0": hex(pc0), "load_addr": hex(t_addr), "text_size": t_size}
            ))

        # ISO9660 Volume Descriptor (PS1 / Saturn / GameCube / PC)
        for iso_sector_off in [0x8000, 0x9300]:
            if sz >= iso_sector_off + 6:
                if data[iso_sector_off:iso_sector_off + 6] in (b"\x01CD001", b"\x02CD001"):
                    sys_id = data[iso_sector_off + 8:iso_sector_off + 40].decode("ascii", errors="replace").strip()
                    vol_id = data[iso_sector_off + 40:iso_sector_off + 72].decode("ascii", errors="replace").strip()
                    out.append(BinaryFingerprint(
                        offset=iso_sector_off, category="filesystem", format_name="ISO9660",
                        confidence=1.0, description=f"ISO9660 Disc Image ('{vol_id}', Sys: '{sys_id}')",
                        metadata={"system_id": sys_id, "volume_id": vol_id}
                    ))

        # Neverland TOC Archive (NLCM)
        if data[:4] == b"NLCM" and sz >= 0x38:
            num_entries = struct.unpack_from(">I", data, 0x0C)[0]
            out.append(BinaryFingerprint(
                offset=0, category="archive", format_name="Neverland_NLCM",
                confidence=1.0, description=f"Neverland TOC Archive ({num_entries} files)",
                metadata={"num_entries": num_entries}
            ))

        # Neverland Multi-Section Script Module (Wii/GameCube)
        if (sz >= 0x60 and
            data[:4] == b"\x00\x00\x00\x00" and
            data[8:12] == b"\x00\x00\x00\x01"):
            hdr_size = struct.unpack_from(">I", data, 4)[0]
            if hdr_size == sz or abs(hdr_size - sz) < 64:
                num_sec = struct.unpack_from(">I", data, 0x14)[0]
                if 1 <= num_sec <= 32:
                    sec2_off = struct.unpack_from(">I", data, 0x48)[0] if sz > 0x4C else 0
                    out.append(BinaryFingerprint(
                        offset=0, category="script", format_name="Neverland_Script",
                        confidence=0.95,
                        description=f"Neverland Multi-Section Script Module ({num_sec} sections, Text Table @ 0x{sec2_off:X})",
                        metadata={"num_sections": num_sec, "text_section_offset": sec2_off, "declared_size": hdr_size}
                    ))


    def _scan_embedded_signatures(self, data: bytes, out: List[BinaryFingerprint]):
        align = self.alignment
        length = len(data)

        for off in range(0, length - 16, align):
            b4 = data[off:off + 4]

            # --- Archive / Container Formats ---
            if b4 == b"NARC":
                byte_order = struct.unpack_from("<H", data, off + 4)[0]
                if byte_order == 0xFFFE or byte_order == 0xFEFF:
                    endian = "<" if byte_order == 0xFFFE else ">"
                    narc_size = struct.unpack_from(f"{endian}I", data, off + 8)[0]
                    out.append(BinaryFingerprint(
                        offset=off, size=narc_size, category="archive",
                        format_name="NARC", confidence=0.98,
                        description="Nitro ARChive (NDS Container)",
                        metadata={"size": narc_size}
                    ))
            elif b4 == b"\x55\xAA\x38\x2D":
                out.append(BinaryFingerprint(
                    offset=off, category="archive", format_name="U8",
                    confidence=0.99, description="Nintendo U8 Archive (.arc / .szs)",
                ))
            elif b4 == b"CPK ":
                out.append(BinaryFingerprint(
                    offset=off, category="archive", format_name="CPK",
                    confidence=0.95, description="CRIWARE CPK Container",
                ))
            elif b4 == b"AFS\x00":
                count, = struct.unpack_from("<I", data, off + 4)
                if 0 < count < 65536:
                    out.append(BinaryFingerprint(
                        offset=off, category="archive", format_name="AFS",
                        confidence=0.90, description=f"AFS Archive ({count} files)",
                        metadata={"file_count": count}
                    ))

            # --- Graphics Formats ---
            elif b4 == b"\x10\x00\x00\x00":  # TIM magic
                if off + 12 <= length:
                    bpp_flag = struct.unpack_from("<I", data, off + 4)[0] & 0x07
                    if bpp_flag in (0, 1, 2, 3):  # 4bpp, 8bpp, 16bpp, 24bpp
                        out.append(BinaryFingerprint(
                            offset=off, category="graphics", format_name="TIM",
                            confidence=0.85, description=f"PS1 TIM Image ({4 << bpp_flag}-bit color)",
                            metadata={"bpp_flag": bpp_flag}
                        ))
            elif b4 == b"\x00\x20\xAF\x30":  # TPL magic
                out.append(BinaryFingerprint(
                    offset=off, category="graphics", format_name="TPL",
                    confidence=0.99, description="GameCube / Wii Texture Palette Library (TPL)",
                ))
            elif b4 == b"RGCN":
                out.append(BinaryFingerprint(
                    offset=off, category="graphics", format_name="NCGR",
                    confidence=0.95, description="Nitro Character Graphic Resource (NDS Tiles)",
                ))
            elif b4 == b"RLCN":
                out.append(BinaryFingerprint(
                    offset=off, category="graphics", format_name="NCLR",
                    confidence=0.95, description="Nitro Color Resource (NDS Palette)",
                ))
            elif b4 == b"RCSN":
                out.append(BinaryFingerprint(
                    offset=off, category="graphics", format_name="NSCR",
                    confidence=0.95, description="Nitro Screen Resource (NDS Tilemap)",
                ))
            elif b4 == b"RTFN":
                out.append(BinaryFingerprint(
                    offset=off, category="graphics", format_name="NFTR",
                    confidence=0.95, description="Nitro Font Resource (NDS Bitmap Font)",
                ))

            # --- Audio Formats ---
            elif b4 == b"SDAT":
                sdat_sz, = struct.unpack_from("<I", data, off + 8)
                out.append(BinaryFingerprint(
                    offset=off, size=sdat_sz, category="audio",
                    format_name="SDAT", confidence=0.98,
                    description="Nitro Sound Data (NDS Audio Bank)",
                    metadata={"size": sdat_sz}
                ))
            elif b4 in (b"PSF\x01", b"PSF\x02"):
                ver = 1 if b4[3] == 1 else 2
                out.append(BinaryFingerprint(
                    offset=off, category="audio", format_name=f"PSF{ver}",
                    confidence=0.95, description=f"PlayStation Sound Format PSF{ver}",
                ))
            elif b4 == b"MThd":
                out.append(BinaryFingerprint(
                    offset=off, category="audio", format_name="MIDI",
                    confidence=0.95, description="Standard MIDI File Header",
                ))
            elif b4 == b"RIFF" and off + 12 <= length and data[off + 8:off + 12] == b"WAVE":
                wave_sz = struct.unpack_from("<I", data, off + 4)[0] + 8
                out.append(BinaryFingerprint(
                    offset=off, size=wave_sz, category="audio",
                    format_name="WAV", confidence=0.99,
                    description="RIFF WAVE Audio Stream",
                    metadata={"size": wave_sz}
                ))

            # --- Compression Formats ---
            elif b4 == b"Yaz0":
                decomp_sz, = struct.unpack_from(">I", data, off + 4)
                out.append(BinaryFingerprint(
                    offset=off, category="compression", format_name="Yaz0",
                    confidence=0.98, description=f"Yaz0 Compressed Stream (Decompressed: {decomp_sz} bytes)",
                    metadata={"decompressed_size": decomp_sz}
                ))
            elif data[off] in (0x10, 0x11) and off + 4 <= length:
                # GBA/NDS LZ10 / LZ11
                comp_type = data[off]
                d_sz = data[off + 1] | (data[off + 2] << 8) | (data[off + 3] << 16)
                if 16 <= d_sz <= 16 * 1024 * 1024:  # Reasonable range: 16B - 16MB
                    name = "LZ10" if comp_type == 0x10 else "LZ11"
                    # We assign lower confidence as single-byte check has false positives
                    out.append(BinaryFingerprint(
                        offset=off, category="compression", format_name=name,
                        confidence=0.60, description=f"BIOS {name} Stream (Target: {d_sz} bytes)",
                        metadata={"decompressed_size": d_sz}
                    ))

            # --- Neverland / Marvelous Text Containers ---
            # Dual-table fefe format: 16-byte header + Table1 at 0x10, Table2 at footer.
            # Found in: Rune Factory series (Wii/DS), Harvest Moon (Marvelous titles).
            # Heuristic: bytes[0..3] == 0x00000000, bytes[8..11] == 0x00000001,
            #             bytes[12..15] == 0x00000000, bytes[4..7] = ptr to Table2 (> 0).
            elif (off + 16 <= length and
                  data[off:off + 4] == b"\x00\x00\x00\x00" and
                  data[off + 8:off + 12] == b"\x00\x00\x00\x01" and
                  data[off + 12:off + 16] == b"\x00\x00\x00\x00"):
                t2_offset = struct.unpack_from(">I", data, off + 4)[0]
                file_sz = length - off
                # FEFE containers are text sub-files (< 2MB) where t2_offset is before EOF
                # and bytes 0x10..0x18 are NOT a script section table (section count is usually at 0x14 in scripts)
                is_script = (off == 0 and length > 0x60 and
                             struct.unpack_from(">I", data, 4)[0] == length and
                             1 <= struct.unpack_from(">I", data, 0x14)[0] <= 32)
                if not is_script and 0 < t2_offset < file_sz and file_sz < 2 * 1024 * 1024:
                    out.append(BinaryFingerprint(
                        offset=off, category="archive", format_name="Neverland_FEFE",
                        confidence=0.85,
                        description=(
                            f"Neverland/Marvelous Dual-Table Text Container "
                            f"(Table1 @ +0x10, Table2 @ +0x{t2_offset:X})"
                        ),
                        metadata={"table2_offset": t2_offset, "file_size": file_sz}
                    ))


@dataclass
class DeepScanReport:
    """Summary of deep binary analysis, detected formats, and entropy profile."""
    total_size: int
    overall_entropy: float
    fingerprints: List[BinaryFingerprint]
    entropy_blocks: List[Tuple[int, float]]

    def summary(self) -> str:
        """Format an informative tabular summary of the scan results."""
        lines = [
            "=" * 78,
            f"DEEP BINARY INSPECTOR REPORT  (Size: {self.total_size:,} bytes, Entropy: {self.overall_entropy:.2f} / 8.00)",
            "=" * 78,
        ]

        if not self.fingerprints:
            lines.append("No known headers or container signatures detected.")
        else:
            lines.append(f"{'Offset':<10} | {'Category':<12} | {'Format':<16} | {'Confidence':<10} | {'Description'}")
            lines.append("-" * 78)
            for fp in self.fingerprints:
                off_str = f"0x{fp.offset:08X}"
                conf_str = f"{int(fp.confidence * 100)}%"
                lines.append(
                    f"{off_str:<10} | {fp.category:<12} | {fp.format_name:<16} | {conf_str:<10} | {fp.description}"
                )

        lines.append("-" * 78)
        # Entropy profile breakdown
        high_entropy_blocks = sum(1 for _, ent in self.entropy_blocks if ent >= 7.2)
        low_entropy_blocks = sum(1 for _, ent in self.entropy_blocks if ent < 2.0)
        total_blocks = len(self.entropy_blocks) or 1
        lines.append(
            f"Entropy Distribution: {high_entropy_blocks/total_blocks*100:.1f}% High (>7.2, compressed/encrypted), "
            f"{low_entropy_blocks/total_blocks*100:.1f}% Sparse (<2.0, zero-padded)"
        )
        lines.append("=" * 78)
        return "\n".join(lines)
