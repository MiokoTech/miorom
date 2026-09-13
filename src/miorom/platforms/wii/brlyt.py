"""
Nintendo Wii BRLYT (Binary Revolution Layout) low-level primitives.
Provides declarative binary structures (BinaryStruct) and section-level manipulation.
Powered by MioROM.
"""

from __future__ import annotations

from typing import List, Optional, Tuple, Union

from miorom.core.schema import (
    BinaryStruct,
    U8,
    U16,
    U32,
    Float32,
    RawBytes,
    FixedString,
)
from miorom.core.binary import BinaryReader, BinaryWriter
from miorom.errors import ParseError


class BRLYTHeaderStruct(BinaryStruct):
    """
    Standard 16-byte BRLYT file header.
    Format:
      magic (4s): 'RLYT'
      bom (u16): 0xFEFF (Big Endian)
      version (u16): 0x0008 or 0x000A
      file_size (u32): Total size in bytes
      header_size (u16): Header size (0x0010)
      section_count (u16): Total number of sections
    """
    _endian = ">"
    magic = RawBytes(4, default=b"RLYT")
    bom = U16(default=0xFEFF)
    version = U16(default=0x000A)
    file_size = U32(default=0)
    header_size = U16(default=16)
    section_count = U16(default=0)


class BRLYTSectionHeaderStruct(BinaryStruct):
    """Standard 8-byte chunk section header."""
    _endian = ">"
    magic = RawBytes(4, default=b"pan1")
    size = U32(default=0)


class BRLYTLyt1Struct(BinaryStruct):
    """
    Layout screen dimension section (lyt1) payload (without 8-byte section header).
    Total size: 12 bytes.
    """
    _endian = ">"
    centered = U8(default=1)
    pad = RawBytes(3, default=b"\x00\x00\x00")
    width = Float32(default=640.0)
    height = Float32(default=480.0)


class BRLYTPaneStruct(BinaryStruct):
    """
    Standard pane (pan1) payload (without 8-byte section header).
    Total payload size: 68 bytes (total section size: 76 bytes).
    """
    _endian = ">"
    flag = U8(default=1)
    origin = U8(default=0)
    alpha = U8(default=255)
    pad = U8(default=0)
    name = FixedString(16, default="")
    x = Float32(default=0.0)
    y = Float32(default=0.0)
    z = Float32(default=0.0)
    rot_x = Float32(default=0.0)
    rot_y = Float32(default=0.0)
    rot_z = Float32(default=0.0)
    pad2 = RawBytes(8, default=b"\x00" * 8)
    scale_x = Float32(default=1.0)
    scale_y = Float32(default=1.0)
    width = Float32(default=0.0)
    height = Float32(default=0.0)


class BRLYTPic1Struct(BinaryStruct):
    """
    Picture pane (pic1) payload (without 8-byte section header).
    Contains pane base fields plus vertex colors, material index, and UV coordinates.
    Total payload size: 120 bytes (total section size: 128 bytes).
    """
    _endian = ">"
    flag = U8(default=1)
    origin = U8(default=0)
    alpha = U8(default=255)
    pad = U8(default=0)
    name = FixedString(16, default="")
    x = Float32(default=0.0)
    y = Float32(default=0.0)
    z = Float32(default=0.0)
    rot_x = Float32(default=0.0)
    rot_y = Float32(default=0.0)
    rot_z = Float32(default=0.0)
    pad2 = RawBytes(8, default=b"\x00" * 8)
    scale_x = Float32(default=1.0)
    scale_y = Float32(default=1.0)
    width = Float32(default=0.0)
    height = Float32(default=0.0)
    # Picture-specific fields (52 bytes)
    vertex_colors = RawBytes(16, default=b"\xff" * 16)
    material_idx = U16(default=0)
    uv_count = U8(default=1)
    pad3 = U8(default=0)
    uv_coords = RawBytes(32, default=b"\x00" * 32)


def parse_brlyt_sections(data: bytes) -> Tuple[BRLYTHeaderStruct, List[Tuple[str, bytes]]]:
    """
    Parses a BRLYT file into its file header and a list of raw (magic, section_bytes) tuples.
    Each section_bytes contains the full section data including its 8-byte chunk header.
    """
    if len(data) < BRLYTHeaderStruct.sizeof():
        raise ParseError(f"Data too short for BRLYT header ({len(data)} bytes).")

    header = BRLYTHeaderStruct.from_bytes(data, offset=0)
    if header.magic != b"RLYT":
        raise ParseError(f"Invalid BRLYT magic: expected b'RLYT', got {header.magic!r}")

    sections: List[Tuple[str, bytes]] = []
    pos = header.header_size
    data_len = len(data)

    while pos < data_len:
        if pos + 8 > data_len:
            break
        sec_magic = data[pos : pos + 4].decode("latin1", errors="replace")
        sec_size = BinaryReader.unpack_u32(data, pos + 4, endian=">")
        if sec_size == 0 or pos + sec_size > data_len:
            break
        sec_bytes = data[pos : pos + sec_size]
        sections.append((sec_magic, sec_bytes))
        pos += sec_size

    return header, sections


def rebuild_brlyt(
    header: BRLYTHeaderStruct,
    sections: List[Tuple[str, bytes]],
) -> bytes:
    """
    Rebuilds BRLYT binary bytes from a header and modified list of sections.
    Updates file_size and section_count automatically.
    """
    writer = BinaryWriter(endian=">")
    total_sections = len(sections)
    body_bytes = b"".join(s_bytes for _, s_bytes in sections)
    total_size = header.header_size + len(body_bytes)

    updated_header = BRLYTHeaderStruct(
        magic=header.magic,
        bom=header.bom,
        version=header.version,
        file_size=total_size,
        header_size=header.header_size,
        section_count=total_sections,
    )

    writer.write_struct(updated_header)
    writer.write_bytes(body_bytes)
    return writer.to_bytes()


def find_pane(
    sections: List[Tuple[str, bytes]],
    pane_name: str,
) -> Optional[Tuple[int, str, Union[BRLYTPaneStruct, BRLYTPic1Struct]]]:
    """
    Searches sections for a pane with the matching name.
    Returns (section_index, magic, struct_instance) or None if not found.
    """
    for idx, (magic, sec_bytes) in enumerate(sections):
        if magic in ("pan1", "pic1"):
            if len(sec_bytes) >= 28:
                payload = sec_bytes[8:]
                if magic == "pan1":
                    struct_inst = BRLYTPaneStruct.from_bytes(payload)
                else:
                    struct_inst = BRLYTPic1Struct.from_bytes(payload)
                if struct_inst.name == pane_name:
                    return (idx, magic, struct_inst)
    return None


def update_pane(
    sections: List[Tuple[str, bytes]],
    pane_index: int,
    pane_struct: Union[BRLYTPaneStruct, BRLYTPic1Struct],
) -> List[Tuple[str, bytes]]:
    """
    Replaces the pane payload at pane_index with the serialized pane_struct.
    Returns the updated sections list.
    """
    magic, orig_bytes = sections[pane_index]
    new_payload = pane_struct.to_bytes()
    new_size = 8 + len(new_payload)
    sec_header = BRLYTSectionHeaderStruct(magic=magic.encode("latin1"), size=new_size)
    new_sec_bytes = sec_header.to_bytes() + new_payload
    sections[pane_index] = (magic, new_sec_bytes)
    return sections
