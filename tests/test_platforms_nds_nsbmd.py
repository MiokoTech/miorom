"""
Unit tests for Nintendo DS NSBMD (BMD0/MDL0) 3D Model Engine.
Tests container parsing, model hierarchy inspection, texture bridge operations,
and NDSRom integration with 100% zero external dependencies.
"""

import os
import tempfile

import pytest

from miorom.errors import ParseError
from miorom.platforms.nds.nsbmd import (
    BMD0HeaderStruct,
    NSBMDFile,
    NSBMDMaterial,
    create_synthetic_nsbmd,
)
from miorom.platforms.nds.nsbtx import NSBTXFile, NSBTXPalette, NSBTXTexture
from miorom.platforms.nds.rom import NDSRom


def test_synthetic_nsbmd_creation_and_header():
    """Verify synthetic NSBMD container generation with 2 blocks (MDL0 + TEX0)."""
    raw_bmd = create_synthetic_nsbmd(
        model_name="mario_model",
        material_name="mat_overalls",
        texture_name="tex_denim",
        palette_name="pal_denim",
        with_tex0=True,
    )
    assert len(raw_bmd) > BMD0HeaderStruct.sizeof()

    bmd = NSBMDFile.from_bytes(raw_bmd)
    assert bmd.MAGIC == b"BMD0"
    assert bmd.has_textures is True
    assert "mario_model" in bmd.model_names


def test_nsbmd_single_block_mdl0_only():
    """Verify NSBMD container with only 1 block (MDL0 only, no embedded textures)."""
    raw_bmd = create_synthetic_nsbmd(
        model_name="prop_box",
        material_name="mat_wood",
        texture_name=None,
        with_tex0=False,
    )
    bmd = NSBMDFile.from_bytes(raw_bmd)
    assert bmd.has_textures is False
    assert bmd.tex0 is None
    assert bmd.model_names == ["prop_box"]

    # Exporting textures should raise ValueError
    with pytest.raises(ValueError, match="does not contain embedded textures"):
        bmd.export_nsbtx()


def test_model_hierarchy_and_material_inspection():
    """Verify model hierarchy inspection, bone nodes, and material-to-texture references."""
    raw_bmd = create_synthetic_nsbmd(
        model_name="kart_luigi",
        material_name="mat_metal",
        texture_name="tex_green",
        palette_name="pal_green",
        with_tex0=True,
    )
    bmd = NSBMDFile.from_bytes(raw_bmd)
    model = bmd.get_model("kart_luigi")
    assert model is not None
    assert model.name == "kart_luigi"
    assert "root_bone" in model.bone_names

    mat = model.get_material("mat_metal")
    assert mat is not None
    assert mat.name == "mat_metal"
    assert mat.texture_name == "tex_green"
    assert mat.palette_name == "pal_green"
    assert model.get_used_texture_names() == ["tex_green"]
    assert model.get_used_palette_names() == ["pal_green"]
    assert bmd.get_all_used_texture_names() == ["tex_green"]
    assert bmd.get_all_used_palette_names() == ["pal_green"]


def test_texture_relational_validation():
    """Verify validate_textures correctly flags matching, missing, and unreferenced assets."""
    raw_bmd = create_synthetic_nsbmd(
        model_name="shop_building",
        material_name="mat_sign",
        texture_name="tex_sign_jp",
        palette_name="pal_sign",
        with_tex0=True,
    )
    bmd = NSBMDFile.from_bytes(raw_bmd)

    # Initial state should be valid
    report = bmd.validate_textures()
    assert report["valid"] is True
    assert report["missing_textures"] == []
    assert report["missing_palettes"] == []

    # Inject a material with an unresolvable texture
    model = bmd.get_model("shop_building")
    assert model is not None
    model.materials.append(
        NSBMDMaterial(name="mat_unresolved", texture_name="missing_tex", palette_name="missing_pal")
    )

    bad_report = bmd.validate_textures()
    assert bad_report["valid"] is False
    assert "missing_tex" in bad_report["missing_textures"]
    assert "missing_pal" in bad_report["missing_palettes"]


