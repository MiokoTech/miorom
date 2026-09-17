"""
miorom.platforms.iso.rvz
~~~~~~~~~~~~~~~~~~~~~~~~
Nintendo Wii & GameCube RVZ / WIA Compressed Disc Image Container Engine.

Implements Dolphin Emulator's RVZ (WIA v2) specification:
- Sector/block-compressed disc image container with chunk-level lazy streaming.
- Compression algorithm support: Zstandard (zstd, Dolphin default), LZMA/LZMA2, Bzip2, and raw uncompressed.
- Deterministic Lagged Fibonacci PRNG padding reconstruction (f = xor, j = 32, k = 521).
- Sparse zero-chunk elimination with O(1) empty block generation.
- Full bidirectional support: reading/extracting and building/repacking.
"""

from __future__ import annotations

import bz2
import hashlib
import io
import lzma
from typing import Any, BinaryIO, Dict, List, Tuple

from miorom.core import schema
from miorom.core.schema import (
    I32,
    U8,
    U32,
    U64,
    BinaryStruct,
    RawBytes,
)
from miorom.errors import CompressionError, ParseError
from miorom.result import MioRomResult

try:
    import zstandard as zstd
except ImportError:
    zstd = None


RVZ_MAGIC = b"RVZ\x01"
WIA_MAGIC = b"WIA\x01"

COMPRESSION_NONE = 0
COMPRESSION_PURGE = 1
COMPRESSION_BZIP2 = 2
COMPRESSION_LZMA = 3
COMPRESSION_LZMA2 = 4
COMPRESSION_ZSTD = 5

DISC_TYPE_UNKNOWN = 0
DISC_TYPE_GAMECUBE = 1
DISC_TYPE_WII = 2

DEFAULT_CHUNK_SIZE = 131072  # 128 KiB chunk size for optimal streaming
MAX_LRU_CHUNKS = 8           # Maximum decompressed chunks kept in RAM (< 16 MB)


class RVZFileHeadStruct(BinaryStruct):
    """
    WIA/RVZ file head located at offset 0x00 (0x48 / 72 bytes).
    Format matches official Dolphin WiaAndRvz.md specification.
    """
    _endian = ">"
    magic = RawBytes(4, default=RVZ_MAGIC)
    version = U32(default=0x01000000)
    version_compatible = U32(default=0x00090000)
    disc_size = U32(default=0)               # Size of following RVZDiscHeadStruct
    disc_hash = RawBytes(20)                 # SHA-1 of RVZDiscHeadStruct
    iso_file_size = U64(default=0)           # Uncompressed disc size in bytes
    wia_file_size = U64(default=0)           # Total compressed file size
    file_head_hash = RawBytes(20)            # SHA-1 of first 0x34 bytes of this struct


class RVZDiscHeadStruct(BinaryStruct):
    """
    WIA/RVZ disc descriptor located at offset 0x48.
    """
    _endian = ">"
    disc_type = U32(default=DISC_TYPE_WII)   # 1 = GameCube, 2 = Wii
    compression = U32(default=COMPRESSION_ZSTD)
    compr_level = I32(default=5)
    chunk_size = U32(default=DEFAULT_CHUNK_SIZE)
    dhead = RawBytes(128)                    # First 128 bytes of root disc header
    n_part = U32(default=0)
    part_t_size = U32(default=0)
    part_off = U64(default=0)
    part_hash = RawBytes(20)
    n_raw_data = U32(default=1)
    raw_data_off = U64(default=0)
    raw_data_size = U32(default=0)
    n_groups = U32(default=0)
    group_off = U64(default=0)
    group_size = U32(default=0)
    compr_data_len = U8(default=0)
    compr_data = RawBytes(7)


class RVZGroupStruct(BinaryStruct):
    """
    12-byte entry in the RVZ group lookup table.
    """
    _endian = ">"
    data_off4 = U32()        # Physical file offset >> 2
    data_size = U32()        # Bit 31: is_compressed; Bits 0..30: compressed size in file
    rvz_packed_size = U32()  # Uncompressed size before RVZ PRNG packing


class RVZRawDataStruct(BinaryStruct):
    """
    Describes an unpartitioned raw data region in the disc image.
    """
    _endian = ">"
    raw_data_off = U64()     # Virtual offset in disc image
    data_size = U64()        # Length of raw data region
    group_index = U32()      # Starting index in group table
    n_groups = U32()         # Number of groups for this raw data

