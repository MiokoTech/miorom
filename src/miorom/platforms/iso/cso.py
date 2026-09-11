"""
miorom.platforms.iso.cso
~~~~~~~~~~~~~~~~~~~~~~~~
Compressed ISO (CSO / CISO) Reader, Extractor, and Compressor.

CSO is a sector-based compressed disc image container utilized across PSP,
PS2, and PlayStation emulators (PPSSPP, PCSX2), reducing ISO sizes by 40-60%.
"""

import io
import os
import struct
import zlib
from typing import BinaryIO, List, Optional, Tuple, Union

from miorom.errors import CompressionError, ParseError
from miorom.result import MioRomResult


CSO_MAGIC = b"CISO"
DEFAULT_BLOCK_SIZE = 2048


class CSOImage(MioRomResult):
    """
    Compressed ISO (CISO / CSO) random-access reader and converter.
    Supports reading individual sectors, streaming ranges, and full decompression to ISO.
    """

    def __init__(self, source: Union[str, bytes, bytearray, BinaryIO]):
        self._owns_stream = False
        if isinstance(source, (bytes, bytearray)):
            self._stream: BinaryIO = io.BytesIO(source)
        elif isinstance(source, str):
            self._stream = open(source, "rb")
            self._owns_stream = True
        else:
            self._stream = source

        self._stream.seek(0)
        hdr = self._stream.read(24)
        if len(hdr) < 24:
            raise ParseError("Data too small for CSO header (minimum 24 bytes).")

        magic = hdr[:4]
        if magic != CSO_MAGIC:
            raise ParseError(f"Invalid CSO magic: {magic!r}, expected {CSO_MAGIC!r}")

        (
            self.header_size,
            self.uncompressed_size,
            self.block_size,
            self.version,
            self.align,
        ) = struct.unpack_from("<IQIBB", hdr, 4)

        if self.block_size == 0:
            self.block_size = DEFAULT_BLOCK_SIZE

        self.total_blocks = (self.uncompressed_size + self.block_size - 1) // self.block_size

        # Read index table (total_blocks + 1 entries of 32-bit uints)
        self._stream.seek(self.header_size)
        index_bytes = self._stream.read((self.total_blocks + 1) * 4)
        if len(index_bytes) < (self.total_blocks + 1) * 4:
            raise ParseError("Incomplete CSO index table.")

        self._index: List[int] = list(
            struct.unpack_from(f"<{self.total_blocks + 1}I", index_bytes)
        )

    def close(self):
        if self._owns_stream and self._stream:
            self._stream.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @property
    def sector_count(self) -> int:
        return self.total_blocks

    @property
    def sector_size(self) -> int:
        return self.block_size

    def read_sector(self, lba: int) -> bytes:
        """Decompresses and returns a single sector at logical block address (LBA)."""
        if lba < 0 or lba >= self.total_blocks:
            raise IndexError(f"LBA {lba} out of range (0..{self.total_blocks - 1}).")

        entry = self._index[lba]
        next_entry = self._index[lba + 1]

        is_raw = (entry & 0x80000000) != 0
        offset = (entry & 0x7FFFFFFF) << self.align
        next_offset = (next_entry & 0x7FFFFFFF) << self.align

        comp_len = next_offset - offset
        if comp_len <= 0:
            return b"\x00" * self.block_size

        self._stream.seek(offset)
        raw_chunk = self._stream.read(comp_len)

        if is_raw:
            return raw_chunk[:self.block_size]

        # Decompress zlib deflate payload
        try:
            # Try raw deflate (-15) then zlib standard
            return zlib.decompress(raw_chunk, -15)
        except zlib.error:
            try:
                return zlib.decompress(raw_chunk)
            except zlib.error as e:
                raise CompressionError(f"Failed to decompress CSO sector {lba}: {e}")

    def read_sectors(self, start_lba: int, count: int) -> bytes:
        """Reads and concatenates multiple consecutive sectors."""
        out = bytearray()
        for lba in range(start_lba, min(self.total_blocks, start_lba + count)):
            out.extend(self.read_sector(lba))
        return bytes(out)

    def read_bytes(self, offset: int, size: int) -> bytes:
        """Reads an arbitrary byte range across sector boundaries."""
        if offset < 0 or offset >= self.uncompressed_size:
            return b""

        actual_size = min(size, self.uncompressed_size - offset)
        start_lba = offset // self.block_size
        offset_in_sector = offset % self.block_size
        end_lba = (offset + actual_size + self.block_size - 1) // self.block_size

        buf = bytearray()
        for lba in range(start_lba, end_lba):
            buf.extend(self.read_sector(lba))

        return bytes(buf[offset_in_sector : offset_in_sector + actual_size])

    def decompress_to_file(self, output_path: str, chunk_sectors: int = 64):
        """Streams uncompressed sectors to an ISO file on disk."""
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "wb") as out_fp:
            for lba in range(0, self.total_blocks, chunk_sectors):
                count = min(chunk_sectors, self.total_blocks - lba)
                out_fp.write(self.read_sectors(lba, count))

    @classmethod
    def compress_iso(
        cls,
        iso_data_or_path: Union[str, bytes],
        output_path: Optional[str] = None,
        block_size: int = DEFAULT_BLOCK_SIZE,
        compression_level: int = 9,
    ) -> bytes:
        """
        Compresses an uncompressed ISO image into CSO format.
        If output_path is provided, writes directly to disk; otherwise returns bytes.
        """
        if isinstance(iso_data_or_path, str):
            iso_size = os.path.getsize(iso_data_or_path)
            stream: BinaryIO = open(iso_data_or_path, "rb")
            should_close = True
        else:
            iso_size = len(iso_data_or_path)
            stream = io.BytesIO(iso_data_or_path)
            should_close = False

        try:
            total_blocks = (iso_size + block_size - 1) // block_size
            header_size = 24
            align = 0  # No shift by default

            # Reserve index table
            index_table = [0] * (total_blocks + 1)
            index_bytes_len = (total_blocks + 1) * 4

            curr_offset = header_size + index_bytes_len

            payload_chunks: List[bytes] = []

            for i in range(total_blocks):
                sector_data = stream.read(block_size)
                if len(sector_data) < block_size:
                    sector_data = sector_data.ljust(block_size, b"\x00")

                # Compress with raw deflate (-15)
                comp = zlib.compress(sector_data, compression_level)
                # Check raw deflate header/trailer
                # In standard CSO, zlib wrapper or raw deflate is used
                # If compression saves space (e.g. comp < block_size):
                if len(comp) < block_size:
                    index_table[i] = curr_offset
                    payload_chunks.append(comp)
                    curr_offset += len(comp)
                else:
                    # Store raw uncompressed (flag bit 31)
                    index_table[i] = curr_offset | 0x80000000
                    payload_chunks.append(sector_data)
                    curr_offset += len(sector_data)

            # Final index entry is EOF offset
            index_table[total_blocks] = curr_offset

            # Build CSO binary header
            header = bytearray(24)
            header[0:4] = CSO_MAGIC
            struct.pack_into("<IQIBBH", header, 4, header_size, iso_size, block_size, 1, align, 0)

            # Pack index table
            packed_index = struct.pack(f"<{total_blocks + 1}I", *index_table)

            if output_path:
                os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
                with open(output_path, "wb") as fp:
                    fp.write(header)
                    fp.write(packed_index)
                    for chunk in payload_chunks:
                        fp.write(chunk)
                return b""
            else:
                out = bytearray(header)
                out.extend(packed_index)
                for chunk in payload_chunks:
                    out.extend(chunk)
                return bytes(out)

        finally:
            if should_close:
                stream.close()