def test_texture_export_to_nsbtx():
    """Verify exporting embedded TEX0 as a standalone NSBTXFile and file on disk."""
    raw_bmd = create_synthetic_nsbmd(
        model_name="tree_obj",
        material_name="mat_bark",
        texture_name="tex_bark",
        palette_name="pal_bark",
        with_tex0=True,
        texture_width=16,
        texture_height=16,
    )
    bmd = NSBMDFile.from_bytes(raw_bmd)

    nsbtx = bmd.export_nsbtx()
    assert isinstance(nsbtx, NSBTXFile)
    assert "tex_bark" in nsbtx.get_texture_names()
    assert "pal_bark" in nsbtx.get_palette_names()

    # Verify RGBA decoding
    rgba = nsbtx.decode_rgba("tex_bark", "pal_bark")
    assert len(rgba) == 16 * 16 * 4

    # Verify export to file
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "exported.nsbtx")
        bmd.export_nsbtx_file(out_path)
        assert os.path.exists(out_path)
        loaded = NSBTXFile.from_file(out_path)
        assert loaded.get_texture_names() == ["tex_bark"]


def test_texture_replacement():
    """Verify replacing an embedded texture in NSBMD while preserving display list geometry."""
    raw_bmd = create_synthetic_nsbmd(
        model_name="flag_banner",
        material_name="mat_flag",
        texture_name="tex_flag_jp",
        palette_name="pal_flag_jp",
        with_tex0=True,
        texture_width=16,
        texture_height=16,
    )
    bmd = NSBMDFile.from_bytes(raw_bmd)
    original_mdl0 = bmd.raw_mdl0

    # Create translated replacement texture (English banner)
    new_tex = NSBTXTexture(
        name="tex_flag_jp",  # reuse slot name
        width=16,
        height=16,
        format_id=3,
        color0_transparent=False,
        raw_data=bytes([0x77] * 128),
    )
    new_pal = NSBTXPalette(
        name="pal_flag_jp",
        colors=[(255, 0, 0)] * 16,
    )

    bmd.replace_texture("tex_flag_jp", new_tex, new_pal)
    rebuilt_bytes = bmd.to_bytes()

    reloaded_bmd = NSBMDFile.from_bytes(rebuilt_bytes)
    assert reloaded_bmd.has_textures is True
    # Display list geometry in MDL0 must remain 100% identical bit-exact
    assert reloaded_bmd.raw_mdl0 == original_mdl0

    # Verify updated texture payload
    assert reloaded_bmd.tex0 is not None
    updated_tex = reloaded_bmd.tex0.get_texture("tex_flag_jp")
    assert updated_tex is not None
    assert updated_tex.raw_data == bytes([0x77] * 128)


def test_texture_stripping():
    """Verify strip_textures converts 2-block NSBMD into 1-block (MDL0 only) container."""
    raw_bmd = create_synthetic_nsbmd(
        model_name="character_naked",
        material_name="mat_skin",
        texture_name="tex_skin",
        with_tex0=True,
    )
    bmd = NSBMDFile.from_bytes(raw_bmd)
    assert bmd.has_textures is True

    bmd.strip_textures()
    assert bmd.has_textures is False
    assert bmd.tex0 is None

    stripped_bytes = bmd.to_bytes()
    reloaded = NSBMDFile.from_bytes(stripped_bytes)
    assert reloaded.has_textures is False
    assert reloaded.tex0 is None
    assert len(stripped_bytes) < len(raw_bmd)


def test_texture_injection_into_textureless_model():
    """Verify importing textures into a model that previously had no textures."""
    raw_bmd = create_synthetic_nsbmd(
        model_name="statue",
        material_name="mat_stone",
        texture_name=None,
        with_tex0=False,
    )
    bmd = NSBMDFile.from_bytes(raw_bmd)
    assert bmd.has_textures is False

    # Create new texture set
    tex = NSBTXTexture(
        name="tex_marble",
        width=16,
        height=16,
        format_id=3,
        color0_transparent=False,
        raw_data=bytes([0x55] * 128),
    )
    pal = NSBTXPalette(name="pal_marble", colors=[(200, 200, 200)] * 16)
    new_nsbtx = NSBTXFile(textures=[tex], palettes=[pal])

    bmd.import_nsbtx(new_nsbtx)
    assert bmd.has_textures is True

    packed = bmd.to_bytes()
    reloaded = NSBMDFile.from_bytes(packed)
    assert reloaded.has_textures is True
    assert "tex_marble" in reloaded.tex0.get_texture_names()


