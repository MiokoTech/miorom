import os
import struct
import pytest
from miorom.project.manager import (
    ProjectWorkflowManager,
    ProjectManifest,
    BuildResult,
)
from miorom.text.po_handler import PoHandler


def test_project_workflow_dump_and_build(tmp_path):
    project_dir = str(tmp_path / "translation_proj")

    # Assemble minimal mock ROM (256 bytes)
    rom_buf = bytearray(256)
    # Strings at 0x40, 0x50
    rom_buf[0x40:0x46] = b"Sword\x00"
    rom_buf[0x50:0x57] = b"Shield\x00"

    # Pointer table at 0x10: 2 32-bit pointers
    struct.pack_into("<I", rom_buf, 0x10, 0x40)
    struct.pack_into("<I", rom_buf, 0x14, 0x50)

    # 1. Initialize project
    tables_config = [
        {
            "name": "items",
            "table_offset": 0x10,
            "entry_count": 2,
            "pointer_size": 4,
            "endian": "<",
        }
    ]
    manifest = ProjectWorkflowManager.init_project(
        project_dir=project_dir,
        name="TestRPG_ID",
        platform="generic",
        text_tables=tables_config,
    )
    assert manifest.name == "TestRPG_ID"

    # 2. Dump project (Bongkar)
    dumped = ProjectWorkflowManager.dump_project(bytes(rom_buf), project_dir, manifest)
    assert len(dumped) == 1
    po_path = dumped[0]
    assert os.path.exists(po_path)

    # 3. Translate with text lengthening (arbitrary expansion)
    po = PoHandler.from_file(po_path)
    assert len(po.entries) == 2
    assert po.entries[0].msgid == "Sword"
    po.entries[0].msgstr = "Pedang Api Legendaris Penakluk Kegelapan"  # 41 bytes >> 6 bytes
    po.entries[1].msgstr = "Perisai Baja Pelindung Jiwa"             # 27 bytes >> 7 bytes
    po.save(po_path)

    # 4. Build project (Pasang)
    out_rom_path = str(tmp_path / "game_id.bin")
    res = ProjectWorkflowManager.build_project(
        rom_buffer=rom_buf,
        project_dir=project_dir,
        output_rom_path=out_rom_path,
    )

    assert res.tables_injected == 1
    assert res.total_strings == 2
    assert res.total_overflowed == 2
    assert os.path.exists(out_rom_path)

    # Verify that pointers in table 0x10 were rewritten to relocated offsets
    new_ptr0 = struct.unpack_from("<I", rom_buf, 0x10)[0]
    new_ptr1 = struct.unpack_from("<I", rom_buf, 0x14)[0]

    # Pointers must have been relocated to valid offsets
    assert new_ptr0 != 0x40
    assert new_ptr1 != 0x50

    # Read back both strings from relocated offsets
    str0 = rom_buf[new_ptr0 : rom_buf.find(b"\x00", new_ptr0)].decode("utf-8")
    str1 = rom_buf[new_ptr1 : rom_buf.find(b"\x00", new_ptr1)].decode("utf-8")
    assert str0 == "Pedang Api Legendaris Penakluk Kegelapan"
    assert str1 == "Perisai Baja Pelindung Jiwa"
