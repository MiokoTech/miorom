import random
import struct

from hypothesis import given, settings
from hypothesis import strategies as st

import pytest

from miorom.compression import LZ10, LZ11, RLE, Yaz0
from miorom.core.schema import ChecksumField, U16
from miorom.core.schema import BinaryStruct
from miorom.errors import PointerOverflowError
from miorom.script.branch import BytecodeBranchScanner


def test_property_compression_roundtrip_deterministic_patterns():
    random.seed(0x4D494F)
    payloads = [
        b"",
        bytes(random.randrange(256) for _ in range(512)),
        bytes(random.choice((0, 0, 0, 1, 2, 3)) for _ in range(1024)),
        bytes((i % 16) for i in range(2048)),
    ]
    codecs = (LZ10, LZ11, RLE, Yaz0)

    for codec in codecs:
        for payload in payloads:
            compressed = codec.compress(payload)
            assert codec.decompress(compressed) == payload


@given(
    data=st.binary(max_size=128),
    codec_name=st.sampled_from(("lz10", "lz11", "rle", "yaz0")),
)
@settings(max_examples=40, deadline=None)
def test_property_compression_roundtrip_hypothesis(data, codec_name):
    codec = {"lz10": LZ10, "lz11": LZ11, "rle": RLE, "yaz0": Yaz0}[codec_name]
    assert codec.decompress(codec.compress(data)) == data


def test_property_branch_relocation_and_overflow_is_deterministic():
    random.seed(0x4D494F52)
    branch_opcode = 0xFE
    base_pc_delta = 3
    branches = []

    for case_index in range(24):
        data = bytearray(0x0400)
        pc = 0x10 + case_index * 16
        for attempt in range(512):
            offset = random.randrange(-0x2000, 0x2000)
            raw = struct.pack("<h", offset)
            target = pc + base_pc_delta + offset
            if branch_opcode not in raw and 0 <= target < len(data) and data[target] == 0:
                break
        else:
            pytest.fail("Unable to build deterministic branch fixture")

        data[pc] = branch_opcode
        data[pc + 1 : pc + 3] = raw
        data[pc + base_pc_delta + offset] = 0xC3
        scan = BytecodeBranchScanner.scan_relative_branches(
            bytes(data),
            branch_opcodes={branch_opcode},
            offset_fmt="<h",
            offset_pos_in_instr=1,
            instr_len=3,
            base_pc_delta=base_pc_delta,
        )
        assert len(scan) == 1
        branches.append(scan[0])

    insertion = 12
    modified = bytearray(b"\x00" * insertion + bytes(data))
    mapper = lambda address: address + insertion
    count = BytecodeBranchScanner.relocate_branches(
        modified,
        branches,
        mapper=mapper,
        base_pc_delta=base_pc_delta,
    )
    assert count == len(branches)

    for branch in branches:
        new_pc = branch.pc + insertion
        new_offset = struct.unpack_from("<h", modified, branch.offset_pos + insertion)[0]
        assert branch.pc + base_pc_delta + branch.offset + insertion == new_pc + base_pc_delta + new_offset


def test_property_branch_overflow_carries_structured_context():
    random.seed(0x4F5645)
    data = bytearray(0x0200)
    data[0x10] = 0xFE
    struct.pack_into("<h", data, 0x11, 0x0100)
    data[0x110] = 0xC3

    branch = BytecodeBranchScanner.scan_relative_branches(
        bytes(data),
        branch_opcodes={0xFE},
        offset_fmt="<h",
        offset_pos_in_instr=1,
        instr_len=3,
        base_pc_delta=3,
    )[0]

    with pytest.raises(PointerOverflowError) as error:
        BytecodeBranchScanner.relocate_branches(
            bytearray(data),
            [branch],
            mapper=lambda address: address + 0x10000 if address > 0x20 else address,
            base_pc_delta=3,
        )
    assert error.value.actual > 32767
    assert error.value.expected == (-32768, 32767)


def test_property_checksum_matches_preceding_prefix():
    random.seed(0x434845)
    class Packet(BinaryStruct):
        payload = U16()
        checksum = ChecksumField(1)

    for _ in range(64):
        value = random.randrange(0x10000)
        packed = Packet(payload=value).to_bytes()
        assert packed[-1] == sum(packed[:-1]) & 0xFF
        assert Packet.from_bytes(packed).checksum == packed[-1]
