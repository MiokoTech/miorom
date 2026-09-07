import struct
import pytest
from miorom.script.vm_profiler import VMBytecodeSynthesizer, OpcodeCategory
from miorom.asm.slicer import JumpTable


def test_vm_bytecode_synthesizer_from_jump_table():
    base_addr = 0x08000000
    code = bytearray(0x200)

    # Handler 0 at 0x08000040:
    # LDRB R0, [R4, #1] (0xE5D40001)
    # BX LR (0xE12FFF1E)
    struct.pack_into("<I", code, 0x40, 0xE5D40001)
    struct.pack_into("<I", code, 0x44, 0xE12FFF1E)

    # Handler 1 at 0x08000060:
    # LDRH R0, [R4, #2] (0xE1D400B2)
    # BL 0x08000100 (0xEB000026)
    # BX LR (0xE12FFF1E)
    struct.pack_into("<I", code, 0x60, 0xE1D400B2)
    struct.pack_into("<I", code, 0x64, 0xEB000026)
    struct.pack_into("<I", code, 0x68, 0xE12FFF1E)

    # Handler 2 at 0x08000080:
    # LDR R0, [R4, #4] (0xE5940004)
    # BX LR (0xE12FFF1E)
    struct.pack_into("<I", code, 0x80, 0xE5940004)
    struct.pack_into("<I", code, 0x84, 0xE12FFF1E)

    jt = JumpTable(
        jump_address=0x08000010,
        table_address=0x08000020,
        entry_count=3,
        stride=4,
        case_targets=[0x08000040, 0x08000060, 0x08000080],
    )

    vm_spec = VMBytecodeSynthesizer.synthesize_from_jump_table(
        code=bytes(code),
        jump_table=jt,
        base_address=base_addr,
        arch="arm",
    )

    assert vm_spec.opcode_count == 3
    assert len(vm_spec.opcodes) == 3

    # Opcode 0
    op0 = vm_spec.opcodes[0]
    assert op0.handler_address == 0x08000040
    assert op0.arg_size == 1

    # Opcode 1
    op1 = vm_spec.opcodes[1]
    assert op1.handler_address == 0x08000060
    assert op1.arg_size == 2

    # Opcode 2
    op2 = vm_spec.opcodes[2]
    assert op2.handler_address == 0x08000080
    assert op2.arg_size == 4

    # Test export configs
    engine_cfg = vm_spec.to_engine_config()
    assert 0 in engine_cfg
    assert engine_cfg[0]["arg_size"] == 1
    assert engine_cfg[1]["arg_size"] == 2

    py_schema = vm_spec.to_python_schema()
    assert "INSTRUCTION_SET = {" in py_schema
    assert "0x00:" in py_schema
    assert "0x01:" in py_schema
