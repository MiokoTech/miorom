"""
miorom.platforms.nds.nsbmd
~~~~~~~~~~~~~~~~~~~~~~~~~~
Nintendo DS Nitro Basic Model (NSBMD / BMD0 / MDL0) Parser and Builder.
Standard 3D model container format used across Nintendo DS games
(e.g., Pokémon Platinum / HGSS / Black / White, Mario Kart DS, Super Mario 64 DS,
The Legend of Zelda: Phantom Hourglass, Animal Crossing: Wild World).

Pure Python implementation using MioROM declarative binary primitives with zero external dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from miorom.core.binary import BinaryReader, BinaryWriter
from miorom.core.schema import U16, U32, BinaryStruct, RawBytes
from miorom.errors import ParseError
from miorom.platforms.nds.nsbtx import (
    NitroDictEntry,
    NSBTXFile,
    NSBTXPalette,
    NSBTXTexture,
    build_nitro_dict,
    parse_nitro_dict,
)


class BMD0HeaderStruct(BinaryStruct):
    """
    16-byte Nitro Container Header for NSBMD 3D Models.
    Followed immediately by an array of 32-bit block offsets (block_count * 4 bytes).
    """

    _endian = "<"
    magic = RawBytes(4)         # b"BMD0"
    byte_order = U16()         # 0xFEFF (Little-endian marker)
    version = U16()            # 0x0100 (v1.0) or 0x0200 (v2.0)
    file_size = U32()          # Total size of the NSBMD container in bytes
    header_size = U16()        # 0x0010 (16 bytes)
    block_count = U16()        # 1 (MDL0 only) or 2 (MDL0 + TEX0)


class MDL0HeaderStruct(BinaryStruct):
    """
    Header of the MDL0 (Model Set) Section.
    """

    _endian = "<"
    magic = RawBytes(4)         # b"MDL0"
    section_size = U32()       # Total size of the MDL0 section in bytes


@dataclass
class NSBMDMaterial:
    """
    Represents a material definition tying geometry meshes to textures and palettes.
    """

    name: str
    texture_name: Optional[str] = None
    palette_name: Optional[str] = None
    alpha: int = 31
    flags: int = 0
    raw_params: bytes = b""


@dataclass
class NSBMDModel:
    """
    Represents a distinct 3D model inside the NSBMD container.
    """

    name: str
    materials: List[NSBMDMaterial] = field(default_factory=list)
    bone_names: List[str] = field(default_factory=list)
    raw_data: bytes = b""

    def get_used_texture_names(self) -> List[str]:
        """Returns all unique texture names required by this model's materials."""
        return sorted({m.texture_name for m in self.materials if m.texture_name})

    def get_used_palette_names(self) -> List[str]:
        """Returns all unique palette names required by this model's materials."""
        return sorted({m.palette_name for m in self.materials if m.palette_name})

    def get_material(self, name: str) -> Optional[NSBMDMaterial]:
        """Finds a material by name."""
        for mat in self.materials:
            if mat.name == name:
                return mat
        return None


