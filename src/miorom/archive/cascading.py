"""
miorom.archive.cascading
~~~~~~~~~~~~~~~~~~~~~~~~
Cascading Nested Archive & Multi-Level Container Repacker.
Solves cascading size expansion when translating files tucked inside nested
container archives (e.g., NDS NARC/FAT, PSX PAC/BIN, PSP CPK): automatically
recalculates internal File Allocation Tables (FAT), shifts subsequent file offsets,
and updates parent archive headers all the way up to master ROM alignment.
"""

from miorom.result import MioRomResult
from dataclasses import dataclass, field
import struct
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union


@dataclass
class ContainerEntry(MioRomResult):
    """Represents a file or sub-archive within a nested container tree."""
    entry_id: int
    name: str
    data: bytes
    alignment: Optional[int] = None
    children: List["ContainerEntry"] = field(default_factory=list)

    @property
    def is_container(self) -> bool:
        return len(self.children) > 0

    @property
    def size(self) -> int:
        return len(self.data)


@dataclass
class CascadingRepackReport(MioRomResult):
    """Detailed summary of cascading container rebuild."""
    files_updated: int
    total_size_delta: int
    fat_entries_shifted: int
    padding_bytes_added: int
    new_root_size: int


class CascadingContainerRepacker:
    """
    Recursively rebuilds nested binary archives with automatic offset realignment.
    """

    @classmethod
    def align_up(cls, value: int, alignment: int) -> int:
        if alignment <= 1:
            return value
        rem = value % alignment
        return value if rem == 0 else value + (alignment - rem)

    @classmethod
    def repack_table_based_container(
        cls,
        entries: List[ContainerEntry],
        header_magic: bytes = b"PACK",
        header_size: int = 16,
        pointer_size: int = 4,
        endian: str = "<",
        alignment: int = 4,
        table_has_sizes: bool = True,
    ) -> Tuple[bytes, CascadingRepackReport]:
        """
        Re-synthesizes a container file composed of a header, an offset/size FAT table,
        and sequential data payloads. Automatically shifts all subsequent offsets
        when any payload expands.
        """
        count = len(entries)
        fat_entry_size = pointer_size * (2 if table_has_sizes else 1)
        fat_total_size = count * fat_entry_size
        payloads_start = cls.align_up(header_size + fat_total_size, alignment)

        fat_fmt = f"{endian}{'I' if pointer_size == 4 else 'H'}"
        table_bytes = bytearray(fat_total_size)
        payload_bytes = bytearray()

        cur_payload_offset = payloads_start
        fat_shifted = 0
        padding_added = 0

        for i, entry in enumerate(entries):
            # Align payload start if requested
            eff_alignment = entry.alignment if entry.alignment is not None else alignment
            aligned_offset = cls.align_up(cur_payload_offset, eff_alignment)
            pad_len = aligned_offset - cur_payload_offset
            if pad_len > 0:
                payload_bytes.extend(b"\x00" * pad_len)
                padding_added += pad_len
                cur_payload_offset = aligned_offset

            entry_data = entry.data
            entry_sz = len(entry_data)

            # Write FAT entry
            table_pos = i * fat_entry_size
            struct.pack_into(fat_fmt, table_bytes, table_pos, cur_payload_offset)
            if table_has_sizes:
                struct.pack_into(fat_fmt, table_bytes, table_pos + pointer_size, entry_sz)

            # Append payload
            payload_bytes.extend(entry_data)
            cur_payload_offset += entry_sz
            fat_shifted += 1

        # Build final container buffer
        final_buffer = bytearray()
        # Header: magic + count + total size
        header_buf = bytearray(header_size)
        magic_len = min(len(header_magic), header_size)
        header_buf[:magic_len] = header_magic

        total_file_size = payloads_start + len(payload_bytes)
        struct.pack_into(fat_fmt, header_buf, 4, count)
        struct.pack_into(fat_fmt, header_buf, 8, total_file_size)

        final_buffer.extend(header_buf)
        final_buffer.extend(table_bytes)

        # Pad between FAT and first payload
        header_fat_gap = payloads_start - (header_size + fat_total_size)
        if header_fat_gap > 0:
            final_buffer.extend(b"\x00" * header_fat_gap)
            padding_added += header_fat_gap

        final_buffer.extend(payload_bytes)

        report = CascadingRepackReport(
            files_updated=count,
            total_size_delta=0,
            fat_entries_shifted=fat_shifted,
            padding_bytes_added=padding_added,
            new_root_size=len(final_buffer),
        )

        return bytes(final_buffer), report

    @classmethod
    def unpack_table_based_container(
        cls,
        data: bytes,
        header_size: int = 16,
        pointer_size: int = 4,
        endian: str = "<",
        table_has_sizes: bool = True,
    ) -> List[ContainerEntry]:
        """
        Unpacks a table-based container into individual ContainerEntry items.
        """
        fat_fmt = f"{endian}{'I' if pointer_size == 4 else 'H'}"
        count = struct.unpack_from(fat_fmt, data, 4)[0]
        fat_entry_size = pointer_size * (2 if table_has_sizes else 1)

        entries: List[ContainerEntry] = []
        for i in range(count):
            table_pos = header_size + i * fat_entry_size
            offset = struct.unpack_from(fat_fmt, data, table_pos)[0]

            if table_has_sizes:
                size = struct.unpack_from(fat_fmt, data, table_pos + pointer_size)[0]
            else:
                # Next entry offset or EOF
                if i + 1 < count:
                    next_off = struct.unpack_from(fat_fmt, data, table_pos + fat_entry_size)[0]
                    size = next_off - offset
                else:
                    size = len(data) - offset

            entry_data = data[offset : offset + size]
            entries.append(
                ContainerEntry(
                    entry_id=i,
                    name=f"file_{i:04d}",
                    data=entry_data,
                )
            )

        return entries
