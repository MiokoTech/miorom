"""
tests/test_platforms_iso_rvz.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for Dolphin RVZ / WIA Compressed Disc Image Container Engine.
Tests cover:
- RVZFileHeadStruct and RVZDiscHeadStruct serialization and SHA-1 checksum verification
- Lagged Fibonacci PRNG padding generation and RVZ packing decoding
- Multi-algorithm chunk compression (Zstandard, LZMA, raw) and lazy streaming decompression
- Sparse zero-chunk skipping (data_size == 0)
- End-to-end GameCube RVZ creation, file extraction, and repacking
- End-to-end Wii RVZ creation, encrypted cluster extraction, and repacking
- RomManager auto-detection routing between GameCube and Wii RVZ containers
"""

from __future__ import annotations

import hashlib
import os
import tempfile

from miorom.core import schema
from miorom.platforms.gc.disc import GameCubeDisc
from miorom.platforms.iso.rvz import (
    COMPRESSION_LZMA,
    COMPRESSION_NONE,
    COMPRESSION_ZSTD,
    RVZ_MAGIC,
    RVZDisc,
    RVZDiscHeadStruct,
    RVZFileHeadStruct,
    decode_rvz_packing,
    generate_rvz_padding,
)
from miorom.platforms.wii import (
    WiiDisc,
    WiiDiscHeader,
    WiiPartition,
)
from miorom.platforms.wii.disc import (
    CLUSTER_SIZE,
    PARTITION_TYPE_DATA,
    WII_COMMON_KEY_RETAIL,
    WII_DISC_MAGIC,
    DiscStream,
)
from miorom.platforms.wii.u8 import (
    WADTicket,
    WADTmd,
    aes128_cbc_encrypt,
)
from miorom.rom.handlers.gc import GameCubeRomHandler
from miorom.rom.handlers.wii import WiiRomHandler
from miorom.rom.manager import RomManager


def test_rvz_header_and_structs():
    """Verify RVZ file head and disc head struct packing, parsing, and SHA-1 hashing."""
    disc_head = RVZDiscHeadStruct(
        disc_type=2,
        compression=COMPRESSION_ZSTD,
        compr_level=5,
        chunk_size=131072,
        dhead=b"RMCE01" + b"\x00" * 122,
        n_groups=4,
    )
    disc_head_bytes = disc_head.to_bytes()
    disc_hash = hashlib.sha1(disc_head_bytes).digest()

    file_head = RVZFileHeadStruct(
        magic=RVZ_MAGIC,
        version=0x01000000,
        version_compatible=0x00090000,
        disc_size=len(disc_head_bytes),
        disc_hash=disc_hash,
        iso_file_size=4699979776,
        wia_file_size=500000,
        file_head_hash=b"\x00" * 20,
    )
    packed_fh = file_head.to_bytes()
    assert len(packed_fh) == 72
    assert packed_fh[:4] == b"RVZ\x01"

    parsed_fh = RVZFileHeadStruct.from_bytes(packed_fh, offset=0)
    assert parsed_fh.magic == b"RVZ\x01"
    assert parsed_fh.iso_file_size == 4699979776


def test_rvz_lagged_fibonacci_prng():
    """Verify Nintendo/Dolphin Lagged Fibonacci PRNG padding generator produces deterministic bytes."""
    seed = bytes.fromhex("0123456789abcdef" * 8 + "00000000")  # 68 bytes
    padding_1 = generate_rvz_padding(seed, 256)
    padding_2 = generate_rvz_padding(seed, 256)

    assert len(padding_1) == 256
    assert padding_1 == padding_2
    assert any(b != 0 for b in padding_1)

    # Verify RVZ packing decoder
    packed = bytearray()
    # Segment 1: Literal 8 bytes
    packed.extend(schema.pack(">I", 8))
    packed.extend(b"LITERAL8")

    # Segment 2: PRNG 64 bytes (MSB set)
    packed.extend(schema.pack(">I", 64 | 0x80000000))
    packed.extend(seed)

    decoded = decode_rvz_packing(bytes(packed), 72)
    assert len(decoded) == 72
    assert decoded[:8] == b"LITERAL8"


