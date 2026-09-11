import pytest
from miorom.graphics.font_injector import FontGlyphInjector
from miorom.text.line_wrapper import VwfLineWrapper, TextBoxPage, LineWrapResult
from miorom.text.pixel_wrapper import FontMetrics


def test_vwf_line_wrapper_basic_measurement():
    wrapper = VwfLineWrapper()
    # Test char measurement
    assert wrapper.measure_char("i") == 4
    assert wrapper.measure_char("W") == 14
    assert wrapper.measure_char(" ") == 5

    # Test measurement ignoring control tags
    plain = "Hello Hero"
    tagged = "Hello [color:red]Hero[/color]"
    assert wrapper.measure_text(plain) == wrapper.measure_text(tagged)


def test_vwf_line_wrapper_custom_sources():
    # Width dict source
    custom_widths = {"A": 10, "B": 10, " ": 4}
    wrapper_dict = VwfLineWrapper(width_source=custom_widths, default_char_width=6)
    assert wrapper_dict.measure_char("A") == 10
    assert wrapper_dict.measure_char("C") == 6

    # Callable source
    wrapper_callable = VwfLineWrapper(width_source=lambda ch: 12 if ch.isupper() else 6)
    assert wrapper_callable.measure_char("A") == 12
    assert wrapper_callable.measure_char("a") == 6

    # FontMetrics instance
    metrics = FontMetrics(widths={"X": 20})
    wrapper_metrics = VwfLineWrapper(width_source=metrics)
    assert wrapper_metrics.measure_char("X") == 20

    # FontGlyphInjector instance
    injector = FontGlyphInjector()
    wrapper_injector = VwfLineWrapper(width_source=injector)
    assert wrapper_injector.measure_char("i") <= wrapper_injector.measure_char("W")

    # Binary table source (ASCII-offset table)
    bin_table = bytes([3, 4, 5, 6] + [8] * 90)
    wrapper_bin = VwfLineWrapper(width_source=bin_table)
    # ASCII 0x20 (' ') is offset 0
    assert wrapper_bin.measure_char("!") == 4


def test_vwf_line_wrapper_word_wrapping():
    wrapper = VwfLineWrapper()
    text = "The quick brown fox jumps over the lazy dog."

    # Wrap with narrow pixel width
    wrapped = wrapper.wrap(text, max_pixel_width=80)
    lines = wrapped.split("\n")
    assert len(lines) > 1
    for line in lines:
        assert wrapper.measure_text(line) <= 80


def test_vwf_line_wrapper_control_code_preservation():
    wrapper = VwfLineWrapper()
    text = "Welcome [name] to the grand [item:sword] castle of [location]!"
    wrapped = wrapper.wrap(text, max_pixel_width=100)
    assert "[name]" in wrapped
    assert "[item:sword]" in wrapped
    assert "[location]!" in wrapped


def test_vwf_line_wrapper_long_word_overflow_and_hyphenation():
    # Without hyphenation
    wrapper = VwfLineWrapper(hyphenate_overflow=False)
    long_word = "Supercalifragilisticexpialidocious"
    wrapped = wrapper.wrap(long_word, max_pixel_width=60)
    chunks = wrapped.split("\n")
    assert len(chunks) > 1
    for c in chunks:
        assert wrapper.measure_text(c) <= 60

    # With hyphenation
    wrapper_hyphen = VwfLineWrapper(hyphenate_overflow=True)
    wrapped_hyphen = wrapper_hyphen.wrap(long_word, max_pixel_width=60)
    hyphen_chunks = wrapped_hyphen.split("\n")
    assert len(hyphen_chunks) > 1
    assert any(c.endswith("-") for c in hyphen_chunks[:-1])


def test_vwf_line_wrapper_pagination():
    wrapper = VwfLineWrapper()
    text = "Line one.\nLine two.\nLine three.\nLine four.\nLine five."
    paginated = wrapper.paginate(text, max_pixel_width=200, max_lines_per_page=2, page_break="[page]\n")
    pages = paginated.split("[page]\n")
    assert len(pages) == 3
    assert pages[0] == "Line one.\nLine two."
    assert pages[1] == "Line three.\nLine four."
    assert pages[2] == "Line five."


def test_vwf_line_wrapper_analyze():
    wrapper = VwfLineWrapper()
    text = "Short text fitting into dialog box."
    result = wrapper.analyze(text, max_pixel_width=300, max_lines_per_page=3)
    assert isinstance(result, LineWrapResult)
    assert result.fits is True
    assert len(result.warnings) == 0
    assert len(result.pages) == 1
    assert isinstance(result.pages[0], TextBoxPage)

    # Multi-page overflow
    long_text = "\n".join([f"Line number {i} with some dialogue content." for i in range(10)])
    result_overflow = wrapper.analyze(long_text, max_pixel_width=200, max_lines_per_page=3)
    assert result_overflow.fits is False
    assert result_overflow.total_lines >= 10
    assert len(result_overflow.pages) >= 4