def generate_rvz_padding(seed: bytes, size: int) -> bytes:
    """
    Generates deterministic pseudo-random disc padding matching the Nintendo GC/Wii
    Lagged Fibonacci PRNG (f = xor, j = 32, k = 521) with 68-byte seed.
    """
    if len(seed) < 68:
        seed = seed.ljust(68, b"\x00")

    words = [schema.unpack_from(">I", seed, i * 4)[0] for i in range(17)]
    buf = [0] * 521
    buf[:17] = words

    for i in range(17, 521):
        buf[i] = (((buf[i - 17] << 23) & 0xFFFFFFFF) ^ (buf[i - 16] >> 9) ^ buf[i - 1]) & 0xFFFFFFFF

    # Run state advance 4 times before outputting
    for _ in range(4):
        for i in range(32):
            buf[i] = (buf[i] ^ buf[i + 521 - 32]) & 0xFFFFFFFF
        for i in range(32, 521):
            buf[i] = (buf[i] ^ buf[i - 32]) & 0xFFFFFFFF

    out = bytearray()
    buf_idx = 0

    while len(out) < size:
        if buf_idx >= 521:
            for i in range(32):
                buf[i] = (buf[i] ^ buf[i + 521 - 32]) & 0xFFFFFFFF
            for i in range(32, 521):
                buf[i] = (buf[i] ^ buf[i - 32]) & 0xFFFFFFFF
            buf_idx = 0

        word = buf[buf_idx]
        buf_idx += 1
        b0 = (word >> 24) & 0xFF
        b1 = (word >> 18) & 0xFF  # Note: 18 bits, not 16, per Nintendo spec
        b2 = (word >> 8) & 0xFF
        b3 = word & 0xFF

        needed = min(4, size - len(out))
        out.extend(bytes([b0, b1, b2, b3])[:needed])

    return bytes(out)


def decode_rvz_packing(packed_data: bytes, expected_size: int) -> bytes:
    """
    Decodes an RVZ packed chunk containing interleaved literal and PRNG segments.
    """
    pos = 0
    out = bytearray()
    data_len = len(packed_data)

    while pos < data_len and len(out) < expected_size:
        if pos + 4 > data_len:
            break
        raw_size = schema.unpack_from(">I", packed_data, pos)[0]
        pos += 4
        is_prng = bool(raw_size & 0x80000000)
        seg_size = raw_size & 0x7FFFFFFF

        if not is_prng:
            chunk = packed_data[pos : pos + seg_size]
            out.extend(chunk)
            pos += seg_size
        else:
            seed = packed_data[pos : pos + 68]
            pos += 68
            padding = generate_rvz_padding(seed, seg_size)
            out.extend(padding)

    return bytes(out)


# ==============================================================================
# Complete RVZ Disc Engine
# ==============================================================================

