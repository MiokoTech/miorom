from miorom.core.symbol_map import SymbolMap
from miorom.naming import FunctionNamer
from miorom.script.ir import IRBlock, IRFunction, IRInstruction, IROp


def test_function_namer_detects_checksum_call_via_symbol_map():
    func = IRFunction(name="sub_08000100", entry_address=0x08000100)
    block = IRBlock(label="loc_08000100", address=0x08000100)
    block.add_instruction(IRInstruction(IROp.CALL, dst="r0", args=[0x08001234], pc=0x08000100))
    func.add_block(block)

    symbols = SymbolMap().add(0x08001234, "crc32")
    namer = FunctionNamer(symbol_map=symbols)

    assert namer._is_checksum_routine(func) is True
    assert namer.name_function(func, "sub_08000100") == "checksum_08000100"


def test_function_namer_detects_checksum_xor_shift_pattern_without_symbols():
    func = IRFunction(name="sub_08000200", entry_address=0x08000200)
    block = IRBlock(label="loc_08000200", address=0x08000200)
    for idx in range(4):
        block.add_instruction(IRInstruction(IROp.XOR, dst="r0", args=["r0", idx], pc=0x08000200 + idx))
    for idx in range(2):
        block.add_instruction(IRInstruction(IROp.SHL, dst="r0", args=["r0", 1], pc=0x08000210 + idx))
    func.add_block(block)

    namer = FunctionNamer()

    assert namer._is_checksum_routine(func) is True
    assert namer.name_function(func, "sub_08000200") == "checksum_08000200"
