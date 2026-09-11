"""
Unit tests for TextCompressionHunter, HuffmanTreeCandidate, and DteDictionaryCandidate.
"""

import pytest
import struct

from miorom.compression.text_compression_hunter import (
    TextCompressionHunter,
    HuffmanTreeCandidate,
    HuffmanNodeEntry,
    DteDictionaryCandidate,
)


def test_huffman_roundtrip_compress_and_decompress():
    """Test building an array-based Huffman tree, compressing strings, and decompressing them."""
    sample_corpus = [
        b"Hello world, this is a test of retro console text compression.\x00",
        b"Another dialogue string with repeating characters: eeeee aaaaa.\x00",
        b"Dragon Quest and Mother style array-based Huffman trees!\x00",
    ]

    tree_bytes, compressed_streams = TextCompressionHunter.compress_huffman(
        sample_corpus,
        entry_size=2,
        endian="<",
        msb_first=True,
    )

    assert len(tree_bytes) > 0
    assert len(compressed_streams) == len(sample_corpus)
    # Compressed streams should be non-empty and smaller than raw data
    total_raw = sum(len(s) for s in sample_corpus)
    total_comp = sum(len(s) for s in compressed_streams)
    assert total_comp < total_raw

    # Parse serialized tree
    node_count = len(tree_bytes) // 4
    nodes = TextCompressionHunter.parse_huffman_node_array(
        tree_bytes,
        offset=0,
        node_count=node_count,
        entry_size=2,
        endian="<",
    )
    assert nodes is not None
    assert len(nodes) == node_count

    candidate = HuffmanTreeCandidate(
        offset=0,
        node_count=node_count,
        entry_size=2,
        endian="<",
        leaf_symbols=[],
        confidence=0.99,
        nodes=nodes,
        root_index=0,
    )

    # Decompress each stream and verify exact match
    for idx, comp in enumerate(compressed_streams):
        decoded, bits_read = candidate.decompress_bitstream(
            comp,
            stream_offset=0,
            msb_first=True,
            terminators=(0x00,),
        )
        assert decoded == sample_corpus[idx]


def test_parse_huffman_node_array_validation():
    """Test validation heuristics: cycles, invalid child indices, and leaf symbol checks."""
    # Construct invalid tree with a cycle: node 0 -> node 1 -> node 0
    bad_data = bytearray(8)
    struct.pack_into("<H", bad_data, 0, 1)      # node 0 left = child 1
    struct.pack_into("<H", bad_data, 2, 0x8041) # node 0 right = leaf 'A'
    struct.pack_into("<H", bad_data, 4, 0)      # node 1 left = child 0 (CYCLE!)
    struct.pack_into("<H", bad_data, 6, 0x8042) # node 1 right = leaf 'B'

    assert TextCompressionHunter.parse_huffman_node_array(
        bytes(bad_data), offset=0, node_count=2, entry_size=2
    ) is None

    # Construct invalid tree with child index out of bounds
    out_of_bounds = bytearray(4)
    struct.pack_into("<H", out_of_bounds, 0, 99) # child 99 does not exist
    struct.pack_into("<H", out_of_bounds, 2, 0x8041)
    assert TextCompressionHunter.parse_huffman_node_array(
        bytes(out_of_bounds), offset=0, node_count=1, entry_size=2
    ) is None


def test_scan_huffman_trees_in_rom():
    """Test scanning and locating a Huffman tree embedded in a noisy ROM buffer."""
    # Build tree from a corpus
    corpus = [b"The hero entered the dark cavern to search for the golden treasure.\x00"]
    tree_bytes, _ = TextCompressionHunter.compress_huffman(
        corpus,
        entry_size=2,
        endian="<",
        msb_first=True,
    )

    node_count = len(tree_bytes) // 4

    # Place tree in ROM at offset 0x800 surrounded by noise
    rom = bytearray(b"\x55" * 4096)
    rom[0x800 : 0x800 + len(tree_bytes)] = tree_bytes

    trees = TextCompressionHunter.scan_huffman_trees(
        bytes(rom),
        min_nodes=node_count,
        max_nodes=node_count,
        step=4,
    )

    assert len(trees) >= 1
    top_tree = trees[0]
    assert top_tree.offset == 0x800
    assert top_tree.node_count == node_count
    assert top_tree.entry_size == 2
    assert top_tree.endian == "<"
    assert top_tree.confidence >= 0.80


def test_dte_table_scan_and_decompress():
    """Test scanning for a 128-entry DTE table and expanding tokens."""
    # Create realistic DTE table: 128 pairs of common English bigrams
    sample_pairs = [
        b"th", b"he", b"in", b"er", b"an", b"re", b"ed", b"on",
        b"es", b"st", b"en", b"at", b"to", b"nt", b"ha", b"nd",
        b"ou", b"ea", b"ng", b"as", b"or", b"ti", b"is", b"et",
        b"it", b"ar", b"te", b"se", b"hi", b"of", b"wa", b"de",
    ]
    # Pad up to 128 pairs
    while len(sample_pairs) < 128:
        sample_pairs.append(b"  ")

    dte_bytes = bytearray()
    for p in sample_pairs:
        dte_bytes.extend(p)

    assert len(dte_bytes) == 256  # 128 entries * 2 bytes

    # Embed in ROM buffer
    rom = bytearray(b"\x00" * 1024)
    rom[0x200 : 0x200 + len(dte_bytes)] = dte_bytes

    candidates = TextCompressionHunter.scan_dte_tables(
        bytes(rom),
        token_base=0x80,
        entry_count=128,
        step=2,
    )

    assert len(candidates) >= 1
    top = candidates[0]
    assert top.offset == 0x200
    assert top.token_base == 0x80
    assert top.entry_count == 128
    assert top.expansion_map[0x80] == b"th"
    assert top.expansion_map[0x81] == b"he"

    # Test decompressing text containing DTE tokens
    compressed_text = b"\x80e hero said \x81llo"  # \x80='th' -> "the", \x81='he' -> "hello"
    decompressed = top.decompress_text(compressed_text)
    assert decompressed == b"the hero said hello"
