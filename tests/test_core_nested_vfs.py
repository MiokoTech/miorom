"""
Unit tests for miorom.core.vfs (NestedArchiveVFS) and CLI vfs commands.
"""

import argparse
import os
import tempfile
import pytest

from miorom.core.vfs import NestedArchiveVFS
from miorom.platforms.wii.u8 import U8Archive
from miorom.compression.yaz0 import Yaz0
from miorom.cli.main import cmd_vfs


def create_test_nested_archives() -> bytes:
    """Creates a nested U8 archive: outer.arc contains inner.arc, which contains payload.txt."""
    # Innermost files
    inner_files = {
        "text/payload.txt": b"HELLO_FROM_INNER_NESTED_ARCHIVE",
        "data/config.bin": b"CONFIG_BYTES_12345",
    }
    inner_u8_bytes = U8Archive.pack_dict(inner_files)

    # Outer files
    outer_files = {
        "sub/inner.arc": inner_u8_bytes,
        "readme.txt": b"OUTER_LEVEL_README",
    }
    outer_u8_bytes = U8Archive.pack_dict(outer_files)
    return outer_u8_bytes


def test_nested_vfs_read():
    outer_data = create_test_nested_archives()
    vfs = NestedArchiveVFS(outer_data)

    # Read nested leaf
    payload = vfs.read_uri("dummy_root.arc::sub/inner.arc::text/payload.txt")
    assert payload == b"HELLO_FROM_INNER_NESTED_ARCHIVE"

    # Read second file
    config = vfs.read_uri("dummy_root.arc::sub/inner.arc::data/config.bin")
    assert config == b"CONFIG_BYTES_12345"

    # Read outer level file
    readme = vfs.read_uri("dummy_root.arc::readme.txt")
    assert readme == b"OUTER_LEVEL_README"


def test_nested_vfs_write_and_atomic_repack():
    outer_data = create_test_nested_archives()
    vfs = NestedArchiveVFS(outer_data)

    new_content = b"REPLACED_INNER_PAYLOAD_NEW_TRANSLATION"
    vfs.write_uri("dummy_root.arc::sub/inner.arc::text/payload.txt", new_content, auto_save=False)

    # Read back through VFS
    re_read = vfs.read_uri("dummy_root.arc::sub/inner.arc::text/payload.txt")
    assert re_read == new_content

    # Inspect the repacked outer bytes independently
    repacked_outer = vfs.save()
    assert len(repacked_outer) % 32 == 0  # 32-byte alignment

    outer_dict = U8Archive.extract_dict(repacked_outer)
    assert "sub/inner.arc" in outer_dict
    assert outer_dict["readme.txt"] == b"OUTER_LEVEL_README"

    inner_dict = U8Archive.extract_dict(outer_dict["sub/inner.arc"])
    assert inner_dict["text/payload.txt"] == new_content
    assert inner_dict["data/config.bin"] == b"CONFIG_BYTES_12345"


def test_nested_vfs_yaz0_transparency():
    # Inner archive compressed with Yaz0 (.szs)
    inner_raw = U8Archive.pack_dict({"file.bin": b"YAZ0_PAYLOAD"})
    inner_szs = Yaz0.compress(inner_raw)

    outer_data = U8Archive.pack_dict({"compressed/inner.szs": inner_szs})
    vfs = NestedArchiveVFS(outer_data)

    # Transparent read
    data = vfs.read_uri("root.arc::compressed/inner.szs::file.bin")
    assert data == b"YAZ0_PAYLOAD"

    # Transparent write and recompression
    new_data = b"MODIFIED_YAZ0_PAYLOAD"
    vfs.write_uri("root.arc::compressed/inner.szs::file.bin", new_data, auto_save=False)

    outer_repacked = vfs.save()
    outer_extracted = U8Archive.extract_dict(outer_repacked)
    szs_bytes = outer_extracted["compressed/inner.szs"]
    assert szs_bytes[:4] == b"Yaz0"  # Verify it was recompressed to Yaz0

    decompressed = Yaz0.decompress(szs_bytes)
    inner_extracted = U8Archive.extract_dict(decompressed)
    assert inner_extracted["file.bin"] == new_data


def test_nested_vfs_list_uri():
    outer_data = create_test_nested_archives()
    vfs = NestedArchiveVFS(outer_data)

    inner_entries = vfs.list_uri("dummy.arc::sub/inner.arc")
    assert "text/payload.txt" in inner_entries
    assert "data/config.bin" in inner_entries


def test_cli_vfs_integration(capsys):
    outer_data = create_test_nested_archives()
    with tempfile.NamedTemporaryFile(suffix=".arc", delete=False) as f_root:
        f_root.write(outer_data)
        root_path = f_root.name

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f_out:
        out_path = f_out.name

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f_in:
        f_in.write(b"CLI_INJECTED_DATA")
        in_path = f_in.name

    try:
        # 1. vfs list
        uri_dir = f"{root_path}::sub/inner.arc"
        args_list = argparse.Namespace(vfs_command="list", uri=uri_dir)
        cmd_vfs(args_list)
        out = capsys.readouterr().out
        assert "text/payload.txt" in out

        # 2. vfs read
        uri_file = f"{root_path}::sub/inner.arc::text/payload.txt"
        args_read = argparse.Namespace(vfs_command="read", uri=uri_file, output=out_path)
        cmd_vfs(args_read)
        out_read = capsys.readouterr().out
        assert "Extracted" in out_read
        with open(out_path, "rb") as f:
            assert f.read() == b"HELLO_FROM_INNER_NESTED_ARCHIVE"

        # 3. vfs write
        args_write = argparse.Namespace(vfs_command="write", uri=uri_file, input_file=in_path)
        cmd_vfs(args_write)
        out_write = capsys.readouterr().out
        assert "Injected" in out_write

        # Verify disk update
        vfs_verify = NestedArchiveVFS(root_path)
        assert vfs_verify.read_uri(uri_file) == b"CLI_INJECTED_DATA"

    finally:
        for p in (root_path, out_path, in_path):
            if os.path.exists(p):
                os.remove(p)
