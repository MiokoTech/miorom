import pytest
from miorom.text.dte_miner import DTEMiner, DTEToken
from miorom.text.charmap import CharMap


def test_dte_miner_basic():
    corpus = [
        "the quick brown fox jumps over the lazy dog",
        "the secret of the island is hidden in the dark cave",
        "the hero entered the dungeon and found the treasure",
    ]
    # "th" and "e " should be very common
    dte_dict = DTEMiner.mine_character_pairs(corpus, max_tokens=10, min_occurrences=3, token_start=0x80)
    assert len(dte_dict) > 0
    # Check that tokens are in byte format 0x80..
    assert b"\x80" in dte_dict
    assert "th" in dte_dict.values()

    # Compress
    sample = "the hero entered the cave"
    compressed = DTEMiner.compress_text(sample, dte_dict)
    assert len(compressed) < len(sample)

    # Decompress
    decompressed = DTEMiner.decompress_bytes(compressed, dte_dict)
    assert decompressed == sample


def test_dte_miner_with_charmap():
    base_map = {bytes([i]): chr(i) for i in range(32, 127)}
    charmap = CharMap(base_map)

    corpus = "hello world hello world hello there"
    dte_dict = DTEMiner.mine_character_pairs(corpus, max_tokens=5, min_occurrences=2, token_start=0xA0)

    dte_charmap = DTEMiner.create_dte_charmap(charmap, dte_dict)
    assert b"\xa0" in dte_charmap.byte_to_char

    sample = "hello world"
    compressed = DTEMiner.compress_text(sample, dte_dict, base_charmap=charmap)
    decompressed = DTEMiner.decompress_bytes(compressed, dte_dict, base_charmap=charmap)
    assert decompressed == sample


def test_dte_token_dataclass():
    token = DTEToken(token_byte=b"\x85", expansion="er", frequency=42)
    assert token.hex_str == "85"
    assert token.expansion == "er"
