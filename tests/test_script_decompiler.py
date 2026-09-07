import pytest
from miorom.script.engine import BytecodeEngine, DisassembledScript, Instruction
from miorom.script.opcode import ArgU8, ArgU16, ArgString
from miorom.script.control_flow import ControlFlowGraph
from miorom.script.decompiler import ScriptDecompiler, ChoiceBlock, ChoiceBranch


def test_script_decompiler_annotated():
    engine = BytecodeEngine(endian="<")
    engine.register_opcode(0x00, "END")
    engine.register_opcode(0x01, "JUMP", [ArgU16("target", is_jump_target=True)])
    engine.register_opcode(0x02, "IF_JUMP", [ArgU8("cond"), ArgU16("target", is_jump_target=True)])
    engine.register_opcode(0x09, "MESSAGE", [ArgString("text")])

    asm_text = """
    MESSAGE "Start"
    IF_JUMP 1 LABEL_TRUE
    MESSAGE "Branch False"
    JUMP LABEL_EXIT
LABEL_TRUE:
    MESSAGE "Branch True"
LABEL_EXIT:
    END
"""
    assembled = engine.assemble(asm_text)
    disasm = engine.disassemble(assembled)

    # Python annotated output
    py_out = ScriptDecompiler.decompile(disasm, language="python")
    assert "def game_event():" in py_out
    assert "MESSAGE(text='Start')" in py_out
    assert "Branch ->" in py_out
    assert "END()" in py_out

    # C annotated output
    c_out = ScriptDecompiler.decompile(disasm, language="c")
    assert "void game_event(void) {" in c_out
    assert "MESSAGE(text='Start');" in c_out
    assert "// Branch ->" in c_out
    assert "}" in c_out


def test_script_decompiler_structured():
    instructions = [
        Instruction(0, 1, "INIT", {}),
        Instruction(1, 2, "IF_FLAG", {"flag": 5, "target": "LABEL_0005"}),
        Instruction(3, 3, "SET_GOLD", {"amount": 50}),
        Instruction(4, 4, "JUMP", {"target": "LABEL_0006"}),
        Instruction(5, 5, "SET_GOLD", {"amount": 100}, label="LABEL_0005"),
        Instruction(6, 6, "END", {}, label="LABEL_0006"),
    ]
    script = DisassembledScript(instructions=instructions)

    # Structured python
    py_struct = ScriptDecompiler.decompile_structured(script, language="python", function_name="event_reward")
    assert "def event_reward():" in py_struct
    assert "if IF_FLAG(flag=5):" in py_struct
    assert "SET_GOLD(amount=100)" in py_struct
    assert "else:" in py_struct
    assert "SET_GOLD(amount=50)" in py_struct

    # Structured C
    c_struct = ScriptDecompiler.decompile_structured(script, language="c", function_name="event_reward")
    assert "void event_reward(void) {" in c_struct
    assert "if (IF_FLAG(flag=5)) {" in c_struct
    assert "} else {" in c_struct


def test_reconstruct_choices():
    # Multi-instruction choice construct
    instructions = [
        Instruction(0, 1, "PROMPT_CHOICE", {"prompt": "Would you like to buy this item?"}),
        Instruction(2, 2, "CHOICE_CASE", {"text": "Yes, please", "target": "LABEL_BUY"}),
        Instruction(4, 3, "CHOICE_CASE", {"text": "No, thank you", "target": "LABEL_CANCEL"}),
        Instruction(6, 4, "END", {}),
    ]
    script = DisassembledScript(instructions=instructions)

    choices = ScriptDecompiler.reconstruct_choices(script)
    assert len(choices) == 1
    ch = choices[0]
    assert ch.offset == 0
    assert ch.prompt == "Would you like to buy this item?"
    assert len(ch.options) == 2
    assert ch.options[0].text == "Yes, please"
    assert ch.options[0].target_label_or_offset == "LABEL_BUY"
    assert ch.options[1].text == "No, thank you"
    assert ch.options[1].target_label_or_offset == "LABEL_CANCEL"


def test_reconstruct_single_instruction_choice():
    # Single-instruction choice with args
    instructions = [
        Instruction(0, 1, "MENU_SELECT", {"prompt": "Select path", "target_opt1": 0x100, "target_opt2": 0x200}),
        Instruction(5, 2, "END", {}),
    ]
    script = DisassembledScript(instructions=instructions)

    choices = ScriptDecompiler.reconstruct_choices(script)
    assert len(choices) == 1
    assert len(choices[0].options) == 2
