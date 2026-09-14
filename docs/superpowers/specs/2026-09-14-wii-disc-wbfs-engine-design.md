# Design Spec: Nintendo Wii Optical Disc & WBFS Partition Engine

**Date:** 2026-09-14  
**Status:** Draft / Self-Review  
**Target Module:** `src/miorom/platforms/wii/disc.py`  
**Export In:** `src/miorom/platforms/wii/__init__.py`, `src/miorom/__init__.py`  
**Test Suite:** `tests/test_platforms_wii_disc.py`  

---

## 1. Overview & Purpose

Nintendo Wii optical disc images are distributed in two primary container formats:
1. **Raw Optical Disc Images (`.iso` / `.wii`)**: Standard 4.7 GB (Single Layer, DVD-5) or 8.5 GB (Dual Layer, DVD-9) disc images.
2. **Wii Backup File System (`.wbfs`)**: Sparse block-mapped container format that strips unused `0x00` padding sectors, widely used in homebrew USB loaders (*USB Loader GX*, *WiiFlow*, *CleanRip*) and modern emulation (*Dolphin*).

Unlike GameCube discs (which are unencrypted), Wii discs feature a multi-layered security architecture:
- Partition Information Table pointing to multiple cryptographically isolated partitions (`DATA`, `UPDATE`, `CHANNEL`).
- Each partition has its own Ticket (`WADTicket`) containing an AES-128 encrypted Title Key.
- Partition data is divided into **32 KB clusters** (0x8000 bytes):
  - `0x0000 - 0x0400` (1024 bytes): Cluster Header containing **31 SHA-1 hashes (H0)** and the **AES-128-CBC Initialization Vector (IV)**.
  - `0x0400 - 0x8000` (31,744 bytes = `0x7C00`): AES-128-CBC encrypted payload.
- A 4-level hierarchical hash tree (**H0 $\rightarrow$ H1 $\rightarrow$ H2 $\rightarrow$ H3**) enforces data integrity down to individual 1 KB blocks.
- The Title Metadata (`WADTmd`) stores the SHA-1 hash of the H3 table and RSA-2048 digital signatures.

This engine provides a pure-Python, zero-dependency, streaming reverse engineering suite for Wii discs:
- **Full decryption & extraction**: Reads `.iso` and `.wbfs` files with low memory usage (< 50 MB RAM), decrypts clusters on-demand, and extracts the entire virtual filesystem (`sys/` and `files/`).
- **In-memory file mutation & injection**: Allows inspecting and replacing files (`disc.partitions[0]["sys/main.dol"] = new_bytes`).
- **Complete hash tree reconstruction**: Recalculates H0, H1, H2, and H3 tables for modified clusters.
- **Trucha Bug fake-signing**: Forges RSA-2048 null signatures on altered Tickets and TMDs so modified games boot on softmodded Wii consoles and Dolphin.
- **Bi-directional repacking**: Rebuilds valid `.iso` and `.wbfs` disc images.

---

## 2. Technical Architecture & Binary Specifications

### 2.1 Disc Header Layout (`0x0000 - 0x0440`)
The root disc header occupies the first 0x440 bytes of the physical disc:
```
Offset  Size   Type   Field
0x0000  0x04   4s     game_id (e.g. "RMCE" for Mario Kart Wii USA)
0x0004  0x02   2s     maker_code (e.g. "01" for Nintendo)
0x0006  0x01   u8     disc_number (0 for disc 1)
0x0007  0x01   u8     version (revision)
0x0008  0x01   u8     audio_streaming (0 or 1)
0x0009  0x01   u8     stream_buf_size
0x000A  0x0E   14s    reserved
0x0018  0x04   u32    magic (0x5D1C9EA3 for Wii, 0xC2339F3D for GC)
0x001C  0x04   4s     magic_wii (b"\x5D\x1C\x9E\xA3")
0x0020  0x40   64s    game_title (Shift-JIS / ASCII string)
0x0060  0x3E0  bytes  padding / GC compatibility flags
```

### 2.2 Partition Information Table (`0x00040000`)
Located at offset `0x40000` in the disc:
```
Offset    Size  Type  Field
0x40000   0x04  u32   total_partitions
0x40004   0x04  u32   partition_table_offset (word offset, << 2 to get byte offset)
```
Each entry in the partition table (8 bytes each):
```
Offset    Size  Type  Field
0x00      0x04  u32   partition_offset (word offset from disc start, << 2)
0x04      0x04  u32   partition_type (0 = DATA, 1 = UPDATE, 2 = CHANNEL)
```

