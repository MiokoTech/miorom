import os
import struct
import tempfile
import pytest

from miorom.core.scanner import StringScanner, PointerScanner
from miorom.core.rom_view import ROM
from miorom.helper.string_pool import StringPoolBuilder
from miorom.helper.tag_converter import TagConverter
from miorom.helper.relocator import BinaryRelocator
from miorom.helper.dual_table import DualTableHelper
from miorom.archive.toc_pair import TocPair
from miorom.formats.csv_handler import CsvHandler, TranslationRow
from miorom.text.pixel_wrapper import FontMetrics, PixelWordWrapper


def test_string_scanner_kwargs():
    # Build sample data with aligned strings and whitespace
    data = bytearray(128)
    data[0:8] = b"  Alpha "
    data[16:26] = b"BetaTest1 "
    data[32:42] = b"BetaTest2 "
    data[45:55] = b"GammaRay  "  # Unaligned (offset 45)

    # Test pattern (case-insensitive)
    found = StringScanner.scan_strings(data, pattern="beta", case_sensitive=False)
    assert len(found) == 2
    assert "BetaTest1" in found[0].text

    # Test pattern (case-sensitive)
    found_case = StringScanner.scan_strings(data, pattern="beta", case_sensitive=True)
    assert len(found_case) == 0

    # Test regex
    found_rx = StringScanner.scan_strings(data, regex=r"Test\d")
    assert len(found_rx) == 2

    # Test alignment
    found_aligned = StringScanner.scan_strings(data, alignment=16)
    assert all(s.offset % 16 == 0 for s in found_aligned)
    assert not any("Gamma" in s.text for s in found_aligned)

    # Test max_strings
    found_max = StringScanner.scan_strings(data, max_strings=1)
    assert len(found_max) == 1

    # Test strip_whitespace
    found_stripped = StringScanner.scan_strings(data, strip_whitespace=True)
    alpha = next(s for s in found_stripped if "Alpha" in s.text)
    assert alpha.text == "Alpha"


def test_pointer_scanner_kwargs():
    # Create synthetic pointer table pointing to targets
    targets = [0x100, 0x120, 0x140, 0x160]
    buf = bytearray(0x200)

    # Table at offset 0x20 (big-endian 32-bit pointers)
    for i, tgt in enumerate(targets):
        struct.pack_into(">I", buf, 0x20 + i * 4, tgt)

    # Accept single stride int and single endian str kwargs
    tables = PointerScanner.find_pointer_tables(
        bytes(buf),
        targets,
        stride=4,
        endian=">",
        min_pointers=4,
        min_confidence=0.5,
        max_tables=1,
    )
    assert len(tables) == 1
    assert tables[0].table_offset == 0x20
    assert tables[0].stride == 4
    assert tables[0].endian == ">"

    # Start offset kwarg
    tables_skipped = PointerScanner.find_pointer_tables(
        bytes(buf),
        targets,
        stride=4,
        endian=">",
        start_offset=0x30,
    )
    assert len(tables_skipped) == 0

    # Footer pointer tables with single stride/endian
    footer_buf = bytearray(0x200)
    for i, tgt in enumerate(targets):
        struct.pack_into(">I", footer_buf, 0x1D0 + i * 4, tgt)

    footer_tables = PointerScanner.find_footer_pointer_tables(
        bytes(footer_buf),
        targets,
        stride=4,
        endian=">",
        min_confidence=0.6,
        max_tables=1,
    )
    assert len(footer_tables) == 1
    assert footer_tables[0].table_offset == 0x1D0


