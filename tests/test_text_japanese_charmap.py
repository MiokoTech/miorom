"""
Unit tests for JapaneseCharMapMiner and Japanese Relative Search Engine.
"""

import pytest
import struct

from miorom.text.japanese_charmap import (
    JapaneseCharMapMiner,
    JapaneseMiningCluster,
    JapaneseWordMatch,
    HIRAGANA_FULL,
    KATAKANA_FULL,
)
from miorom.script.dialogue_dissector import DialogueDissector


def test_search_kana_word_1byte():
    """Test 1-byte relative search for Hiragana and Katakana words."""
    # Test word: "たたかう"
    # Indices in HIRAGANA_FULL:
    # 'た': 15, 'た': 15, 'か': 5, 'う': 2
    base_delta = 0x40
    encoded = bytes([
        (base_delta + 15) & 0xFF,
        (base_delta + 15) & 0xFF,
        (base_delta + 5) & 0xFF,
        (base_delta + 2) & 0xFF,
    ])

    rom_buffer = b"\x00" * 100 + encoded + b"\xFF" * 50
    matches = JapaneseCharMapMiner.search_kana_word(
        rom_buffer, "たたかう", ordering="hiragana_gojuon", mode="1byte"
    )

    assert len(matches) == 1
    m = matches[0]
    assert m.word == "たたかう"
    assert m.offset == 100
    assert m.base_delta == base_delta
    assert m.matched_bytes == encoded
    assert m.mode == "1byte"
    assert m.offset_hex == "0x00000064"


def test_search_kana_word_katakana():
    """Test 1-byte search for Katakana word 'アイテム'."""
    # 'ア': 0, 'イ': 1, 'テ': 18, 'ム': 32
    base_delta = 0x80
    encoded = bytes([
        (base_delta + 0) & 0xFF,
        (base_delta + 1) & 0xFF,
        (base_delta + 18) & 0xFF,
        (base_delta + 32) & 0xFF,
    ])

    rom_buffer = b"\x12\x34" * 20 + encoded + b"\x56\x78" * 20
    matches = JapaneseCharMapMiner.search_kana_word(
        rom_buffer, "アイテム", ordering="katakana_gojuon", mode="1byte"
    )

    assert len(matches) == 1
    assert matches[0].offset == 40
    assert matches[0].base_delta == base_delta


def test_search_kana_word_2byte():
    """Test 2-byte 16-bit word aligned relative search (big and little endian)."""
    base_delta_be = 0x1000
    # "まほう": 'ま': 30, 'ほ': 29, 'う': 2
    words_be = [
        (base_delta_be + 30) & 0xFFFF,
        (base_delta_be + 29) & 0xFFFF,
        (base_delta_be + 2) & 0xFFFF,
    ]
    raw_be = struct.pack(">3H", *words_be)
    rom_be = b"\x00" * 32 + raw_be + b"\x00" * 32

    matches_be = JapaneseCharMapMiner.search_kana_word(
        rom_be, "まほう", ordering="hiragana_gojuon", mode="2byte_be"
    )
    assert len(matches_be) == 1
    assert matches_be[0].offset == 32
    assert matches_be[0].base_delta == 0x1000

    base_delta_le = 0x2000
    raw_le = struct.pack("<3H", *words_be)
    # Replace base delta
    words_le = [
        (base_delta_le + 30) & 0xFFFF,
        (base_delta_le + 29) & 0xFFFF,
        (base_delta_le + 2) & 0xFFFF,
    ]
    raw_le = struct.pack("<3H", *words_le)
    rom_le = b"\x00" * 16 + raw_le + b"\x00" * 16

    matches_le = JapaneseCharMapMiner.search_kana_word(
        rom_le, "まほう", ordering="hiragana_gojuon", mode="2byte_le"
    )
    assert len(matches_le) == 1
    assert matches_le[0].offset == 16
    assert matches_le[0].base_delta == 0x2000


def test_mine_charmap_multi_word_consensus():
    """Test discovering a character table using multi-word consensus and rejecting false positives."""
    h_base = 0x30
    k_base = 0x90

    def encode_h(text: str) -> bytes:
        return bytes([(h_base + HIRAGANA_FULL.index(c)) & 0xFF for c in text])

    def encode_k(text: str) -> bytes:
        return bytes([(k_base + KATAKANA_FULL.index(c)) & 0xFF for c in text])

    # Construct a simulated RPG menu bank
    rom = bytearray(b"\xAA" * 2048)

    # Insert "たたかう", "まほう", "にげる" at base 0x30
    rom[0x100 : 0x104] = encode_h("たたかう")
    rom[0x110 : 0x113] = encode_h("まほう")
    rom[0x120 : 0x123] = encode_h("にげる")

    # Insert "アイテム" at base 0x90
    rom[0x130 : 0x134] = encode_k("アイテム")

    # Add random noise that matches only 1 word at a different base delta
    noise_word = encode_h("たたかう")  # same deltas, but we alter offset
    rom[0x500 : 0x504] = bytes([(0x77 + HIRAGANA_FULL.index(c)) & 0xFF for c in "たたかう"])

    clusters = JapaneseCharMapMiner.mine_charmap(
        bytes(rom),
        dictionary=["たたかう", "まほう", "にげる", "アイテム", "そうび"],
        min_consensus=2,
    )

    assert len(clusters) >= 1
    top_cluster = clusters[0]
    assert top_cluster.base_delta == 0x30
    assert top_cluster.ordering_name == "hiragana_gojuon"
    assert top_cluster.unique_word_count == 3  # たたかう, まほう, にげる
    assert top_cluster.confidence >= 0.98
    # Cross-alphabet correlation should have linked Katakana base
    assert top_cluster.katakana_base_delta == 0x90

    # The noise at 0x500 (only 1 word matching delta 0x77) should have been filtered out!
    assert not any(c.base_delta == 0x77 for c in clusters)


