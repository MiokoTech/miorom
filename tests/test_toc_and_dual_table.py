import os
import struct
import tempfile
import pytest

from miorom.archive.toc_pair import TocPair, TocEntry
from miorom.core.scanner import StringScanner, PointerScanner
from miorom.scanner.deep import DeepScanner


def test_toc_pair_nlcm_lifecycle():
    with tempfile.TemporaryDirectory() as tmpdir:
        bin_file = os.path.join(tmpdir, "archive.bin")
        dat_file = os.path.join(tmpdir, "archive.dat")

        # Create dummy dat payload
        file0 = b"Hello, File 0!"
        file1 = b"Neverland Data Block 123456"
        with open(dat_file, "wb") as f:
            f.write(file0)
            # pad to 32
            pad = (32 - (f.tell() % 32)) % 32
            f.write(b"\x00" * pad)
            f1_off = f.tell()
            f.write(file1)

        # Create NLCM header (0x38 bytes) + 2 entries (0x10 bytes each)
        bin_data = bytearray(0x38 + 2 * 0x10)
        bin_data[0:4] = b"NLCM"
        struct.pack_into(">I", bin_data, 0x0C, 2)  # 2 entries
        # Entry 0: size, flags, offset
        struct.pack_into(">I", bin_data, 0x38, len(file0))
        struct.pack_into(">I", bin_data, 0x38 + 8, 0)
        # Entry 1
        struct.pack_into(">I", bin_data, 0x48, len(file1))
        struct.pack_into(">I", bin_data, 0x48 + 8, f1_off)

        with open(bin_file, "wb") as f:
            f.write(bin_data)

        # 1. Load and inspect
        toc = TocPair.load(bin_file, dat_file)
        assert len(toc) == 2
        assert toc.format_type == "nlcm"
        assert toc.get_entry(0).size == len(file0)
        assert toc.get_entry(1).offset == f1_off

        # 2. Extract
        ext0 = toc.extract(0)
        assert ext0 == file0
        ext1 = toc.extract(1)
        assert ext1 == file1

        # 3. In-place inject (smaller or equal)
        toc.inject(0, b"Short")
        assert toc.extract(0) == b"Short"
        assert toc.get_entry(0).size == 5

        # 4. Expanding inject (larger -> append at EOF aligned to 32)
        big_data = b"X" * 100
        toc.inject(1, big_data)
        assert toc.extract(1) == big_data
        assert toc.get_entry(1).size == 100
        assert toc.get_entry(1).offset % 32 == 0


def test_deep_scanner_neverland_signatures():
    # 1. NLCM archive header
    nlcm_buf = bytearray(0x38)
    nlcm_buf[0:4] = b"NLCM"
    struct.pack_into(">I", nlcm_buf, 0x0C, 100)
    report = DeepScanner().scan(bytes(nlcm_buf))
    fp_names = [fp.format_name for fp in report.fingerprints]
    assert "Neverland_NLCM" in fp_names

    # 2. Multi-section Script binary header
    script_sz = 0x1000
    script_buf = bytearray(script_sz)
    script_buf[0:4] = b"\x00\x00\x00\x00"
    struct.pack_into(">I", script_buf, 4, script_sz)
    script_buf[8:12] = b"\x00\x00\x00\x01"
    struct.pack_into(">I", script_buf, 0x14, 5) # 5 sections
    struct.pack_into(">I", script_buf, 0x48, 0x200) # text table offset
    report_script = DeepScanner().scan(bytes(script_buf))
    fp_names_script = [fp.format_name for fp in report_script.fingerprints]
    assert "Neverland_Script" in fp_names_script


def test_footer_pointer_scanner():
    # Create synthetic binary:
    # 0x00 - 0x10: padding
    # 0x10 - 0x30: strings
    # 0x40 - 0x50: footer pointer table (pointing to 0x10, 0x20)
    buf = bytearray(0x60)
    s1 = b"String One\x00"
    s2 = b"String Two\x00"
    buf[0x10:0x10 + len(s1)] = s1
    buf[0x20:0x20 + len(s2)] = s2

    # Footer table at 0x40
    struct.pack_into(">I", buf, 0x40, 0x10)
    struct.pack_into(">I", buf, 0x44, 0x20)

    tables = PointerScanner.find_footer_pointer_tables(
        bytes(buf),
        target_offsets=[0x10, 0x20],
        strides=(4,),
        endians=(">",),
        min_pointers=2,
        footer_scan_bytes=48,
    )
    assert len(tables) >= 1
    assert tables[0].table_offset == 0x40
    assert tables[0].count == 2