def test_rvz_synthetic_raw_disc_compression_and_decompression():
    """Verify multi-chunk slicing, compression, and random-access lazy streaming across boundaries."""
    total_size = 512 * 1024  # 512 KiB (4 chunks of 128 KiB)
    raw_disc = bytearray(total_size)
    for i in range(4):
        chunk_pattern = f"CHUNK_PAYLOAD_INDEX_{i}_SAMPLE_DATA_".encode("ascii") * 200
        raw_disc[i * 131072 : i * 131072 + len(chunk_pattern)] = chunk_pattern

    raw_disc[:6] = b"TEST01"
    raw_disc[0x18:0x1C] = schema.pack(">I", WII_DISC_MAGIC)

    stream = DiscStream.from_bytes(bytes(raw_disc))
    rvz_bytes = RVZDisc.create_from_stream(
        disc_stream=stream,
        total_size=total_size,
        disc_type=2,
        compression=COMPRESSION_LZMA,  # Test stdlib LZMA
        chunk_size=131072,
    )

    assert len(rvz_bytes) > 0
    assert rvz_bytes[:4] == b"RVZ\x01"

    # Open and verify RVZDisc properties
    rvz_disc = RVZDisc.from_bytes(rvz_bytes)
    assert rvz_disc.game_id == "TEST01"
    assert rvz_disc.magic == WII_DISC_MAGIC
    assert rvz_disc.iso_file_size == total_size

    # Test random access reading crossing chunk boundary (chunk 1 -> chunk 2)
    cross_offset = 131072 - 100
    slice_data = rvz_disc.read_at(cross_offset, 200)
    assert slice_data == raw_disc[cross_offset : cross_offset + 200]


def test_rvz_sparse_zero_chunks():
    """Verify sparse all-zero chunks are stored with data_size == 0 and produce compact files."""
    total_size = 2 * 1024 * 1024  # 2 MB (16 chunks of 128 KiB)
    sparse_disc = bytearray(total_size)
    sparse_disc[:6] = b"SPAR01"
    # Only populate chunk 0; chunks 1..15 are completely empty 0x00
    sparse_disc[100:150] = b"NON_ZERO_DATA_IN_CHUNK_0"

    stream = DiscStream.from_bytes(bytes(sparse_disc))
    rvz_bytes = RVZDisc.create_from_stream(
        disc_stream=stream,
        total_size=total_size,
        compression=COMPRESSION_NONE,
        chunk_size=131072,
    )

    rvz_disc = RVZDisc.from_bytes(rvz_bytes)
    # Check that chunks 1..15 have data_size == 0
    for idx in range(1, 16):
        assert (rvz_disc.groups[idx].data_size & 0x7FFFFFFF) == 0

    # Reading chunk 5 should return 128 KiB of 0x00
    empty_read = rvz_disc.read_at(5 * 131072, 1024)
    assert empty_read == b"\x00" * 1024


def _create_synthetic_gc_disc() -> bytes:
    """Helper to synthesize a minimal GameCube disc image."""
    synth = bytearray(0x450000)
    synth[:4] = b"GM8E"
    synth[4:6] = b"01"
    schema.pack_into(">I", synth, 0x1C, GameCubeDisc.GC_MAGIC)
    schema.pack_into(">I", synth, 0x420, 0x10000)  # dol_offset

    # Mock DOL binary at 0x10000
    dol_hdr = bytearray(0x100)
    schema.pack_into(">I", dol_hdr, 0x00, 0x100)
    schema.pack_into(">I", dol_hdr, 0x48, 0x80003100)
    schema.pack_into(">I", dol_hdr, 0x90, 0x200)
    synth[0x10000:0x10100] = dol_hdr
    synth[0x10100:0x10300] = b"GC_MAIN_DOL_EXECUTABLE_CODE" * 8

    disc = GameCubeDisc(bytes(synth))
    disc.files["Stage/level1.dat"] = b"GC_LEVEL_ONE_DATA_12345"
    disc.files["Text/game.msg"] = b"GC_GAME_MESSAGE_STRINGS"
    return disc.to_bytes()


