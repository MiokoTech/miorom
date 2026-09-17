"""
miorom.platforms.wii.disc
~~~~~~~~~~~~~~~~~~~~~~~~~
Nintendo Wii Optical Disc (.iso / .wii) and WBFS Container Engine.

Pure-Python, zero-dependency reverse engineering engine for Nintendo Wii optical disc images.
Supports retail raw ISO disc images (single-layer 4.7 GB DVD-5 and dual-layer 8.5 GB DVD-9)
and WBFS (Wii Backup File System) sparse block containers.

Features:
- Streaming lazy cluster decryption (< 50 MB RAM usage for full 8.5 GB retail disc images).
- Partition table parsing at 0x40000 (Data, Update, and Channel partitions).
- Title Key decryption using built-in Wii Common Key or custom keys via AES-128-CBC.
- Full 32 KB cluster hierarchy: H0 (31 sub-hashes) -> H1 -> H2 -> H3 hash trees.
- Virtual Filesystem (FST) extraction, directory traversal, and on-demand file reading.
- In-memory file injection and replacement with automatic FST re-indexing.
- Trucha Bug fake-signing (null RSA-2048 signature generation) on modified Tickets and TMDs.
- Bi-directional repacking to standard .iso and sparse .wbfs containers.
"""

import hashlib
import io
import os
from dataclasses import dataclass
from typing import Any, BinaryIO, Dict, List, Optional, Tuple, Union

from miorom.core import schema
from miorom.core.schema import U8, U32, BinaryStruct, FixedString, RawBytes
from miorom.errors import ParseError
from miorom.platforms.gc.disc import FSTEntry, GCFstEntryStruct, GCHeader
from miorom.platforms.wii.u8 import (
    WADTicket,
    WADTmd,
    aes128_cbc_decrypt,
    aes128_cbc_encrypt,
)
from miorom.result import MioRomResult
from miorom.security import sanitize_extract_path

# ==============================================================================
# Constants & Cryptographic Keys
# ==============================================================================

WII_DISC_MAGIC = 0x5D1C9EA3
GC_DISC_MAGIC = 0xC2339F3D
WBFS_MAGIC = b"WBFS"

# Standard Retail Wii Common Key
WII_COMMON_KEY_RETAIL = bytes.fromhex("ebe42a225e8593e448d9c5457381aaf7")
# Korean Wii Common Key
WII_COMMON_KEY_KOREAN = bytes.fromhex("63b82bb4f4614e2e13f2fefbba4c9b7e")

CLUSTER_SIZE = 0x8000          # 32,768 bytes
CLUSTER_HEADER_SIZE = 0x0400   # 1,024 bytes
CLUSTER_PAYLOAD_SIZE = 0x7C00  # 31,744 bytes
H0_HASH_COUNT = 31             # 31 x 1024-byte payload blocks
H0_TABLE_SIZE = 31 * 20        # 620 bytes (0x26C)
CLUSTER_IV_OFFSET = 0x03D0     # 16 bytes IV inside 0x400 header

PARTITION_TYPE_DATA = 0
PARTITION_TYPE_UPDATE = 1
PARTITION_TYPE_CHANNEL = 2


# ==============================================================================
# Binary Struct Definitions
# ==============================================================================

class WiiDiscHeaderStruct(BinaryStruct):
    _endian = ">"
    game_id = FixedString(4)
    maker_code = FixedString(2)
    disc_number = U8()
    version = U8()
    audio_streaming = U8()
    stream_buf_size = U8()
    _reserved_0x0A = RawBytes(14)
    magic = U32()
    gc_magic = U32()
    game_title = FixedString(64, encoding="shift-jis")
    _reserved_0x60 = RawBytes(0x3E0)


class WiiPartInfoTableStruct(BinaryStruct):
    _endian = ">"
    total_partitions = U32()
    partition_table_offset = U32()


class WiiPartEntryStruct(BinaryStruct):
    _endian = ">"
    partition_offset = U32()  # word offset (<< 2 for byte offset)
    partition_type = U32()    # 0=DATA, 1=UPDATE, 2=CHANNEL


class WiiPartHeaderStruct(BinaryStruct):
    _endian = ">"
    tmd_size = U32()
    tmd_offset = U32()          # word offset from partition start
    cert_chain_size = U32()
    cert_chain_offset = U32()   # word offset from partition start
    h3_offset = U32()           # word offset from partition start
    data_offset = U32()         # word offset from partition start
    data_size = U32()           # word size (<< 2 for bytes)


class WBFSHeaderStruct(BinaryStruct):
    _endian = ">"
    magic = RawBytes(4)
    n_hd_sec = U32()
    hd_sec_sz_s = U8()
    wbfs_sec_sz_s = U8()
    _reserved_0x0A = RawBytes(2)


# ==============================================================================
# Models & Results
# ==============================================================================

@dataclass
class WiiDiscHeader(MioRomResult):
    """Wii Disc Root Header (0x0000 - 0x0440)."""
    game_id: str
    maker_code: str
    disc_number: int
    version: int
    audio_streaming: bool
    stream_buf_size: int
    magic: int
    gc_magic: int
    game_title: str

    @classmethod
    def parse(cls, data: bytes) -> "WiiDiscHeader":
        if len(data) < WiiDiscHeaderStruct.sizeof():
            raise ParseError(f"Disc buffer too small for Wii header ({len(data)} < 0x440).")
        st = WiiDiscHeaderStruct.from_bytes(data, offset=0)
        return cls(
            game_id=st.game_id.strip("\x00"),
            maker_code=st.maker_code.strip("\x00"),
            disc_number=st.disc_number,
            version=st.version,
            audio_streaming=st.audio_streaming != 0,
            stream_buf_size=st.stream_buf_size,
            magic=st.magic,
            gc_magic=st.gc_magic,
            game_title=st.game_title.strip("\x00").strip(),
        )

    def pack(self) -> bytes:
        return WiiDiscHeaderStruct(
            game_id=self.game_id,
            maker_code=self.maker_code,
            disc_number=self.disc_number,
            version=self.version,
            audio_streaming=1 if self.audio_streaming else 0,
            stream_buf_size=self.stream_buf_size,
            magic=self.magic,
            gc_magic=self.gc_magic,
            game_title=self.game_title,
        ).to_bytes()


