import os
import struct
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any


@dataclass
class NARCEntry:
    index: int
    name: str
    size: int
    data: bytes


class NARCArchive:
    """
    Nintendo DS Nitro ARChive (NARC) unpacker and packer.
    Universal resource archive used in NDS games (Pokémon, Rune Factory, Dragon Quest, etc.).
    """

    MAGIC = b"NARC"
    BTAF_MAGIC = b"BTAF"
    BTNF_MAGIC = b"BTNF"
    GMIF_MAGIC = b"GMIF"

    @classmethod
    def is_narc(cls, data: bytes) -> bool:
        return len(data) >= 16 and data[:4] == cls.MAGIC

    @classmethod
    def extract_all(cls, narc_path: str, output_dir: str) -> List[str]:
        """Extracts all files from a NARC archive to output_dir."""
        with open(narc_path, "rb") as f:
            data = f.read()

        entries = cls.unpack_entries(data)
        os.makedirs(output_dir, exist_ok=True)
        extracted = []

        padding = max(4, len(str(len(entries))))
        for e in entries:
            filename = e.name if e.name else f"file_{e.index:0{padding}d}.bin"
            file_path = os.path.join(output_dir, filename)
            with open(file_path, "wb") as f_out:
                f_out.write(e.data)
            extracted.append(file_path)

        return extracted

    @classmethod
    def unpack_entries(cls, data: bytes) -> List[NARCEntry]:
        """Parses all file entries from NARC binary data."""
        if not cls.is_narc(data):
            raise ValueError("Data is not a valid Nintendo NARC archive.")

        # Header (16 bytes): MAGIC (4), BOM (2), Version (2), FileSize (4), HeaderSize (2), Chunks (2)
        bom, version, file_size, header_size, num_chunks = struct.unpack_from("<HHIHH", data, 4)

        # 1. BTAF section (File Allocation Table)
        btaf_pos = header_size
        btaf_magic, btaf_size = struct.unpack_from("<4sI", data, btaf_pos)
        if btaf_magic != cls.BTAF_MAGIC:
            raise ValueError(f"Expected BTAF header at 0x{btaf_pos:X}, got {btaf_magic}")

        file_count = struct.unpack_from("<H", data, btaf_pos + 8)[0]
        fat_entries = []
        fat_ptr = btaf_pos + 12

        for i in range(file_count):
            start_off, end_off = struct.unpack_from("<II", data, fat_ptr)
            fat_entries.append((start_off, end_off))
            fat_ptr += 8

        # 2. BTNF section (File Name Table)
        btnf_pos = btaf_pos + btaf_size
        btnf_magic, btnf_size = struct.unpack_from("<4sI", data, btnf_pos)
        if btnf_magic != cls.BTNF_MAGIC:
            raise ValueError(f"Expected BTNF header at 0x{btnf_pos:X}, got {btnf_magic}")

        # Parse file names if BTNF is not dummy (size > 16)
        names = cls._parse_btnf_names(data[btnf_pos:btnf_pos + btnf_size], file_count)

        # 3. GMIF section (Game Image File / Payload)
        gmif_pos = btnf_pos + btnf_size
        gmif_magic, gmif_size = struct.unpack_from("<4sI", data, gmif_pos)
        if gmif_magic != cls.GMIF_MAGIC:
            raise ValueError(f"Expected GMIF header at 0x{gmif_pos:X}, got {gmif_magic}")

        gmif_data_start = gmif_pos + 8

        entries: List[NARCEntry] = []
        for i, (start_off, end_off) in enumerate(fat_entries):
            file_bytes = data[gmif_data_start + start_off : gmif_data_start + end_off]
            name = names[i] if i < len(names) and names[i] else f"file_{i:04d}.bin"
            entries.append(NARCEntry(
                index=i,
                name=name,
                size=len(file_bytes),
                data=file_bytes
            ))

        return entries

    @classmethod
    def _parse_btnf_names(cls, btnf_data: bytes, file_count: int) -> List[str]:
        # Minimal dummy BTNF is 16 bytes: 4s (BTNF), I (size=16), 8 bytes table
        if len(btnf_data) <= 16:
            return [""] * file_count

        # For simplicity, fallback to empty names if complex directory tree
        # or parse sequential null-terminated strings
        return [""] * file_count

    @classmethod
    def pack(cls, input_dir: str, output_narc_path: str) -> None:
        """Packs a directory of files into a standard NDS NARC archive."""
        files = sorted(os.listdir(input_dir))
        file_payloads = []

        for f in files:
            full_path = os.path.join(input_dir, f)
            if os.path.isfile(full_path):
                with open(full_path, "rb") as f_in:
                    file_payloads.append(f_in.read())

        narc_bytes = cls.pack_files(file_payloads)
        with open(output_narc_path, "wb") as f_out:
            f_out.write(narc_bytes)

    @classmethod
    def pack_files(cls, files: List[bytes]) -> bytes:
        """Constructs a binary NARC archive from a list of byte payloads."""
        file_count = len(files)

        # 1. Build GMIF payload with 4-byte alignment
        gmif_body = bytearray()
        fat_offsets = []

        for f_bytes in files:
            # 4-byte align for each file
            while len(gmif_body) % 4 != 0:
                gmif_body.append(0xFF)

            start = len(gmif_body)
            gmif_body.extend(f_bytes)
            end = len(gmif_body)
            fat_offsets.append((start, end))

        # Pad GMIF body end to 4 bytes
        while len(gmif_body) % 4 != 0:
            gmif_body.append(0xFF)

        gmif_section = bytearray()
        gmif_section.extend(cls.GMIF_MAGIC)
        gmif_section.extend(struct.pack("<I", len(gmif_body) + 8))
        gmif_section.extend(gmif_body)

        # 2. Build BTAF section
        btaf_body = bytearray()
        btaf_body.extend(struct.pack("<HH", file_count, 0))
        for start, end in fat_offsets:
            btaf_body.extend(struct.pack("<II", start, end))

        btaf_section = bytearray()
        btaf_section.extend(cls.BTAF_MAGIC)
        btaf_section.extend(struct.pack("<I", len(btaf_body) + 8))
        btaf_section.extend(btaf_body)

        # 3. Build minimal dummy BTNF section (16 bytes)
        btnf_section = bytearray()
        btnf_section.extend(cls.BTNF_MAGIC)
        btnf_section.extend(struct.pack("<I", 16))
        # 8 bytes standard root directory record
        btnf_section.extend(struct.pack("<IHBB", 0x00000004, 0x0000, 0x01, 0x00))

        # 4. Build NARC Header
        header_size = 16
        total_size = header_size + len(btaf_section) + len(btnf_section) + len(gmif_section)

        header = bytearray()
        header.extend(cls.MAGIC)
        header.extend(struct.pack("<HHIHH", 0xFFFE, 0x0100, total_size, header_size, 3))

        return bytes(header + btaf_section + btnf_section + gmif_section)
