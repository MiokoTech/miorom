# Implementation Plan: Nintendo Wii Optical Disc & WBFS Partition Engine

**Spec Reference:** [`docs/superpowers/specs/2026-09-14-wii-disc-wbfs-engine-design.md`](file:///home/mioko/miorom/docs/superpowers/specs/2026-09-14-wii-disc-wbfs-engine-design.md)  
**Target Files:**
- `src/miorom/platforms/wii/disc.py`
- `src/miorom/platforms/wii/__init__.py`
- `src/miorom/__init__.py`
- `tests/test_platforms_wii_disc.py`

---

## Proposed Tasks

### Task 1: Binary Structures, Disc Header & Partition Info Table
- Create `src/miorom/platforms/wii/disc.py`.
- Define standard binary structures with `BinaryStruct` (`WiiDiscHeaderStruct`, `WiiPartEntryStruct`, `WiiPartHeaderStruct`, `WBFSHeaderStruct`).
- Implement `WiiDiscHeader` and `WiiPartitionInfo` parsing and serialization.
- Validate Wii disc magic `0x5D1C9EA3` and GameCube compatibility magic `0xC2339F3D`.
- Include standard retail Wii Common Key (`EBE42A22...`) and Korean Common Key (`63B82BB4...`).

### Task 2: 32 KB Cluster Cryptographic Engine & Hash Trees (H0, H1, H2, H3)
- Implement cluster decryption:
  - Extract cluster IV at `0x3D0` of the 0x400 header.
  - Decrypt 0x7C00 payload with AES-128-CBC using Title Key.
  - Validate 31 SHA-1 hashes in H0 table.
- Implement cluster encryption & hash tree calculation:
  - Generate H0 table (31 SHA-1 hashes for 1024-byte payload chunks).
  - Encrypt payload with AES-128-CBC.
  - Compute H1 table per 8 clusters (160 bytes).
  - Compute H2 table per 8 H1 groups / 64 clusters (160 bytes).
  - Build H3 root table and verify/update TMD content record.

### Task 3: Virtual Partition & Filesystem (FST) Engine (`WiiPartition`)
- Implement `WiiPartition`:
  - Wrap partition header (Ticket, TMD, H3 table, Certs).
  - Parse decrypted partition header (`boot.bin`, `bi2.bin`, `apploader.img`, `main.dol`, `fst.bin`).
  - Parse FST entries into a searchable directory tree.
  - Provide dictionary-like access (`partition["files/Stage/Course.arc"]`) with lazy cluster decryption.
  - Support file replacement/injection (`partition["files/Stage/Course.arc"] = new_bytes` or `partition.replace_file()`).
  - Support batch extraction (`partition.extract_all(dest_dir)`).

### Task 4: Complete Disc Engine & WBFS Support (`WiiDisc` & `WBFSDisc`)
- Implement `WBFSDisc`:
  - Detect and parse WBFS header (`b"WBFS"`, sector sizes, WBL block table).
  - Map virtual disc offsets to physical WBFS block offsets.
- Implement `WiiDisc`:
  - `from_file()` and `from_bytes()`.
  - Expose `disc.header`, `disc.partitions`, and `disc.data_partition`.
  - Implement streaming repack to `.iso` (`disc.save()` / `disc.to_bytes()`).
  - Implement repack to `.wbfs` (`disc.save_wbfs()`).
  - Apply Trucha Bug fake-signing (`fake_sign=True`) on modified Tickets and TMDs.

### Task 5: Module Exports
- Export `WiiDisc`, `WiiPartition`, `WiiDiscHeader`, `WBFSDisc` in `src/miorom/platforms/wii/__init__.py` and `src/miorom/__init__.py`.

### Task 6: Comprehensive Unit Test Suite & Verification
- Create `tests/test_platforms_wii_disc.py`:
  - Disc header and partition table parsing.
  - Single 32 KB cluster decryption, encryption, and H0 verification.
  - Full H0 -> H1 -> H2 -> H3 hash tree calculation matching TMD record.
  - Virtual FST filesystem parsing, extraction, and file replacement.
  - Full roundtrip repack of synthetic Wii ISO and verification.
  - WBFS block mapping and reading.
  - Trucha Bug fake-signing validation.
- Verify with `pytest` and `ruff check`.
