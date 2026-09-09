import io
from pathlib import Path

import pytest

from miorom.archive.container import ArchiveContainer, ArchiveEntry
from miorom.security import UnsafeArchivePathError, sanitize_extract_path


def test_sanitize_extract_path_rejects_escape_paths(tmp_path):
    evil_names = [
        "../../../tmp/evil.txt",
        "/etc/passwd",
        "..\\..\\evil.txt",
        "a/../../b/../../evil.txt",
    ]
    for evil_name in evil_names:
        with pytest.raises(UnsafeArchivePathError):
            sanitize_extract_path(str(tmp_path), evil_name)

def test_sanitize_extract_path_rejects_windows_absolute_paths(tmp_path):
    for evil_name in ("C:\\Windows\\evil.txt", "C:/Windows/evil.txt"):
        with pytest.raises(UnsafeArchivePathError):
            sanitize_extract_path(str(tmp_path), evil_name)


def test_sanitize_extract_path_allows_subdirectories(tmp_path):
    assert sanitize_extract_path(str(tmp_path), "subdir/file.bin") == str(
        tmp_path / "subdir" / "file.bin"
    )

def test_sanitize_extract_path_rejects_symlink_escape(tmp_path):
    outside_dir = tmp_path.parent / "miorom-symlink-outside"
    outside_dir.mkdir(exist_ok=True)
    inside_link = tmp_path / "inside-link"
    inside_link.symlink_to(outside_dir, target_is_directory=True)

    with pytest.raises(UnsafeArchivePathError):
        sanitize_extract_path(str(tmp_path), "inside-link/evil.txt")


def test_container_extract_rejects_path_traversal(tmp_path):
    entry = ArchiveEntry(index=0, name="../../../tmp/evil.txt", offset=0, size=5)
    container = ArchiveContainer([entry])
    with pytest.raises(UnsafeArchivePathError):
        container.extract_to_dir(io.BytesIO(b"PWNED"), str(tmp_path))


def test_container_extract_normal_names_still_work(tmp_path):
    entry = ArchiveEntry(index=0, name="subdir/file.bin", offset=0, size=5)
    container = ArchiveContainer([entry])
    container.extract_to_dir(io.BytesIO(b"HELLO"), str(tmp_path))
    assert (tmp_path / "subdir" / "file.bin").read_bytes() == b"HELLO"