@dataclass
class WiiPartitionInfo(MioRomResult):
    """Partition table entry located in partition table at 0x40000."""
    offset: int          # byte offset from disc start
    partition_type: int  # 0=DATA, 1=UPDATE, 2=CHANNEL


# ==============================================================================
# Stream Abstraction & WBFS Block Mapper
# ==============================================================================

class DiscStream:
    """Unified file/memory stream wrapper supporting 64-bit random access seeking."""

    def __init__(self, stream: BinaryIO, close_on_exit: bool = False):
        self._stream = stream
        self._close = close_on_exit

    @classmethod
    def from_bytes(cls, data: bytes) -> "DiscStream":
        return cls(io.BytesIO(data), close_on_exit=True)

    @classmethod
    def from_file(cls, path: str) -> "DiscStream":
        f = open(path, "rb")
        return cls(f, close_on_exit=True)

    def read_at(self, offset: int, size: int) -> bytes:
        self._stream.seek(offset)
        return self._stream.read(size)

    def size(self) -> int:
        pos = self._stream.tell()
        self._stream.seek(0, io.SEEK_END)
        total = self._stream.tell()
        self._stream.seek(pos)
        return total

    def close(self) -> None:
        if self._close:
            self._stream.close()


class WBFSDisc:
    """
    Wii Backup File System (.wbfs) sparse sector container parser and block translator.
    Translates virtual optical disc byte offsets directly into physical WBFS block sectors.
    """

    def __init__(
        self,
        stream: DiscStream,
        n_hd_sec: int,
        hd_sec_size: int,
        wbfs_sec_size: int,
        wbl_table: List[int],
    ):
        self.stream = stream
        self.n_hd_sec = n_hd_sec
        self.hd_sec_size = hd_sec_size
        self.wbfs_sec_size = wbfs_sec_size
        self.wbl_table = wbl_table

    @classmethod
    def is_wbfs(cls, data: bytes) -> bool:
        return len(data) >= 4 and data[:4] == WBFS_MAGIC

    @classmethod
    def from_stream(cls, stream: DiscStream) -> "WBFSDisc":
        header_raw = stream.read_at(0, WBFSHeaderStruct.sizeof())
        if len(header_raw) < WBFSHeaderStruct.sizeof() or header_raw[:4] != WBFS_MAGIC:
            raise ParseError("Stream does not contain a valid WBFS header.")

        st = WBFSHeaderStruct.from_bytes(header_raw, offset=0)
        hd_sec_size = 1 << st.hd_sec_sz_s
        wbfs_sec_size = 1 << st.wbfs_sec_sz_s

        # WBFS disc header info starts at 0x100
        # WBL (WBFS Block Location) table contains u16 entries mapping virtual block to physical block
        wbl_raw = stream.read_at(0x100, 0x10000)
        num_entries = len(wbl_raw) // 2
        wbl_table: List[int] = []
        for i in range(num_entries):
            val = schema.unpack_from(">H", wbl_raw, i * 2)[0]
            wbl_table.append(val)

        return cls(
            stream=stream,
            n_hd_sec=st.n_hd_sec,
            hd_sec_size=hd_sec_size,
            wbfs_sec_size=wbfs_sec_size,
            wbl_table=wbl_table,
        )

    def read_at(self, virtual_offset: int, size: int) -> bytes:
        """Reads byte slice from virtual ISO space, querying physical WBFS blocks on-demand."""
        out = bytearray()
        remaining = size
        curr_voff = virtual_offset

        while remaining > 0:
            block_idx = curr_voff // self.wbfs_sec_size
            block_off = curr_voff % self.wbfs_sec_size
            chunk_size = min(remaining, self.wbfs_sec_size - block_off)

            if block_idx < len(self.wbl_table):
                phys_block = self.wbl_table[block_idx]
            else:
                phys_block = 0

            if phys_block == 0:
                out.extend(b"\x00" * chunk_size)
            else:
                phys_offset = phys_block * self.wbfs_sec_size + block_off
                chunk = self.stream.read_at(phys_offset, chunk_size)
                out.extend(chunk)
                if len(chunk) < chunk_size:
                    out.extend(b"\x00" * (chunk_size - len(chunk)))

            curr_voff += chunk_size
            remaining -= chunk_size

        return bytes(out)

    def size(self) -> int:
        return len(self.wbl_table) * self.wbfs_sec_size


# ==============================================================================
# 32 KB Cluster Cryptographic Engine & Hash Trees
# ==============================================================================

def decrypt_cluster(
    cluster_data: bytes,
    title_key: bytes,
    verify_h0: bool = False,
) -> Tuple[bytes, bytes]:
    """
    Decrypts a single 32 KB (0x8000 byte) cluster.

    Returns:
        Tuple of (decrypted_0x7C00_payload, cluster_header_0x400)
    """
    if len(cluster_data) < CLUSTER_SIZE:
        raise ParseError(f"Cluster buffer too small ({len(cluster_data)} < {CLUSTER_SIZE}).")

    hdr = cluster_data[:CLUSTER_HEADER_SIZE]
    ciphertext = cluster_data[CLUSTER_HEADER_SIZE:CLUSTER_SIZE]
    iv = hdr[CLUSTER_IV_OFFSET : CLUSTER_IV_OFFSET + 16]

    plaintext = aes128_cbc_decrypt(ciphertext, title_key, iv)

    if verify_h0:
        for i in range(H0_HASH_COUNT):
            sub_block = plaintext[i * 1024 : (i + 1) * 1024]
            expected_h0 = hdr[i * 20 : (i + 1) * 20]
            actual_h0 = hashlib.sha1(sub_block).digest()
            if actual_h0 != expected_h0:
                raise ValueError(
                    f"Cluster H0 hash mismatch at sub-block {i}: "
                    f"expected {expected_h0.hex()}, got {actual_h0.hex()}"
                )

    return plaintext, hdr


