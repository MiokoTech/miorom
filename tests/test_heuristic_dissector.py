import struct
import pytest
from miorom.archive.dissector import HeuristicArchiveDissector, DissectedArchive


def test_implicit_offsets_with_count():
    # Build a simulated proprietary archive with 3 files:
    # 0x00: count = 3 (uint32 LE)
    # 0x04: off[0] = 0x14 (20)
    # 0x08: off[1] = 0x24 (36)
    # 0x0C: off[2] = 0x34 (52)
    # 0x10: sentinel = 0x48 (72)
    # 0x14: File 0 (BMP magic)
    # 0x24: File 1 (PSX TIM magic)
    # 0x34: File 2 (ASCII Text)
    file0 = b"BM_FAKE_BMP_DATA_123"            # 20 bytes -> padded to 16
    file1 = b"\x10\x00\x00\x00TIM_IMAGE_DATA"  # 18 bytes
    file2 = b"Hello, World! Dialogue script"   # 28 bytes

    pack = bytearray()
    header_size = 20  # 4 + 4*4
    off0 = header_size
    off1 = off0 + len(file0)
    off2 = off1 + len(file1)
    off_end = off2 + len(file2)

    pack.extend(struct.pack("<5I", 3, off0, off1, off2, off_end))
    pack.extend(file0)
    pack.extend(file1)
    pack.extend(file2)

    raw_bytes = bytes(pack)
    dissected = HeuristicArchiveDissector.dissect(raw_bytes)

    assert dissected is not None
    assert dissected.format_type == "implicit_offsets"
    assert dissected.endianness == "<"
    assert dissected.pointer_size == 4
    assert len(dissected.entries) == 3

    # Check detected extensions
    assert dissected.entries[0].name.endswith(".bmp")
    assert dissected.entries[1].name.endswith(".tim")
    assert dissected.entries[2].name.endswith(".txt")

    # Check contents
    assert dissected.entries[0].data == file0
    assert dissected.entries[1].data == file1
    assert dissected.entries[2].data == file2

    # Repack
    repacked = dissected.repack(alignment=1)
    assert repacked == raw_bytes


def test_explicit_offset_size_pairs():
    # 2 files with explicit (offset, size) pairs
    file0 = b"RIFF_WAV_HEADER_DATA"
    file1 = b"OggS_VORBIS_DATA_STREAM"

    header_size = 4 + (2 * 8)  # count + 2 pairs of (uint32, uint32) = 20
    off0 = header_size
    sz0 = len(file0)
    off1 = off0 + sz0
    sz1 = len(file1)

    pack = bytearray()
    pack.extend(struct.pack("<I", 2))
    pack.extend(struct.pack("<II", off0, sz0))
    pack.extend(struct.pack("<II", off1, sz1))
    pack.extend(file0)
    pack.extend(file1)

    raw_bytes = bytes(pack)
    dissected = HeuristicArchiveDissector.dissect(raw_bytes)

    assert dissected is not None
    assert dissected.format_type == "explicit_offset_size"
    assert len(dissected.entries) == 2
    assert dissected.entries[0].name.endswith(".wav")
    assert dissected.entries[1].name.endswith(".ogg")
    assert dissected.entries[0].data == file0
    assert dissected.entries[1].data == file1

    # Repack
    repacked = dissected.repack(alignment=1)
    assert repacked == raw_bytes


def test_magic_carving_fallback():
    # File without header table, just concatenated magic streams
    file0 = b"BM_BITMAP_1" + b"\x00" * 20
    file1 = b"RIFF_AUDIO_1" + b"\x00" * 30
    combined = file0 + file1

    dissected = HeuristicArchiveDissector.dissect(combined, min_entries=2)
    assert dissected is not None
    assert dissected.format_type == "magic_carved"
    assert len(dissected.entries) >= 2


def test_dissected_extract_and_vfs(tmp_path):
    file0 = b"BM_BITMAP_DATA"
    file1 = b"Hello, Text!"
    pack = bytearray()
    pack.extend(struct.pack("<4I", 2, 16, 16 + len(file0), 16 + len(file0) + len(file1)))
    pack.extend(file0)
    pack.extend(file1)

    dissected = HeuristicArchiveDissector.dissect(bytes(pack))
    assert dissected is not None

    # VFS
    vfs = dissected.to_vfs()
    assert len(vfs.root.list()) == 2

    # Extract to disk
    out_dir = tmp_path / "extracted_pack"
    dissected.extract_to_dir(str(out_dir))
    extracted_files = sorted(out_dir.iterdir())
    assert len(extracted_files) == 2
    assert extracted_files[0].read_bytes() == file0
    assert extracted_files[1].read_bytes() == file1
