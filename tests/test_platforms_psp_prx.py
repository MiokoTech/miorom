"""
tests/test_platforms_psp_prx.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for Sony PlayStation Portable (PSP) PRX executable module engine,
MIPS ELF inspector, NID resolver, stub hooker, and PSPRom integration.
"""

import struct

import pytest

from miorom.errors import ParseError
from miorom.platforms.psp import (
    PRXModule,
    PSPNIDResolver,
    PSPRom,
    create_synthetic_prx,
    create_synthetic_psp_iso,
)


def test_nid_calculation_and_resolution():
    """Verify bit-exact algorithmic SHA-1 NID calculation and standard Sony SDK reverse lookup."""
    expected_nids = {
        "sceDisplayWaitVblankStart": 0x984C27E7,
        "sceDisplaySetMode": 0x0E20F177,
        "sceCtrlReadBufferPositive": 0x1F803938,
        "sceIoOpen": 0x109F50BC,
        "sceIoRead": 0x6A638D83,
        "sceIoWrite": 0x42EC03AC,
        "sceAudioOutputPannedBlocking": 0x13F592BC,
        "sceKernelCreateThread": 0x446D8DE6,
        "sceKernelExitGame": 0x05572A5F,
        "sceFontOpen": 0xA834319D,
        "sceFontGetCharInfo": 0xDCC80C2F,
    }

    for name, expected_nid in expected_nids.items():
        calc_nid = PSPNIDResolver.calculate_nid(name)
        assert calc_nid == expected_nid, f"NID mismatch for {name}: expected {hex(expected_nid)}, got {hex(calc_nid)}"

        # Reverse resolution
        resolved = PSPNIDResolver.resolve_nid(expected_nid)
        assert resolved == name, f"Reverse resolution failed for {hex(expected_nid)}: expected {name}, got {resolved}"

    # Test custom registration
    custom_nid = 0xDEADBEEF
    PSPNIDResolver.register_nid(custom_nid, "custom_vwf_render_glyph")
    assert PSPNIDResolver.resolve_nid(custom_nid) == "custom_vwf_render_glyph"
    assert PSPNIDResolver.resolve_name("custom_vwf_render_glyph") == custom_nid


def test_synthetic_prx_parsing():
    """Verify parsing of synthetic 32-bit Little-Endian MIPS ELF PRX."""
    prx_bytes = create_synthetic_prx(
        module_name="TEST_MODULE",
        major_version=2,
        minor_version=1,
        is_kernel_mode=False,
    )

    prx = PRXModule.from_bytes(prx_bytes)
    assert prx.header.e_ident_magic == b"\x7fELF"
    assert prx.header.e_ident_class == 1  # 32-bit
    assert prx.header.e_ident_data == 1  # Little-endian
    assert prx.header.e_machine == 8  # MIPS

    assert prx.module_info is not None
    assert prx.module_info.name == "TEST_MODULE"
    assert prx.module_info.major_version == 2
    assert prx.module_info.minor_version == 1
    assert prx.module_info.is_kernel_mode is False
    assert prx.module_info.gp_value == 0x08900000

    # Sections
    sec_names = [sec.name for sec in prx.sections]
    assert ".text" in sec_names
    assert ".rodata" in sec_names
    assert ".rodata.sceModuleInfo" in sec_names
    assert ".rodata.sceResEnt" in sec_names
    assert ".rodata.sceStub.text" in sec_names
    assert ".rodata.sceNID" in sec_names


def test_prx_kernel_mode():
    """Verify kernel-mode attribute flag detection."""
    k_prx_bytes = create_synthetic_prx(module_name="KERNEL_DRV", is_kernel_mode=True)
    k_prx = PRXModule.from_bytes(k_prx_bytes)
    assert k_prx.module_info is not None
    assert k_prx.module_info.is_kernel_mode is True