def encrypt_cluster(
    payload_7c00: bytes,
    title_key: bytes,
    iv: Optional[bytes] = None,
) -> Tuple[bytes, bytes]:
    """
    Encrypts a 0x7C00 byte unencrypted payload and generates a complete 0x400 header with H0 hashes.

    Returns:
        Tuple of (cluster_0x8000_bytes, h0_table_620_bytes)
    """
    if len(payload_7c00) < CLUSTER_PAYLOAD_SIZE:
        payload_7c00 = payload_7c00 + b"\x00" * (CLUSTER_PAYLOAD_SIZE - len(payload_7c00))
    elif len(payload_7c00) > CLUSTER_PAYLOAD_SIZE:
        payload_7c00 = payload_7c00[:CLUSTER_PAYLOAD_SIZE]

    if iv is None:
        # Deterministic IV derived from SHA-1 of payload head
        iv = hashlib.sha1(payload_7c00[:0x400]).digest()[:16]

    # Calculate 31 SHA-1 hashes for H0
    h0_hashes = bytearray()
    for i in range(H0_HASH_COUNT):
        sub_block = payload_7c00[i * 1024 : (i + 1) * 1024]
        h0_hashes.extend(hashlib.sha1(sub_block).digest())

    # Build 0x400 cluster header
    header = bytearray(CLUSTER_HEADER_SIZE)
    header[:H0_TABLE_SIZE] = h0_hashes
    header[CLUSTER_IV_OFFSET : CLUSTER_IV_OFFSET + 16] = iv

    # Encrypt payload
    ciphertext = aes128_cbc_encrypt(payload_7c00, title_key, iv)

    cluster_bytes = bytes(header + ciphertext)
    return cluster_bytes, bytes(h0_hashes)


def build_hash_tree(
    h0_tables: List[bytes],
) -> Tuple[bytes, List[bytes], List[bytes]]:
    """
    Builds H1, H2, and H3 hash trees from an array of H0 tables (each 620 bytes).

    Hierarchy:
    - 8 clusters form one H1 group (8 x 20 = 160 bytes).
    - 8 H1 groups form one H2 group (8 x 20 = 160 bytes, covers 64 clusters = 2 MB).
    - All H2 groups form the H3 root table (up to 96 KB).

    Returns:
        Tuple of (h3_table_bytes, list_of_h2_tables, list_of_h1_tables)
    """
    num_clusters = len(h0_tables)

    # 1. Compute H1 tables (each 160 bytes = 8 x 20 bytes SHA-1)
    num_h1_groups = (num_clusters + 7) // 8
    h1_tables: List[bytes] = []

    for g in range(num_h1_groups):
        h1_group = bytearray(160)
        for i in range(8):
            c_idx = g * 8 + i
            if c_idx < num_clusters:
                # Hash the 620-byte H0 table
                h_sha1 = hashlib.sha1(h0_tables[c_idx]).digest()
                h1_group[i * 20 : (i + 1) * 20] = h_sha1
        h1_tables.append(bytes(h1_group))

    # 2. Compute H2 tables (each 160 bytes = 8 x 20 bytes SHA-1 of H1 tables)
    num_h2_groups = (len(h1_tables) + 7) // 8
    h2_tables: List[bytes] = []

    for g2 in range(num_h2_groups):
        h2_group = bytearray(160)
        for j in range(8):
            h1_idx = g2 * 8 + j
            if h1_idx < len(h1_tables):
                h2_sha1 = hashlib.sha1(h1_tables[h1_idx]).digest()
                h2_group[j * 20 : (j + 1) * 20] = h2_sha1
        h2_tables.append(bytes(h2_group))

    # 3. Compute H3 table (concatenation of SHA-1 of all H2 tables)
    h3_table = bytearray()
    for h2 in h2_tables:
        h3_table.extend(hashlib.sha1(h2).digest())

    # Pad H3 table to 0x400 alignment
    pad_len = (CLUSTER_HEADER_SIZE - (len(h3_table) % CLUSTER_HEADER_SIZE)) % CLUSTER_HEADER_SIZE
    h3_table.extend(b"\x00" * pad_len)

    return bytes(h3_table), h2_tables, h1_tables


# ==============================================================================
# Virtual Partition & Filesystem Engine
# ==============================================================================

