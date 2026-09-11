"""
Unit tests for Nintendo BMG and MSBT dialogue format containers.
"""

import pytest
from miorom.text.bmg import BMGFile, BMGMessage
from miorom.text.msbt import MSBTFile, MSBTEntry
from miorom.errors import ParseError


def test_bmg_roundtrip():
    m1 = BMGMessage(text="Hello, hero of Hyrule!", message_id=1001)
    m2 = BMGMessage(text="Be careful in the dungeon.", message_id=1002)

    bmg = BMGFile(messages=[m1, m2], encoding=2)
    raw = bmg.to_bytes()
    assert raw[:8] == b"MESGbmg1"

    reloaded = BMGFile.from_bytes(raw)
    assert len(reloaded.messages) == 2
    assert reloaded.messages[0].text == "Hello, hero of Hyrule!"
    assert reloaded.messages[0].message_id == 1001
    assert reloaded.messages[1].text == "Be careful in the dungeon."
    assert reloaded.messages[1].message_id == 1002


def test_bmg_invalid():
    with pytest.raises(ParseError):
        BMGFile.from_bytes(b"BAD_HEADER_DATA_12345678901234567890")


def test_msbt_roundtrip():
    e1 = MSBTEntry(label="TUTORIAL_01", text="Press A to jump.")
    e2 = MSBTEntry(label="TUTORIAL_02", text="Collect coins for extra lives!")

    msbt = MSBTFile(entries=[e1, e2], encoding="utf-16", endian="<")
    raw = msbt.to_bytes()
    assert raw[:8] == b"MsgStdBn"

    reloaded = MSBTFile.from_bytes(raw)
    assert len(reloaded.entries) == 2
    assert reloaded.get_text("TUTORIAL_01") == "Press A to jump."
    assert reloaded.get_text("TUTORIAL_02") == "Collect coins for extra lives!"


def test_msbt_invalid():
    with pytest.raises(ParseError):
        MSBTFile.from_bytes(b"INVALID_MSBT_STRING_123456789012")
