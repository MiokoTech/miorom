import json
import struct
import pytest
from miorom.text.bilingual_bridge import (
    BilingualAssetBridge,
    BridgeImportReport,
)
from miorom.text.po_handler import PoHandler, PoEntry


def test_export_to_po_and_json():
    dialogues = [
        (0, "Hello [HERO]! Welcome to town."),
        (1, "Here is your [ITEM:01]."),
    ]

    po = BilingualAssetBridge.export_to_po(dialogues, domain="intro")
    assert len(po.entries) == 2
    assert po.entries[0].msgid == "Hello [HERO]! Welcome to town."
    assert po.entries[0].msgstr == ""
    assert "intro:0000" in po.entries[0].msgctxt

    records = [
        {"id": 1, "name": "Potion", "price": 50},
        {"id": 2, "name": "Elixir", "price": 500},
    ]
    json_str = BilingualAssetBridge.export_to_json(records)
    parsed = json.loads(json_str)
    assert len(parsed) == 2
    assert parsed[0]["name"] == "Potion"


def test_import_and_repack_table():
    # Table of 2 pointers at 0x00
    # Original strings at 0x20 and 0x30
    buf = bytearray(0x100)
    struct.pack_into("<I", buf, 0x00, 0x20)
    struct.pack_into("<I", buf, 0x04, 0x30)
    buf[0x20:0x26] = b"Hi!\x00"
    buf[0x30:0x36] = b"Bye!\x00"

    po = PoHandler()
    po.entries = [
        PoEntry(
            msgid="Hi [NAME]!",
            msgstr="Halo [ NAME ] yang pemberani!",  # Has space typo in tag
            msgctxt="dialogue:0000",
        ),
        PoEntry(
            msgid="Bye!",
            msgstr="Sampai jumpa lagi di lain waktu!",
            msgctxt="dialogue:0001",
        ),
    ]

    updated_buf, report = BilingualAssetBridge.import_and_repack_table(
        buffer=buf,
        po=po,
        table_offset=0x00,
        record_count=2,
        pointer_size=4,
        heap_start_offset=0x50,
        endian="<",
        sanitize_tags=True,
    )

    assert report.total_strings == 2
    assert report.translated_strings == 2
    assert report.heap_bytes_written > 0
    assert report.new_heap_end > 0x50

    # Read back updated pointers
    ptr0 = struct.unpack_from("<I", updated_buf, 0x00)[0]
    ptr1 = struct.unpack_from("<I", updated_buf, 0x04)[0]

    assert ptr0 == 0x50
    assert ptr1 > 0x50

    # Verify strings at pointers:
    # Tag [ NAME ] was sanitized to [NAME]
    str0 = updated_buf[ptr0 : updated_buf.find(b"\x00", ptr0)].decode("utf-8")
    str1 = updated_buf[ptr1 : updated_buf.find(b"\x00", ptr1)].decode("utf-8")

    assert str0 == "Halo [NAME] yang pemberani!"
    assert str1 == "Sampai jumpa lagi di lain waktu!"
