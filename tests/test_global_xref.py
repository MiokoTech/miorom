import struct
import pytest
from miorom.asm.xref import GlobalXrefEngine, XRefType, CallerGraph


def test_global_xref_arm_literal_pools():
    base_addr = 0x08000000
    code = bytearray(64)

    # At 0x08000000: LDR R0, [PC, #8] -> PC is 0x08000008, target literal pool is at 0x08000010 (offset 0x10)
    # Opcode: LDR R0, [PC, #8] -> 0xE59F0008
    struct.pack_into("<I", code, 0x00, 0xE59F0008)

    # At offset 0x10 (address 0x08000010): store target address 0x08000050 (e.g. text dialog address)
    target_data_addr = 0x08000050
    struct.pack_into("<I", code, 0x10, target_data_addr)

    xrefs = GlobalXrefEngine.scan_literal_pools_arm(bytes(code), base_address=base_addr)
    assert len(xrefs) == 1
    xr = xrefs[0]
    assert xr.source_address == 0x08000000
    assert xr.target_address == target_data_addr
    assert xr.xref_type == XRefType.LITERAL_POOL


def test_caller_graph_and_mermaid():
    cg = CallerGraph()
    cg.add_call(0x08001000, 0x08002000)
    cg.add_call(0x08001000, 0x08003000)
    cg.add_call(0x08002000, 0x08004000)

    assert len(cg.functions) == 4
    assert 0x08001000 in cg.callers_of[0x08002000]
    assert 0x08002000 in cg.callees_of[0x08001000]

    mermaid = cg.to_mermaid()
    assert "graph TD" in mermaid
    assert 'fn_08001000["sub_08001000"] --> fn_08002000["sub_08002000"]' in mermaid
