import pytest
from miorom.asm.snippet import AsmSnippet, ThumbSnippet, PpcSnippet, SnesSnippet
from miorom.asm.disasm import UniversalDisassembler
from miorom.asm.branch import ARMBranch, ThumbBranch, PowerPCBranch, MIPSBranch
from miorom.errors import ParseError


def test_thumb_snippet_push_pop():
    snip = AsmSnippet.thumb()
    snip.push(["r4", "r5", "lr"]).pop(["r4", "r5", "pc"])
    raw = snip.emit()
    assert len(raw) == 4
    # push {r4, r5, lr} = 0xB530 (little-endian: 30 B5)
    # pop {r4, r5, pc} = 0xBD30 (little-endian: 30 BD)
    assert raw == b"\x30\xB5\x30\xBD"

    instrs = UniversalDisassembler.disassemble(raw, base_address=0x08000000, arch="thumb")
    assert len(instrs) == 2
    assert instrs[0].mnemonic == "push"
    assert instrs[1].mnemonic == "pop"


def test_thumb_snippet_mov_add_sub_cmp():
    snip = AsmSnippet.thumb()
    snip.mov_imm("r0", 42)
    snip.mov_reg("r1", "r0")
    snip.add_imm("r1", 10)
    snip.sub_imm("r1", 5)
    snip.cmp_imm("r1", 47)
    snip.bx("lr")
    raw = snip.emit()

    instrs = UniversalDisassembler.disassemble(raw, base_address=0x08000100, arch="thumb")
    assert len(instrs) == 6
    assert instrs[0].mnemonic == "mov"
    assert "r0" in instrs[0].operands[0]
    assert instrs[1].mnemonic == "mov"
    assert instrs[2].mnemonic == "add"
    assert instrs[3].mnemonic == "sub"
    assert instrs[4].mnemonic == "cmp"
    assert instrs[5].mnemonic == "bx"


def test_thumb_snippet_loads_stores():
    snip = AsmSnippet.thumb()
    snip.ldr_imm("r2", "r0", 8)
    snip.str_imm("r2", "r1", 8)
    snip.ldr_pc("r3", 16)
    snip.ldr_sp("r4", 4)
    snip.str_sp("r4", 4)
    raw = snip.emit()
    assert len(raw) == 10

    instrs = UniversalDisassembler.disassemble(raw, base_address=0x08000200, arch="thumb")
    assert len(instrs) == 5
    assert instrs[0].mnemonic == "ldr"
    assert instrs[1].mnemonic == "str"
    assert instrs[2].mnemonic == "ldr"
    assert instrs[3].mnemonic == "ldr"
    assert instrs[4].mnemonic == "str"


def test_thumb_snippet_branch_and_bl():
    snip = AsmSnippet.thumb()
    snip.b(target_vaddr=0x08000020, current_pc=0x08000000)
    snip.b_cond(cond="eq", target_vaddr=0x08000020, current_pc=0x08000002)
    snip.bl(target_vaddr=0x08001000, current_pc=0x08000004)
    raw = snip.emit()
    assert len(raw) == 8

    instrs = UniversalDisassembler.disassemble(raw, base_address=0x08000000, arch="thumb")
    assert len(instrs) == 3
    assert instrs[0].mnemonic == "b"
    assert instrs[0].target_address == 0x08000020
    assert instrs[1].mnemonic == "beq"
    assert instrs[1].target_address == 0x08000020
    assert instrs[2].mnemonic == "bl"
    assert instrs[2].target_address == 0x08001000


def test_thumb_snippet_validation_errors():
    snip = AsmSnippet.thumb()
    with pytest.raises(ParseError):
        snip.mov_imm("r8", 10)  # r8 is high register, mov_imm requires r0..r7
    with pytest.raises(ParseError):
        snip.mov_imm("r0", 1000)  # > 255
    with pytest.raises(ParseError):
        snip.ldr_imm("r0", "r1", 7)  # not multiple of 4
    with pytest.raises(ParseError):
        snip.b(0x08000001, 0x08000000)  # unaligned target


def test_ppc_snippet_basic():
    snip = AsmSnippet.ppc()
    snip.stwu("r1", -32, "r1")
    snip.mflr("r0")
    snip.stw("r0", 36, "r1")
    snip.li("r3", 100)
    snip.li("r4", 0x80205000)
    snip.mr("r5", "r3")
    snip.lwz("r0", 36, "r1")
    snip.mtlr("r0")
    snip.addi("r1", "r1", 32)
    snip.blr()
    raw = snip.emit()

    assert len(raw) == 44  # 11 instructions (32-bit li emits lis + ori)
    instrs = UniversalDisassembler.disassemble(raw, base_address=0x80001000, arch="ppc")
    assert len(instrs) == 11
    assert instrs[0].mnemonic == "stwu"
    assert instrs[1].mnemonic == "mflr"
    assert instrs[10].mnemonic == "blr"


def test_ppc_snippet_branches():
    snip = AsmSnippet.ppc()
    snip.b(target_vaddr=0x80002000, current_pc=0x80001000)
    snip.bl(target_vaddr=0x80003000, current_pc=0x80001004)
    snip.nop(2)
    raw = snip.emit()

    assert len(raw) == 16
    instrs = UniversalDisassembler.disassemble(raw, base_address=0x80001000, arch="ppc")
    assert instrs[0].mnemonic == "b"
    assert instrs[0].target_address == 0x80002000
    assert instrs[1].mnemonic == "bl"
    assert instrs[1].target_address == 0x80003000


def test_snes_snippet():
    snip = AsmSnippet.snes()
    snip.clc().rep(0x20)  # 16-bit A
    snip.lda_imm(0x1234, is_16bit=True)
    snip.sta_addr(0x2100)
    snip.sep(0x20)  # 8-bit A
    snip.lda_imm(0x55, is_16bit=False)
    snip.sta_dp(0x10)
    snip.jsr(0x8500)
    snip.rts()
    raw = snip.emit()

    # Disassemble with 65816 disassembler
    instrs = UniversalDisassembler.disassemble(raw, base_address=0x8000, arch="65816")
    mnemonics = [i.mnemonic for i in instrs]
    assert "clc" in mnemonics
    assert "rep" in mnemonics
    assert "lda" in mnemonics
    assert "sta" in mnemonics
    assert "sep" in mnemonics
    assert "jsr" in mnemonics
    assert "rts" in mnemonics


def test_branch_parse_error_import():
    # Verify ARMBranch and ThumbBranch properly raise ParseError on unaligned target
    with pytest.raises(ParseError):
        ARMBranch.encode_b(source_pc=0x08000000, target_addr=0x08000003)
    with pytest.raises(ParseError):
        ThumbBranch.encode_b(source_pc=0x08000000, target_addr=0x08000003)
    with pytest.raises(ParseError):
        PowerPCBranch.encode_b(source_pc=0x80000000, target_addr=0x80000001)
    with pytest.raises(ParseError):
        MIPSBranch.encode_j(source_pc=0x80000000, target_addr=0x80000001)
