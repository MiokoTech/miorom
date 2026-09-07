import pytest
from miorom.script.paging_weaver import SmartScriptPagingWeaver, PagingWeaveConfig
from miorom.text.paginator import PaginationConfig


def test_weave_dialogue_sequence():
    # Configure tiny page limits to force multiple pages:
    # 20 pixels max width, default 8px char width -> ~2 chars per line, 2 lines per page = ~4-5 chars per page!
    pag_cfg = PaginationConfig(
        max_width_px=30,
        max_lines_per_page=2,
        default_char_width_px=5,
        page_break_tag="[PAGE]",
    )
    weaver = SmartScriptPagingWeaver(pagination_config=pag_cfg)

    long_text = "Ini adalah cerita tentang seorang pahlawan besar di desa terpencil"
    seq = weaver.weave_dialogue_sequence(long_text, speaker=1)

    assert len(seq) > 1
    # Check that sequence starts with MESSAGE, followed by WAIT_BUTTON, CLEAR_BOX, MESSAGE...
    assert seq[0][0] == "MESSAGE"
    assert seq[0][1][0] == 1  # speaker
    assert seq[1][0] == "WAIT_BUTTON"
    assert seq[2][0] == "CLEAR_BOX"
    assert seq[3][0] == "MESSAGE"


def test_weave_text_script():
    pag_cfg = PaginationConfig(
        max_width_px=40,
        max_lines_per_page=2,
        default_char_width_px=5,
        page_break_tag="[PAGE]",
    )
    weaver = SmartScriptPagingWeaver(pagination_config=pag_cfg)

    script_src = """
    ENTRY:
        SET_FLAG 0x01
        MESSAGE 0x05, "Selamat datang di kerajaan yang sangat megah dan indah ini wahai petualang!"
        FADE_OUT
    """

    woven_script = weaver.weave_text_script(script_src)

    # Check that single MESSAGE expanded into multiple MESSAGE opcodes with WAIT and CLEAR
    assert woven_script.count("MESSAGE") > 1
    assert "WAIT_BUTTON" in woven_script
    assert "CLEAR_BOX" in woven_script
    assert "SET_FLAG 0x01" in woven_script
    assert "FADE_OUT" in woven_script