### 2.3 Partition Header Layout
Starting at `partition_offset = entry.partition_offset << 2`:
```
Offset   Size   Type   Field
0x0000   0x02A4 bytes  ticket (WADTicket, standard Nintendo Ticket v0)
0x02A4   0x0004 u32    tmd_size (in bytes)
0x02A8   0x0004 u32    tmd_offset (word offset from partition_offset, << 2)
0x02AC   0x0004 u32    cert_chain_size
0x02B0   0x0004 u32    cert_chain_offset (word offset, << 2)
0x02B4   0x0004 u32    h3_offset (word offset, << 2)
0x02B8   0x0004 u32    data_offset (word offset, << 2)
0x02BC   0x0004 u32    data_size (word size, << 2)
```

### 2.4 Cryptographic Keys & Title Key Decryption
- **Wii Common Key (Retail)**:
  `EBE42A225E8593E448D9C5457381AAF7`
- **Wii Korean Key**:
  `63B82BB4F4614E2E13F2FEFBBA4C9B7E`
- **Title Key Decryption**:
  Inside the partition Ticket (`WADTicket`):
  - Encrypted Title Key is 16 bytes at Ticket offset `0x1F0:0x200`.
  - Title ID is 8 bytes at Ticket offset `0x1CB:0x1D3`.
  - IV: `title_id + b"\x00" * 8`.
  - Decrypted via `aes128_cbc_decrypt(encrypted_title_key, common_key, iv)`.

### 2.5 32 KB (0x8000) Cluster Layout & Hash Tree
Partition data is structured into consecutive 32 KB clusters:
```
Cluster Offset   Size    Description
0x0000 - 0x026C  620 B   31 x 20-byte SHA-1 hashes (H0 table)
0x026C - 0x03D0  356 B   Padding (zeros)
0x03D0 - 0x03E0  16 B    Cluster IV (used for AES-128-CBC decryption)
0x03E0 - 0x0400  32 B    Padding (zeros)
0x0400 - 0x8000  31,744B Encrypted cluster payload (0x7C00 bytes)
```
- **H0 Table**: 31 hashes. Each hash $i \in [0, 30]$ corresponds to $1024$ bytes of decrypted payload ($31 \times 1024 = 31,744$ bytes).
- **H1 Table**: 8 clusters form one H1 group ($8 \times 20 = 160$ bytes). An H1 table stores the SHA-1 hash of each cluster's H0 table.
- **H2 Table**: 8 H1 groups form one H2 group ($8 \times 20 = 160$ bytes). Stores SHA-1 hash of each H1 table. One H2 group covers $64 \times 32 \text{ KB} = 2 \text{ MB}$ of data.
- **H3 Table**: Stores SHA-1 hashes of all H2 groups (up to 96 KB). Located at `h3_offset << 2`.
- The SHA-1 hash of the entire H3 table is stored in the partition TMD content record 0.

### 2.6 Virtual Decrypted Filesystem (FST)
When all 0x7C00 payloads are decrypted and concatenated:
- `0x0000 - 0x0440`: `boot.bin` (Disc header copy, holds `dol_offset` and `fst_offset`).
- `0x0440 - 0x2440`: `bi2.bin`.
- `0x2440 - ...`: `apploader.img`.
- `dol_offset`: `main.dol` (PowerPC executable binary).
- `fst_offset`: `fst.bin` (File System Table, 12 bytes per entry + string pool):
  - Root node: `flags=1`, `name_offset=0`, `parent_index=0`, `next_entry_index=total_entries`.
  - Directory: `flags=1`, `name_offset`, `parent_index`, `next_entry_index`.
  - File: `flags=0`, `name_offset`, `file_offset` (word offset from partition data start, `<< 2`), `file_size`.

