import struct
import pytest
from miorom.script import BytecodeEngine, ArgU8, ArgU16, ArgString


def build_test_engine():
    engine = BytecodeEngine(endian="<")
    engine.register_opcode(0x00, "END")
    engine.register_opcode(0x01, "JUMP", [ArgU16("target", is_jump_target=True)])
    engine.register_opcode(0x02, "JUMP_IF", [ArgU8("flag"), ArgU16("target", is_jump_target=True)])
    engine.register_opcode(0x09, "MESSAGE", [ArgString("text", null_terminated=True)])
    engine.register_opcode(0x0B, "SET_SPEAKER", [ArgU8("speaker_id")])
    return engine


def test_bytecode_disassemble_and_assemble_roundtrip():
    engine = build_test_engine()

    # Construct binary bytecode:
    # 0x00: SET_SPEAKER 1 -> 0x0B 0x01 (2 bytes)
    # 0x02: MESSAGE "Hello" -> 0x09 'H' 'e' 'l' 'l' 'o' 0x00 (7 bytes)
    # 0x09: JUMP 0x0E -> 0x01 0x0E 0x00 (3 bytes)
    # 0x0C: MESSAGE "Skip" -> 0x09 'S' 'k' 'i' 'p' 0x00 (6 bytes)
    # 0x12: END -> 0x00 (1 byte)
    raw = bytearray()
    raw.extend(b"\x0B\x01")
    raw.extend(b"\x09Hello\x00")
    raw.extend(b"\x01\x12\x00") # JUMP to 0x12 (END)
    raw.extend(b"\x09Skip\x00")
    raw.extend(b"\x00")

    script = engine.disassemble(bytes(raw))

    # Verify instruction count
    assert len(script.instructions) == 5
    assert script.instructions[0].name == "SET_SPEAKER"
    assert script.instructions[0].args["speaker_id"] == 1
    assert script.instructions[1].name == "MESSAGE"
    assert script.instructions[1].args["text"] == "Hello"

    # Verify jump target was detected as a label
    assert script.instructions[2].name == "JUMP"
    assert script.instructions[2].args["target"] == "LABEL_0012"
    assert script.instructions[4].label == "LABEL_0012"

    # Assemble back
    assembled = engine.assemble(script)
    assert assembled == bytes(raw)


def test_bytecode_text_editing_and_recomputing_jumps():
    engine = build_test_engine()

    asm_text = """
    ; Test assembly script
    SET_SPEAKER 0x02
    MESSAGE "Halo Dunia!"
    JUMP LABEL_EXIT
    MESSAGE "Pesan ini dilewati"
LABEL_EXIT:
    END
    """

    binary = engine.assemble(asm_text)
    assert len(binary) > 0

    # Disassemble again to verify labels and positions
    script2 = engine.disassemble(binary)
    assert script2.instructions[0].args["speaker_id"] == 2
    assert script2.instructions[1].args["text"] == "Halo Dunia!"
    assert script2.instructions[-1].name == "END"
    assert script2.instructions[2].args["target"] == script2.instructions[-1].label


def test_bytecode_string_extraction_and_replacement():
    engine = build_test_engine()

    raw = b"\x0B\x01\x09Original Text\x00\x00"
    script = engine.disassemble(raw)

    strings = script.extract_strings()
    assert len(strings) == 1
    offset, arg_name, text = strings[0]
    assert text == "Original Text"

    # Replace string
    count = script.replace_strings({(offset, arg_name): "Teks Terjemahan"})
    assert count == 1

    new_bin = engine.assemble(script)
    assert b"Teks Terjemahan\x00" in new_bin
