import pytest
from miorom.text.charmap import CharMap
from miorom.text.dte import DteCodec, DteEntry, DteOptimizer, DteStats


def test_dte_ngram_analysis():
    corpus = [
        "The quick brown fox jumps over the lazy dog.",
        "The fox was very quick and the dog was very lazy.",
        "There were many foxes in the forest.",
    ]
    ngrams = DteOptimizer.analyze_ngrams(corpus, min_len=2, max_len=4)
    assert "th" in ngrams or "the" in ngrams or "the " in ngrams
    assert ngrams.get("the ", 0) >= 2


def test_dte_build_dictionary_and_stats():
    corpus = (
        "The hero arrived in the castle. The hero spoke with the king. "
        "The king gave the hero a magical sword. The hero left the castle."
    )
    stats = DteOptimizer.build_dictionary(
        corpus=corpus,
        num_slots=8,
        min_len=2,
        max_len=5,
        start_code=0x80,
    )

    assert isinstance(stats, DteStats)
    assert len(stats.dictionary) <= 8
    assert stats.uncompressed_bytes > stats.compressed_bytes
    assert stats.bytes_saved > 0
    assert stats.compression_ratio < 100.0

    # Ensure all assigned codes are in 0x80..0x87
    for code, text in stats.dictionary.items():
        assert 0x80 <= code < 0x88
        assert len(text) >= 2

    # Check entries structure
    for entry in stats.entries:
        assert isinstance(entry, DteEntry)
        assert entry.hex_code == f"{entry.code:02X}"
        assert entry.bytes_saved > 0


def test_dte_tbl_export_and_import():
    dictionary = {
        0x80: "the ",
        0x81: "hero",
        0x82: "in",
    }
    tbl_str = DteOptimizer.to_tbl(dictionary)
    assert "80=the " in tbl_str
    assert "81=hero" in tbl_str
    assert "82=in" in tbl_str

    imported_dict = DteOptimizer.from_tbl(tbl_str)
    assert imported_dict == dictionary


def test_dte_codec_encode_decode():
    dictionary = {
        0x80: "the ",
        0x81: "ing",
        0x82: "hero",
    }
    text = "the hero is walking"

    encoded = DteCodec.encode(text, dictionary)
    assert 0x80 in encoded
    assert 0x82 in encoded

    decoded = DteCodec.decode(encoded, dictionary)
    assert decoded == text


def test_dte_codec_with_charmap():
    dictionary = {
        0x80: "th",
        0x81: "er",
    }
    # Custom game charmap where 'A' is 0x01, 'B' is 0x02, etc.
    custom_map = {
        b"\x01": "A",
        b"\x02": "B",
        b"\x03": "e",
        b"\x04": "r",
        b"\x05": "o",
    }
    charmap = CharMap(custom_map)

    text = "ther"
    encoded = DteCodec.encode(text, dictionary, charmap=charmap)
    # "th" is 0x80, "er" is 0x81
    assert encoded == bytes([0x80, 0x81])
    decoded = DteCodec.decode(encoded, dictionary, charmap=charmap)
    assert decoded == text


def test_dte_reserved_codes():
    corpus = "Hello world! Hello friend! Hello enemy!"
    # Reserve 0x80, 0x81
    stats = DteOptimizer.build_dictionary(
        corpus=corpus,
        num_slots=4,
        start_code=0x80,
        reserved_codes={0x80, 0x81},
    )
    for code in stats.dictionary.keys():
        assert code not in {0x80, 0x81}