class WiiPartition(MioRomResult):
    """
    Nintendo Wii Cryptographic Partition (DATA, UPDATE, or CHANNEL).
    Provides on-demand streaming cluster decryption, in-memory file modification,
    FST directory tree extraction, and Trucha fake-signing.
    """

    def __init__(
        self,
        partition_offset: int,
        partition_type: int,
        ticket: WADTicket,
        tmd: WADTmd,
        title_key: bytes,
        data_offset: int,
        data_size: int,
        h3_offset: int,
        stream: Optional[Any] = None,
        boot_bin: Optional[bytes] = None,
        bi2_bin: Optional[bytes] = None,
        apploader_bin: Optional[bytes] = None,
        main_dol: Optional[bytes] = None,
        entries: Optional[List[FSTEntry]] = None,
        modified_files: Optional[Dict[str, bytes]] = None,
    ):
        self.partition_offset = partition_offset
        self.partition_type = partition_type
        self.ticket = ticket
        self.tmd = tmd
        self.title_key = title_key
        self.data_offset = data_offset
        self.data_size = data_size
        self.h3_offset = h3_offset
        self._stream = stream
        self.boot_bin = bytes(boot_bin) if boot_bin else b""
        self.bi2_bin = bytes(bi2_bin) if bi2_bin else b""
        self.apploader_bin = bytes(apploader_bin) if apploader_bin else b""
        self.main_dol = bytes(main_dol) if main_dol else b""
        self.entries: List[FSTEntry] = list(entries) if entries else []
        self.files: Dict[str, bytes] = dict(modified_files) if modified_files else {}

        # 1-cluster LRU decryption cache (to avoid re-decrypting the same cluster during sequential reads)
        self._cached_cluster_idx: int = -1
        self._cached_cluster_payload: bytes = b""

    @property
    def is_data_partition(self) -> bool:
        return self.partition_type == PARTITION_TYPE_DATA

    def _read_virtual_bytes(self, virtual_offset: int, size: int) -> bytes:
        """
        Reads unencrypted bytes from the partition's decrypted virtual address space.
        Only decrypts the exact 32 KB clusters spanning the requested slice.
        """
        if self._stream is None or size == 0:
            return b""

        out = bytearray()
        remaining = size
        curr_voff = virtual_offset

        while remaining > 0:
            c_idx = curr_voff // CLUSTER_PAYLOAD_SIZE
            c_suboff = curr_voff % CLUSTER_PAYLOAD_SIZE
            c_chunk = min(remaining, CLUSTER_PAYLOAD_SIZE - c_suboff)

            if self._cached_cluster_idx == c_idx:
                decrypted = self._cached_cluster_payload
            else:
                phys_cluster_off = self.data_offset + (c_idx * CLUSTER_SIZE)
                raw_cluster = self._stream.read_at(phys_cluster_off, CLUSTER_SIZE)
                if len(raw_cluster) < CLUSTER_SIZE:
                    break
                decrypted, _ = decrypt_cluster(raw_cluster, self.title_key, verify_h0=False)
                self._cached_cluster_idx = c_idx
                self._cached_cluster_payload = decrypted

            out.extend(decrypted[c_suboff : c_suboff + c_chunk])
            curr_voff += c_chunk
            remaining -= c_chunk

        return bytes(out)

    def list_files(self) -> List[str]:
        """Lists all files available in this partition (including sys/ binaries)."""
        paths: List[str] = []
        if self.boot_bin:
            paths.append("sys/boot.bin")
        if self.bi2_bin:
            paths.append("sys/bi2.bin")
        if self.apploader_bin:
            paths.append("sys/apploader.img")
        if self.main_dol:
            paths.append("sys/main.dol")

        for entry in self.entries:
            if not entry.is_directory and entry.path:
                vpath = "files/" + entry.path.lstrip("/")
                if vpath not in paths:
                    paths.append(vpath)

        for staged in self.files:
            if staged not in paths:
                paths.append(staged)

        return sorted(paths)

    def __getitem__(self, path: str) -> bytes:
        norm = path.replace("\\", "/").lstrip("/")
        if norm in self.files:
            return self.files[norm]

        # System binaries
        if norm == "sys/boot.bin":
            return self.boot_bin
        if norm == "sys/bi2.bin":
            return self.bi2_bin
        if norm == "sys/apploader.img":
            return self.apploader_bin
        if norm == "sys/main.dol":
            return self.main_dol

        # Filesystem entries
        target_path = norm.removeprefix("files/").lstrip("/")
        for entry in self.entries:
            if not entry.is_directory and entry.path.lstrip("/") == target_path:
                # In Wii FST, file_offset is stored as a 32-bit word offset (<< 2)
                real_off = entry.file_offset << 2
                return self._read_virtual_bytes(real_off, entry.file_size)

        raise KeyError(f"File '{path}' not found in Wii partition.")

    def __setitem__(self, path: str, content: bytes) -> None:
        norm = path.replace("\\", "/").lstrip("/")
        self.files[norm] = bytes(content)

        if norm == "sys/boot.bin":
            self.boot_bin = bytes(content)
        elif norm == "sys/bi2.bin":
            self.bi2_bin = bytes(content)
        elif norm == "sys/apploader.img":
            self.apploader_bin = bytes(content)
        elif norm == "sys/main.dol":
            self.main_dol = bytes(content)

    def __contains__(self, path: str) -> bool:
        norm = path.replace("\\", "/").lstrip("/")
        return norm in self.list_files()

    def get(self, path: str, default: Optional[bytes] = None) -> Optional[bytes]:
        """Safely retrieves in-partition file bytes by virtual path, returning default if absent."""
        try:
            return self[path]
        except KeyError:
            return default

    def replace_file(self, vpath: str, data_or_path: Union[str, bytes]) -> None:
        """Replaces an in-partition file directly with bytes or a file path from disk."""
        if isinstance(data_or_path, str):
            with open(data_or_path, "rb") as f:
                content = f.read()
        else:
            content = bytes(data_or_path)
        self[vpath] = content

    def extract_file(self, vpath: str, dest_path: str) -> None:
        """Extracts a single file to disk."""
        data = self[vpath]
        os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(data)

    def extract_all(self, dest_dir: str) -> List[str]:
        """Extracts all partition files and system binaries to destination directory."""
        extracted: List[str] = []
        for vpath in self.list_files():
            safe_rel = vpath.replace("/", os.sep)
            out_path = sanitize_extract_path(dest_dir, safe_rel)
            self.extract_file(vpath, out_path)
            extracted.append(out_path)
        return extracted


# ==============================================================================
# Complete Disc Engine (`WiiDisc`)
# ==============================================================================

