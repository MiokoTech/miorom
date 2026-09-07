import struct
import pytest
from miorom.archive.cascading import (
    CascadingContainerRepacker,
    ContainerEntry,
    CascadingRepackReport,
)


def test_cascading_archive_repack_and_unpack():
    # Create 3 synthetic container entries
    entries = [
        ContainerEntry(entry_id=0, name="dialogue_0", data=b"Hello World!"),
        ContainerEntry(entry_id=1, name="script_1", data=b"JumpToEndIfZero\x00\x01\x02"),
        ContainerEntry(entry_id=2, name="system_2", data=b"SaveDataInit"),
    ]

    container_bytes, report = CascadingContainerRepacker.repack_table_based_container(
        entries=entries,
        header_magic=b"MIO\x00",
        header_size=16,
        pointer_size=4,
        endian="<",
        alignment=4,
        table_has_sizes=True,
    )

    assert report.files_updated == 3
    assert report.fat_entries_shifted == 3
    assert report.new_root_size == len(container_bytes)
    assert container_bytes[:4] == b"MIO\x00"

    # Verify count and total size in header
    count, total_sz = struct.unpack_from("<II", container_bytes, 4)
    assert count == 3
    assert total_sz == len(container_bytes)

    # Unpack and verify content fidelity
    unpacked = CascadingContainerRepacker.unpack_table_based_container(
        data=container_bytes,
        header_size=16,
        pointer_size=4,
        endian="<",
        table_has_sizes=True,
    )

    assert len(unpacked) == 3
    assert unpacked[0].data == b"Hello World!"
    assert unpacked[1].data == b"JumpToEndIfZero\x00\x01\x02"
    assert unpacked[2].data == b"SaveDataInit"


def test_cascading_archive_expansion_shifts_offsets():
    # Simulate text expansion: entry 0 is expanded 10x
    expanded_entry0 = b"Halo Dunia yang Indah dan Penuh Petualangan Tanpa Akhir! " * 5
    entries = [
        ContainerEntry(entry_id=0, name="dialogue_0", data=expanded_entry0),
        ContainerEntry(entry_id=1, name="script_1", data=b"SmallPayload"),
    ]

    container_bytes, report = CascadingContainerRepacker.repack_table_based_container(
        entries=entries,
        alignment=16,
    )

    unpacked = CascadingContainerRepacker.unpack_table_based_container(
        data=container_bytes,
        table_has_sizes=True,
    )

    assert len(unpacked) == 2
    assert unpacked[0].data == expanded_entry0
    assert unpacked[1].data == b"SmallPayload"


def test_cascading_archive_no_sizes_table():
    entries = [
        ContainerEntry(entry_id=0, name="f0", data=b"EntryZeroData"),
        ContainerEntry(entry_id=1, name="f1", data=b"EntryOneData"),
    ]

    container_bytes, report = CascadingContainerRepacker.repack_table_based_container(
        entries=entries,
        alignment=1,
        table_has_sizes=False,
    )

    unpacked = CascadingContainerRepacker.unpack_table_based_container(
        data=container_bytes,
        table_has_sizes=False,
    )

    assert len(unpacked) == 2
    assert unpacked[0].data == b"EntryZeroData"
    assert unpacked[1].data == b"EntryOneData"