def test_prx_exports_enumeration():
    """Verify parsing and resolution of export library entries."""
    exports_def = [
        ("module_start", 0x08900100),
        ("module_stop", 0x08900140),
        ("module_reboot_before", 0x08900180),
    ]
    prx_bytes = create_synthetic_prx(exported_functions=exports_def)
    prx = PRXModule.from_bytes(prx_bytes)

    exports = prx.list_exports()
    assert len(exports) == 1
    syslib = exports[0]
    assert syslib.name == "syslib"
    assert len(syslib.functions) == 3

    fn_names = [fn.name for fn in syslib.functions]
    assert fn_names == ["module_start", "module_stop", "module_reboot_before"]
    assert syslib.functions[0].entry_point == 0x08900100


def test_prx_imports_enumeration():
    """Verify parsing and resolution of import library stub tables."""
    imported_libs = {
        "sceDisplay_driver": ["sceDisplayWaitVblankStart", "sceDisplaySetMode"],
        "sceIo_driver": ["sceIoOpen", "sceIoRead", "sceIoWrite", "sceIoClose"],
    }
    prx_bytes = create_synthetic_prx(imported_libs=imported_libs)
    prx = PRXModule.from_bytes(prx_bytes)

    imports = prx.list_imports()
    assert len(imports) == 2

    disp_lib = next(lib for lib in imports if lib.name == "sceDisplay_driver")
    assert len(disp_lib.functions) == 2
    assert disp_lib.functions[0].name == "sceDisplayWaitVblankStart"
    assert disp_lib.functions[0].nid == 0x984C27E7
    assert disp_lib.functions[0].stub_offset > 0

    io_lib = next(lib for lib in imports if lib.name == "sceIo_driver")
    assert len(io_lib.functions) == 4
    io_names = [fn.name for fn in io_lib.functions]
    assert io_names == ["sceIoOpen", "sceIoRead", "sceIoWrite", "sceIoClose"]


def test_prx_stub_redirection():
    """Verify MIPS call stub redirection for VWF and translation function hooking."""
    prx_bytes = create_synthetic_prx()
    prx = PRXModule.from_bytes(prx_bytes)

    fn = prx.find_import("sceDisplay_driver", "sceDisplayWaitVblankStart")
    assert fn is not None
    stub_off = fn.stub_offset

    target_hook_addr = 0x08954320
    prx.redirect_stub("sceDisplay_driver", "sceDisplayWaitVblankStart", target_hook_addr)

    # Validate generated MIPS bytecode
    # Word 0: 'j target_hook_addr' -> 0x08000000 | ((target_hook_addr >> 2) & 0x03FFFFFF)
    # Word 1: 'nop' -> 0x00000000
    jump_inst, nop_inst = struct.unpack_from("<II", prx.raw_data, stub_off)
    expected_jump = 0x08000000 | ((target_hook_addr >> 2) & 0x03FFFFFF)
    assert jump_inst == expected_jump
    assert nop_inst == 0

    # Verify reloading re-maintains byte changes
    reloaded = PRXModule.from_bytes(prx.to_bytes())
    reloaded_jump, reloaded_nop = struct.unpack_from("<II", reloaded.raw_data, stub_off)
    assert reloaded_jump == expected_jump
    assert reloaded_nop == 0


def test_prx_import_nid_replacement():
    """Verify replacing an imported NID in the PRX NID table."""
    prx_bytes = create_synthetic_prx()
    prx = PRXModule.from_bytes(prx_bytes)

    # Replace sceIoRead with sceIoWrite
    prx.replace_import_nid("sceIo_driver", "sceIoRead", "sceIoWrite")

    reloaded = PRXModule.from_bytes(prx.to_bytes())
    new_fn = reloaded.find_import("sceIo_driver", "sceIoWrite")
    assert new_fn is not None
    assert new_fn.name == "sceIoWrite"
    assert new_fn.nid == PSPNIDResolver.calculate_nid("sceIoWrite")