def test_gamecube_rvz_handler_roundtrip():
    """Verify GameCubeRomHandler end-to-end repack(format='rvz') and unpack_rvz."""
    gc_iso = _create_synthetic_gc_disc()
    gc_handler = GameCubeRomHandler()

    with tempfile.TemporaryDirectory() as tmpdir:
        # Unpack original GC ISO
        unpacked_dir = os.path.join(tmpdir, "unpacked")
        gc_handler.unpack(gc_iso, unpacked_dir)

        # Repack to RVZ
        gc_rvz_bytes = gc_handler.repack(unpacked_dir, format="rvz")
        assert gc_rvz_bytes[:4] == b"RVZ\x01"

        # Verify can_handle accepts this GameCube RVZ
        assert gc_handler.can_handle(gc_rvz_bytes) is True

        # Unpack from RVZ directly
        extracted_dir = os.path.join(tmpdir, "from_rvz")
        meta = gc_handler.unpack(gc_rvz_bytes, extracted_dir)
        assert meta["format"] == "gamecube"
        assert meta["game_id"].startswith("GM8E")

        with open(os.path.join(extracted_dir, "root", "Stage", "level1.dat"), "rb") as f:
            assert f.read() == b"GC_LEVEL_ONE_DATA_12345"
        with open(os.path.join(extracted_dir, "root", "Text", "game.msg"), "rb") as f:
            assert f.read() == b"GC_GAME_MESSAGE_STRINGS"

        # Verify sys/disc_base.bin and sys/main.dol exist after RVZ unpack
        assert os.path.isfile(os.path.join(extracted_dir, "sys", "disc_base.bin"))
        assert os.path.isfile(os.path.join(extracted_dir, "sys", "main.dol"))

        # Repack from the RVZ-extracted directory back to GameCube ISO and verify files
        repacked_iso = gc_handler.repack(extracted_dir)
        reloaded_gc = GameCubeDisc(repacked_iso)
        assert reloaded_gc.read_file("Stage/level1.dat") == b"GC_LEVEL_ONE_DATA_12345"
        assert reloaded_gc.read_file("Text/game.msg") == b"GC_GAME_MESSAGE_STRINGS"


def _create_synthetic_wii_disc() -> WiiDisc:
    """Helper to synthesize a minimal playable WiiDisc with 1 data partition."""
    header = WiiDiscHeader(
        game_id="RMCE",
        maker_code="01",
        disc_number=0,
        version=1,
        audio_streaming=False,
        stream_buf_size=0,
        magic=WII_DISC_MAGIC,
        gc_magic=0xC2339F3D,
        game_title="Mario Kart Wii RVZ Test",
    )

    title_id = b"\x00\x01\x00\x00RMCE"
    title_key = bytes.fromhex("112233445566778899aabbccddeeff00")

    tik_raw = bytearray(0x2A4)
    tik_raw[0x1CB : 0x1D3] = title_id
    iv = title_id + (b"\x00" * 8)
    enc_title_key = aes128_cbc_encrypt(title_key, WII_COMMON_KEY_RETAIL, iv)
    tik_raw[0x1F0 : 0x200] = enc_title_key
    ticket = WADTicket.from_bytes(bytes(tik_raw))

    tmd_raw = bytearray(0x1E4 + 36)
    schema.pack_into(">H", tmd_raw, 0x1DE, 1)
    tmd = WADTmd.from_bytes(bytes(tmd_raw))

    part = WiiPartition(
        partition_offset=0x50000,
        partition_type=PARTITION_TYPE_DATA,
        ticket=ticket,
        tmd=tmd,
        title_key=title_key,
        data_offset=0x58000,
        data_size=CLUSTER_SIZE * 2,
        h3_offset=0x51000,
        boot_bin=b"BOOT_BIN_DATA" + b"\x00" * (0x440 - 13),
        bi2_bin=b"BI2_BIN_DATA" + b"\x00" * (0x2000 - 12),
        apploader_bin=b"APPLOADER_PAYLOAD",
        main_dol=b"MAIN_DOL_PAYLOAD",
    )
    part["files/Stage/Course.arc"] = b"COURSE_PAYLOAD_DATA_RVZ_TEST"
    part["files/Text/message.bmg"] = b"BMG_MESSAGE_DATA_RVZ_TEST"

    return WiiDisc(header=header, partitions=[part])


