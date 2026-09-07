import struct
from miorom.asm.jump_table import JumpTableDetector, JumpTableResolver
from miorom.asm.disambiguator import CodeDataDisambiguator, ByteClassification
from miorom.asm.slicer import JumpTable


def test_jump_table_detector_arm_add_pc():
    base_addr = 0x08000100
    code = bytearray()

    # 1. CMP R0, #3 (0x08000100) -> 4 cases (0, 1, 2, 3)
    # CMP R0, #3: 0xE3500003
    code.extend(struct.pack("<I", 0xE3500003))

    # 2. BHI default_label (0x08000104)
    # Target: 0x08000140. Offset = 0x08000140 - (0x08000104 + 8) = 0x34 bytes = 13 words = 0x0D
    # BHI opcode: 0x8A00000D
    code.extend(struct.pack("<I", 0x8A00000D))

    # 3. ADD PC, PC, R0, LSL #2 (0x08000108)
    # Opcode: 0xE08FF100
    code.extend(struct.pack("<I", 0xE08FF100))

    # 4. In ARM state, PC is +8 (0x08000110). Next word at 0x0800010C is padding / prefetch
    code.extend(struct.pack("<I", 0xE1A00000))  # NOP

    # 5. Jump table starts at 0x08000110 (PC+8)
    # 4 entries of absolute target addresses
    targets = [0x08000200, 0x08000250, 0x08000300, 0x08000350]
    for t in targets:
        code.extend(struct.pack("<I", t))

    # Trailing code / padding
    code.extend(b"\x00" * 64)

    jts = JumpTableDetector.detect_arm_jump_tables(bytes(code), base_address=base_addr)
    assert len(jts) == 1
    jt = jts[0]

    assert jt.jump_address == 0x08000108
    assert jt.table_address == 0x08000110
    assert jt.entry_count == 4
    assert jt.stride == 4
    assert jt.case_targets == targets
    assert jt.default_target == 0x08000140


def test_jump_table_detector_arm_branch_instructions():
    base_addr = 0x02000000
    code = bytearray()

    # CMP R1, #2 (3 cases: 0, 1, 2)
    code.extend(struct.pack("<I", 0xE3510002))
    # BHI default
    code.extend(struct.pack("<I", 0x8A000008))
    # ADD PC, PC, R1, LSL #2
    code.extend(struct.pack("<I", 0xE08FF101))
    # Prefetch NOP
    code.extend(struct.pack("<I", 0xE1A00000))

    # Table starts at +16 bytes (0x02000010)
    # Entries are B <target> (0xEAxxxxxx) instructions:
    # Target 1: 0x02000080 -> offset from 0x02000010 + 8 = 0x68 bytes = 26 words (0x1A)
    # Target 2: 0x020000A0 -> offset from 0x02000014 + 8 = 0x84 bytes = 33 words (0x21)
    # Target 3: 0x020000C0 -> offset from 0x02000018 + 8 = 0xA0 bytes = 40 words (0x28)
    b1 = 0xEA000000 | 0x1A
    b2 = 0xEA000000 | 0x21
    b3 = 0xEA000000 | 0x28
    code.extend(struct.pack("<I", b1))
    code.extend(struct.pack("<I", b2))
    code.extend(struct.pack("<I", b3))
    code.extend(b"\x00" * 128)

    jts = JumpTableDetector.detect_arm_jump_tables(bytes(code), base_address=base_addr)
    assert len(jts) == 1
    jt = jts[0]
    assert jt.entry_count == 3
    assert jt.case_targets == [0x02000080, 0x020000A0, 0x020000C0]


def test_jump_table_resolver_facade_and_disambiguator():
    base_addr = 0x08000000
    code = bytearray(64)
    # Instruction at offset 8: ADD PC, PC, R0, LSL #2
    struct.pack_into("<I", code, 8, 0xE08FF100)
    # Targets at table offset 16 (4 entries * 4 = 16 bytes: offsets 16..31)
    for c in range(4):
        struct.pack_into("<I", code, 16 + c * 4, 0x08000100 + c * 0x20)

    tables = JumpTableResolver.resolve_all(bytes(code), base_address=base_addr, arch="arm")
    assert len(tables) == 1
    jt = tables[0]

    # Test disambiguator protection
    disambiguator = CodeDataDisambiguator(len(code))
    protected_count = JumpTableResolver.mark_in_disambiguator(disambiguator, tables, base_address=base_addr)
    assert protected_count == 16  # 4 entries * 4 bytes

    # Check that bytes 16..31 are tagged as JUMP_TABLE
    for b in range(16, 32):
        assert disambiguator.classifications[b] == ByteClassification.JUMP_TABLE


def test_jump_table_to_c_switch():
    jt = JumpTable(
        jump_address=0x08001000,
        table_address=0x08001008,
        entry_count=3,
        stride=4,
        default_target=0x08001999,
        case_targets=[0x08002000, 0x08002100, 0x08002200],
    )

    c_code = JumpTableResolver.to_c_switch(jt, switch_var="action_id")
    assert "switch (action_id) {" in c_code
    assert "case 0:" in c_code
    assert "goto loc_08002000;" in c_code
    assert "case 1:" in c_code
    assert "goto loc_08002100;" in c_code
    assert "case 2:" in c_code
    assert "goto loc_08002200;" in c_code
    assert "default:" in c_code
    assert "goto loc_08001999;" in c_code

    mapping = JumpTableResolver.to_switch_cases(jt)
    assert mapping[0] == 0x08002000
    assert mapping[1] == 0x08002100
    assert mapping[2] == 0x08002200
