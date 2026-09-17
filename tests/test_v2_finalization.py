import struct
import tempfile
from pathlib import Path

from miorom.diff.bindiff import BinDiffEngine, FunctionMatch
from miorom.diff.porter import CrossRegionPorter
from miorom.patch.ips import IpsPatcher
from miorom.scanner.xref import XRefAnalyzer, XRefType
from miorom.script.ir import IRBlock, IRFunction, IRInstruction, IROp
from miorom.script.lifter import BinaryLifter


def _code_function(address):
    function = IRFunction(name=f"sub_{address:08X}", entry_address=address)
    entry = IRBlock(label=f"loc_{address:08X}", address=address)
    entry.instructions.append(IRInstruction(op=IROp.CALL, args=[address + 0x20], pc=address))
    target = IRBlock(label=f"loc_{address + 0x20:08X}", address=address + 0x20)
    target.instructions.append(IRInstruction(op=IROp.RETURN, args=["r3"], pc=address + 0x20))
    entry.successors.append(target.label)
    target.predecessors.append(entry.label)
    function.add_block(entry)
    function.add_block(target)
    return function


def test_xref_mermaid_ir_groups_blocks():
    functions = [_code_function(0x100), _code_function(0x120)]
    graph = XRefAnalyzer.analyze_ir(functions)
    mermaid = graph.to_mermaid_ir(functions, center_address=0x100, radius=1)

    assert "subgraph sub_00000100" in mermaid
    assert "0x00000120" in mermaid
    assert "CALL" in mermaid
    assert "-. CFG .->" in mermaid


def test_xref_analyze_ir_records_conditional_branch_target():
    # ARM: cmp r0,#0; beq 0x100C; mov r1,#1; bx lr
    code = struct.pack("<IIII", 0xE3500000, 0x0A000000, 0xE3A01001, 0xE12FFF1E)
    ir_func = BinaryLifter.lift(code, 0x1000, arch="arm")
    graph = XRefAnalyzer.analyze_ir([ir_func])

    refs_from_branch = graph.forward_refs[0x1004]

    assert len(refs_from_branch) == 1
    assert refs_from_branch[0].source == 0x1004
    assert refs_from_branch[0].target == 0x100C
    assert refs_from_branch[0].xref_type == XRefType.CODE_JUMP
    assert refs_from_branch[0].context == f"{ir_func.name}:BRANCH_COND"
    assert graph.backward_refs[0x100C][0] == refs_from_branch[0]


def test_lifter_disk_cache_roundtrip():
    code = bytes.fromhex("3800000148000008386000004e800020")
    with tempfile.TemporaryDirectory() as cache_dir:
        BinaryLifter.disk_cache_dir = cache_dir
        try:
            first = BinaryLifter.lift(code, base_address=0x1000, arch="ppc")
            second = BinaryLifter.lift(code, base_address=0x1000, arch="ppc")
            assert first == second
            assert any(Path(cache_dir).glob("*.json"))
        finally:
            BinaryLifter.disk_cache_dir = None


def test_port_patch_uses_function_matches_before_binary_mapper():
    source = bytearray(b"A" * 0x20 + bytes.fromhex("3800000148000008386000004e800020") + b"Z" * 0x10)
    target = bytearray(b"B" * 0x40 + bytes.fromhex("3800000148000008386000004e800020") + b"Z" * 0x10)
    modified = bytearray(source)
    modified[0x20:0x24] = b"\x38\x60\x00\x07"
    patch = IpsPatcher.create(source, modified)

    match = FunctionMatch(0x20, 0x40, 1.0, "Exact")
    porter = CrossRegionPorter()
    translated_patch, report = porter.port_patch(source, target, patch, [match])
    assert report.migrated_strings == 1
    assert report.unmatched_strings == 0
    assert report.strategy == "function_anchors"

    migrated = IpsPatcher.apply(target, translated_patch)
    assert migrated[0x40:0x44] == b"\x38\x60\x00\x07"


def test_bin_diff_engine_discovers_aligned_internal_pointers():
    data = struct.pack(">II", 0, 0x100)
    assert BinDiffEngine.discover_function_candidates(data, 0x100) == [0x100]
