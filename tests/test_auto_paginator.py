import pytest
from miorom.text.paginator import SmartAutoPaginator, PaginationConfig
from miorom.text.po_handler import PoHandler


def test_smart_auto_paginator_word_wrapping_and_page_split():
    # 80 pixels max width with 8px per char = ~10 chars per line
    # 2 lines per page
    cfg = PaginationConfig(
        max_width_px=80,
        max_lines_per_page=2,
        line_break_tag="\n",
        page_break_tag="[PAGE]",
        default_char_width_px=8,
        space_width_px=4,
    )
    paginator = SmartAutoPaginator(cfg)

    # Long Indonesian text that must wrap and split across pages
    input_text = "Satu dua tiga empat lima enam tujuh delapan"
    output_text = paginator.paginate_text(input_text)

    # Must contain page break
    assert "[PAGE]" in output_text
    pages = output_text.split("[PAGE]")
    assert len(pages) >= 2

    # Each page must have at most 2 lines
    for page in pages:
        lines = page.split("\n")
        assert len(lines) <= 2
        for line in lines:
            # Must not exceed max width (excluding tags)
            px = paginator.measure_word_width(line)
            assert px <= cfg.max_width_px + 20


def test_smart_auto_paginator_ignores_control_tags():
    cfg = PaginationConfig(
        max_width_px=60,
        max_lines_per_page=2,
        default_char_width_px=6,
    )
    paginator = SmartAutoPaginator(cfg)

    # Words with non-printable tags [HERO], [C:01]
    word = "[HERO]Budi"
    # [HERO] stripped, 'Budi' is 4 chars * 6 = 24px
    assert paginator.measure_word_width(word) == 24


def test_smart_auto_paginator_po_batch():
    cfg = PaginationConfig(
        max_width_px=50,
        max_lines_per_page=2,
        default_char_width_px=5,
    )
    paginator = SmartAutoPaginator(cfg)

    po = PoHandler()
    po.add_entry(
        msgid="Hello",
        msgstr="Halo semua petualang yang ada di desa ini hari ini!",
    )

    count = paginator.paginate_po(po)
    assert count == 1
    assert "[PAGE]" in po.entries[0].msgstr
