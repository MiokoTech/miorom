import pytest
from miorom.script.engine import BytecodeEngine
from miorom.script.opcode import ArgU8, ArgU16, ArgString
from miorom.script.control_flow import ControlFlowGraph, ScriptDecompiler


def test_control_flow_graph_and_decompiler():
    engine = BytecodeEngine(endian="<")
    engine.register_opcode(0x00, "END")
    engine.register_opcode(0x01, "JUMP", [ArgU16("target", is_jump_target=True)])
    engine.register_opcode(0x02, "IF_JUMP", [ArgU8("cond"), ArgU16("target", is_jump_target=True)])
    engine.register_opcode(0x09, "MESSAGE", [ArgString("text")])

    asm_text = """
    MESSAGE "Hello"
    IF_JUMP 1 LABEL_TRUE
    MESSAGE "False branch"
    JUMP LABEL_END
LABEL_TRUE:
    MESSAGE "True branch"
LABEL_END:
    END
"""
    assembled = engine.assemble(asm_text)
    disasm = engine.disassemble(assembled)

    cfg = ControlFlowGraph.from_script(disasm)
    assert len(cfg.blocks) >= 3

    # Check decompilation output
    decompiled = ScriptDecompiler.decompile(disasm)
    assert "def game_event():" in decompiled
    assert "MESSAGE(text='Hello')" in decompiled
    assert "MESSAGE(text='True branch')" in decompiled
    assert "MESSAGE(text='False branch')" in decompiled
    assert "END()" in decompiled
