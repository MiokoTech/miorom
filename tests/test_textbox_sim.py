import pytest
from miorom.text import TextboxConfig, AutoPaginator, TextboxSimulator, BitmapFont, Glyph


def test_auto_paginator_wrapping():
    cfg = TextboxConfig(
        box_width_pixels=100,
        max_lines_per_page=2,
        margin_left=0,
        margin_right=0,
    )
    paginator = AutoPaginator(cfg)

    # 8 pixels per char: 100 pixels fits ~12 chars per line
    text = "The quick brown fox jumps over the lazy dog."
    pages = paginator.paginate(text, font_or_measurer=lambda s: len(s) * 8)

    assert len(pages) >= 2
    for p in pages:
        assert p.line_count <= 2
        for line in p.lines:
            assert len(line) * 8 <= 100


def test_auto_paginator_format_with_tags():
    cfg = TextboxConfig(
        box_width_pixels=80,
        max_lines_per_page=2,
        margin_left=0,
        margin_right=0,
        page_break_tag="<PAGE>",
        line_break_tag="<LINE>",
    )
    paginator = AutoPaginator(cfg)

    text = "Line1 text Line2 text Line3 text Line4 text"
    formatted = paginator.format_with_tags(text, font_or_measurer=lambda s: len(s) * 8)

    assert "<LINE>" in formatted
    assert "<PAGE>" in formatted


def test_textbox_simulator_render_image():
    cfg = TextboxConfig(box_width_pixels=120, box_height_pixels=40, max_lines_per_page=2)
    simulator = TextboxSimulator(cfg)

    pages = simulator.paginator.paginate("Hello World!")
    img = simulator.render_page(pages[0])

    assert img.size == (120, 40)
    assert img.mode == "RGBA"
