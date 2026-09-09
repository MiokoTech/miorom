"""SM83 (Game Boy) micro-assembler tests — encodings verified against SM83 opcode tables."""

import pytest

from miorom.asm import AsmSnippet, SM83Snippet


def test_load_dd_hl():
    s = AsmSnippet.sm83()
    s.ld_rr("d", "h", "l")  # LD D, (HL) = 0x56
    code = s.emit()
    assert code == b"\x56"


def test_load_hl_r():
    s = AsmSnippet.sm83()
    s.ld_tr("h", "l", "a")  # LD (HL), A = 0x77
    assert s.emit() == b"\x77"


def test_load_r_n():
    s = AsmSnippet.sm83()
    s.ld_r_n("a", 0x3C)
    assert s.emit() == b"\x3e\x3c"


def test_load_a_rr():
    s = AsmSnippet.sm83()
    s.ld_rr("a", "b", "c")  # LD A, (BC) = 0x0A
    assert s.emit() == b"\x0a"


def test_ld_a_nn():
    s = AsmSnippet.sm83()
    s.ld_a_nn(0x1234)  # 0xFA lo hi
    assert s.emit() == b"\xfa\x34\x12"


def test_inc_dec_16bit():
    s = AsmSnippet.sm83()
    s.inc_rp("bc")  # 0x03
    s.dec_rp("hl")  # 0x2B
    assert s.emit() == b"\x03\x2b"


def test_jr_nz():
    s = AsmSnippet.sm83()
    s.jr_cc("nz", 0x7C)
    assert s.emit() == b"\x20\x7c"


def test_jr_backward_negative():
    s = AsmSnippet.sm83()
    s.jr(-4)  # 0x18 0xFC
    assert s.emit() == b"\x18\xfc"


def test_jp_hl():
    s = AsmSnippet.sm83()
    s.jp_hl()
    assert s.emit() == b"\xe9"


def test_ret_and_di_ei():
    s = AsmSnippet.sm83()
    s.ret()
    s.di()
    s.ei()
    assert s.emit() == b"\xc9\xf3\xfb"


def test_push_pop():
    s = AsmSnippet.sm83()
    s.push("bc")  # 0xC5
    s.pop("hl")   # 0xE1
    assert s.emit() == b"\xc5\xe1"


def test_call():
    s = AsmSnippet.sm83()
    s.call(0x0038)  # 0xCD lo hi
    assert s.emit() == b"\xcd\x38\x00"


def test_rst():
    s = AsmSnippet.sm83()
    s.rst(0x38)  # 0xFF
    assert s.emit() == b"\xff"


def test_xor_and_cp():
    s = AsmSnippet.sm83()
    s.xor("a")  # 0xAF
    s.cp("b")   # 0xB8
    assert s.emit() == b"\xaf\xb8"


def test_ldh_a_c():
    s = AsmSnippet.sm83()
    s.ldh_a_c()  # 0xF2
    assert s.emit() == b"\xf2"


def test_ldh_a_n():
    s = AsmSnippet.sm83()
    s.ldh_a_n(0x80)  # 0xF0 0x80
    assert s.emit() == b"\xf0\x80"


def test_cb_prefix():
    s = AsmSnippet.sm83()
    s.cb("bit", "h", 7)  # BIT 7,H = CB 7C
    assert s.emit() == b"\xcb\x7c"
    s2 = AsmSnippet.sm83()
    s2.cb("res", "l", 3)  # RES 3,L = CB 9D
    assert s2.emit() == b"\xcb\x9d"


def test_unknown_register_raises():
    s = AsmSnippet.sm83()
    with pytest.raises(ValueError, match="SM83"):
        s.xor("x9")


def test_factory_returns_sm83():
    assert isinstance(AsmSnippet.sm83(), SM83Snippet)


def test_direct_class_construction():
    s = SM83Snippet()
    s.nop()
    assert s.emit() == b"\x00"
