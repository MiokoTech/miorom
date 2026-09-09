import struct
import pytest
from miorom.script.branch import BytecodeBranchScanner, RelativeBranch, SwitchTable


def test_scan_and_relocate_relative_branches():
    # Construct a bytecode buffer:
    # 0x00: NOP (0x00)
    # 0x01: BRANCH (0x0F) [rel16: +10] -> target 1 + 3 + 10 = 14 (0x0E)
    # 0x04: CALL (0xF4) [rel16: +20]   -> target 4 + 3 + 20 = 27 (0x1B)
    # 0x07..0x0D: Text block "Hello\x00"
    # 0x0E: Target of branch (NOP 0x00)
    # 0x0F..0x1A: Padding
    # 0x1B: Target of call (RETURN 0x16)
    buf = bytearray(0x30)
    buf[0] = 0x00
    # Branch 0x0F at 1
    buf[1] = 0x0F
    struct.pack_into("<h", buf, 2, 10)
    # Call 0xF4 at 4
    buf[4] = 0xF4
    struct.pack_into("<h", buf, 5, 20)
    # Text block at 7..13
    buf[7:13] = b"Hello\x00"

    branches = BytecodeBranchScanner.scan_relative_branches(
        data=bytes(buf),
        branch_opcodes={0x0F, 0xF4},
        offset_fmt="<h",
        offset_pos_in_instr=1,
        base_pc_delta=3,
        excluded_ranges=[(7, 13)],
    )

    assert len(branches) == 2
    b1, b2 = branches[0], branches[1]
    assert b1.pc == 1
    assert b1.opcode == 0x0F
    assert b1.target == 14

    assert b2.pc == 4
    assert b2.opcode == 0xF4
    assert b2.target == 27

    # Test relocation with a simulated offset shift (insert 10 bytes at offset 7)
    def shift_mapper(old_addr):
        return old_addr + 10 if old_addr >= 7 else old_addr

    modified = bytearray(buf[:7] + b"A" * 10 + buf[7:])
    count = BytecodeBranchScanner.relocate_branches(
        buffer=modified,
        branches=branches,
        mapper=shift_mapper,
        base_pc_delta=3,
    )
    assert count == 2

    # Verify updated offsets:
    # Branch at 1: new_pc = 1, new_target = 14 + 10 = 24.
    # new_off = 24 - (1 + 3) = 20
    new_off1 = struct.unpack_from("<h", modified, 2)[0]
    assert new_off1 == 20

    # Call at 4: new_pc = 4, new_target = 27 + 10 = 37.
    # new_off = 37 - (4 + 3) = 30
    new_off2 = struct.unpack_from("<h", modified, 5)[0]
    assert new_off2 == 30


def test_scan_and_relocate_switch_tables():
    # Construct a switch table:
    # 0x05: SWITCH (0xF2) [cnt: 3] [off0: +2] [off1: +10] [off2: +20]
    # base_pc_delta = 2, so:
    # case 0 at 7: target = 7 + 2 + 2 = 11
    # case 1 at 9: target = 9 + 2 + 10 = 21
    # case 2 at 11: target = 11 + 2 + 20 = 33
    buf = bytearray(0x40)
    buf[5] = 0xF2
    buf[6] = 3  # count
    struct.pack_into("<h", buf, 7, 2)
    struct.pack_into("<h", buf, 9, 10)
    struct.pack_into("<h", buf, 11, 20)

    tables = BytecodeBranchScanner.scan_switch_tables(
        data=bytes(buf),
        switch_opcodes={0xF2},
        count_fmt="<B",
        offset_fmt="<h",
        base_pc_delta=2,
        min_cases=2,
    )

    assert len(tables) == 1
    st = tables[0]
    assert st.pc == 5
    assert st.case_count == 3
    assert st.cases[0].target == 11
    assert st.cases[1].target == 21
    assert st.cases[2].target == 33

    # Relocate with mapper
    def mapper(addr):
        return addr + 8 if addr >= 15 else addr

    modified = bytearray(buf)
    count = BytecodeBranchScanner.relocate_switch_tables(
        buffer=modified,
        tables=tables,
        mapper=mapper,
        base_pc_delta=2,
    )
    assert count == 3
    # Case 0 target was 11 (<15, unchanged): off = 11 - (7 + 2) = 2
    assert struct.unpack_from("<h", modified, 7)[0] == 2
    # Case 1 target was 21 (>=15, new 29): off = 29 - (9 + 2) = 18
    assert struct.unpack_from("<h", modified, 9)[0] == 18