def test_roundtrip_bit_exactness():
    """Verify idempotency of serialization: from_bytes(to_bytes()) == to_bytes()."""
    raw_bmd = create_synthetic_nsbmd(
        model_name="castle_gate",
        material_name="mat_iron",
        texture_name="tex_iron",
        palette_name="pal_iron",
        with_tex0=True,
    )
    bmd1 = NSBMDFile.from_bytes(raw_bmd)
    bytes1 = bmd1.to_bytes()

    bmd2 = NSBMDFile.from_bytes(bytes1)
    bytes2 = bmd2.to_bytes()

    assert bytes1 == bytes2


def test_error_handling_malformed_inputs():
    """Verify proper ParseError on corrupt headers, invalid magics, and truncated inputs."""
    # Data too short
    with pytest.raises(ParseError, match="Data too short for BMD0 header"):
        NSBMDFile.from_bytes(b"BMD0\x00")

    # Wrong magic
    with pytest.raises(ParseError, match="Invalid BMD0 magic"):
        NSBMDFile.from_bytes(b"XYZ0" + b"\x00" * 20)

    # Wrong endianness
    bad_endian = bytearray(create_synthetic_nsbmd(with_tex0=False))
    bad_endian[4:6] = b"\x00\x00"
    with pytest.raises(ParseError, match="Invalid endianness marker"):
        NSBMDFile.from_bytes(bytes(bad_endian))

    # Bad block count
    bad_blocks = bytearray(create_synthetic_nsbmd(with_tex0=False))
    bad_blocks[14:16] = b"\x05\x00"  # block_count = 5
    with pytest.raises(ParseError, match="Unsupported block count"):
        NSBMDFile.from_bytes(bytes(bad_blocks))

    # Corrupt MDL0 magic
    bad_mdl0 = bytearray(create_synthetic_nsbmd(with_tex0=False))
    # MDL0 starts at offset 0x14
    bad_mdl0[0x14 : 0x18] = b"XXXX"
    with pytest.raises(ParseError, match="Invalid MDL0 section magic"):
        NSBMDFile.from_bytes(bytes(bad_mdl0))


def test_ndsrom_integration():
    """Verify NDSRom.get_model() and NDSRom.set_model() integration."""
    raw_bmd = create_synthetic_nsbmd(
        model_name="in_game_sign",
        material_name="mat_sign_text",
        texture_name="tex_sign_jp",
        with_tex0=True,
    )

    # Create dummy NDSRom with a file in FAT
    # 0x000: Header (0x200 bytes)
    # 0x200: FAT entry (0x8 bytes: start=0x300, end=0x300+len(raw_bmd))
    # 0x300: BMD0 payload
    rom_data = bytearray(0x1000)
    rom_data[0x48:0x4C] = (0x200).to_bytes(4, "little")  # fat_offset
    rom_data[0x4C:0x50] = (8).to_bytes(4, "little")      # fat_size = 8 (1 entry)

    start_off = 0x300
    end_off = start_off + len(raw_bmd)
    rom_data[0x200:0x204] = start_off.to_bytes(4, "little")
    rom_data[0x204:0x208] = end_off.to_bytes(4, "little")
    rom_data[start_off:end_off] = raw_bmd

    rom = NDSRom(rom_data)
    model = rom.get_model(0)
    assert isinstance(model, NSBMDFile)
    assert model.has_textures is True
    assert "in_game_sign" in model.model_names

    # Modify and set model back into ROM
    model.strip_textures()
    rom.set_model(0, model)

    # Re-read from ROM and verify changes
    updated_model = rom.get_model(0)
    assert updated_model.has_textures is False
