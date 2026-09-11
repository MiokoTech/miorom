"""
miorom.platforms.nds.nsbtx
~~~~~~~~~~~~~~~~~~~~~~~~~~
Nintendo DS Nitro Basic Texture (NSBTX / BTX0 / TEX0) Parser and Builder.
Standard 3D texture container format used in Nintendo DS games
(e.g., Pokémon Platinum / HGSS / Black / White, Super Mario 64 DS, Mario Kart DS).

Pure Python implementation using MioROM declarative binary primitives.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Dict, List, Optional, Tuple, Union

from miorom.core.binary import BinaryReader, BinaryWriter
from miorom.core.schema import BinaryStruct, RawBytes, U16, U32
from miorom.errors import ParseError
from miorom.result import MioRomResult

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


# Texel format names on Nintendo DS 3D hardware
NSBTX_FORMAT_NAMES = {
    0: "None",
    1: "A3I5",               # 8-bit (3-bit alpha, 5-bit color index)
    2: "Palette 4",          # 2 bpp (4 colors)
    3: "Palette 16",         # 4 bpp (16 colors)
    4: "Palette 256",        # 8 bpp (256 colors)
    5: "4x4 Texel Comp",     # Block compression
    6: "A5I3",               # 8-bit (5-bit alpha, 3-bit color index)
    7: "Direct Color",       # 16-bit direct RGB555
}


class BTX0HeaderStruct(BinaryStruct):
    _endian = "<"
    magic = RawBytes(4)         # b"BTX0"
    byte_order = U16()         # 0xFEFF
    version = U16()            # 0x0100 or 0x0101
    file_size = U32()
    header_size = U16()        # 0x0010
    block_count = U16()        # 1
    tex0_offset = U32()        # 0x0014


class TEX0HeaderStruct(BinaryStruct):
    _endian = "<"
    magic = RawBytes(4)                     # b"TEX0"
    section_size = U32()
    vram_tex_offset = U16()
    vram_tex_size = U16()
    _reserved = U32()
    vram_tex_real_offset = U32()
    texture_dict_offset = U32()
    texture_data_offset = U32()
    texture_data_size = U32()
    compressed_tex_dict_offset = U32()
    compressed_tex_data_offset = U32()
    compressed_tex_data_size = U32()
    compressed_tex_info_offset = U32()
    compressed_tex_info_size = U32()
    palette_dict_offset = U32()
    palette_data_offset = U32()
    palette_data_size = U32()


@dataclass
class NitroDictEntry:
    name: str
    data: bytes


def parse_nitro_dict(raw: bytes, offset: int) -> List[NitroDictEntry]:
    """Parses a standard Nitro Patricia Tree Dictionary structure."""
    if offset + 8 > len(raw):
        return []
    num_entries = raw[offset + 1]
    if num_entries == 0:
        return []

    data_offset = raw[offset + 6] | (raw[offset + 7] << 8)
    dp = offset + data_offset
    if dp + 4 > len(raw):
        return []

    entry_siz = raw[dp] | (raw[dp + 1] << 8)
    entries_data_pos = dp + 4
    names_pos = entries_data_pos + num_entries * entry_siz

    entries: List[NitroDictEntry] = []
    for i in range(num_entries):
        np = names_pos + i * 16
        name_raw = raw[np : np + 16]
        name = name_raw.split(b"\x00", 1)[0].decode("ascii", errors="replace")

        edp = entries_data_pos + i * entry_siz
        data = raw[edp : edp + entry_siz]
        entries.append(NitroDictEntry(name=name, data=data))

    return entries


def build_nitro_dict(entries: List[NitroDictEntry], entry_siz: int) -> bytes:
    """Serializes a standard Nitro Patricia Tree Dictionary structure."""
    num_entries = len(entries)
    if num_entries == 0:
        return bytes([0, 0, 8, 0, 8, 0, 8, 0])

    tree_bytes = bytearray()
    tree_bytes.extend([0x7F, 1, 0, 0])  # root entry
    for i in range(num_entries):
        tree_bytes.extend([0, i, i, i])

    tree_offset = 8
    data_offset = 8 + len(tree_bytes)
    data_sec_size = 4 + num_entries * entry_siz

    data_bytes = bytearray()
    data_bytes.extend([(entry_siz & 0xFF), (entry_siz >> 8) & 0xFF])
    data_bytes.extend([(data_sec_size & 0xFF), (data_sec_size >> 8) & 0xFF])
    for e in entries:
        pad_data = e.data.ljust(entry_siz, b"\x00")[:entry_siz]
        data_bytes.extend(pad_data)

    names_bytes = bytearray()
    for e in entries:
        name_ascii = e.name.encode("ascii", errors="replace")[:16].ljust(16, b"\x00")
        names_bytes.extend(name_ascii)

    total_size = 8 + len(tree_bytes) + len(data_bytes) + len(names_bytes)

    hdr = bytearray()
    hdr.append(0)  # dummy
    hdr.append(num_entries)
    hdr.extend([(total_size & 0xFF), (total_size >> 8) & 0xFF])
    hdr.extend([(tree_offset & 0xFF), (tree_offset >> 8) & 0xFF])
    hdr.extend([(data_offset & 0xFF), (data_offset >> 8) & 0xFF])

    return bytes(hdr + tree_bytes + data_bytes + names_bytes)


def decode_bgr555_color(val: int) -> Tuple[int, int, int]:
    r = (val & 0x1F) * 255 // 31
    g = ((val >> 5) & 0x1F) * 255 // 31
    b = ((val >> 10) & 0x1F) * 255 // 31
    return (r, g, b)


def encode_bgr555_color(r: int, g: int, b: int) -> int:
    r5 = (r * 31 + 127) // 255
    g5 = (g * 31 + 127) // 255
    b5 = (b * 31 + 127) // 255
    return (r5 & 0x1F) | ((g5 & 0x1F) << 5) | ((b5 & 0x1F) << 10)


@dataclass
class NSBTXTexture:
    name: str
    width: int
    height: int
    format_id: int
    color0_transparent: bool
    raw_data: bytes
    extra_info: int = 0

    @property
    def format_name(self) -> str:
        return NSBTX_FORMAT_NAMES.get(self.format_id, f"Format {self.format_id}")


@dataclass
class NSBTXPalette:
    name: str
    colors: List[Tuple[int, int, int]]


class NSBTXFile:
    """
    Nintendo DS Nitro Basic Texture (NSBTX / BTX0) file parser and builder.
    """

    MAGIC = b"BTX0"

    def __init__(
        self,
        textures: Optional[List[NSBTXTexture]] = None,
        palettes: Optional[List[NSBTXPalette]] = None,
    ):
        self.textures: List[NSBTXTexture] = textures or []
        self.palettes: List[NSBTXPalette] = palettes or []

    @classmethod
    def from_file(cls, filepath: str) -> "NSBTXFile":
        with open(filepath, "rb") as f:
            data = f.read()
        return cls.from_bytes(data)

    @classmethod
    def from_bytes(cls, data: bytes) -> "NSBTXFile":
        if len(data) < BTX0HeaderStruct.sizeof():
            raise ParseError("Data too short for BTX0 header.")

        btx_hdr = BTX0HeaderStruct.from_bytes(data, offset=0)
        if btx_hdr.magic != cls.MAGIC:
            raise ParseError(f"Invalid BTX0 magic: {btx_hdr.magic!r} (expected b'BTX0').")

        tex0_offset = btx_hdr.tex0_offset
        if tex0_offset >= len(data) or data[tex0_offset : tex0_offset + 4] != b"TEX0":
            raise ParseError(f"Invalid or missing TEX0 section at offset 0x{tex0_offset:X}.")

        tex0_data = data[tex0_offset:]
        tex0_hdr = TEX0HeaderStruct.from_bytes(tex0_data, offset=0)

        # 1. Parse Palettes
        palettes: List[NSBTXPalette] = []
        if tex0_hdr.palette_dict_offset > 0:
            pal_dict_entries = parse_nitro_dict(tex0_data, tex0_hdr.palette_dict_offset)
            pal_raw = tex0_data[tex0_hdr.palette_data_offset :]
            for entry in pal_dict_entries:
                pal_offset = 0
                if len(entry.data) >= 2:
                    pal_offset = (entry.data[0] | (entry.data[1] << 8)) * 8
                # Read 256 colors maximum or until end of pal_raw
                cur_pal = pal_raw[pal_offset:]
                num_colors = min(256, len(cur_pal) // 2)
                colors: List[Tuple[int, int, int]] = []
                for ci in range(num_colors):
                    val = cur_pal[ci * 2] | (cur_pal[ci * 2 + 1] << 8)
                    colors.append(decode_bgr555_color(val))
                palettes.append(NSBTXPalette(name=entry.name, colors=colors))

        # 2. Parse Textures
        textures: List[NSBTXTexture] = []
        if tex0_hdr.texture_dict_offset > 0:
            tex_dict_entries = parse_nitro_dict(tex0_data, tex0_hdr.texture_dict_offset)
            tex_raw = tex0_data[tex0_hdr.texture_data_offset :]

            for entry in tex_dict_entries:
                if len(entry.data) < 8:
                    continue
                param = (
                    entry.data[0]
                    | (entry.data[1] << 8)
                    | (entry.data[2] << 16)
                    | (entry.data[3] << 24)
                )
                extra = (
                    entry.data[4]
                    | (entry.data[5] << 8)
                    | (entry.data[6] << 16)
                    | (entry.data[7] << 24)
                )

                tex_offset = (param & 0xFFFF) * 8
                s_size = (param >> 20) & 7
                t_size = (param >> 23) & 7
                width = 8 << s_size
                height = 8 << t_size
                format_id = (param >> 26) & 7
                color0_trans = bool((param >> 29) & 1)

                # Calculate byte size
                if format_id == 1:       # A3I5 (1 byte/pixel)
                    data_size = width * height
                elif format_id == 2:     # 2 bpp (4 pixels/byte)
                    data_size = (width * height + 3) // 4
                elif format_id == 3:     # 4 bpp (2 pixels/byte)
                    data_size = (width * height + 1) // 2
                elif format_id == 4:     # 8 bpp (1 byte/pixel)
                    data_size = width * height
                elif format_id == 6:     # A5I3 (1 byte/pixel)
                    data_size = width * height
                elif format_id == 7:     # Direct Color (2 bytes/pixel)
                    data_size = width * height * 2
                else:
                    data_size = width * height

                raw_bytes = tex_raw[tex_offset : tex_offset + data_size]
                textures.append(
                    NSBTXTexture(
                        name=entry.name,
                        width=width,
                        height=height,
                        format_id=format_id,
                        color0_transparent=color0_trans,
                        raw_data=raw_bytes,
                        extra_info=extra,
                    )
                )

        return cls(textures=textures, palettes=palettes)

    def get_texture_names(self) -> List[str]:
        return [t.name for t in self.textures]

    def get_palette_names(self) -> List[str]:
        return [p.name for p in self.palettes]

    def get_texture(self, name: str) -> Optional[NSBTXTexture]:
        for t in self.textures:
            if t.name == name:
                return t
        return None

    def get_palette(self, name: str) -> Optional[NSBTXPalette]:
        for p in self.palettes:
            if p.name == name:
                return p
        return None

    def decode_rgba(self, texture_name: str, palette_name: Optional[str] = None) -> bytes:
        """
        Decodes the specified texture into linear uncompressed RGBA8888 byte stream.
        """
        tex = self.get_texture(texture_name)
        if tex is None:
            raise KeyError(f"Texture '{texture_name}' not found in NSBTX.")

        pal = None
        if palette_name:
            pal = self.get_palette(palette_name)
        if pal is None and self.palettes:
            # Fallback: try match by name or pick first palette
            pal = self.get_palette(texture_name) or self.palettes[0]

        w, h = tex.width, tex.height
        out = bytearray(w * h * 4)
        raw = tex.raw_data
        fmt = tex.format_id

        if fmt == 1:  # A3I5 (3-bit alpha, 5-bit index)
            pal_colors = pal.colors if pal else [(i * 8, i * 8, i * 8) for i in range(32)]
            for i in range(min(w * h, len(raw))):
                b = raw[i]
                alpha3 = (b >> 5) & 7
                alpha = alpha3 * 255 // 7
                idx = b & 0x1F
                r, g, b_col = pal_colors[idx] if idx < len(pal_colors) else (0, 0, 0)
                out[i * 4 : i * 4 + 4] = bytes([r, g, b_col, alpha])

        elif fmt == 2:  # Palette 4 (2 bpp)
            pal_colors = pal.colors if pal else [(0, 0, 0), (85, 85, 85), (170, 170, 170), (255, 255, 255)]
            pix_idx = 0
            for b in raw:
                for shift in (0, 2, 4, 6):
                    if pix_idx >= w * h:
                        break
                    idx = (b >> shift) & 3
                    r, g, b_col = pal_colors[idx] if idx < len(pal_colors) else (0, 0, 0)
                    alpha = 0 if (idx == 0 and tex.color0_transparent) else 255
                    out[pix_idx * 4 : pix_idx * 4 + 4] = bytes([r, g, b_col, alpha])
                    pix_idx += 1

        elif fmt == 3:  # Palette 16 (4 bpp)
            pal_colors = pal.colors if pal else [(i * 17, i * 17, i * 17) for i in range(16)]
            pix_idx = 0
            for b in raw:
                for idx in (b & 0x0F, (b >> 4) & 0x0F):
                    if pix_idx >= w * h:
                        break
                    r, g, b_col = pal_colors[idx] if idx < len(pal_colors) else (0, 0, 0)
                    alpha = 0 if (idx == 0 and tex.color0_transparent) else 255
                    out[pix_idx * 4 : pix_idx * 4 + 4] = bytes([r, g, b_col, alpha])
                    pix_idx += 1

        elif fmt == 4:  # Palette 256 (8 bpp)
            pal_colors = pal.colors if pal else [(i, i, i) for i in range(256)]
            for i in range(min(w * h, len(raw))):
                idx = raw[i]
                r, g, b_col = pal_colors[idx] if idx < len(pal_colors) else (0, 0, 0)
                alpha = 0 if (idx == 0 and tex.color0_transparent) else 255
                out[i * 4 : i * 4 + 4] = bytes([r, g, b_col, alpha])

        elif fmt == 6:  # A5I3 (5-bit alpha, 3-bit index)
            pal_colors = pal.colors if pal else [(i * 36, i * 36, i * 36) for i in range(8)]
            for i in range(min(w * h, len(raw))):
                b = raw[i]
                alpha5 = (b >> 3) & 0x1F
                alpha = alpha5 * 255 // 31
                idx = b & 7
                r, g, b_col = pal_colors[idx] if idx < len(pal_colors) else (0, 0, 0)
                out[i * 4 : i * 4 + 4] = bytes([r, g, b_col, alpha])

        elif fmt == 7:  # Direct Color (16-bit RGB555 + 1-bit alpha)
            for i in range(min(w * h, len(raw) // 2)):
                val = raw[i * 2] | (raw[i * 2 + 1] << 8)
                r = (val & 0x1F) * 255 // 31
                g = ((val >> 5) & 0x1F) * 255 // 31
                b = ((val >> 10) & 0x1F) * 255 // 31
                alpha = 255 if (val & 0x8000) else 0
                out[i * 4 : i * 4 + 4] = bytes([r, g, b, alpha])

        else:
            # Fallback
            for i in range(min(w * h, len(raw))):
                out[i * 4 : i * 4 + 4] = bytes([raw[i], raw[i], raw[i], 255])

        return bytes(out)

    def to_image(
        self, texture_name: str, palette_name: Optional[str] = None
    ) -> "Image.Image":
        """Renders the specified texture to a PIL Image."""
        if not HAS_PIL:
            raise ImportError("Pillow is required for NSBTXFile.to_image().")

        tex = self.get_texture(texture_name)
        if tex is None:
            raise KeyError(f"Texture '{texture_name}' not found.")

        rgba = self.decode_rgba(texture_name, palette_name)
        return Image.frombytes("RGBA", (tex.width, tex.height), rgba)

    def to_bytes(self) -> bytes:
        """
        Serializes the NSBTX container back to standard Nintendo DS BTX0/TEX0 binary format.
        """
        writer = BinaryWriter(endian="<")

        # BTX0 header placeholder
        btx_hdr = BTX0HeaderStruct(
            magic=self.MAGIC,
            byte_order=0xFEFF,
            version=0x0100,
            file_size=0,         # placeholder
            header_size=16,
            block_count=1,
            tex0_offset=20,      # TEX0 starts at 0x14
        )
        writer.write_struct(btx_hdr)
        tex0_start = writer.tell()

        # 2. Build Palette Data & Dict
        pal_data_writer = BinaryWriter(endian="<")
        pal_dict_entries: List[NitroDictEntry] = []

        for pal in self.palettes:
            pal_offset = pal_data_writer.tell()
            pal_data_writer.align(8)
            pal_offset = pal_data_writer.tell()

            # Store offset/8 in entry data (u16)
            entry_data = bytearray()
            val_div8 = pal_offset // 8
            entry_data.extend([(val_div8 & 0xFF), ((val_div8 >> 8) & 0xFF), 0, 0])
            pal_dict_entries.append(NitroDictEntry(name=pal.name, data=bytes(entry_data)))

            for r, g, b in pal.colors:
                c16 = encode_bgr555_color(r, g, b)
                pal_data_writer.write_u16(c16)

        pal_raw_data = pal_data_writer.to_bytes()
        pal_dict_bytes = build_nitro_dict(pal_dict_entries, 4)

        # 3. Build Texture Data & Dict
        tex_data_writer = BinaryWriter(endian="<")
        tex_dict_entries: List[NitroDictEntry] = []

        for tex in self.textures:
            tex_data_writer.align(8)
            tex_offset = tex_data_writer.tell()

            # Encode TEXIMAGE_PARAM:
            # 0-15: offset / 8
            # 20-22: s_size (width = 8 << s_size)
            # 23-25: t_size (height = 8 << t_size)
            # 26-28: format_id
            # 29: color0_transparent
            s_size = max(0, (tex.width // 8).bit_length() - 1)
            t_size = max(0, (tex.height // 8).bit_length() - 1)
            param = (
                (tex_offset // 8) & 0xFFFF
                | (s_size << 20)
                | (t_size << 23)
                | (tex.format_id << 26)
                | ((1 if tex.color0_transparent else 0) << 29)
            )

            entry_data = bytearray()
            entry_data.extend([
                param & 0xFF,
                (param >> 8) & 0xFF,
                (param >> 16) & 0xFF,
                (param >> 24) & 0xFF,
                tex.extra_info & 0xFF,
                (tex.extra_info >> 8) & 0xFF,
                (tex.extra_info >> 16) & 0xFF,
                (tex.extra_info >> 24) & 0xFF,
            ])
            tex_dict_entries.append(NitroDictEntry(name=tex.name, data=bytes(entry_data)))
            tex_data_writer.write_bytes(tex.raw_data)

        tex_raw_data = tex_data_writer.to_bytes()
        tex_dict_bytes = build_nitro_dict(tex_dict_entries, 8)

        # 4. Assemble TEX0 Block
        tex0_writer = BinaryWriter(endian="<")
        # Placeholder for TEX0HeaderStruct (64 bytes)
        tex0_writer.pad(64, 0)

        # Place Texture Dict at 0x40 (rel to TEX0)
        tex0_writer.align(4)
        tex_dict_rel_offset = tex0_writer.tell()
        tex0_writer.write_bytes(tex_dict_bytes)

        # Place Palette Dict
        tex0_writer.align(4)
        pal_dict_rel_offset = tex0_writer.tell()
        tex0_writer.write_bytes(pal_dict_bytes)

        # Place Texture Data aligned to 8 bytes
        tex0_writer.align(8)
        tex_data_rel_offset = tex0_writer.tell()
        tex0_writer.write_bytes(tex_raw_data)

        # Place Palette Data aligned to 8 bytes
        tex0_writer.align(8)
        pal_data_rel_offset = tex0_writer.tell()
        tex0_writer.write_bytes(pal_raw_data)

        tex0_total_size = tex0_writer.tell()

        # Patch TEX0 header at offset 0
        with tex0_writer.at(0):
            t_hdr = TEX0HeaderStruct(
                magic=b"TEX0",
                section_size=tex0_total_size,
                vram_tex_offset=0,
                vram_tex_size=len(tex_raw_data) // 8,
                _reserved=0,
                vram_tex_real_offset=0,
                texture_dict_offset=tex_dict_rel_offset,
                texture_data_offset=tex_data_rel_offset,
                texture_data_size=len(tex_raw_data),
                compressed_tex_dict_offset=0,
                compressed_tex_data_offset=0,
                compressed_tex_data_size=0,
                compressed_tex_info_offset=0,
                compressed_tex_info_size=0,
                palette_dict_offset=pal_dict_rel_offset,
                palette_data_offset=pal_data_rel_offset,
                palette_data_size=len(pal_raw_data),
            )
            tex0_writer.write_struct(t_hdr)

        writer.write_bytes(tex0_writer.to_bytes())
        total_file_size = writer.tell()

        # Patch BTX0 header file_size
        with writer.at(0):
            patched_btx = BTX0HeaderStruct(
                magic=self.MAGIC,
                byte_order=0xFEFF,
                version=0x0100,
                file_size=total_file_size,
                header_size=16,
                block_count=1,
                tex0_offset=20,
            )
            writer.write_struct(patched_btx)

        return writer.to_bytes()

    def to_file(self, filepath: str) -> None:
        with open(filepath, "wb") as f:
            f.write(self.to_bytes())
