import struct
from typing import Dict, List, Optional, Tuple


class SDATFileEntry:
    def __init__(self, index: int, offset: int, size: int, data: bytes):
        self.index = index
        self.offset = offset
        self.size = size
        self.data = bytearray(data)


class SDATContainer:
    """
    Nintendo DS SDAT (Sound Data) container parser and file extractor/injector.
    Stores SSEQ (music sequence), SWAR (wave archive), SBNK (sound bank), and SSAR.
    """

    MAGIC = b"SDAT"

    def __init__(self, data: bytes):
        if len(data) < 64:
            raise ValueError("Data too small for SDAT header (minimum 64 bytes).")

        if data[:4] != self.MAGIC:
            raise ValueError(f"Invalid SDAT magic: {data[:4]!r}")

        self.data = bytearray(data)
        self.file_size = struct.unpack_from("<I", self.data, 8)[0]

        # Block locations
        self.symb_offset, self.symb_size = struct.unpack_from("<II", self.data, 0x10)
        self.info_offset, self.info_size = struct.unpack_from("<II", self.data, 0x18)
        self.fat_offset, self.fat_size = struct.unpack_from("<II", self.data, 0x20)
        self.file_block_offset, self.file_block_size = struct.unpack_from("<II", self.data, 0x28)

        self.entries: List[SDATFileEntry] = []
        self._parse_fat()

    @classmethod
    def from_file(cls, path: str) -> "SDATContainer":
        with open(path, "rb") as f:
            return cls(f.read())

    def _parse_fat(self):
        self.entries = []
        if self.fat_offset == 0 or self.fat_offset >= len(self.data):
            return

        fat_count = struct.unpack_from("<I", self.data, self.fat_offset + 8)[0]
        rec_pos = self.fat_offset + 12

        for i in range(fat_count):
            if rec_pos + 8 > len(self.data):
                break
            rel_off, f_size = struct.unpack_from("<II", self.data, rec_pos)
            abs_off = self.file_block_offset + rel_off
            f_data = self.data[abs_off : abs_off + f_size]
            self.entries.append(SDATFileEntry(index=i, offset=rel_off, size=f_size, data=f_data))
            rec_pos += 8

    def get_file(self, index: int) -> bytes:
        if 0 <= index < len(self.entries):
            return bytes(self.entries[index].data)
        raise IndexError(f"File index out of range: {index}")

    def replace_file(self, index: int, new_data: bytes):
        """Replaces sound file data at specified index."""
        if not (0 <= index < len(self.entries)):
            raise IndexError(f"File index out of range: {index}")
        self.entries[index].data = bytearray(new_data)
        self.entries[index].size = len(new_data)

    def to_bytes(self) -> bytes:
        """Rebuilds the SDAT file container with updated FAT and FILE blocks."""
        # Align files to 32 bytes inside FILE block
        new_file_block = bytearray(b"FILE")
        # Placeholder for block size and count
        new_file_block.extend(struct.pack("<II", 0, len(self.entries)))

        fat_records = bytearray()
        cur_rel_offset = len(new_file_block)

        for entry in self.entries:
            # 32-byte alignment
            pad = (32 - (cur_rel_offset % 32)) % 32
            if pad > 0:
                new_file_block.extend(b"\x00" * pad)
                cur_rel_offset += pad

            fat_records.extend(struct.pack("<II", cur_rel_offset, len(entry.data)))
            new_file_block.extend(entry.data)
            cur_rel_offset += len(entry.data)

        # Finalize FILE block header
        struct.pack_into("<I", new_file_block, 4, len(new_file_block))

        # Build FAT block
        fat_block = bytearray(b"FAT ")
        fat_block_len = 12 + len(fat_records)
        fat_block.extend(struct.pack("<II", fat_block_len, len(self.entries)))
        fat_block.extend(fat_records)

        # Assemble new SDAT
        # Keep SYMB and INFO blocks intact
        symb_block = self.data[self.symb_offset : self.symb_offset + self.symb_size] if self.symb_offset else b""
        info_block = self.data[self.info_offset : self.info_offset + self.info_size] if self.info_offset else b""

        new_symb_off = 64 if symb_block else 0
        new_info_off = new_symb_off + len(symb_block) if info_block else 0
        new_fat_off = (new_info_off + len(info_block)) if (new_info_off or new_symb_off) else 64
        # Pad to 32 bytes
        fat_pad = (32 - (new_fat_off % 32)) % 32
        new_fat_off += fat_pad

        new_file_off = new_fat_off + len(fat_block)
        file_pad = (32 - (new_file_off % 32)) % 32
        new_file_off += file_pad

        total_sdat_len = new_file_off + len(new_file_block)

        header = bytearray(self.MAGIC)
        header.extend(struct.pack("<HH", 0xFEFF, 0x0100))
        header.extend(struct.pack("<I", total_sdat_len))
        header.extend(struct.pack("<HH", 64, 4))
        header.extend(struct.pack("<II", new_symb_off, len(symb_block)))
        header.extend(struct.pack("<II", new_info_off, len(info_block)))
        header.extend(struct.pack("<II", new_fat_off, len(fat_block)))
        header.extend(struct.pack("<II", new_file_off, len(new_file_block)))
        # Pad header to 64 bytes
        header = header.ljust(64, b"\x00")

        out = bytearray(header)
        if symb_block:
            out.extend(symb_block)
        if info_block:
            out.extend(info_block)
        if fat_pad > 0:
            out.extend(b"\x00" * fat_pad)
        out.extend(fat_block)
        if file_pad > 0:
            out.extend(b"\x00" * file_pad)
        out.extend(new_file_block)

        return bytes(out)