### 2.7 WBFS Container Specification
WBFS files start with a 0x100 byte header:
```
Offset  Size  Type  Field
0x00    0x04  4s    magic (b"WBFS")
0x04    0x04  u32   n_hd_sec (number of sectors)
0x08    0x01  u8    hd_sec_sz_s (log2 sector size, e.g. 9 = 512 bytes)
0x09    0x01  u8    wbfs_sec_sz_s (log2 WBFS block size, e.g. 21 = 2MB, 22 = 4MB)
0x0A    0x02  16s   reserved
0x0C    0x100 bytes disc_table (maps slot 0..N)
```
- A WBL (WBFS Block Location) table of 16-bit integers maps each virtual disc block (size $2^{\text{wbfs\_sec\_sz\_s}}$) to the physical block in the WBFS file.
- If an entry in the WBL table is 0, the virtual block contains all zeros.

---

## 3. High-Level Class Design & API

```python
class WiiDiscHeader(MioRomResult):
    game_id: str
    maker_code: str
    disc_number: int
    version: int
    audio_streaming: bool
    magic: int
    game_title: str

class WiiPartitionInfo(MioRomResult):
    offset: int
    partition_type: int  # 0=DATA, 1=UPDATE, 2=CHANNEL

class WiiPartition(MioRomResult):
    ticket: WADTicket
    tmd: WADTmd
    partition_type: int
    title_key: bytes
    boot_bin: bytes
    bi2_bin: bytes
    apploader_bin: bytes
    main_dol: bytes
    entries: List[FSTEntry]
    files: Dict[str, bytes]  # Modified or staged files

    def list_files(self) -> List[str]: ...
    def __getitem__(self, path: str) -> bytes: ...
    def __setitem__(self, path: str, content: bytes) -> None: ...
    def __contains__(self, path: str) -> bool: ...
    def extract_file(self, vpath: str, dest_path: str) -> None: ...
    def extract_all(self, dest_dir: str) -> List[str]: ...
    def replace_file(self, vpath: str, data_or_path: Union[str, bytes]) -> None: ...

class WiiDisc(MioRomResult):
    header: WiiDiscHeader
    partitions: List[WiiPartition]

    @property
    def data_partition(self) -> Optional[WiiPartition]: ...

    @classmethod
    def from_file(cls, path: str, common_key: Optional[bytes] = None) -> "WiiDisc": ...
    @classmethod
    def from_bytes(cls, data: bytes, common_key: Optional[bytes] = None) -> "WiiDisc": ...

    def extract_all(self, dest_dir: str) -> Dict[str, List[str]]: ...
    def to_bytes(self, fake_sign: bool = True) -> bytes: ...
    def save(self, path: str, fake_sign: bool = True) -> None: ...
    def save_wbfs(self, path: str, fake_sign: bool = True) -> None: ...

class WBFSDisc:
    """Wrapper that resolves WBFS sparse block offsets to raw disc byte offsets."""
    @classmethod
    def is_wbfs(cls, data_or_path: Union[bytes, str]) -> bool: ...
    @classmethod
    def read_block(cls, stream: Any, virtual_offset: int, size: int) -> bytes: ...
```

---

## 4. Verification & Testing Plan

1. **Disc Header & Partition Table Parser**:
   - Parse synthetic Wii disc header with magic `0x5D1C9EA3` and partition table entries at `0x40000`.
2. **Title Key & AES-128 Decryption**:
   - Verify decryption of Title Key with default retail Common Key.
   - Verify single 32 KB cluster decryption and match all 31 H0 SHA-1 sub-hashes.
3. **Pohon Hash Hirarkis (H0 $\rightarrow$ H1 $\rightarrow$ H2 $\rightarrow$ H3)**:
   - Calculate H0, H1, H2, and H3 for multi-cluster partition data.
   - Verify SHA-1 of generated H3 matches TMD content record.
4. **FST Filesystem Extraction & Injection**:
   - Parse FST entries (`sys/boot.bin`, `sys/main.dol`, `files/game_data.bin`).
   - Replace a file in memory, assert updated contents and modified flag.
5. **Trucha Bug Fake-Signing**:
   - Verify altered Ticket and TMD produce RSA null signature (`b"\x00" * 256`) and signature type `0x10001`.
6. **End-to-End Repack & Roundtrip (ISO)**:
   - Build a mini-Wii ISO containing a data partition with DOL and asset files.
   - Repack to bytes, parse back with `WiiDisc.from_bytes()`, extract files, and assert 100% data integrity.
7. **WBFS Support**:
   - Test detection and reading through `WBFSDisc`.
8. **Code Quality & Zero Dependencies**:
   - Zero external dependencies (`dependencies = []`).
   - Run `ruff check` on all modified code with 0 errors.
   - Full regression test suite passes.
