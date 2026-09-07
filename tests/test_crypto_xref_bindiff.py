import struct
import pytest

from miorom.scanner.crypto import CryptoScanner, CryptoMatch, CryptoReport
from miorom.scanner.xref import XRefAnalyzer, XRefGraph, XRefType
from miorom.diff.bindiff import BinDiffEngine, BinDiffReport, FunctionMatch
from miorom.archive.synthesizer import ArchiveSynthesizer, ArchiveLayout


def test_crypto_scanner():
    # Build buffer containing AES S-Box, MD5 constants, and TEA delta
    data = bytearray(b"\x00" * 64)
    # Inject AES forward S-box prefix
    aes_off = 0x10
    data[aes_off : aes_off + len(CryptoScanner.AES_SBOX_PREFIX)] = CryptoScanner.AES_SBOX_PREFIX

    # Inject MD5 constants (Big-Endian)
    md5_off = 0x40
    data.extend(CryptoScanner.MD5_CONSTANTS_BE)

    # Inject TEA delta (Big-Endian)
    tea_off = len(data)
    data.extend(CryptoScanner.TEA_DELTA_BE)

    report = CryptoScanner.scan(bytes(data), base_address=0x80000000)
    assert report.total_bytes == len(data)
    assert len(report.matches) >= 3

    algos = [m.algorithm for m in report.matches]
    assert "AES" in algos
    assert "MD5" in algos
    assert "TEA/XTEA" in algos

    summary = report.summary()
    assert "CryptoHunter Binary Scanner Report" in summary
    assert "AES" in summary


def test_xref_graph_and_chains():
    # Build code block with calls and pointer references
    # 0x00: bl 0x80000008 (call)
    # 0x04: blr
    # 0x08: blr
    # 0x0C: 0x80000014 (pointer pointing to 0x14)
    # 0x10: 0x8000000C (pointer pointing to pointer at 0x0C)
    # 0x14: "Text\x00"
    buf = bytearray(32)
    struct.pack_into(">I", buf, 0x00, 0x48000009)  # bl 0x80000008 (from 0x80000000: diff=8)
    struct.pack_into(">I", buf, 0x04, 0x4E800020)  # blr
    struct.pack_into(">I", buf, 0x08, 0x4E800020)  # blr
    struct.pack_into(">I", buf, 0x0C, 0x80000014)  # Pointer 1 -> 0x14
    struct.pack_into(">I", buf, 0x10, 0x8000000C)  # Pointer 2 -> 0x0C -> 0x14
    buf[0x14:0x19] = b"Text\x00"

    graph = XRefAnalyzer.analyze(bytes(buf), base_address=0x80000000, arch="ppc")

    # Check caller of 0x80000008 is 0x80000000
    callers = graph.get_callers_of(0x80000008)
    assert 0x80000000 in callers

    # Check callees from 0x80000000
    callees = graph.get_callees_from(0x80000000)
    assert 0x80000008 in callees

    # Check pointer references
    refs_to_14 = graph.get_data_references(0x80000014)
    assert 0x8000000C in refs_to_14

    # Test multi-level pointer chain: target 0x80000014
    chains = graph.find_pointer_chains(0x80000014, max_depth=3)
    assert len(chains) >= 1
    # One of the chains should be [0x80000010, 0x8000000C, 0x80000014]
    assert any(c == [0x80000010, 0x8000000C, 0x80000014] for c in chains)

    # Test mermaid export
    mermaid = graph.to_mermaid(0x80000000, radius=2)
    assert "graph TD" in mermaid
    assert "0x80000000" in mermaid


def test_bindiff_engine():
    # Function A (PPC):
    # li r3, 10; addi r3, r3, 5; blr
    code_a = bytearray(12)
    struct.pack_into(">I", code_a, 0x00, 0x3860000A)
    struct.pack_into(">I", code_a, 0x04, 0x38630005)
    struct.pack_into(">I", code_a, 0x08, 0x4E800020)

    # Function B (identical logic, slightly different immediate):
    # li r3, 10; addi r3, r3, 7; blr
    code_b = bytearray(12)
    struct.pack_into(">I", code_b, 0x00, 0x3860000A)
    struct.pack_into(">I", code_b, 0x04, 0x38630007)
    struct.pack_into(">I", code_b, 0x08, 0x4E800020)

    fp_a = BinDiffEngine.fingerprint_function(bytes(code_a), 0x80001000, 0x80001000, arch="ppc")
    fp_b = BinDiffEngine.fingerprint_function(bytes(code_b), 0x80002000, 0x80002000, arch="ppc")

    sim = BinDiffEngine.compare_fingerprints(fp_a, fp_b)
    # Identical CFG and opcode counts, similarity should be 1.0!
    assert sim >= 0.99

    report = BinDiffEngine.diff_binaries(
        data_a=bytes(code_a),
        base_a=0x80001000,
        funcs_a=[0x80001000],
        data_b=bytes(code_b),
        base_b=0x80002000,
        funcs_b=[0x80002000],
        arch="ppc",
    )
    assert report.total_funcs_a == 1
    assert len(report.matches) == 1
    assert report.matches[0].func_a_address == 0x80001000
    assert report.matches[0].func_b_address == 0x80002000
    assert "BinDiff CFG Isomorphism Report" in report.summary()


def test_archive_synthesizer():
    # Build a synthetic container:
    # 0x00: Magic 'MYPK'
    # 0x04: File count = 2
    # 0x08..0x18: TOC (8 bytes per entry: offset, size)
    #   Entry 0: off 0x20, size 0x10 ("Hello World!\x00")
    #   Entry 1: off 0x30, size 0x08 ("TestData")
    data = bytearray(0x40)
    data[0x00:0x04] = b"MYPK"
    struct.pack_into("<I", data, 0x04, 2)  # 2 files, Little-Endian
    # TOC at 0x08:
    struct.pack_into("<II", data, 0x08, 0x20, 13)
    struct.pack_into("<II", data, 0x10, 0x30, 8)

    # Payloads
    data[0x20:0x2D] = b"Hello World!\x00"
    data[0x30:0x38] = b"TestData"

    layout = ArchiveSynthesizer.analyze(bytes(data))
    assert layout.magic == b"MYPK"
    assert layout.file_count == 2
    assert len(layout.entries) == 2
    assert layout.entries[0].data.startswith(b"Hello World")
    assert layout.entries[0].guessed_type == "TEXT"
    assert layout.entries[1].data == b"TestData"

    # Verify generated Python class
    assert "class SynthesizedArchive:" in layout.generated_python_code
    assert "def pack(self)" in layout.generated_python_code
    assert "MYPK" in layout.summary()