class RVZDisc(MioRomResult):
    """
    Nintendo GameCube & Wii RVZ / WIA block-compressed disc container.
    Provides random-access lazy streaming (read_at) with multi-algorithm decompression
    and automatic sparse chunk caching (< 16 MB RAM footprint).
    """

    def __init__(
        self,
        stream: BinaryIO,
        file_head: RVZFileHeadStruct,
        disc_head: RVZDiscHeadStruct,
        groups: List[RVZGroupStruct],
    ):
        self._stream = stream
        self.file_head = file_head
        self.disc_head = disc_head
        self.groups = list(groups)
        self.chunk_size = disc_head.chunk_size
        self.compression = disc_head.compression
        self.iso_file_size = file_head.iso_file_size
        self.disc_type = disc_head.disc_type
        self.dhead = disc_head.dhead

        # Chunk LRU memory cache: Dict[group_idx, bytes]
        self._cache: Dict[int, bytes] = {}
        self._cache_keys: List[int] = []

    @property
    def game_id(self) -> str:
        """Returns the 6-character Nintendo Game ID (e.g. 'RMCE01')."""
        return self.dhead[:6].decode("ascii", errors="replace").strip("\x00")

    @property
    def game_title(self) -> str:
        """Returns the internal disc game title."""
        raw_title = self.dhead[0x20:0x80]
        end = raw_title.find(b"\x00")
        if end != -1:
            raw_title = raw_title[:end]
        return raw_title.decode("shift-jis", errors="replace").strip()

    @property
    def magic(self) -> int:
        """Returns the 32-bit disc magic (0x5D1C9EA3 for Wii)."""
        return schema.unpack_from(">I", self.dhead, 0x18)[0]

    @property
    def gc_magic(self) -> int:
        """Returns the 32-bit GameCube magic (0xC2339F3D)."""
        return schema.unpack_from(">I", self.dhead, 0x1C)[0]

    def is_hash_valid(self) -> bool:
        """Verifies the SHA-1 checksums of the file header and disc descriptor."""
        fh_bytes = self.file_head.to_bytes()
        expected_fh_hash = hashlib.sha1(fh_bytes[:0x34]).digest()
        if self.file_head.file_head_hash != expected_fh_hash:
            return False

        dh_bytes = self.disc_head.to_bytes()
        expected_dh_hash = hashlib.sha1(dh_bytes).digest()
        return self.file_head.disc_hash == expected_dh_hash

    def close(self) -> None:
        """Closes the underlying binary stream if open."""
        if hasattr(self._stream, "close") and callable(self._stream.close):
            self._stream.close()

    def __enter__(self) -> "RVZDisc":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @classmethod
    def is_rvz(cls, data: bytes) -> bool:
        """Checks whether binary data starts with an RVZ or WIA header."""
        return len(data) >= 4 and (data[:4] == RVZ_MAGIC or data[:4] == WIA_MAGIC)

    @classmethod
    def from_bytes(cls, data: bytes) -> "RVZDisc":
        """Loads and parses an RVZ disc container from an in-memory byte buffer."""
        return cls.from_stream(io.BytesIO(data))

    @classmethod
    def from_file(cls, filepath: str) -> "RVZDisc":
        """Loads and parses an RVZ disc container directly from a file on disk."""
        f = open(filepath, "rb")
        return cls.from_stream(f)

    @classmethod
    def from_stream(cls, stream: BinaryIO) -> "RVZDisc":
        """Parses an RVZ/WIA disc container from any seekable binary stream."""
        stream.seek(0)
        file_head_raw = stream.read(RVZFileHeadStruct.sizeof())
        if len(file_head_raw) < RVZFileHeadStruct.sizeof():
            raise ParseError("Stream too small for RVZ file header (minimum 72 bytes).")

        magic = file_head_raw[:4]
        if magic != RVZ_MAGIC and magic != WIA_MAGIC:
            raise ParseError(f"Invalid RVZ/WIA magic: {magic!r}")

        file_head = RVZFileHeadStruct.from_bytes(file_head_raw, offset=0)

        # 2. Parse RVZDiscHeadStruct (starts at 0x48)
        stream.seek(0x48)
        disc_head_raw = stream.read(RVZDiscHeadStruct.sizeof())
        if len(disc_head_raw) < RVZDiscHeadStruct.sizeof():
            raise ParseError("Stream truncated before RVZ disc header.")

        disc_head = RVZDiscHeadStruct.from_bytes(disc_head_raw, offset=0)

        # 3. Read Group Table
        stream.seek(disc_head.group_off)
        group_table_raw = stream.read(disc_head.group_size)

        # If group table was compressed, decompress it
        if disc_head.compression == COMPRESSION_ZSTD and zstd is not None:
            try:
                group_table_raw = zstd.ZstdDecompressor().decompress(group_table_raw)
            except Exception:
                pass
        elif disc_head.compression in (COMPRESSION_LZMA, COMPRESSION_LZMA2):
            try:
                group_table_raw = lzma.decompress(group_table_raw)
            except Exception:
                pass
        elif disc_head.compression == COMPRESSION_BZIP2:
            try:
                group_table_raw = bz2.decompress(group_table_raw)
            except Exception:
                pass

        num_groups = disc_head.n_groups
        groups: List[RVZGroupStruct] = []
        entry_size = RVZGroupStruct.sizeof()

        for i in range(num_groups):
            off = i * entry_size
            if off + entry_size <= len(group_table_raw):
                groups.append(RVZGroupStruct.from_bytes(group_table_raw, offset=off))
            else:
                groups.append(RVZGroupStruct(data_off4=0, data_size=0, rvz_packed_size=0))

        return cls(
            stream=stream,
            file_head=file_head,
            disc_head=disc_head,
            groups=groups,
        )

    def _decompress_group(self, group_idx: int) -> bytes:
        """Decompresses and caches a single chunk group with LRU management."""
        if group_idx in self._cache:
            return self._cache[group_idx]

        if group_idx < 0 or group_idx >= len(self.groups):
            return b"\x00" * self.chunk_size

        g = self.groups[group_idx]
        data_size_flag = g.data_size
        is_compressed = bool(data_size_flag & 0x80000000)
        stored_size = data_size_flag & 0x7FFFFFFF

        # Special case: stored_size == 0 means chunk is 100% zeroes
        if stored_size == 0:
            zero_chunk = b"\x00" * self.chunk_size
            self._cache_chunk(group_idx, zero_chunk)
            return zero_chunk

        phys_offset = g.data_off4 << 2
        self._stream.seek(phys_offset)
        raw_payload = self._stream.read(stored_size)

        decompressed: bytes
        if is_compressed:
            if self.compression == COMPRESSION_ZSTD:
                if zstd is None:
                    raise CompressionError("Zstandard decompression requested but 'zstandard' module is not installed.")
                decompressed = zstd.ZstdDecompressor().decompress(raw_payload, max_output_size=self.chunk_size * 2)
            elif self.compression in (COMPRESSION_LZMA, COMPRESSION_LZMA2):
                decompressed = lzma.decompress(raw_payload)
            elif self.compression == COMPRESSION_BZIP2:
                decompressed = bz2.decompress(raw_payload)
            elif self.compression == COMPRESSION_NONE:
                decompressed = raw_payload
            else:
                raise CompressionError(f"Unsupported RVZ compression method: {self.compression}")
        else:
            decompressed = raw_payload

        # Decode RVZ packing if present
        if g.rvz_packed_size > 0:
            decompressed = decode_rvz_packing(decompressed, self.chunk_size)

        # Pad or truncate to chunk_size if necessary
        if len(decompressed) < self.chunk_size:
            decompressed = decompressed.ljust(self.chunk_size, b"\x00")
        elif len(decompressed) > self.chunk_size:
            decompressed = decompressed[: self.chunk_size]

        self._cache_chunk(group_idx, decompressed)
        return decompressed

    def _cache_chunk(self, group_idx: int, data: bytes) -> None:
        """Stores chunk in memory with LRU eviction."""
        if len(self._cache_keys) >= MAX_LRU_CHUNKS:
            oldest = self._cache_keys.pop(0)
            self._cache.pop(oldest, None)
        self._cache[group_idx] = data
        self._cache_keys.append(group_idx)

    def read_at(self, virtual_offset: int, size: int) -> bytes:
        """
        Reads an unencrypted byte slice from the virtual optical disc image.
        Decompresses and caches only the exact chunks covering the requested range.
        Satisfies the DiscStream interface.
        """
        if size <= 0 or virtual_offset >= self.iso_file_size:
            return b""

        # Cap size to remaining virtual disc size
        actual_size = min(size, self.iso_file_size - virtual_offset)
        out = bytearray()
        remaining = actual_size
        curr_voff = virtual_offset

        while remaining > 0:
            group_idx = curr_voff // self.chunk_size
            chunk_suboff = curr_voff % self.chunk_size
            chunk_bytes = min(remaining, self.chunk_size - chunk_suboff)

            chunk_data = self._decompress_group(group_idx)
            out.extend(chunk_data[chunk_suboff : chunk_suboff + chunk_bytes])

            curr_voff += chunk_bytes
            remaining -= chunk_bytes

        return bytes(out)

    @classmethod
    def create_from_stream(
        cls,
        disc_stream: Any,
        total_size: int,
        disc_type: int = DISC_TYPE_WII,
        compression: int = COMPRESSION_ZSTD,
        compr_level: int = 5,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> bytes:
        """
        Compresses an arbitrary disc stream into a compliant RVZ binary buffer.
        Optimizes zero-byte chunks with zero storage overhead.
        """
        if compression == COMPRESSION_ZSTD and zstd is None:
            # Fallback to LZMA if zstandard is not available
            compression = COMPRESSION_LZMA

        # 1. Read first 128 bytes of root disc header
        dhead = disc_stream.read_at(0, 128)
        if len(dhead) < 128:
            dhead = dhead.ljust(128, b"\x00")

        # 2. Slice disc into chunks
        num_chunks = (total_size + chunk_size - 1) // chunk_size
        groups: List[RVZGroupStruct] = []
        payload_chunks: List[Tuple[int, bytes]] = []

        # Data starts after FileHead (0x48) + DiscHead (0xA0) + GroupTable
        # We estimate header size and write sequentially
        group_table_size = num_chunks * RVZGroupStruct.sizeof()
        file_data_offset = (0x48 + RVZDiscHeadStruct.sizeof() + group_table_size + 3) & ~3

        curr_phys_offset = file_data_offset

        for i in range(num_chunks):
            v_off = i * chunk_size
            chunk_data = disc_stream.read_at(v_off, chunk_size)

            # Check if chunk is completely zero
            if not any(b != 0 for b in chunk_data):
                # Sparse zero-chunk: size = 0
                groups.append(RVZGroupStruct(data_off4=0, data_size=0, rvz_packed_size=0))
                continue

            # Compress chunk
            is_comp = True
            compressed: bytes
            if compression == COMPRESSION_ZSTD and zstd is not None:
                compressed = zstd.ZstdCompressor(level=compr_level).compress(chunk_data)
            elif compression in (COMPRESSION_LZMA, COMPRESSION_LZMA2):
                compressed = lzma.compress(chunk_data)
            elif compression == COMPRESSION_BZIP2:
                compressed = bz2.compress(chunk_data)
            else:
                compressed = chunk_data
                is_comp = False

            # If compression didn't shrink data, store raw
            if len(compressed) >= len(chunk_data):
                compressed = chunk_data
                is_comp = False

            data_flag = len(compressed)
            if is_comp:
                data_flag |= 0x80000000  # Set MSB

            groups.append(
                RVZGroupStruct(
                    data_off4=curr_phys_offset >> 2,
                    data_size=data_flag,
                    rvz_packed_size=0,
                )
            )
            payload_chunks.append((curr_phys_offset, compressed))
            curr_phys_offset = (curr_phys_offset + len(compressed) + 3) & ~3

        total_rvz_size = curr_phys_offset

        # 3. Build Disc Head
        disc_head = RVZDiscHeadStruct(
            disc_type=disc_type,
            compression=compression,
            compr_level=compr_level,
            chunk_size=chunk_size,
            dhead=dhead,
            n_part=0,
            part_t_size=0,
            part_off=0,
            part_hash=b"\x00" * 20,
            n_raw_data=1,
            raw_data_off=0,
            raw_data_size=0,
            n_groups=num_chunks,
            group_off=0x48 + RVZDiscHeadStruct.sizeof(),
            group_size=group_table_size,
            compr_data_len=0,
            compr_data=b"\x00" * 7,
        )

        disc_head_bytes = disc_head.to_bytes()
        disc_head_hash = hashlib.sha1(disc_head_bytes).digest()

        # 4. Build File Head
        file_head_partial = bytearray(0x34)
        file_head_partial[:4] = RVZ_MAGIC
        schema.pack_into(">I", file_head_partial, 4, 0x01000000)
        schema.pack_into(">I", file_head_partial, 8, 0x00090000)
        schema.pack_into(">I", file_head_partial, 12, len(disc_head_bytes))
        file_head_partial[16:36] = disc_head_hash
        schema.pack_into(">Q", file_head_partial, 36, total_size)
        schema.pack_into(">Q", file_head_partial, 44, total_rvz_size)

        head_hash = hashlib.sha1(file_head_partial).digest()

        file_head_full = file_head_partial + head_hash

        # 5. Assemble buffer
        bio = io.BytesIO()
        bio.write(file_head_full)
        bio.seek(0x48)
        bio.write(disc_head_bytes)

        # Write Group Table
        bio.seek(disc_head.group_off)
        for g in groups:
            bio.write(g.to_bytes())

        # Write Chunks
        for p_off, p_data in payload_chunks:
            bio.seek(p_off)
            bio.write(p_data)

        # Pad file to 4-byte boundary
        val = bytearray(bio.getvalue())
        if len(val) < total_rvz_size:
            val.extend(b"\x00" * (total_rvz_size - len(val)))

        return bytes(val)

    def save(self, path: str) -> None:
        """Saves this RVZ container to a file on disk."""
        with open(path, "wb") as f:
            f.write(self.to_bytes())

    def to_bytes(self) -> bytes:
        """Serializes this disc back into an in-memory byte buffer."""
        return self.create_from_stream(
            disc_stream=self,
            total_size=self.iso_file_size,
            disc_type=self.disc_type,
            compression=self.compression,
            chunk_size=self.chunk_size,
        )
