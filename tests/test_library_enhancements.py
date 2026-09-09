import pytest
import struct
from io import BytesIO

from miorom.archive import (
    DmaTableEntryStruct,
    DmaFileEntry,
    DmaTableArchive,
)
from miorom.asm.disasm import UniversalDisassembler
from miorom.script.lifter import BinaryLifter
from miorom.patch import FarMemoryHeap
from miorom.graphics import (
    N64TextureFormat,
    N64TextureDecoder,
    N64TextureEncoder,
    Fast3DBuilder,
    Fast3DParser,
    Palette,
    Color,
    FloydSteinbergDitherer,
)
from miorom.text import (
    ControlCodeDef,
    ControlCodeSchema,
    ControlCodeTokenizer,
    GlyphWidthTable,
    VWFMetricsInspector,
)
from miorom.text.charmap_miner import CharMapMiner
from miorom.formats.script_catalog import DialogueCleaner, ScriptCatalog
from miorom.core.pointer import SegmentTable, SegmentedAddressResolver
from miorom.patch.ips import IpsPatcher
from miorom.audio.n64_seq import M64Sequence, N64Audiobank
from miorom.save.checksum import SaveChecksumEngine
from miorom.core.symbol_map import SymbolMap
from miorom.asm.prologue_scanner import FunctionPrologueScanner
from miorom.link.relocator import CompoundRelocationLinker
from miorom.script.vm_profiler import VMBytecodeSynthesizer
from miorom.diff.patch_auditor import PatchAuditor, PatchHunk
from miorom.core.schema import BinaryStruct, U16, ParseError
from miorom.platforms.n64 import N64Rom
from miorom.analysis_db import AnalysisDatabase
from miorom.core.schema import U8
from miorom.scanner.xref import XRefType
from miorom.scanner.table_detector import HeuristicTableDetector


# --- Textures ---

def test_n64_rgba16_roundtrip():
    raw_rgba16 = bytes([
        0xF8, 0x01,  0x07, 0xC1,
        0x00, 0x3F,  0x00, 0x00,
    ])
    rgba_bytes = N64TextureDecoder.decode(raw_rgba16, N64TextureFormat.RGBA16, width=2, height=2)
    assert len(rgba_bytes) == 16
    assert rgba_bytes[0] == 255 and rgba_bytes[1] == 0 and rgba_bytes[2] == 0 and rgba_bytes[3] == 255
    assert rgba_bytes[15] == 0
    re_encoded = N64TextureEncoder.encode(rgba_bytes, N64TextureFormat.RGBA16, width=2, height=2)
    assert re_encoded == raw_rgba16


def test_n64_ia16_decode():
    raw = bytes([100, 200, 50, 0])
    rgba = N64TextureDecoder.decode(raw, "ia16", width=2, height=1)
    assert len(rgba) == 8
    assert rgba[0] == 100 and rgba[1] == 100 and rgba[2] == 100 and rgba[3] == 200
    assert rgba[4] == 50 and rgba[5] == 50 and rgba[6] == 50 and rgba[7] == 0


def test_n64_i8_roundtrip():
    raw = bytes([10, 50, 150, 250])
    rgba = N64TextureDecoder.decode(raw, "i8", width=2, height=2)
    encoded = N64TextureEncoder.encode(rgba, "i8", width=2, height=2)
    assert encoded == raw


# --- DMA Table Filesystem ---

def test_dma_table_archive_parsing():
    rom = bytearray(0x8000)
    struct.pack_into(">IIII", rom, 0x1000, 0x80000000, 0x80001000, 0x00002000, 0x00000000)
    struct.pack_into(">IIII", rom, 0x1010, 0x80001000, 0x80002000, 0x00003000, 0x00003800)
    struct.pack_into(">IIII", rom, 0x1020, 0, 0, 0, 0)
    rom[0x2000:0x2005] = b"HELLO"

    dma = DmaTableArchive.from_bytes(bytes(rom), table_offset=0x1000, entry_names={0: "boot.bin"})
    assert len(dma.entries) == 2
    assert dma.entries[0].name == "boot.bin"
    assert dma.entries[0].size_decompressed == 0x1000
    assert dma.entries[1].is_compressed is True
    assert dma.entries[1].size_rom == 0x800

    extracted = dma.extract_file(bytes(rom), index=0, decompress_yaz0=False)
    assert extracted.startswith(b"HELLO")
    assert dma.find_by_vaddr(0x80000500).index == 0


# --- MIPS COP1 & Disasm / Lifter ---

