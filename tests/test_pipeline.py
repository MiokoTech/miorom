import json
import os
import tempfile
from miorom.pipeline import (
    CompressStep,
    CreatePatchStep,
    DecompressStep,
    FixChecksumStep,
    PipelineContext,
    PipelineRecipe,
)
from miorom.platforms.md import MDHeader, calculate_md_checksum, verify_md_checksum


def test_pipeline_execution_and_serialization():
    with tempfile.TemporaryDirectory() as tmpdir:
        raw_file = os.path.join(tmpdir, "test.raw")
        comp_file = os.path.join(tmpdir, "test.lz")
        decomp_file = os.path.join(tmpdir, "test.decomp")
        rom_file = os.path.join(tmpdir, "test.md")
        patch_file = os.path.join(tmpdir, "test.bps")

        # Prepare raw test file
        test_payload = b"MioROM Pipeline Workflow Automated Data " * 10
        with open(raw_file, "wb") as f:
            f.write(test_payload)

        # Prepare dummy Mega Drive ROM
        rom_data = bytearray(0x0400)
        hdr = MDHeader(
            system_type="SEGA MEGA DRIVE",
            copyright="(C)SEGA 1991.MAY",
            domestic_title="SONIC",
            overseas_title="SONIC",
            serial_number="GM MK-1008 -00",
            checksum=0,
            io_support="J",
            rom_start=0x00000000,
            rom_end=0x0007FFFF,
            ram_start=0x00FF0000,
            ram_end=0x00FFFFFF,
            sram_support=False,
            region="JUE",
        )
        rom_data[0x0100:0x0200] = hdr.pack()
        rom_data[0x0200:0x0204] = b"\x4E\x71\x4E\x75"
        with open(rom_file, "wb") as f:
            f.write(rom_data)

        # Build pipeline recipe
        recipe = PipelineRecipe(name="Automated_Test_Pipeline")
        recipe.add_step(CompressStep(input_path="{dir}/test.raw", output_path="{dir}/test.lz", format_name="lz10"))
        recipe.add_step(DecompressStep(input_path="{dir}/test.lz", output_path="{dir}/test.decomp"))
        recipe.add_step(FixChecksumStep(rom_path="{dir}/test.md", platform="md"))
        recipe.add_step(CreatePatchStep(original_path="{dir}/test.raw", modified_path="{dir}/test.decomp", patch_output_path="{dir}/test.bps", patch_format="bps"))

        # Test serialization
        recipe_json = recipe.to_json()
        loaded_recipe = PipelineRecipe.from_json(recipe_json)
        assert len(loaded_recipe.steps) == 4
        assert loaded_recipe.name == "Automated_Test_Pipeline"

        # Execute recipe
        ctx = loaded_recipe.execute({"dir": tmpdir})

        # Verify step results
        assert os.path.isfile(comp_file)
        assert os.path.isfile(decomp_file)
        with open(decomp_file, "rb") as f:
            assert f.read() == test_payload

        # Verify Mega Drive checksum was fixed
        with open(rom_file, "rb") as f:
            assert verify_md_checksum(f.read()) is True

        # Verify patch was generated
        assert os.path.isfile(patch_file)
        assert os.path.getsize(patch_file) > 0