def test_encrypted_eboot_detection():
    """Verify clear and informative ParseError on encrypted ~PSP files."""
    encrypted_bytes = b"~PSP" + b"\x00" * 128
    with pytest.raises(ParseError) as exc_info:
        PRXModule.from_bytes(encrypted_bytes)
    assert "Encrypted PSP executable detected" in str(exc_info.value)
    assert "BOOT.BIN" in str(exc_info.value)


def test_invalid_elf_magic():
    """Verify error on invalid non-ELF binaries."""
    with pytest.raises(ParseError) as exc_info:
        PRXModule.from_bytes(b"INVALID_HEADER_DATA" * 4)
    assert "expected ELF magic '\\x7fELF'" in str(exc_info.value)


def test_prx_file_io(tmp_path):
    """Verify saving to and reading from disk files."""
    prx_bytes = create_synthetic_prx(module_name="DISK_IO_TEST")
    prx = PRXModule.from_bytes(prx_bytes)

    file_path = tmp_path / "test.prx"
    prx.save(file_path)
    assert file_path.exists()

    loaded = PRXModule.from_file(file_path)
    assert loaded.module_info is not None
    assert loaded.module_info.name == "DISK_IO_TEST"


def test_psprom_integration():
    """Verify PSPRom integration: get_boot_prx, replace_boot_prx on UMD disc images."""
    prx_data = create_synthetic_prx(module_name="GAME_PRX")
    iso_bytes = create_synthetic_psp_iso(
        game_id="ULUS10001",
        title="PRX Test Game",
        boot_bin_data=prx_data,
    )

    rom = PSPRom(iso_bytes)
    boot_prx = rom.get_boot_prx()
    assert boot_prx is not None
    assert boot_prx.module_info is not None
    assert boot_prx.module_info.name == "GAME_PRX"

    # Hook a stub in the PRX
    boot_prx.redirect_stub("sceDisplay_driver", "sceDisplayWaitVblankStart", 0x08990000)
    rom.replace_boot_prx(boot_prx)

    # Re-read from ROM
    rom2 = PSPRom(rom.to_bytes())
    boot_prx2 = rom2.get_boot_prx()
    assert boot_prx2 is not None
    fn = boot_prx2.find_import("sceDisplay_driver", "sceDisplayWaitVblankStart")
    assert fn is not None

    jump_inst, nop_inst = struct.unpack_from("<II", boot_prx2.raw_data, fn.stub_offset)
    expected_jump = 0x08000000 | ((0x08990000 >> 2) & 0x03FFFFFF)
    assert jump_inst == expected_jump
    assert nop_inst == 0


def test_prx_imported_variables():
    """Verify parsing and replacement of imported variable stubs."""
    imported_libs = {
        "sceIo_driver": ["sceIoOpen", "sceIoRead"],
    }
    imported_vars = {
        "sceIo_driver": ["sceIoErrno"],
    }
    prx_bytes = create_synthetic_prx(
        imported_libs=imported_libs,
        imported_variables=imported_vars,
    )
    prx = PRXModule.from_bytes(prx_bytes)

    imports = prx.list_imports()
    io_lib = next(lib for lib in imports if lib.name == "sceIo_driver")
    assert len(io_lib.functions) == 2
    assert len(io_lib.variables) == 1
    assert io_lib.variables[0].nid == PSPNIDResolver.calculate_nid("sceIoErrno")
    assert io_lib.variables[0].stub_offset > 0

    # find_import_variable
    var_entry = prx.find_import_variable("sceIo_driver", "sceIoErrno")
    assert var_entry is not None
    assert var_entry.name == "sceIoErrno"

    # replace_import_nid for variable
    prx.replace_import_nid("sceIo_driver", "sceIoErrno", "custom_var")
    reloaded = PRXModule.from_bytes(prx.to_bytes())
    new_var = reloaded.find_import_variable("sceIo_driver", "custom_var")
    assert new_var is not None
    assert new_var.nid == PSPNIDResolver.calculate_nid("custom_var")