def test_mips_cop1_disasm_and_lift():
    code = bytearray(20)
    struct.pack_into(">I", code, 0,  0xC4800000) # lwc1 $f0, 0($a0)
    struct.pack_into(">I", code, 4,  0x46000080) # add.s $f2, $f0, $f0
    struct.pack_into(">I", code, 8,  0xE4820004) # swc1 $f2, 4($a0)
    struct.pack_into(">I", code, 12, 0x03E00008) # jr $ra
    struct.pack_into(">I", code, 16, 0x00000000) # nop

    instrs = UniversalDisassembler.disassemble(bytes(code), base_address=0x80000000, arch="mips", endian=">")
    assert len(instrs) == 5
    assert instrs[0].mnemonic == "lwc1"
    assert instrs[1].mnemonic == "add.s"
    assert instrs[2].mnemonic == "swc1"
    assert instrs[3].mnemonic == "jr"

    ir = BinaryLifter.lift(bytes(code), base_address=0x80000000, arch="mips", endian=">", function_name="test_fpu")
    c_code = BinaryLifter.decompile_to_c(ir)
    assert "int test_fpu()" in c_code
    assert "$f2_1 = $f0_1 + $f0_1;" in c_code


def test_disasm_and_lift_sm83():
    code = bytes([0x3E, 0x42, 0xC9])
    instrs = UniversalDisassembler.disassemble(code, arch="sm83")
    assert instrs[0].mnemonic == "ld"
    assert instrs[1].mnemonic == "ret"
    ir = BinaryLifter.lift(code, base_address=0x100, arch="sm83")
    assert "return a;" in BinaryLifter.decompile_to_c(ir)


def test_disasm_and_lift_m68k():
    code = bytes([0x70, 0x2A, 0x4E, 0x75])
    instrs = UniversalDisassembler.disassemble(code, arch="m68k")
    assert instrs[0].mnemonic == "moveq"
    assert instrs[1].mnemonic == "rts"
    ir = BinaryLifter.lift(code, base_address=0x1000, arch="m68k")
    assert "return d0;" in BinaryLifter.decompile_to_c(ir)


# --- Memory Allocation & Patching ---

def test_far_memory_heap_allocation():
    buf = bytearray(0x1000)
    heap = FarMemoryHeap(buf, base_offset=0x1000, max_size=0x2000, alignment=16)
    p1 = heap.write(b"PAYLOAD_ONE", alignment=16)
    assert p1 == 0x1000
    assert len(heap.buffer) >= 0x1000 + len(b"PAYLOAD_ONE")
    p2 = heap.write(b"PAYLOAD_TWO", alignment=16)
    assert p2 == 0x1010
    assert heap.total_allocated_bytes == len(b"PAYLOAD_ONE") + len(b"PAYLOAD_TWO")


def test_ips_patch_streaming():
    src = BytesIO(b"ABCDEFGHIJ" * 10)
    patch = IpsPatcher.create(b"ABCDEFGHIJ" * 10, b"ABCZZZGHIJ" * 10)
    dst = BytesIO()
    IpsPatcher.apply_stream(src, patch, dst, chunk_size=16)
    assert dst.getvalue() == b"ABCZZZGHIJ" * 10


# --- Fast3D Microcode ---

def test_fast3d_parser_and_builder():
    builder = (
        Fast3DBuilder()
        .set_timg(fmt=0, siz=2, image_ptr=0x02001000)
        .set_tile_size(tile=0, uls=0, ult=0, lrs=31, lrt=31)
        .end_dl()
    )
    code = builder.emit()
    assert len(code) == 24

    texs = Fast3DParser.find_textures(code)
    assert len(texs) == 1
    t = texs[0]
    assert t.format_name == "rgba16"
    assert t.width == 32
    assert t.height == 32
    assert t.image_ptr == 0x02001000


# --- Text Tokenizing & Script Catalogs ---

def test_control_code_tokenizer_bidirectional():
    schema = ControlCodeSchema(
        codes=[
            ControlCodeDef(byte_id=0x01, name="NL", description="New line"),
            ControlCodeDef(byte_id=0x05, name="COLOR", arg_bytes=1, description="Text color"),
        ],
        terminator=b"\x02",
    )
    raw = ControlCodeTokenizer.encode("Hello<NL><COLOR:0A>World", schema=schema)
    assert raw == b"Hello\x01\x05\x0AWorld\x02"
    decoded = ControlCodeTokenizer.decode(raw, schema=schema)
    assert decoded == "Hello<NL><COLOR:0A>World"