class NSBMDFile:
    """
    Nintendo DS Nitro Basic Model (NSBMD / BMD0) container parser and builder.
    """

    MAGIC = b"BMD0"

    def __init__(
        self,
        models: Optional[List[NSBMDModel]] = None,
        tex0: Optional[NSBTXFile] = None,
        raw_mdl0: bytes = b"",
    ):
        self.models: List[NSBMDModel] = models or []
        self.tex0: Optional[NSBTXFile] = tex0
        self.raw_mdl0: bytes = raw_mdl0

    @classmethod
    def from_file(cls, filepath: str) -> NSBMDFile:
        """Parses an NSBMD file from disk."""
        with open(filepath, "rb") as f:
            data = f.read()
        return cls.from_bytes(data)

    @classmethod
    def from_bytes(cls, data: bytes) -> NSBMDFile:
        """Parses an NSBMD file from raw bytes."""
        if len(data) < BMD0HeaderStruct.sizeof():
            raise ParseError(
                f"Data too short for BMD0 header: expected at least {BMD0HeaderStruct.sizeof()} bytes, got {len(data)}."
            )

        hdr = BMD0HeaderStruct.from_bytes(data, offset=0)
        if hdr.magic != cls.MAGIC:
            raise ParseError(f"Invalid BMD0 magic: {hdr.magic!r} (expected b'BMD0').")
        if hdr.byte_order != 0xFEFF:
            raise ParseError(f"Invalid endianness marker: 0x{hdr.byte_order:04X} (expected 0xFEFF).")
        if hdr.block_count not in (1, 2):
            raise ParseError(f"Unsupported block count: {hdr.block_count} (expected 1 or 2).")

        offset_table_start = hdr.header_size
        offset_table_size = hdr.block_count * 4
        if offset_table_start + offset_table_size > len(data):
            raise ParseError("Data truncated before block offsets table.")

        reader = BinaryReader(data[offset_table_start:], endian="<")
        block_offsets = [reader.read_u32() for _ in range(hdr.block_count)]

        # 1. Parse MDL0 section (block 0)
        mdl0_offset = block_offsets[0]
        if mdl0_offset + MDL0HeaderStruct.sizeof() > len(data):
            raise ParseError(f"MDL0 offset 0x{mdl0_offset:X} exceeds file length {len(data)}.")

        mdl0_hdr = MDL0HeaderStruct.from_bytes(data, offset=mdl0_offset)
        if mdl0_hdr.magic != b"MDL0":
            raise ParseError(f"Invalid MDL0 section magic: {mdl0_hdr.magic!r} (expected b'MDL0').")

        mdl0_size = mdl0_hdr.section_size
        if mdl0_offset + mdl0_size > len(data):
            # Tolerate slight discrepancies if file ends normally
            mdl0_size = len(data) - mdl0_offset

        raw_mdl0 = data[mdl0_offset : mdl0_offset + mdl0_size]
        models = cls._parse_mdl0_models(raw_mdl0)

        # 2. Parse optional TEX0 section (block 1)
        tex0: Optional[NSBTXFile] = None
        if hdr.block_count >= 2:
            tex0_offset = block_offsets[1]
            if tex0_offset + 4 > len(data):
                raise ParseError(f"TEX0 offset 0x{tex0_offset:X} exceeds file length.")
            if data[tex0_offset : tex0_offset + 4] != b"TEX0":
                raise ParseError(
                    f"Invalid TEX0 magic at offset 0x{tex0_offset:X}: {data[tex0_offset:tex0_offset+4]!r}."
                )
            tex0 = NSBTXFile.from_tex0_bytes(data[tex0_offset:])

        return cls(models=models, tex0=tex0, raw_mdl0=raw_mdl0)

    @classmethod
    def _parse_mdl0_models(cls, raw_mdl0: bytes) -> List[NSBMDModel]:
        """
        Extracts model names, bone nodes, and materials from the MDL0 ModelSet section.
        """
        if len(raw_mdl0) < 16:
            return []

        # Model dictionary starts at offset 0x08
        model_dict_entries = parse_nitro_dict(raw_mdl0, 8)
        models: List[NSBMDModel] = []

        for entry in model_dict_entries:
            model_name = entry.name
            # Model data offset is relative to MDL0 start (usually u32 or u16 in entry.data)
            rel_offset = 0
            if len(entry.data) >= 4:
                rel_offset = int.from_bytes(entry.data[:4], "little")
            elif len(entry.data) >= 2:
                rel_offset = int.from_bytes(entry.data[:2], "little")

            materials: List[NSBMDMaterial] = []
            bone_names: List[str] = []
            model_raw = b""

            if 0 < rel_offset < len(raw_mdl0):
                # Parse Model Data structure
                m_slice = raw_mdl0[rel_offset:]
                if len(m_slice) >= 8:
                    model_size = int.from_bytes(m_slice[:4], "little")
                    if model_size > 0:
                        model_raw = m_slice[:model_size]
                    else:
                        model_raw = m_slice

                    # 1. Bone / Node dictionary
                    for cand_off in (8, 12):
                        if len(m_slice) >= cand_off + 4:
                            b_rel = int.from_bytes(m_slice[cand_off : cand_off + 4], "little")
                            if b_rel > 0:
                                for cand_pos in (rel_offset + b_rel, b_rel):
                                    if 0 < cand_pos < len(raw_mdl0):
                                        b_entries = parse_nitro_dict(raw_mdl0, cand_pos)
                                        if b_entries and not bone_names:
                                            bone_names = [b.name for b in b_entries]

                    # 2. Material dictionary
                    for cand_off in (12, 16):
                        if len(m_slice) >= cand_off + 4:
                            m_rel = int.from_bytes(m_slice[cand_off : cand_off + 4], "little")
                            if m_rel > 0:
                                for cand_pos in (rel_offset + m_rel, m_rel):
                                    if 0 < cand_pos < len(raw_mdl0):
                                        m_entries = parse_nitro_dict(raw_mdl0, cand_pos)
                                        if m_entries and not materials:
                                            for mat_e in m_entries:
                                                tex_name: Optional[str] = None
                                                pal_name: Optional[str] = None
                                                alpha = 31
                                                flags = 0

                                                if len(mat_e.data) >= 32:
                                                    tex_raw = mat_e.data[:16].split(b"\x00", 1)[0]
                                                    if tex_raw:
                                                        tex_name = tex_raw.decode("ascii", errors="replace").strip()
                                                    pal_raw = mat_e.data[16:32].split(b"\x00", 1)[0]
                                                    if pal_raw:
                                                        pal_name = pal_raw.decode("ascii", errors="replace").strip()
                                                elif len(mat_e.data) >= 4:
                                                    alpha = mat_e.data[0] & 0x1F

                                                materials.append(
                                                    NSBMDMaterial(
                                                        name=mat_e.name,
                                                        texture_name=tex_name,
                                                        palette_name=pal_name,
                                                        alpha=alpha,
                                                        flags=flags,
                                                        raw_params=mat_e.data,
                                                    )
                                                )

            models.append(
                NSBMDModel(
                    name=model_name,
                    materials=materials,
                    bone_names=bone_names,
                    raw_data=model_raw,
                )
            )

        return models

    @property
    def has_textures(self) -> bool:
        """Returns True if this NSBMD container holds an embedded TEX0 texture block."""
        return self.tex0 is not None and len(self.tex0.textures) > 0

    @property
    def model_names(self) -> List[str]:
        """Returns the names of all 3D models contained in this NSBMD file."""
        return [m.name for m in self.models]

    def get_model(self, name: str) -> Optional[NSBMDModel]:
        """Finds a 3D model by its name."""
        for m in self.models:
            if m.name == name:
                return m
        return None

    def get_all_used_texture_names(self) -> List[str]:
        """Returns a sorted list of unique texture names referenced across all models."""
        used: Set[str] = set()
        for m in self.models:
            used.update(m.get_used_texture_names())
        return sorted(used)

    def get_all_used_palette_names(self) -> List[str]:
        """Returns a sorted list of unique palette names referenced across all models."""
        used: Set[str] = set()
        for m in self.models:
            used.update(m.get_used_palette_names())
        return sorted(used)

    def validate_textures(self) -> Dict[str, Any]:
        """
        Audits texture and palette linkages between models' materials and the embedded TEX0 block.
        Returns a report identifying missing or unreferenced assets.
        """
        req_textures = set(self.get_all_used_texture_names())
        req_palettes = set(self.get_all_used_palette_names())

        avail_textures = set(self.tex0.get_texture_names()) if self.tex0 else set()
        avail_palettes = set(self.tex0.get_palette_names()) if self.tex0 else set()

        missing_textures = sorted(req_textures - avail_textures)
        missing_palettes = sorted(req_palettes - avail_palettes)
        unreferenced_textures = sorted(avail_textures - req_textures)

        is_valid = len(missing_textures) == 0 and len(missing_palettes) == 0
        return {
            "valid": is_valid,
            "missing_textures": missing_textures,
            "missing_palettes": missing_palettes,
            "unreferenced_textures": unreferenced_textures,
        }

    def export_nsbtx(self) -> NSBTXFile:
        """
        Exports the embedded TEX0 section as a standalone NSBTXFile instance.
        Raises ValueError if the model has no embedded textures.
        """
        if not self.has_textures or self.tex0 is None:
            raise ValueError("NSBMD model does not contain embedded textures.")
        # Return deep copy via serialization roundtrip
        return NSBTXFile.from_bytes(self.tex0.to_bytes())

    def export_nsbtx_file(self, filepath: str) -> None:
        """Saves the embedded textures to disk as a standalone .nsbtx file."""
        nsbtx = self.export_nsbtx()
        nsbtx.to_file(filepath)

    def import_nsbtx(self, nsbtx: NSBTXFile) -> None:
        """
        Imports or replaces the embedded texture block with a given NSBTXFile.
        """
        self.tex0 = nsbtx

    def replace_texture(
        self,
        name: str,
        new_texture: NSBTXTexture,
        new_palette: Optional[NSBTXPalette] = None,
    ) -> None:
        """
        Replaces or inserts a texture (and optional palette) within the embedded TEX0 block.
        """
        if self.tex0 is None:
            self.tex0 = NSBTXFile(
                textures=[new_texture],
                palettes=[new_palette] if new_palette else [],
            )
            return

        # Replace existing texture or append
        replaced = False
        for idx, tex in enumerate(self.tex0.textures):
            if tex.name == name:
                self.tex0.textures[idx] = new_texture
                replaced = True
                break
        if not replaced:
            self.tex0.textures.append(new_texture)

        # Replace existing palette or append
        if new_palette is not None:
            pal_replaced = False
            for idx, pal in enumerate(self.tex0.palettes):
                if pal.name == new_palette.name:
                    self.tex0.palettes[idx] = new_palette
                    pal_replaced = True
                    break
            if not pal_replaced:
                self.tex0.palettes.append(new_palette)

    def strip_textures(self) -> None:
        """
        Strips the embedded TEX0 section, converting the container into a single-block (MDL0-only) model.
        """
        self.tex0 = None

    def to_bytes(self) -> bytes:
        """
        Serializes the NSBMD container back to official Nintendo DS BMD0 binary format.
        Automatically manages block counts (1 vs 2) and recalculates all section offsets.
        """
        has_tex = self.has_textures
        block_count = 2 if has_tex else 1

        writer = BinaryWriter(endian="<")

        # 1. BMD0 Header Placeholder (16 bytes)
        bmd_hdr = BMD0HeaderStruct(
            magic=self.MAGIC,
            byte_order=0xFEFF,
            version=0x0100,
            file_size=0,         # placeholder
            header_size=16,
            block_count=block_count,
        )
        writer.write_struct(bmd_hdr)

        # 2. Block Offsets Table Placeholder
        # 1 block: 4 bytes (offset 0x10..0x14)
        # 2 blocks: 8 bytes (offset 0x10..0x18)
        offset_table_pos = writer.tell()
        for _ in range(block_count):
            writer.write_u32(0)

        # 3. Write MDL0 Section
        writer.align(4)
        mdl0_offset = writer.tell()

        if self.raw_mdl0:
            writer.write_bytes(self.raw_mdl0)
        else:
            # Generate minimal MDL0 section if empty
            mdl0_writer = BinaryWriter(endian="<")
            mdl0_writer.write_struct(MDL0HeaderStruct(magic=b"MDL0", section_size=16))
            mdl0_writer.pad(8, 0)
            writer.write_bytes(mdl0_writer.to_bytes())

        # 4. Write TEX0 Section if present
        tex0_offset = 0
        if has_tex and self.tex0 is not None:
            writer.align(4)
            tex0_offset = writer.tell()
            tex0_bytes = self.tex0.to_tex0_bytes()
            writer.write_bytes(tex0_bytes)

        total_file_size = writer.tell()

        # 5. Patch Header and Block Offsets Table
        with writer.at(0):
            patched_hdr = BMD0HeaderStruct(
                magic=self.MAGIC,
                byte_order=0xFEFF,
                version=0x0100,
                file_size=total_file_size,
                header_size=16,
                block_count=block_count,
            )
            writer.write_struct(patched_hdr)

        with writer.at(offset_table_pos):
            writer.write_u32(mdl0_offset)
            if block_count == 2:
                writer.write_u32(tex0_offset)

        return writer.to_bytes()

    def to_file(self, filepath: str) -> None:
        """Saves the NSBMD container to disk."""
        with open(filepath, "wb") as f:
            f.write(self.to_bytes())


