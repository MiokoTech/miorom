from miorom.result import MioRomResult
import os
from miorom.errors import ParseError
from dataclasses import dataclass
from miorom.core.schema import BinaryStruct, FixedString, RawBytes, U8, U16, U32
from typing import List, Optional, Tuple, Dict, Any

from miorom.security import sanitize_extract_path


@dataclass
class NARCEntry(MioRomResult):
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

    class _Header(BinaryStruct):
        _endian = "<"
        magic = FixedString(4)
        bom = U16()
        version = U16()
        file_size = U32()
        header_size = U16()
        num_chunks = U16()

    class _SectionHeader(BinaryStruct):
        _endian = "<"
        magic = RawBytes(4)
        size = U32()

    class _FatHeader(BinaryStruct):
        _endian = "<"
        file_count = U16()
        _reserved = U16()

    class _FatEntry(BinaryStruct):
        _endian = "<"
        start_offset = U32()
        end_offset = U32()

    class _BtNFRoot(BinaryStruct):
        _endian = "<"
        root_offset = U32()
        first_file_id = U16()
        directory_count = U8()
        _reserved = U8()

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
            file_path = sanitize_extract_path(output_dir, filename)
            with open(file_path, "wb") as f_out:
                f_out.write(e.data)
            extracted.append(file_path)

        return extracted

    @classmethod
    def unpack_entries(cls, data: bytes) -> List[NARCEntry]:
        """Parses all file entries from NARC binary data."""
        if not cls.is_narc(data):
            raise ParseError("Data is not a valid Nintendo NARC archive.")

        # NARC header (16 bytes)
        narc_header = cls._Header.from_bytes(data, offset=0)
        bom = narc_header.bom
        version = narc_header.version
        file_size = narc_header.file_size
        header_size = narc_header.header_size
        num_chunks = narc_header.num_chunks

        # File Allocation Table (BTAF)
        btaf_pos = header_size
        btaf_header = cls._SectionHeader.from_bytes(data, offset=btaf_pos)
        btaf_magic = btaf_header.magic
        btaf_size = btaf_header.size
        if btaf_magic != cls.BTAF_MAGIC:
            raise ParseError(f"Expected BTAF header at 0x{btaf_pos:X}, got {btaf_magic}")

        fat_header = cls._FatHeader.from_bytes(data, offset=btaf_pos + 8)
        file_count = fat_header.file_count
        fat_entries = []
        fat_ptr = btaf_pos + 12

        for i in range(file_count):
            fat_entry = cls._FatEntry.from_bytes(data, offset=fat_ptr)
            start_off = fat_entry.start_offset
            end_off = fat_entry.end_offset
            fat_entries.append((start_off, end_off))
            fat_ptr += 8

        # File Name Table (BTNF)
        btnf_pos = btaf_pos + btaf_size
        btnf_header = cls._SectionHeader.from_bytes(data, offset=btnf_pos)
        btnf_magic = btnf_header.magic
        btnf_size = btnf_header.size
        if btnf_magic != cls.BTNF_MAGIC:
            raise ParseError(f"Expected BTNF header at 0x{btnf_pos:X}, got {btnf_magic}")

        # Parse file names if BTNF is not dummy (size > 16)
        names = cls._parse_btnf_names(data[btnf_pos:btnf_pos + btnf_size], file_count)

        # Image payload (GMIF)
        gmif_pos = btnf_pos + btnf_size
        gmif_header = cls._SectionHeader.from_bytes(data, offset=gmif_pos)
        gmif_magic = gmif_header.magic
        gmif_size = gmif_header.size
        if gmif_magic != cls.GMIF_MAGIC:
            raise ParseError(f"Expected GMIF header at 0x{gmif_pos:X}, got {gmif_magic}")

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
        # Dummy BTNF check (<= 16 bytes)
        if len(btnf_data) <= 16:
            return [""] * file_count

        # Fallback to empty names on complex tree
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

        # Build GMIF payload with 4-byte alignment
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
        gmif_section.extend(cls._SectionHeader(magic=cls.GMIF_MAGIC, size=len(gmif_body) + 8).to_bytes()[4:])
        gmif_section.extend(gmif_body)

        # Build BTAF section
        btaf_body = bytearray()
        btaf_body.extend(cls._FatHeader(file_count=file_count, _reserved=0).to_bytes())
        for start, end in fat_offsets:
            btaf_body.extend(cls._FatEntry(start_offset=start, end_offset=end).to_bytes())

        btaf_section = bytearray()
        btaf_section.extend(cls.BTAF_MAGIC)
        btaf_section.extend(cls._SectionHeader(magic=cls.BTAF_MAGIC, size=len(btaf_body) + 8).to_bytes()[4:])
        btaf_section.extend(btaf_body)

        # Build minimal BTNF section
        btnf_section = bytearray()
        btnf_section.extend(cls.BTNF_MAGIC)
        btnf_section.extend(cls._SectionHeader(magic=cls.BTNF_MAGIC, size=16).to_bytes()[4:])
        # 8 bytes standard root directory record
        btnf_section.extend(cls._BtNFRoot(root_offset=4, first_file_id=0, directory_count=1, _reserved=0).to_bytes())

        # Build NARC header
        header_size = 16
        total_size = header_size + len(btaf_section) + len(btnf_section) + len(gmif_section)

        header = bytearray()
        header.extend(cls.MAGIC)
        narc_header = cls._Header(
            magic=cls.MAGIC,
            bom=0xFFFE,
            version=0x0100,
            file_size=total_size,
            header_size=header_size,
            num_chunks=3,
        )
        header.extend(narc_header.to_bytes()[4:])

        return bytes(header + btaf_section + btnf_section + gmif_section)