def test_string_pool_builder_kwargs():
    # Test deduplicate=True
    pool = StringPoolBuilder(encoding="utf-16-be", endian=">", stride=4, deduplicate=True)
    i0 = pool.add("Duplicate")
    i1 = pool.add("Unique")
    i2 = pool.add("Duplicate")  # Should reuse offset of i0

    assert pool.count == 3
    assert pool.get_offset(i0) == pool.get_offset(i2)
    assert pool.get_offset(i0) != pool.get_offset(i1)

    # Test prefix_offset
    pool_pfx = StringPoolBuilder(encoding="ascii", prefix_offset=0x8000)
    pool_pfx.add("Hello")
    assert pool_pfx.get_offset(0) >= 0x8000

    # Test length_prefix (1 byte)
    pool_len = StringPoolBuilder(encoding="ascii", length_prefix=1, null_terminate=False)
    pool_len.add("Test")
    raw_pool = pool_len.build_pool()
    assert raw_pool[0] == 4
    assert raw_pool[1:5] == b"Test"

    # Test add_many
    pool_multi = StringPoolBuilder(encoding="ascii")
    indices = pool_multi.add_many(["A", "B", "C"])
    assert indices == [0, 1, 2]
    assert pool_multi.count == 3

    # Test pad_to_size
    padded_pool = pool_multi.build_pool(pad_to_size=64)
    assert len(padded_pool) == 64

    combined = pool_multi.build_combined(pad_to_size=128)
    assert len(combined) == 128


def test_tag_converter_kwargs():
    tc = TagConverter({"<HERO>": "[0x1234]"})

    # Test decode_utf16 kwargs: stop_on_null, max_length, strip, replace_newlines
    # Construct UTF-16 BE with \n and trailing spaces
    sample_text = "  Hero [0x1234]\nNext  "
    encoded = tc.encode_utf16(sample_text, endian=">")

    decoded_stripped = tc.decode_utf16(encoded, endian=">", strip=True, replace_newlines="<BR>")
    assert decoded_stripped == "Hero <HERO><BR>Next"

    # Test max_length
    decoded_short = tc.decode_utf16(encoded, endian=">", max_length=6)
    assert len(decoded_short) <= 6

    # Test encode_utf16 kwargs: pad_to, pad_byte, max_bytes
    padded_bytes = tc.encode_utf16("Short", endian=">", pad_to=32, pad_byte=b"\xFF")
    assert len(padded_bytes) == 32
    assert padded_bytes[-2:] == b"\xFF\xFF"

    truncated_bytes = tc.encode_utf16("Very long text here", endian=">", max_bytes=8)
    assert len(truncated_bytes) == 8


def test_relocator_kwargs():
    buf = bytearray(b"0123456789ABCDEF")
    reloc = BinaryRelocator(buf)

    # Test dry_run=True (does not mutate buffer)
    delta_dry = reloc.replace_range(4, 4, b"XXXX_EXTRA", dry_run=True)
    assert delta_dry == 6
    assert reloc.to_bytes() == b"0123456789ABCDEF"

    # Test align kwarg (pads replacement data to 16 bytes)
    delta_aligned = reloc.replace_range(0, 4, b"NEW", align=16, pad_byte=0xCC)
    assert len(reloc) == 16 - 4 + 16
    assert reloc.buffer[3:16] == b"\xCC" * 13


def test_dual_table_kwargs():
    tc = TagConverter({"<ITEM>": "[0x9999]"})
    t1 = ["Hello <ITEM>", "  World  ", ""]
    t2 = ["Footer <ITEM>"]

    # Repack with tag_converter and alignment=64
    repacked = DualTableHelper.repack(
        t1, t2,
        encoding="utf-16-be",
        alignment=64,
        tag_converter=tc,
    )
    assert len(repacked) % 64 == 0

    # Extract with strip, filter_empty, tag_converter
    ext_t1, ext_t2 = DualTableHelper.extract(
        repacked,
        encoding="utf-16-be",
        strip=True,
        filter_empty=True,
        tag_converter=tc,
    )
    assert ext_t1 == ["Hello <ITEM>", "World"]
    assert ext_t2 == ["Footer <ITEM>"]