def create_synthetic_nsbmd(
    model_name: str = "test_model",
    material_name: str = "mat_main",
    texture_name: Optional[str] = "tex_main",
    palette_name: Optional[str] = "pal_main",
    with_tex0: bool = True,
    texture_width: int = 16,
    texture_height: int = 16,
) -> bytes:
    """
    Synthesizes a valid Nintendo DS NSBMD (BMD0) binary container for unit testing
    and zero-dependency test fixtures.
    """
    # 1. Build Material Dictionary
    # In Nitro SDK, each material dict entry holds parameters
    mat_param = bytearray(32)
    if texture_name:
        mat_param[:16] = texture_name.encode("ascii")[:16].ljust(16, b"\x00")
    if palette_name:
        mat_param[16:32] = palette_name.encode("ascii")[:16].ljust(16, b"\x00")

    mat_entries = [NitroDictEntry(name=material_name, data=bytes(mat_param))]
    mat_dict_bytes = build_nitro_dict(mat_entries, 32)

    # 2. Build Model Data Block
    model_writer = BinaryWriter(endian="<")
    # ModelData placeholder (size=4, sbc_offset=4, bone_dict_offset=4, mat_dict_offset=4, shp_dict_offset=4)
    model_writer.pad(24, 0)

    # Bone dictionary at offset
    bone_entries = [NitroDictEntry(name="root_bone", data=b"\x00\x00\x00\x00")]
    bone_dict_bytes = build_nitro_dict(bone_entries, 4)

    bone_dict_rel = model_writer.tell()
    model_writer.write_bytes(bone_dict_bytes)

    # Material dictionary
    model_writer.align(4)
    mat_dict_rel = model_writer.tell()
    model_writer.write_bytes(mat_dict_bytes)

    # Dummy FIFO display list commands (BEGIN_VTXS 0x40, COLOR, END_VTXS)
    model_writer.align(4)
    model_writer.write_bytes(b"\x40\x00\x00\x00\x11\x22\x33\x44\x40\x00\x00\x01\x00\x00\x00\x00")

    model_data_size = model_writer.tell()

    # Patch ModelData header
    with model_writer.at(0):
        model_writer.write_u32(model_data_size)  # model_size
        model_writer.write_u32(0)                # sbc_offset
        model_writer.write_u32(bone_dict_rel)    # bone_dict_offset
        model_writer.write_u32(mat_dict_rel)     # mat_dict_offset
        model_writer.write_u32(0)                # shp_dict_offset
        model_writer.write_u32(0)                # reserved

    model_bytes = model_writer.to_bytes()

    # 3. Build ModelSet Dictionary at offset 0x08
    # Model Dict Entry data points to ModelData relative offset in MDL0
    # MDL0 header = 8 bytes. Model Dict follows at 8.
    # ModelData will follow right after Model Dict.
    dummy_dict = build_nitro_dict([NitroDictEntry(name=model_name, data=b"\x00\x00\x00\x00")], 4)
    model_data_offset_in_mdl0 = 8 + len(dummy_dict)

    # Re-build with accurate relative offset
    model_dict_entry_data = model_data_offset_in_mdl0.to_bytes(4, "little")
    model_dict_bytes = build_nitro_dict([NitroDictEntry(name=model_name, data=model_dict_entry_data)], 4)

    # 4. Assemble MDL0 section
    mdl0_writer = BinaryWriter(endian="<")
    mdl0_writer.write_struct(MDL0HeaderStruct(magic=b"MDL0", section_size=0))  # placeholder
    mdl0_writer.write_bytes(model_dict_bytes)
    mdl0_writer.write_bytes(model_bytes)

    mdl0_total_size = mdl0_writer.tell()
    with mdl0_writer.at(0):
        mdl0_writer.write_struct(MDL0HeaderStruct(magic=b"MDL0", section_size=mdl0_total_size))

    raw_mdl0 = mdl0_writer.to_bytes()

    # 5. Build TEX0 if requested
    tex0: Optional[NSBTXFile] = None
    if with_tex0 and texture_name:
        # Create 4bpp texture
        num_pixels = texture_width * texture_height
        raw_tex_data = bytes([0x12] * (num_pixels // 2))
        tex_obj = NSBTXTexture(
            name=texture_name,
            width=texture_width,
            height=texture_height,
            format_id=3,  # Palette 16 (4 bpp)
            color0_transparent=False,
            raw_data=raw_tex_data,
        )
        pal_name = palette_name or "pal_main"
        pal_obj = NSBTXPalette(
            name=pal_name,
            colors=[(i * 16, i * 16, i * 16) for i in range(16)],
        )
        tex0 = NSBTXFile(textures=[tex_obj], palettes=[pal_obj])

    # 6. Parse and serialize via NSBMDFile
    bmd = NSBMDFile(raw_mdl0=raw_mdl0, tex0=tex0)
    # Parse models from raw_mdl0
    bmd.models = NSBMDFile._parse_mdl0_models(raw_mdl0)
    return bmd.to_bytes()
