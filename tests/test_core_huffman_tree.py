import pytest
from miorom.core.bitstream import BitReader, BitWriter
from miorom.core.huffman_tree import (
    HuffmanNode,
    build_huffman_tree,
    extract_code_lengths,
    generate_canonical_codes,
    CanonicalHuffmanTable,
)
from miorom.errors import ParseError


def test_tree_construction_and_lengths():
    freqs = {ord("A"): 10, ord("B"): 1, ord("C"): 2, ord("D"): 4}
    tree = build_huffman_tree(freqs)
    assert tree is not None

    lengths = extract_code_lengths(tree)
    assert ord("A") in lengths
    assert ord("B") in lengths
    # More frequent symbols must have shorter or equal bit-length
    assert lengths[ord("A")] <= lengths[ord("D")]
    assert lengths[ord("D")] <= lengths[ord("B")]


def test_canonical_codes_prefix_free():
    lengths = {1: 1, 2: 2, 3: 3, 4: 3}
    codes = generate_canonical_codes(lengths)

    # 1: length 1 -> code 0 (binary 0)
    # 2: length 2 -> code 2 (binary 10)
    # 3: length 3 -> code 6 (binary 110)
    # 4: length 3 -> code 7 (binary 111)
    assert codes[1] == (0, 1)
    assert codes[2] == (2, 2)
    assert codes[3] == (6, 3)
    assert codes[4] == (7, 3)

    # Verify prefix-free property
    bin_strings = {sym: f"{code:0{length}b}" for sym, (code, length) in codes.items()}
    for sym1, s1 in bin_strings.items():
        for sym2, s2 in bin_strings.items():
            if sym1 != sym2:
                assert not s2.startswith(s1)


def test_canonical_huffman_roundtrip():
    message = [ord(c) for c in "ABRACADABRA_SUPER_CALIFRAGILISTIC"]
    frequencies = {}
    for c in message:
        frequencies[c] = frequencies.get(c, 0) + 1

    table = CanonicalHuffmanTable.from_frequencies(frequencies)

    # Encode with BitWriter
    writer = BitWriter(bit_order="msb")
    table.encode(message, writer)
    raw_bits = writer.to_bytes()

    # Decode with BitReader
    reader = BitReader(raw_bits, bit_order="msb")
    decoded = table.decode(reader, count=len(message))
    assert decoded == message


def test_single_symbol():
    freqs = {42: 100}
    table = CanonicalHuffmanTable.from_frequencies(freqs)
    writer = BitWriter()
    table.encode([42, 42, 42], writer)
    reader = BitReader(writer.to_bytes())
    decoded = table.decode(reader, count=3)
    assert decoded == [42, 42, 42]


def test_invalid_symbol_and_eof():
    table = CanonicalHuffmanTable.from_lengths({1: 1, 2: 2})
    with pytest.raises(KeyError):
        table.encode_symbol(999)

    reader = BitReader(b"\x00")
    # Read past EOF
    with pytest.raises(EOFError):
        table.decode(reader, count=100)
