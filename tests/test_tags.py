from miorom.text.tags import TagManager
from miorom.text.line_wrapper import WordWrapper


def test_tag_manager():
    tm = TagManager({
        "[0xff20]": "<WARNA>",
        "[0x30e9]": "<PLAYER>"
    })

    raw = "Halo [0x30e9], ini [0xff20]pedang[0xff20]!\nBagus kan?"
    decoded = tm.decode_tags(raw, newline_tag="<ENTER>")
    assert decoded == "Halo <PLAYER>, ini <WARNA>pedang<WARNA>!<ENTER>Bagus kan?"

    encoded = tm.encode_tags(decoded, newline_tag="<ENTER>")
    assert encoded == raw

    # Tag validation test: <PLAYER>, <WARNA>, and <ENTER> are all missing
    valid, missing = tm.validate_tags(decoded, "Halo, pedang bagus!")
    assert not valid
    assert len(missing) == 3  # <PLAYER>, <WARNA>, and <ENTER> missing


def test_tag_manager_escaped_newline_handling():
    tm = TagManager()
    # By default, literal \n is preserved as \n and NOT converted to <ENTER>
    text_with_escaped = "Line 1\\nLine 2\nLine 3"
    decoded = tm.decode_tags(text_with_escaped, newline_tag="<ENTER>")
    assert decoded == "Line 1\\nLine 2<ENTER>Line 3"

    # When convert_escaped_newlines is True, both \n and \\n are converted
    decoded_converted = tm.decode_tags(text_with_escaped, newline_tag="<ENTER>", convert_escaped_newlines=True)
    assert decoded_converted == "Line 1<ENTER>Line 2<ENTER>Line 3"


def test_word_wrapper():
    ww = WordWrapper(max_chars_per_line=15, max_lines_per_box=2, newline_tag="<ENTER>")
    wrapped = ww.wrap_text("Halo nama saya Raguna dan ini ladangku.")
    assert "<ENTER>" in wrapped

    valid, warnings = ww.validate_textbox(wrapped)
    assert not valid  # Likely exceeds 2 lines