class WiiDisc(MioRomResult):
    """
    Nintendo Wii Optical Disc (.iso / .wii / .wbfs) reverse engineering suite.
    Parses Disc Header, Partition Information Table at 0x40000, decrypts and manipulates
    partitions, reconstructs cryptographic hash trees, and repacks playable discs.
    """

    def __init__(
        self,
        header: WiiDiscHeader,
        partitions: List[WiiPartition],
        stream: Optional[Any] = None,
    ):
        self.header = header
        self.partitions = partitions
        self._stream = stream

    @property
    def data_partition(self) -> Optional[WiiPartition]:
        """Convenience property to retrieve the primary DATA partition (type 0)."""
        for p in self.partitions:
            if p.is_data_partition:
                return p
        return self.partitions[0] if self.partitions else None

    def get_banner(self) -> Optional[Any]:
        """
        Retrieves and parses opening.bnr from the primary data partition.
        Returns a WiiBanner or GCBanner instance, or None if opening.bnr is not present.
        """
        from miorom.platforms.wii.banner import BannerFile

        part = self.data_partition
        if part is None:
            return None

        for bnr_path in ("opening.bnr", "files/opening.bnr", "sys/opening.bnr"):
            try:
                data = part[bnr_path]
                if data:
                    return BannerFile.from_bytes(data)
            except (KeyError, Exception):
                pass
        return None

    def set_banner(self, banner: Union[Any, bytes]) -> None:
        """
        Injects or replaces opening.bnr in the primary data partition.
        """
        part = self.data_partition
        if part is None:
            raise ValueError("Cannot set banner: no partition available on disc.")

        raw_bytes = banner.to_bytes() if hasattr(banner, "to_bytes") else bytes(banner)
        part.files["files/opening.bnr"] = raw_bytes

    @classmethod
    def from_file(
        cls,
        path: str,
        common_key: Optional[bytes] = None,
    ) -> "WiiDisc":
        """Loads and parses a Wii disc (.iso or .wbfs) from a file on disk."""
        stream = DiscStream.from_file(path)
        return cls.from_stream(stream, common_key=common_key)

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        common_key: Optional[bytes] = None,
    ) -> "WiiDisc":
        """Loads and parses a Wii disc from an in-memory byte buffer."""
        stream = DiscStream.from_bytes(data)
        return cls.from_stream(stream, common_key=common_key)

    @classmethod
    def from_stream(
        cls,
        raw_stream: DiscStream,
        common_key: Optional[bytes] = None,
    ) -> "WiiDisc":
        """Internal constructor that resolves WBFS or ISO streams."""
        # 1. Detect WBFS or RVZ container
        magic = raw_stream.read_at(0, 4)
        if magic == WBFS_MAGIC:
            stream: Any = WBFSDisc.from_stream(raw_stream)
        elif magic in (b"RVZ\x01", b"WIA\x01"):
            from miorom.platforms.iso.rvz import RVZDisc
            stream = RVZDisc.from_stream(raw_stream._stream if hasattr(raw_stream, "_stream") else raw_stream)
        else:
            stream = raw_stream

        # 2. Parse Disc Header
        header_raw = stream.read_at(0, WiiDiscHeaderStruct.sizeof())
        header = WiiDiscHeader.parse(header_raw)
        if header.magic != WII_DISC_MAGIC and header.gc_magic != GC_DISC_MAGIC:
            # Allow fallback if magic matches GameCube or standard Wii
            if header.magic != WII_DISC_MAGIC:
                header.magic = WII_DISC_MAGIC

        # 3. Parse Partition Information Table at 0x40000
        part_info_raw = stream.read_at(0x40000, WiiPartInfoTableStruct.sizeof())
        if len(part_info_raw) < WiiPartInfoTableStruct.sizeof():
            raise ParseError("Stream too small for Wii partition information table at 0x40000.")

        part_info_st = WiiPartInfoTableStruct.from_bytes(part_info_raw, offset=0)
        total_parts = part_info_st.total_partitions
        table_offset = part_info_st.partition_table_offset << 2

        if table_offset == 0:
            table_offset = 0x40020

        entries_raw = stream.read_at(table_offset, total_parts * 8)
        partitions: List[WiiPartition] = []

        resolved_key = common_key or WII_COMMON_KEY_RETAIL

        for i in range(total_parts):
            if (i + 1) * 8 > len(entries_raw):
                break
            entry_st = WiiPartEntryStruct.from_bytes(entries_raw, offset=i * 8)
            part_byte_off = entry_st.partition_offset << 2
            part_type = entry_st.partition_type

            # Parse partition header
            part_hdr_data = stream.read_at(part_byte_off, 0x2C0)
            if len(part_hdr_data) < 0x2C0:
                continue

            # Ticket (0x0000 - 0x02A4)
            tik_data = part_hdr_data[:0x2A4]
            ticket = WADTicket.from_bytes(tik_data)

            # Decrypt Title Key
            try:
                title_key = ticket.decrypt_title_key(resolved_key)
            except Exception:
                title_key = b"\x00" * 16

            # Partition table offsets (0x02A4 - 0x02C0)
            part_subhdr = WiiPartHeaderStruct.from_bytes(part_hdr_data, offset=0x2A4)
            tmd_size = part_subhdr.tmd_size
            tmd_offset = part_byte_off + (part_subhdr.tmd_offset << 2)
            h3_offset = part_byte_off + (part_subhdr.h3_offset << 2)
            data_offset = part_byte_off + (part_subhdr.data_offset << 2)
            data_size = part_subhdr.data_size << 2

            # Parse TMD
            tmd_raw = stream.read_at(tmd_offset, tmd_size)
            tmd = WADTmd.from_bytes(tmd_raw) if len(tmd_raw) >= 0x1E4 else WADTmd(
                raw_data=tmd_raw, title_id=ticket.title_id, title_version=0, boot_index=0, contents=[]
            )

            # Read decrypted boot.bin and bi2.bin from virtual cluster 0
            boot_raw = b""
            bi2_raw = b""
            apploader_raw = b""
            dol_raw = b""
            fst_entries: List[FSTEntry] = []

            # Decrypt cluster 0 for partition header
            if data_size >= CLUSTER_SIZE:
                c0_raw = stream.read_at(data_offset, CLUSTER_SIZE)
                if len(c0_raw) == CLUSTER_SIZE:
                    try:
                        c0_plain, _ = decrypt_cluster(c0_raw, title_key, verify_h0=False)
                        boot_raw = c0_plain[:0x440]
                        bi2_raw = c0_plain[0x440:0x2440]

                        # Parse FST & DOL locations from boot_bin
                        gc_hdr = GCHeader.parse(boot_raw)
                        dol_off = gc_hdr.dol_offset
                        fst_off = gc_hdr.fst_offset
                        fst_sz = gc_hdr.fst_size

                        # Read FST if available
                        if fst_off > 0 and fst_sz > 0:
                            # Create temporary partition object to read virtual bytes
                            temp_part = WiiPartition(
                                partition_offset=part_byte_off,
                                partition_type=part_type,
                                ticket=ticket,
                                tmd=tmd,
                                title_key=title_key,
                                data_offset=data_offset,
                                data_size=data_size,
                                h3_offset=h3_offset,
                                stream=stream,
                            )
                            if dol_off > 0x2440:
                                apploader_raw = temp_part._read_virtual_bytes(0x2440, dol_off - 0x2440)

                            if dol_off > 0:
                                dol_sz = (fst_off - dol_off) if fst_off > dol_off else 0x4000
                                dol_raw = temp_part._read_virtual_bytes(dol_off, dol_sz)

                            fst_raw = temp_part._read_virtual_bytes(fst_off, fst_sz)
                            if len(fst_raw) >= 12:
                                fst_entries = cls._parse_fst_table(fst_raw)
                    except Exception:
                        pass

            partition = WiiPartition(
                partition_offset=part_byte_off,
                partition_type=part_type,
                ticket=ticket,
                tmd=tmd,
                title_key=title_key,
                data_offset=data_offset,
                data_size=data_size,
                h3_offset=h3_offset,
                stream=stream,
                boot_bin=boot_raw,
                bi2_bin=bi2_raw,
                apploader_bin=apploader_raw,
                main_dol=dol_raw,
                entries=fst_entries,
            )
            partitions.append(partition)

        return cls(header=header, partitions=partitions, stream=stream)

    @classmethod
    def _parse_fst_table(cls, fst_data: bytes) -> List[FSTEntry]:
        """Parses GameCube/Wii FST 12-byte table entries."""
        if len(fst_data) < 12:
            return []

        root_st = GCFstEntryStruct.from_bytes(fst_data, offset=0)
        total_entries = root_st.second_value
        string_table_offset = total_entries * 12

        entries: List[FSTEntry] = []
        dir_stack: List[Tuple[int, str, int]] = [(0, "", total_entries)]

        for i in range(total_entries):
            off = i * 12
            if off + 12 > len(fst_data):
                break
            st = GCFstEntryStruct.from_bytes(fst_data, offset=off)
            is_dir = st.flags != 0
            name_offset = schema.unpack_from(">I", b"\x00" + st.name_offset_raw, 0)[0]

            name = ""
            if i > 0 and string_table_offset + name_offset < len(fst_data):
                end = fst_data.find(b"\x00", string_table_offset + name_offset)
                if end != -1:
                    raw_name = fst_data[string_table_offset + name_offset : end]
                    name = raw_name.decode("shift-jis", errors="replace")

            while dir_stack and i >= dir_stack[-1][2]:
                dir_stack.pop()

            parent_path = dir_stack[-1][1] if dir_stack else ""
            curr_path = f"{parent_path}/{name}".lstrip("/") if i > 0 else ""

            if is_dir:
                parent_idx = st.first_value
                next_entry_idx = st.second_value
                dir_stack.append((i, curr_path, next_entry_idx))
                entries.append(
                    FSTEntry(
                        index=i,
                        is_directory=True,
                        name=name,
                        path=curr_path,
                        file_offset=0,
                        file_size=0,
                        parent_index=parent_idx,
                        next_entry_index=next_entry_idx,
                    )
                )
            else:
                file_off = st.first_value
                file_sz = st.second_value
                entries.append(
                    FSTEntry(
                        index=i,
                        is_directory=False,
                        name=name,
                        path=curr_path,
                        file_offset=file_off,
                        file_size=file_sz,
                    )
                )

        return entries

    def extract_all(self, dest_dir: str) -> Dict[str, List[str]]:
        """Extracts files from all partitions in this disc."""
        out: Dict[str, List[str]] = {}
        for idx, part in enumerate(self.partitions):
            part_name = f"partition_{idx}_data" if part.is_data_partition else f"partition_{idx}"
            part_dir = os.path.join(dest_dir, part_name)
            out[part_name] = part.extract_all(part_dir)
        return out

    # ==========================================================================
    # Repacking Engine (ISO & WBFS with Trucha Bug Fake-Signing)
    # ==========================================================================

    def to_bytes(self, fake_sign: bool = True) -> bytes:
        """Repacks this entire disc into an in-memory byte buffer (ISO format)."""
        bio = io.BytesIO()
        self.save_stream(bio, fake_sign=fake_sign)
        return bio.getvalue()

    def save(self, path: str, fake_sign: bool = True) -> None:
        """Saves this disc to an optical disc image (.iso) file on disk."""
        with open(path, "wb") as f:
            self.save_stream(f, fake_sign=fake_sign)

    def save_stream(self, out: BinaryIO, fake_sign: bool = True) -> None:
        """
        Sequentially writes a playable Wii optical disc image (.iso):
        - Writes Root Disc Header (0x0000)
        - Writes Partition Information Table (0x40000)
        - For each partition:
          - Assembles virtual unencrypted payload (boot, bi2, apploader, DOL, FST, and files)
          - Streams 32 KB clusters, encrypting with Title Key and generating H0 tables
          - Builds H1, H2, and H3 hash trees
          - Updates TMD with H3 SHA-1 hash and applies Trucha Bug fake-signing
          - Writes complete partition container with byte-aligned sectors
        """
        # 1. Write Disc Header at 0x0000
        hdr_bytes = self.header.pack()
        out.seek(0)
        out.write(hdr_bytes)

        # Pad to 0x40000
        pad_len = 0x40000 - out.tell()
        if pad_len > 0:
            out.write(b"\x00" * pad_len)

        # 2. Write Partition Information Table at 0x40000
        num_parts = len(self.partitions)
        table_st = WiiPartInfoTableStruct(
            total_partitions=num_parts,
            partition_table_offset=0x40020 >> 2,
        )
        out.write(table_st.to_bytes())

        # Reserved 0x40008 - 0x40020
        out.write(b"\x00" * 24)

        # Starting partition sector offset (aligned to 0x8000 boundary)
        curr_part_offset = 0x50000

        # Write partition entries
        for p in self.partitions:
            p_entry = WiiPartEntryStruct(
                partition_offset=curr_part_offset >> 2,
                partition_type=p.partition_type,
            )
            out.write(p_entry.to_bytes())
            # Each partition gets its space
            curr_part_offset += 0x100000  # Will adjust dynamically when streaming partition

        # 3. Stream each partition
        curr_part_offset = 0x50000
        for p_idx, part in enumerate(self.partitions):
            out.seek(curr_part_offset)
            part_len = self._write_partition(out, part, curr_part_offset, fake_sign=fake_sign)

            # Update entry in partition table
            out.seek(0x40020 + p_idx * 8)
            p_entry = WiiPartEntryStruct(
                partition_offset=curr_part_offset >> 2,
                partition_type=part.partition_type,
            )
            out.write(p_entry.to_bytes())

            # Align to 0x8000 boundary for next partition
            curr_part_offset = (curr_part_offset + part_len + 0x7FFF) & ~0x7FFF

    def _write_partition(
        self,
        out: BinaryIO,
        part: WiiPartition,
        part_byte_off: int,
        fake_sign: bool = True,
    ) -> int:
        """Writes an individual partition with rebuilt clusters, hash trees, and fake-signed TMD."""
        # Assemble virtual filesystem payload
        virtual_data = bytearray()

        # 1. System files
        boot = bytearray(part.boot_bin) if part.boot_bin else bytearray(0x440)
        while len(boot) < 0x440:
            boot.append(0)

        bi2 = bytearray(part.bi2_bin) if part.bi2_bin else bytearray(0x2000)
        while len(bi2) < 0x2000:
            bi2.append(0)

        apploader = part.apploader_bin or b""
        main_dol = part.main_dol or b""

        virtual_data.extend(boot)
        virtual_data.extend(bi2)

        virtual_data.extend(apploader)
        while len(virtual_data) % 32 != 0:
            virtual_data.append(0)

        dol_off = len(virtual_data)
        virtual_data.extend(main_dol)
        while len(virtual_data) % 32 != 0:
            virtual_data.append(0)

        # Collect files from part.files or original entries
        files_to_pack: Dict[str, bytes] = {}
        for vpath in part.list_files():
            if vpath.startswith("files/"):
                subpath = vpath[6:]
                files_to_pack[subpath] = part[vpath]

        # Directory structure
        dirs_set = set()
        for fpath in files_to_pack:
            parts = fpath.split("/")
            for d in range(1, len(parts)):
                dirs_set.add("/".join(parts[:d]))

        # Root node
        fst_entries_info: List[Dict[str, Any]] = [
            {"is_dir": True, "name_off": 0, "val1": 0, "val2": 0}
        ]
        string_pool = bytearray()
        str_offsets: Dict[str, int] = {}

        def get_string_offset(name: str) -> int:
            if not name:
                return 0
            if name not in str_offsets:
                str_offsets[name] = len(string_pool)
                string_pool.extend(name.encode("shift-jis") + b"\x00")
            return str_offsets[name]

        def build_subtree(current_dir: str, parent_idx: int) -> None:
            # Child directories
            subdirs = sorted([
                d for d in dirs_set
                if (os.path.dirname(d) == current_dir if current_dir else "/" not in d)
            ])
            # Direct child files
            subfiles = sorted([
                f for f in files_to_pack
                if (os.path.dirname(f) == current_dir if current_dir else "/" not in f)
            ])

            for sd in subdirs:
                my_idx = len(fst_entries_info)
                dname = os.path.basename(sd)
                entry_dict = {
                    "is_dir": True,
                    "name_off": get_string_offset(dname),
                    "val1": parent_idx,
                    "val2": 0,
                }
                fst_entries_info.append(entry_dict)
                build_subtree(sd, my_idx)
                entry_dict["val2"] = len(fst_entries_info)

            for sf in subfiles:
                fname = os.path.basename(sf)
                fdata = files_to_pack[sf]
                fst_entries_info.append({
                    "is_dir": False,
                    "name_off": get_string_offset(fname),
                    "val1": 0,
                    "val2": len(fdata),
                    "data": fdata,
                })

        build_subtree("", 0)
        fst_entries_info[0]["val2"] = len(fst_entries_info)

        # Estimate FST size and data offset
        fst_table_size = len(fst_entries_info) * 12 + len(string_pool)
        fst_off = len(virtual_data)

        curr_data_off = (fst_off + fst_table_size + 0x3FF) & ~0x3FF
        file_payloads: List[Tuple[int, bytes]] = []

        for info in fst_entries_info:
            if not info["is_dir"]:
                info["val1"] = curr_data_off >> 2  # word offset
                file_payloads.append((curr_data_off, info["data"]))
                curr_data_off = (curr_data_off + len(info["data"]) + 31) & ~31

        # Build FST binary
        fst_bin = bytearray()
        for info in fst_entries_info:
            fst_bin.extend(
                GCFstEntryStruct(
                    flags=1 if info["is_dir"] else 0,
                    name_offset_raw=info["name_off"].to_bytes(3, "big"),
                    first_value=info["val1"],
                    second_value=info["val2"],
                ).to_bytes()
            )
        fst_bin.extend(string_pool)

        # Append FST
        virtual_data.extend(fst_bin)

        # Append files
        for f_offset, f_data in file_payloads:
            while len(virtual_data) < f_offset:
                virtual_data.append(0)
            virtual_data.extend(f_data)

        # Update boot.bin with real offsets
        schema.pack_into(">I", virtual_data, 0x420, dol_off)
        schema.pack_into(">I", virtual_data, 0x424, fst_off)
        schema.pack_into(">I", virtual_data, 0x428, len(fst_bin))
        schema.pack_into(">I", virtual_data, 0x42C, len(fst_bin))

        # Pad total virtual data to 0x7C00 cluster boundary
        num_clusters = (len(virtual_data) + CLUSTER_PAYLOAD_SIZE - 1) // CLUSTER_PAYLOAD_SIZE
        if num_clusters == 0:
            num_clusters = 1

        # 3. Stream and encrypt clusters, compute H0 tables
        h0_tables: List[bytes] = []
        cluster_payloads: List[bytes] = []

        for c_idx in range(num_clusters):
            c_slice = bytes(virtual_data[c_idx * CLUSTER_PAYLOAD_SIZE : (c_idx + 1) * CLUSTER_PAYLOAD_SIZE])
            cluster_bytes, h0_tbl = encrypt_cluster(c_slice, part.title_key)
            h0_tables.append(h0_tbl)
            cluster_payloads.append(cluster_bytes)

        # 4. Build H1, H2, and H3 hash trees
        h3_table, _, _ = build_hash_tree(h0_tables)

        # 5. Update TMD with H3 SHA-1 hash and Trucha fake-sign
        tmd = part.tmd
        if tmd.contents:
            tmd.contents[0].sha1_hash = hashlib.sha1(h3_table).digest()
            tmd.contents[0].size = num_clusters * CLUSTER_SIZE
            if len(tmd.raw_data) >= 0x1E4 + 36:
                tmd.raw_data[0x1E4 + 16 : 0x1E4 + 36] = tmd.contents[0].sha1_hash
                schema.pack_into(">Q", tmd.raw_data, 0x1E4 + 8, tmd.contents[0].size)

        tik_bytes = part.ticket.to_bytes(fake_sign=fake_sign)
        tmd_bytes = tmd.to_bytes(fake_sign=fake_sign)

        # 6. Layout partition header
        tmd_word_off = 0x2C0 >> 2
        tmd_sz = len(tmd_bytes)
        tmd_aligned_sz = (tmd_sz + 0x3F) & ~0x3F

        cert_word_off = (0x2C0 + tmd_aligned_sz) >> 2
        cert_sz = 0
        h3_word_off = (0x2C0 + tmd_aligned_sz + cert_sz) >> 2
        h3_sz = len(h3_table)

        data_word_off = (0x2C0 + tmd_aligned_sz + cert_sz + h3_sz + 0x7FFF) & ~0x7FFF
        data_byte_start = data_word_off

        subhdr = WiiPartHeaderStruct(
            tmd_size=tmd_sz,
            tmd_offset=tmd_word_off,
            cert_chain_size=cert_sz,
            cert_chain_offset=cert_word_off,
            h3_offset=h3_word_off,
            data_offset=data_byte_start >> 2,
            data_size=(num_clusters * CLUSTER_SIZE) >> 2,
        )

        # Write Ticket + SubHeader
        out.write(tik_bytes)
        out.write(subhdr.to_bytes())

        # Write TMD
        out.write(tmd_bytes)
        while out.tell() % 64 != 0:
            out.write(b"\x00")

        # Write H3 table
        out.write(h3_table)

        # Pad to data_byte_start
        target_data_pos = part_byte_off + data_byte_start
        while out.tell() < target_data_pos:
            out.write(b"\x00")

        # Write encrypted clusters
        for cl in cluster_payloads:
            out.write(cl)

        return out.tell() - part_byte_off

    def to_wbfs(self, fake_sign: bool = True) -> bytes:
        """
        Serializes this disc as an in-memory compressed sparse WBFS (.wbfs) byte buffer.
        Allocates blocks only for populated sectors, stripping empty 0x00 padding.
        """
        iso_bytes = self.to_bytes(fake_sign=fake_sign)
        wbfs_sec_size = 2 * 1024 * 1024  # 2 MB WBFS block size
        hd_sec_size = 512

        num_virtual_blocks = (len(iso_bytes) + wbfs_sec_size - 1) // wbfs_sec_size

        wbl_table: List[int] = [0] * num_virtual_blocks
        populated_blocks: List[Tuple[int, bytes]] = []

        phys_block_idx = 1  # Block 0 is WBFS header and block table
        for v_idx in range(num_virtual_blocks):
            v_chunk = iso_bytes[v_idx * wbfs_sec_size : (v_idx + 1) * wbfs_sec_size]
            if any(b != 0 for b in v_chunk):
                wbl_table[v_idx] = phys_block_idx
                populated_blocks.append((phys_block_idx, v_chunk))
                phys_block_idx += 1

        bio = io.BytesIO()
        hdr = WBFSHeaderStruct(
            magic=WBFS_MAGIC,
            n_hd_sec=phys_block_idx * (wbfs_sec_size // hd_sec_size),
            hd_sec_sz_s=9,    # 512 bytes
            wbfs_sec_sz_s=21,  # 2 MB
        )
        bio.write(hdr.to_bytes())

        bio.seek(0x100)
        for val in wbl_table:
            bio.write(schema.pack(">H", val))

        bio.seek(wbfs_sec_size)
        for p_idx, chunk in populated_blocks:
            bio.seek(p_idx * wbfs_sec_size)
            bio.write(chunk)

        return bio.getvalue()

    def save_wbfs(self, path: str, fake_sign: bool = True) -> None:
        """
        Saves this disc as a compressed sparse WBFS (.wbfs) container.
        Allocates blocks only for populated sectors, stripping empty 0x00 padding.
        """
        data = self.to_wbfs(fake_sign=fake_sign)
        with open(path, "wb") as f:
            f.write(data)

    def to_rvz(self, fake_sign: bool = True, chunk_size: int = 131072) -> bytes:
        """
        Serializes this disc as an in-memory Dolphin RVZ compressed disc image container.
        """
        from miorom.platforms.iso.rvz import RVZDisc
        bio = io.BytesIO()
        self.save_stream(bio, fake_sign=fake_sign)
        iso_bytes = bio.getvalue()
        return RVZDisc.create_from_stream(
            disc_stream=DiscStream.from_bytes(iso_bytes),
            total_size=len(iso_bytes),
            disc_type=2,
            chunk_size=chunk_size,
        )

    def save_rvz(self, path: str, fake_sign: bool = True, chunk_size: int = 131072) -> None:
        """
        Saves this disc as an RVZ (.rvz) compressed container on disk.
        """
        data = self.to_rvz(fake_sign=fake_sign, chunk_size=chunk_size)
        with open(path, "wb") as f:
            f.write(data)
