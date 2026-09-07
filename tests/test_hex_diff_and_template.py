import pytest
from miorom.core import HexDiffHighlighter
from miorom.text import GameTextTemplate


def test_hex_diff_formatting():
    orig = b"\x00\x01\x02\x03\x04\x05"
    mod = b"\x00\xFF\x02\x03\x04\xEE"

    diff_str = HexDiffHighlighter.format_diff(orig, mod, use_color=False)
    assert "OFFSET" in diff_str
    assert "00000000 *" in diff_str
    assert "00 FF 02 03 04 EE" in diff_str


def test_hex_diff_empty():
    res = HexDiffHighlighter.format_diff(b"", b"")
    assert res == "No data to diff."


def test_game_text_template_render_and_extract():
    template_str = "Hello [HERO:{name}]! You have received {count} [ITEM:{item}]."
    tmpl = GameTextTemplate(template_str)

    assert tmpl.variables == ["name", "count", "item"]

    rendered = tmpl.render(name="Raguna", count=5, item="Turnip")
    assert rendered == "Hello [HERO:Raguna]! You have received 5 [ITEM:Turnip]."

    extracted = tmpl.extract(rendered)
    assert extracted is not None
    assert extracted["name"] == "Raguna"
    assert extracted["count"] == "5"
    assert extracted["item"] == "Turnip"

    # Non-matching text returns None
    assert tmpl.extract("Invalid message format") is None
