import struct
import tempfile
from pathlib import Path

from miorom.diff.bindiff import BinDiffEngine, FunctionMatch
from miorom.diff.porter import CrossRegionPorter
from miorom.patch.ips import IpsPatcher
from miorom.script.lifter import BinaryLifter
from miorom.script.ir import IRBlock, IRFunction, IRInstruction, IROp
from miorom.scanner.xref import XRefAnalyzer, XRefType


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
