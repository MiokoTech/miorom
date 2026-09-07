import struct
import pytest
from miorom.scanner.table_detector import (
    HeuristicTableDetector,
    TableCandidate,
)


def test_detect_pointer_tables():
    # Construct a synthetic binary with:
    # 0x00 - 0x14: 5 pointers (32-bit LE) pointing to strings at 0x40, 0x50, 0x60, 0x70, 0x80
    # Strings: "Apple", "Banana", "Cherry", "Durian", "Elderberry"
    buf = bytearray(0x100)
    strings = ["Apple", "Banana", "Cherry", "Durian", "Elderberry"]
    target_offsets = [0x40, 0x50, 0x60, 0x70, 0x80]

    for i, (s, target) in enumerate(zip(strings, target_offsets)):
        struct.pack_into("<I", buf, i * 4, target)
        buf[target : target + len(s)] = s.encode("ascii")
        buf[target + len(s)] = 0

    candidates = HeuristicTableDetector.detect_pointer_tables(
        data=bytes(buf),
        min_entries=4,
        pointer_size=4,
        endian="<",
    )

    assert len(candidates) >= 1
    cand = candidates[0]
    assert cand.offset == 0
    assert cand.count == 5
    assert cand.stride == 4
    assert cand.confidence >= 0.8
    assert "Apple" in cand.sample_strings

    # Test string extraction
    extracted = HeuristicTableDetector.extract_strings(bytes(buf), cand)
    assert len(extracted) == 5
    assert extracted[0] == (0, "Apple")
    assert extracted[1] == (1, "Banana")
    assert extracted[4] == (4, "Elderberry")


def test_detect_stride_records():
    # 16-byte records:
    # [u32 id][u32 ptr_to_text][u32 val1][u32 val2]
    buf = bytearray(0x200)
    strings = ["Warrior", "Mage", "Rogue", "Cleric"]
    targets = [0x100, 0x120, 0x140, 0x160]

    for i, (s, target) in enumerate(zip(strings, targets)):
        rec_off = i * 16
        struct.pack_into("<I", buf, rec_off + 0, i + 1)
        struct.pack_into("<I", buf, rec_off + 4, target)  # ptr at offset 4
        struct.pack_into("<I", buf, rec_off + 8, 100)
        struct.pack_into("<I", buf, rec_off + 12, 200)

        buf[target : target + len(s)] = s.encode("ascii")
        buf[target + len(s)] = 0

    records = HeuristicTableDetector.detect_stride_records(
        data=bytes(buf),
        candidate_strides=(16,),
        min_records=4,
        pointer_size=4,
        endian="<",
    )

    assert len(records) >= 1
    rec = records[0]
    assert rec.stride == 16
    assert rec.pointer_offset_in_entry == 4
    assert rec.count == 4
    assert "Warrior" in rec.sample_strings
