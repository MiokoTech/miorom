"""
Unit tests for Nintendo Wii U8 Archive (.arc, .szs).
"""

import os
import tempfile
import pytest
from miorom.platforms.wii.u8 import U8Archive
from miorom.errors import ParseError


def test_u8_pack_unpack_roundtrip():
    with tempfile.TemporaryDirectory() as tmpdir:
        src_dir = os.path.join(tmpdir, "src")
        os.makedirs(os.path.join(src_dir, "subdir"), exist_ok=True)
        
        file1 = os.path.join(src_dir, "file1.bin")
        file2 = os.path.join(src_dir, "subdir", "file2.tpl")
        file3_png = os.path.join(src_dir, "preview.png")
        
        with open(file1, "wb") as f:
            f.write(b"BINARY_PAYLOAD_1")
        with open(file2, "wb") as f:
            f.write(b"TEXTURE_PAYLOAD_2")
        with open(file3_png, "wb") as f:
            f.write(b"PNG_DATA_DO_NOT_PACK")
            
        arc_path = os.path.join(tmpdir, "test.arc")
        U8Archive.pack(src_dir, arc_path, exclude_extensions=[".png"])
        
        assert os.path.exists(arc_path)
        
        # Reload and inspect
        entries = U8Archive.list_files(arc_path)
        names = [e.name for e in entries]
        assert "file1.bin" in names
        assert "file2.tpl" in names
        assert "preview.png" not in names
        
        # Test extract_all
        out_dir = os.path.join(tmpdir, "out")
        extracted = U8Archive.extract_all(arc_path, out_dir)
        assert any(p.endswith("file1.bin") for p in extracted)
        assert any(p.endswith("file2.tpl") for p in extracted)
        assert not any(p.endswith("preview.png") for p in extracted)


def test_u8_archive_get_mapping():
    """Verify U8Archive dict mapping methods including .get()."""
    arc = U8Archive()
    arc["files/main.dol"] = b"DOL_PAYLOAD"
    assert arc.get("files/main.dol") == b"DOL_PAYLOAD"
    assert arc.get("/files/main.dol") == b"DOL_PAYLOAD"
    assert arc.get("nonexistent.bin") is None
    assert arc.get("nonexistent.bin", b"DEFAULT") == b"DEFAULT"