def test_cluster_to_tbl_and_charmap():
    """Test generating .tbl format and building CharMap from a discovered cluster."""
    h_base = 0x20
    k_base = 0x80

    cluster = JapaneseMiningCluster(
        base_delta=h_base,
        ordering_name="hiragana_gojuon",
        matches=[
            JapaneseWordMatch("たたかう", 0x100, b"", h_base, "hiragana_gojuon"),
            JapaneseWordMatch("まほう", 0x110, b"", h_base, "hiragana_gojuon"),
        ],
        confidence=0.95,
        min_offset=0x100,
        max_offset=0x110,
        katakana_base_delta=k_base,
    )

    tbl = cluster.to_tbl(include_katakana=True, include_latin=True, include_digits=True)
    assert "20=あ" in tbl
    assert "21=い" in tbl
    assert "80=ア" in tbl
    assert "81=イ" in tbl

    cm = cluster.build_charmap(include_katakana=True)
    assert cm.char_to_byte["あ"] == b"\x20"
    assert cm.char_to_byte["ア"] == b"\x80"

    # Test decoding encoded strings
    def encode_h(text: str) -> bytes:
        return bytes([(h_base + HIRAGANA_FULL.index(c)) & 0xFF for c in text])

    test_bytes = encode_h("たたかう")
    assert cm.decode(test_bytes) == "たたかう"


def test_decode_preview():
    """Test preview decoding around a cluster offset."""
    h_base = 0x20
    cluster = JapaneseMiningCluster(
        base_delta=h_base,
        ordering_name="hiragana_gojuon",
        matches=[
            JapaneseWordMatch("たたかう", 0x10, b"", h_base, "hiragana_gojuon"),
            JapaneseWordMatch("まほう", 0x20, b"", h_base, "hiragana_gojuon"),
        ],
        confidence=0.95,
        min_offset=0x10,
        max_offset=0x20,
    )

    def encode_h(text: str) -> bytes:
        return bytes([(h_base + HIRAGANA_FULL.index(c)) & 0xFF for c in text])

    buffer = bytearray(b"\x00" * 128)
    buffer[0x10 : 0x14] = encode_h("たたかう")
    buffer[0x14] = 0x00
    buffer[0x20 : 0x23] = encode_h("まほう")

    preview = cluster.decode_preview(bytes(buffer), offset=0x10, length=20)
    assert "たたかう" in preview


def test_auto_discover_and_build_end_to_end():
    """Test one-shot automatic discovery and building of CharMap on binary ROM data."""
    h_base = 0x25
    k_base = 0x75

    def encode_h(text: str) -> bytes:
        return bytes([(h_base + HIRAGANA_FULL.index(c)) & 0xFF for c in text])

    def encode_k(text: str) -> bytes:
        return bytes([(k_base + KATAKANA_FULL.index(c)) & 0xFF for c in text])

    data = bytearray(b"\x00" * 1024)
    data[0x50 : 0x54] = encode_h("たたかう")
    data[0x60 : 0x63] = encode_h("まほう")
    data[0x70 : 0x74] = encode_k("アイテム")

    cluster = JapaneseCharMapMiner.auto_discover_and_build(bytes(data))
    assert cluster is not None
    assert cluster.base_delta == h_base
    assert cluster.charmap is not None

    decoded = cluster.charmap.decode(data[0x50 : 0x54])
    assert decoded == "たたかう"


def test_dialogue_dissector_integration():
    """Test full integration: JapaneseCharMapMiner auto-discovery with DialogueDissector extraction."""
    h_base = 0x30

    def encode_h(text: str) -> bytes:
        return bytes([(h_base + HIRAGANA_FULL.index(c)) & 0xFF for c in text])

    rom = bytearray(b"\x00" * 1024)

    # String payloads
    str1 = encode_h("たたかう") + b"\x00"  # at 0x100
    str2 = encode_h("まほう") + b"\x00"    # at 0x108
    str3 = encode_h("にげる") + b"\x00"    # at 0x110

    rom[0x100 : 0x100 + len(str1)] = str1
    rom[0x108 : 0x108 + len(str2)] = str2
    rom[0x110 : 0x110 + len(str3)] = str3

    # Pointer table at 0x20
    rom[0x20:0x22] = (0x0100).to_bytes(2, "little")
    rom[0x22:0x24] = (0x0108).to_bytes(2, "little")
    rom[0x24:0x26] = (0x0110).to_bytes(2, "little")

    # Step 1: Auto-discover Japanese CharMap
    cluster = JapaneseCharMapMiner.auto_discover_and_build(bytes(rom))
    assert cluster is not None
    assert cluster.base_delta == h_base

    # Step 2: Use discovered CharMap in DialogueDissector
    block = DialogueDissector.extract_from_table(
        bytes(rom),
        table_offset=0x20,
        pointer_count=3,
        pointer_size=2,
        endian="<",
        charmap=cluster.charmap,
        terminator=b"\x00",
    )

    assert len(block.entries) == 3
    assert block.entries[0].text == "たたかう"
    assert block.entries[1].text == "まほう"
    assert block.entries[2].text == "にげる"

    # Step 3: Verify PO catalog export
    po_text = block.to_po()
    assert 'msgid "たたかう"' in po_text
    assert 'msgid "まほう"' in po_text
    assert 'msgid "にげる"' in po_text