def test_script_catalog_and_dialogue_cleaner():
    raw = "<1A><13>-<08>You borrowed a <05>APocket Egg<05>@!<09><01>A Pocket Cucco will hatch from<01>it overnight."
    cleaned = DialogueCleaner.clean(raw)
    assert "<" not in cleaned
    assert "You borrowed a APocket Egg@!" in cleaned
    assert "\n" in cleaned

    script = "[0]\nHello World\nLine 2\n\n[1]\nSecond entry\n"
    d = ScriptCatalog.parse_script(script)
    assert d[0] == "Hello World\nLine 2"
    assert d[1] == "Second entry"


def test_segmented_address_resolver():
    table = SegmentTable({7: 0x0090BAC0})
    resolver = SegmentedAddressResolver(table)
    phys = resolver.to_physical(0x07001000)
    assert phys == 0x0090CAC0
    seg = resolver.to_segmented(phys, segment_id=7)
    assert seg == 0x07001000


def test_solve_ngram_frequencies():
    sample = b"the the the he in in er an an"
    table = CharMapMiner.solve_ngram_frequencies(sample, min_occurrences=1)
    assert isinstance(table, dict)
    assert len(table) > 0


def test_vwf_kerning_and_collision_inspector():
    table = GlyphWidthTable({c: 8 for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"})
    inspector = VWFMetricsInspector(table)
    inspector.set_kerning("A", "V", -2)
    assert inspector.measure_text("AV") == 14
    rep = inspector.inspect("A" * 20, max_width_px=100, max_lines=2)
    assert rep.overflowed


# --- Miscellaneous Tooling ---

def test_m64_sequence_parser():
    seq_data = bytes([0xDF, 0x64, 0xFC, 0x01, 0x20, 0xFF])
    seq = M64Sequence.from_bytes(seq_data)
    assert len(seq.commands) == 3
    assert seq.commands[0].name == "VOLUME"
    assert seq.commands[1].name == "CALL"
    assert seq.commands[2].name == "END"


def test_save_checksum_engine():
    data = bytearray(0x20)
    data[0:4] = b"TEST"
    matched = SaveChecksumEngine.verify_and_fix(data, checksum_offset=0x10, data_range=(0, 0x10), algo="crc16_xmodem")
    assert not matched
    matched_after = SaveChecksumEngine.verify_and_fix(data, checksum_offset=0x10, data_range=(0, 0x10), algo="crc16_xmodem")
    assert matched_after


def test_symbol_map_exporters():
    sm = SymbolMap()
    sm.add(0x80001000, "main")
    ghidra = sm.to_ghidra_script()
    assert "currentProgram.getSymbolTable()" in ghidra
    assert "0x80001000" in ghidra
    ida = sm.to_ida_idc()
    assert "set_name" in ida
    sym = sm.to_sym()
    assert "80001000 main" in sym


def test_function_prologue_scanner():
    code = bytearray(0x20)
    struct.pack_into(">I", code, 0x04, 0x27BDFFE0)
    funcs = FunctionPrologueScanner.scan(bytes(code), base_address=0x80000000, arch="mips")
    assert len(funcs) == 1
    assert funcs[0].address == 0x80000004


def test_compound_relocation_linker():
    hi, lo = CompoundRelocationLinker.calculate_hi_lo_pair(0x80009000)
    assert hi == 0x8001
    assert lo == 0x9000


def test_floyd_steinberg_dithering():
    pal = Palette([Color(0, 0, 0), Color(255, 255, 255)])
    pixels = [[(128, 128, 128) for _ in range(4)] for _ in range(4)]
    idx_matrix = FloydSteinbergDitherer.dither(pixels, pal)
    assert len(idx_matrix) == 4
    assert len(idx_matrix[0]) == 4


def test_vm_dispatcher_table_detector():
    code = bytearray(0x80)
    for i in range(8):
        struct.pack_into("<I", code, i * 4, 0x40 + i * 4)
    tables = VMBytecodeSynthesizer.detect_dispatcher_tables(bytes(code), base_address=0, min_opcodes=8)
    assert len(tables) == 1
    assert tables[0] == (0, 8)


def test_patch_auditor():
    hunks = [PatchHunk(offset=0x10, data=b"XX"), PatchHunk(offset=0x2000, data=b"PATCH")]
    protected = [("HEADER", 0x00, 0x40)]
    report = PatchAuditor.audit(hunks, protected)
    assert not report.is_safe
    assert len(report.collisions) == 1
    assert report.collisions[0].region_name == "HEADER"


def test_schema_validation_hook():
    class ValidatedHeader(BinaryStruct):
        _endian = ">"
        count = U16(validate=lambda v: v < 100)

    inst = ValidatedHeader.from_bytes(b"\x00\x32")
    assert inst.count == 50

    with pytest.raises(ParseError, match="Validation constraint failed"):
        ValidatedHeader.from_bytes(b"\x00\xC8")


def test_n64_rom_preserve_database_crc():
    hdr = bytearray(0x101000)
    hdr[0:4] = b"\x80\x37\x12\x40"
    hdr[0x10:0x18] = (0x12345678).to_bytes(4, "big") + (0x87654321).to_bytes(4, "big")
    hdr[0x20:0x34] = b"TEST ROM            "
    hdr[0x3C:0x40] = b"CZLE"

    rom = N64Rom(bytes(hdr))
    crc1, crc2 = rom.recalculate_checksum(preserve_database_crc=True)
    assert crc1 == 0x12345678
    assert crc2 == 0x87654321


# --- Dynamic Sizing & Overread Guard ---

class _SimpleStruct(BinaryStruct):
    a = U8()
    b = U16()


def test_binary_struct_dynamic_size_and_offset():
    data = b"\x12\x34\x56"
    assert _SimpleStruct.sizeof_dynamic(data) == 3
    assert _SimpleStruct.offset_of_dynamic("b", data) == 1


def test_binary_struct_overread_has_structured_context():
    with pytest.raises(ParseError) as exc_info:
        _SimpleStruct.from_bytes(b"\x12\x34")
    error = exc_info.value
    assert error.offset == 1
    assert error.expected == 2
    assert error.actual == 1


def test_iter_stride_records_stops_before_full_scan():
    large_buffer = bytearray(0x100000)
    for record_index in range(4):
        struct.pack_into(
            "<I",
            large_buffer,
            record_index * 16 + 4,
            0x8000 + record_index * 32,
        )
    for text_offset, text in ((0x8000, b"ABCD"), (0x8020, b"EFGH"), (0x8040, b"IJKL"), (0x8060, b"MNOP")):
        large_buffer[text_offset:text_offset + len(text)] = text
        large_buffer[text_offset + len(text)] = 0

    candidates = HeuristicTableDetector.iter_stride_records(
        bytes(large_buffer),
        candidate_strides=(16,),
        min_records=4,
        max_scan_bytes=0x100,
    )
    assert len(list(candidates)) == 1


def test_analysis_database_roundtrip_sqlite(tmp_path):
    path = str(tmp_path / "analysis.mioromdb")
    database = AnalysisDatabase(path)
    database.xref_graph.add_xref(
        0x1000,
        0x2000,
        XRefType.CODE_CALL,
        context="main",
    )
    database.set_function_name(0x2000, "target_func")
    database.add_signature_match(0x2000, "memcpy", 0.97)

    database.save()
    loaded = AnalysisDatabase.load(path)
    assert loaded.get_function_name(0x2000) == "target_func"
    assert [(m.name, m.confidence) for m in loaded.signature_matches] == [("memcpy", 0.97)]
    assert len(loaded.xref_graph.backward_refs[0x2000]) == 1
    assert AnalysisDatabase._is_sqlite(path)


def test_analysis_database_direct_sqlite_query(tmp_path):
    path = str(tmp_path / "analysis.mioromdb")
    database = AnalysisDatabase(path)
    for source in range(0x1000, 0x1010):
        database.xref_graph.add_xref(source, 0x2000, XRefType.CODE_CALL)
    database.set_function_name(0x2000, "target_func")
    database.save()

    entries = list(AnalysisDatabase.query_xrefs(path, target=0x2000, limit=3))
    assert [entry.source for entry in entries] == [0x1000, 0x1001, 0x1002]
    assert list(AnalysisDatabase.query_function_names(path, prefix="target")) == [(0x2000, "target_func")]


def test_rom_manager_mmap_forces_mmap_stream(tmp_path):
    from miorom.rom.manager import RomManager
    data = bytearray(0x1000)
    data[0:4] = b"TEST"
    struct.pack_into("<I", data, 0x20, 0x200)
    struct.pack_into("<I", data, 0x30, 0x300)
    data[0x12] = 0
    path = tmp_path / "sample.nds"
    path.write_bytes(data)

    class _MmapProbeHandler:
        name = "mmap_probe"

        def can_handle(self, rom_data: bytes, filepath=None):
            return False

        def unpack(self, rom_data, output_dir, filepath=None):
            return {"is_mmap": type(rom_data).__name__ == "mmap"}

        def repack(self, input_dir, **kwargs):
            return b""

    manager = RomManager()
    manager.register(_MmapProbeHandler())
    manager.detect_format = lambda rom_data, filepath=None: "mmap_probe"
    meta = manager.unpack(str(path), str(tmp_path / "out"), use_mmap=True)
    assert meta["used_mmap"] is True
