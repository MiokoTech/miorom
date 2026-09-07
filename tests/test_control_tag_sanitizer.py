import pytest
from miorom.text.sanitizer import (
    ControlTagSanitizer,
    TagValidationResult,
)
from miorom.text.po_handler import PoHandler, PoEntry


def test_control_tag_extraction_and_syntax():
    text = "[HERO] memperoleh [ITEM:05] dan [NUM:100] koin emas!"
    tags = ControlTagSanitizer.extract_tags(text)
    assert tags == ["HERO", "ITEM:05", "NUM:100"]

    # Valid syntax
    assert len(ControlTagSanitizer.check_syntax(text)) == 0

    # Unclosed bracket
    broken_text = "[HERO memperoleh [ITEM:05]"
    errs = ControlTagSanitizer.check_syntax(broken_text)
    assert len(errs) > 0
    assert "Mismatched brackets" in errs[0]

    # Empty bracket
    empty_tag = "Halo [] dunia!"
    errs_empty = ControlTagSanitizer.check_syntax(empty_tag)
    assert any("Empty tag" in e for e in errs_empty)


def test_validate_translation():
    orig = "Welcome, [NAME]! Here is your [ITEM:01]."

    # Perfectly preserved
    trans_ok = "Selamat datang, [NAME]! Ini adalah [ITEM:01] milikmu."
    res_ok = ControlTagSanitizer.validate_translation(orig, trans_ok)
    assert res_ok.is_valid
    assert len(res_ok.missing_tags) == 0

    # Missing tag [ITEM:01]
    trans_missing = "Selamat datang, [NAME]! Ini barangmu."
    res_missing = ControlTagSanitizer.validate_translation(orig, trans_missing)
    assert not res_missing.is_valid
    assert "ITEM:01" in res_missing.missing_tags

    # Unexpected tag
    trans_unexpected = "Selamat datang, [NAME]! [COLOR:RED]Hati-hati![COLOR:WHITE] Ini [ITEM:01]."
    res_unexp = ControlTagSanitizer.validate_translation(orig, trans_unexpected)
    assert res_unexp.is_valid  # Still valid since essential variables were preserved
    assert "COLOR:RED" in res_unexp.unexpected_tags


def test_sanitize_typos():
    text_with_typos = "Halo [[HERO]], kamu mendapatkan [ ITEM:99 ] sekarang!"
    cleaned = ControlTagSanitizer.sanitize(text_with_typos)
    assert cleaned == "Halo [HERO], kamu mendapatkan [ITEM:99] sekarang!"


def test_lint_po_catalog():
    po = PoHandler()
    po.entries = [
        PoEntry(msgid="Hello [NAME]!", msgstr="Halo [NAME]!"),
        PoEntry(msgid="Take [ITEM:1] to [NPC:2].", msgstr="Bawa ke sana."),  # Missing both tags!
    ]

    issues = ControlTagSanitizer.lint_po_catalog(po)
    assert len(issues) == 1
    assert issues[0]["entry_index"] == 1
    assert "ITEM:1" in issues[0]["missing_tags"]
    assert "NPC:2" in issues[0]["missing_tags"]
