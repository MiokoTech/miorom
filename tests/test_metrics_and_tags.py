import pytest
from miorom.text.metrics_measurer import (
    PixelTextMeasurer,
    WordWrapSplitter,
    DialoguePagePartitioner,
)
from miorom.text.tag_validator import (
    TagSyntaxValidator,
    TagValidationReport,
)


def test_pixel_text_measurer():
    widths = {ord("A"): 10, ord("B"): 10, ord("C"): 10}
    # "ABC" without tags = 30px
    assert PixelTextMeasurer.measure_string("ABC", glyph_widths=widths, default_width=8) == 30
    # "[COLOR:1]ABC[COLOR:0]" with tags should still be 30px (tags stripped)
    assert PixelTextMeasurer.measure_string("[COLOR:1]ABC[COLOR:0]", glyph_widths=widths) == 30


def test_word_wrap_splitter():
    # Each char is 10px, space is 5px.
    # Words: "AAA" (30px), "BBB" (30px), "CCC" (30px)
    # Line limit: 70px.
    # "AAA BBB" = 30 + 5 + 30 = 65px <= 70px.
    # "AAA BBB CCC" = 65 + 5 + 30 = 100px > 70px, so "CCC" wraps to next line.
    widths = {ord("A"): 10, ord("B"): 10, ord("C"): 10}
    text = "AAA BBB CCC"
    wrapped = WordWrapSplitter.wrap_by_pixels(
        text=text,
        max_px=70,
        glyph_widths=widths,
        default_width=10,
        space_width=5,
        line_break="\n",
    )
    lines = wrapped.split("\n")
    assert len(lines) == 2
    assert lines[0] == "AAA BBB"
    assert lines[1] == "CCC"


def test_dialogue_page_partitioner():
    text = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"
    pages = DialoguePagePartitioner.partition_pages(text, max_lines_per_page=2)
    assert len(pages) == 3
    assert pages[0] == ["Line 1", "Line 2"]
    assert pages[1] == ["Line 3", "Line 4"]
    assert pages[2] == ["Line 5"]

    page_str = DialoguePagePartitioner.partition_pages_text(text, max_lines_per_page=2, page_break="[PAGE]")
    assert page_str.count("[PAGE]") == 2


def test_tag_syntax_validator():
    # Valid syntax
    rep_ok = TagSyntaxValidator.validate("Halo [NAME], ambil [ITEM:1] sekarang!")
    assert rep_ok.is_valid
    assert len(rep_ok.syntax_errors) == 0

    # Broken bracket
    rep_bad = TagSyntaxValidator.validate("Halo [NAME, ambil [ITEM:1]")
    assert not rep_bad.is_valid
    assert len(rep_bad.syntax_errors) > 0

    # Pair validation: missing required variable
    orig = "Halo [NAME], terimalah [ITEM:99]."
    trans_missing = "Halo ksatria, terimalah hadiah ini."  # Missing both NAME and ITEM:99
    rep_pair = TagSyntaxValidator.validate_pair(orig, trans_missing)
    assert not rep_pair.is_valid
    assert "NAME" in rep_pair.missing_variables
    assert "ITEM:99" in rep_pair.missing_variables