def test_wii_rvz_handler_roundtrip():
    """Verify WiiRomHandler end-to-end repack(format='rvz') and unpack_rvz."""
    wii_disc = _create_synthetic_wii_disc()
    wii_handler = WiiRomHandler()

    with tempfile.TemporaryDirectory() as tmpdir:
        # Unpack original synthetic Wii disc
        unpacked_dir = os.path.join(tmpdir, "unpacked")
        wii_handler.unpack(wii_disc.to_bytes(), unpacked_dir)

        # Repack to RVZ
        wii_rvz_bytes = wii_handler.repack(unpacked_dir, format="rvz")
        assert wii_rvz_bytes[:4] == b"RVZ\x01"

        # Verify can_handle accepts this Wii RVZ
        assert wii_handler.can_handle(wii_rvz_bytes) is True

        # Unpack from RVZ directly
        extracted_dir = os.path.join(tmpdir, "from_rvz")
        meta = wii_handler.unpack(wii_rvz_bytes, extracted_dir)
        assert meta["format"] == "wii"
        assert meta["game_id"] == "RMCE"

        # Check that decrypted partition files match
        with open(os.path.join(extracted_dir, "root", "Stage", "Course.arc"), "rb") as f:
            assert f.read() == b"COURSE_PAYLOAD_DATA_RVZ_TEST"
        with open(os.path.join(extracted_dir, "root", "Text", "message.bmg"), "rb") as f:
            assert f.read() == b"BMG_MESSAGE_DATA_RVZ_TEST"


def test_rom_manager_rvz_routing():
    """Verify RomManager auto-detects and correctly routes GameCube vs Wii RVZ files."""
    gc_iso = _create_synthetic_gc_disc()
    gc_handler = GameCubeRomHandler()
    with tempfile.TemporaryDirectory() as tmpdir:
        gc_handler.unpack(gc_iso, tmpdir)
        gc_rvz = gc_handler.repack(tmpdir, format="rvz")

    wii_disc = _create_synthetic_wii_disc()
    wii_rvz = wii_disc.to_rvz()

    manager = RomManager()
    assert manager.detect_format(gc_rvz) == "gamecube"
    assert manager.detect_format(wii_rvz) == "wii"


def test_rvz_size_alignment_and_hash_validity():
    """Verify RVZ 4-byte padding alignment and SHA-1 hash integrity."""
    class OddByteStream:
        def read_at(self, off, size):
            return b"ODD_CHUNK_123" if off == 0 else b""

    rvz_bytes = RVZDisc.create_from_stream(
        OddByteStream(), 13, chunk_size=1024, compression=COMPRESSION_NONE
    )
    disc = RVZDisc.from_bytes(rvz_bytes)
    assert len(rvz_bytes) == disc.file_head.wia_file_size
    assert len(rvz_bytes) % 4 == 0
    assert disc.is_hash_valid() is True

    # Test context manager and close
    with disc as d:
        assert d.is_hash_valid() is True
    disc.close()