def test_toc_pair_kwargs():
    with tempfile.TemporaryDirectory() as tmpdir:
        bin_file = os.path.join(tmpdir, "test.bin")
        dat_file = os.path.join(tmpdir, "test.dat")

        # Create raw TOC pair (2 entries: offset, size)
        # Entry 0: offset 0, size 16
        # Entry 1: offset 16, size 16
        with open(bin_file, "wb") as f:
            f.write(struct.pack(">IIII", 0, 16, 16, 16))
        with open(dat_file, "wb") as f:
            f.write(b"A" * 16 + b"B" * 16)

        toc = TocPair.load(bin_file, dat_file)

        # Test dry_run=True on inject
        new_chunk = b"C" * 64
        simulated_off = toc.inject(0, new_chunk, dry_run=True, alignment=64)
        assert simulated_off == 64  # 32 bytes dat aligned to 64

        # Test actual inject with alignment=64
        toc.inject(0, new_chunk, alignment=64)
        assert toc.get_entry(0).size == 64

        # Test extract_all
        out_sub = os.path.join(tmpdir, "extracted")
        paths = toc.extract_all(out_sub, prefix="sub_", extension=".dat")
        assert len(paths) == 2
        assert os.path.exists(paths[0])
        assert os.path.basename(paths[0]) == "sub_0000.dat"


def test_rom_view_kwargs():
    buf = bytearray(256)
    buf[0:16] = b"Attack Power 10\x00"
    buf[32:48] = b"Defense Guard 5\x00"
    buf[64:80] = b"Attack Speed 15\x00"

    rom = ROM.from_bytes(bytes(buf), name="TestROM")

    # Test StringQuery.filter with regex, max_results, alignment
    res_rx = rom.strings.filter(regex=r"Attack", max_results=1)
    assert len(res_rx) == 1
    assert "Attack" in res_rx[0].text

    # Test alignment filter
    res_align = rom.strings.filter(alignment=32)
    assert all(s.offset % 32 == 0 for s in res_align)

    # Test ROM.find_pointers with stride and endian kwargs
    targets = [0, 32, 64]
    for i, t in enumerate(targets):
        struct.pack_into(">I", rom.bytearray, 128 + i * 4, t)
    struct.pack_into(">I", rom.bytearray, 128 + 3 * 4, 64)

    tables = rom.find_pointers(targets=targets, stride=4, endian=">", min_confidence=0.5, max_tables=1)
    assert len(tables) == 1
    assert tables[0].stride == 4
    assert tables[0].endian == ">"


def test_csv_handler_kwargs():
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_file = os.path.join(tmpdir, "dialogues.csv")

        rows = [
            TranslationRow(index=0, offset=0x10, original="Sword", translation=" Pedang ", context="Item"),
            TranslationRow(index=1, offset=0x20, original="Shield", translation="", context="Item"),
        ]

        # Test export without context column
        CsvHandler.export_csv(csv_file, rows, include_context=False)
        with open(csv_file, "r") as f:
            header = f.readline().strip().split(",")
            assert "Context" not in header

        # Test import as dict with strip_whitespace and fallback_to_original
        data_dict = CsvHandler.import_csv(
            csv_file,
            as_dict=True,
            strip_whitespace=True,
            fallback_to_original=True,
        )
        assert data_dict[0] == "Pedang"
        assert data_dict[1] == "Shield"  # Fallback to original


def test_pixel_wrapper_kwargs():
    metrics = FontMetrics()
    wrapper = PixelWordWrapper(metrics, max_pixel_width=200, max_lines=3)

    text = "The quick brown fox jumps over the lazy dog"

    # Test wrap with max_pixel_width override and custom newline
    wrapped = wrapper.wrap(text, max_pixel_width=100, newline="<BR>")
    assert "<BR>" in wrapped

    # Test validate with kwargs override
    valid, warnings = wrapper.validate(wrapped.replace("<BR>", "\n"), max_lines=1)
    assert not valid
    assert any("exceeds maximum lines" in w for w in warnings)
