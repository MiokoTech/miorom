import pytest
from miorom.text import PoHandler, PoEntry


def test_po_handler_create_and_serialize():
    po = PoHandler()
    po.headers["Project-Id-Version"] = "MyGame v1.0"

    po.add_entry(
        msgid="Hello world!",
        msgstr="Halo dunia!",
        msgctxt="intro_scene",
        comment="Greeting at beginning",
        extracted_comment="Offset: 0x081234, MaxLen: 32",
        reference="script/intro.bin:14",
    )

    po_text = po.to_string()
    assert 'msgctxt "intro_scene"' in po_text
    assert 'msgid "Hello world!"' in po_text
    assert 'msgstr "Halo dunia!"' in po_text
    assert "# Greeting at beginning" in po_text
    assert "#. Offset: 0x081234, MaxLen: 32" in po_text
    assert "#: script/intro.bin:14" in po_text


def test_po_handler_roundtrip(tmp_path):
    sample_po = """msgid ""
msgstr ""
"Project-Id-Version: Test 1.0\\n"
"Content-Type: text/plain; charset=UTF-8\\n"

# Context note
#. Max: 64B
#: file.bin:100
msgctxt "menu_start"
msgid "Press START button"
msgstr "Tekan tombol START"

msgid "Multi\\nline\\nstring"
msgstr "String\\nmulti\\nbaris"
"""
    po = PoHandler.from_string(sample_po)
    assert len(po.entries) == 2

    e1 = po.get_entry("Press START button", msgctxt="menu_start")
    assert e1 is not None
    assert e1.msgstr == "Tekan tombol START"
    assert "Context note" in e1.comments
    assert "Max: 64B" in e1.extracted_comments

    e2 = po.get_entry("Multi\nline\nstring")
    assert e2 is not None
    assert e2.msgstr == "String\nmulti\nbaris"

    # Test dictionary export
    t_dict = po.to_translation_dict()
    assert t_dict["Press START button"] == "Tekan tombol START"

    ctx_dict = po.to_contextual_dict()
    assert ctx_dict[("menu_start", "Press START button")] == "Tekan tombol START"

    # Save to file and reload
    po_file = tmp_path / "test.po"
    po.save(str(po_file))

    reloaded = PoHandler.from_file(str(po_file))
    assert len(reloaded.entries) == 2
    assert reloaded.get_entry("Press START button", "menu_start").msgstr == "Tekan tombol START"
