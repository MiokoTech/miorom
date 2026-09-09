"""Tests for SymbolMap import: Dolphin .map and Ghidra CSV round-trips."""

from miorom.core import SymbolMap


def test_export_csv_roundtrip():
    m = SymbolMap()
    m.add(0x80001234, "fn_main", size=0x40, kind="code", comment="entry")
    m.add(0x80005678, "tbl_items", size=0x100, kind="table")
    csv_text = m.export_csv()
    m2 = SymbolMap()
    count = m2.import_csv(csv_text)
    assert count == 2
    sym = m2.resolve("fn_main")
    assert sym.address == 0x80001234
    assert sym.size == 0x40
    assert sym.kind == "code"
    assert sym.comment == "entry"
    sym2 = m2.resolve("tbl_items")
    assert sym2.size == 0x100
    assert sym2.kind == "table"
    assert sym2.comment == ""


def test_import_dolphin_map():
    dolphin = """// dolphin map header
// link order: forcing
..text:0x80003100
fooMainEntry|addr=0x80003100|size=0x000000E4|ver=108
SomeFunction|addr=0x800031E4|size=0x00000090|ver=108
.data:0x80004800
gTable|addr=0x80004800|size=0x00000100|ver=108
"""
    m = SymbolMap()
    count = m.import_dolphin_map(dolphin)
    assert count == 3
    assert m["fooMainEntry"] == 0x80003100
    assert m["SomeFunction"] == 0x800031E4
    assert m["gTable"] == 0x80004800
    assert m.resolve("gTable").size == 0x100


def test_import_dolphin_map_ignores_sections_and_junk():
    m = SymbolMap()
    count = m.import_dolphin_map("garbage line without pipes\n..sbss:0x80005000\n")
    assert count == 0


def test_import_sym_text_with_size_field():
    sym = "08000000 start\n08000100 fn_a 0x40 ; comment here\n; comment line\n"
    m = SymbolMap()
    count = m.import_sym_text(sym)
    assert count == 2
    assert m["fn_a"] == 0x08000100
    assert m.resolve("fn_a").size == 0x40


def test_import_csv_bad_rows_skipped():
    m = SymbolMap()
    csv_text = 'Name,Address,Size,Type,Comment\n"ok",0x100,8,"code","c"\nbroken_row_without_quotes,0x\n'
    count = m.import_csv(csv_text)
    assert count == 1
    assert m["ok"] == 0x100


def test_export_sym_file_roundtrip_with_comments():
    m = SymbolMap()
    m.add(0x02000100, "handler", size=0x20, kind="code", comment="irq vec")
    text = m.export_sym_file()
    m2 = SymbolMap()
    assert m2.import_sym_text(text) == 1
    assert m2["handler"] == 0x02000100
