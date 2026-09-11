import heapq
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from miorom.core.bitstream import BitReader, BitWriter
from miorom.errors import ParseError


class HuffmanNode:
    """Represents a node within a binary Huffman frequency tree."""

    def __init__(
        self,
        freq: int,
        symbol: Optional[int] = None,
        left: Optional["HuffmanNode"] = None,
        right: Optional["HuffmanNode"] = None,
        uid: int = 0,
    ):
        self.freq = freq
        self.symbol = symbol
        self.left = left
        self.right = right
        self.uid = uid

    @property
    def is_leaf(self) -> bool:
        return self.left is None and self.right is None

    def __lt__(self, other: "HuffmanNode") -> bool:
        if self.freq != other.freq:
            return self.freq < other.freq
        return self.uid < other.uid


def build_huffman_tree(frequencies: Mapping[int, int]) -> Optional[HuffmanNode]:
    """
    Constructs an optimal binary Huffman prefix tree from a symbol frequency table.
    Returns the root node of the tree.
    """
    if not frequencies:
        return None

    heap: List[HuffmanNode] = []
    uid = 0

    for symbol, freq in frequencies.items():
        if freq > 0:
            heapq.heappush(heap, HuffmanNode(freq=freq, symbol=symbol, uid=uid))
            uid += 1

    if not heap:
        return None

    if len(heap) == 1:
        single = heapq.heappop(heap)
        return HuffmanNode(freq=single.freq, left=single, uid=uid)

    while len(heap) > 1:
        left = heapq.heappop(heap)
        right = heapq.heappop(heap)
        parent = HuffmanNode(
            freq=left.freq + right.freq,
            left=left,
            right=right,
            uid=uid,
        )
        uid += 1
        heapq.heappush(heap, parent)

    return heap[0]


def extract_code_lengths(root: Optional[HuffmanNode]) -> Dict[int, int]:
    """Traverses a Huffman tree to compute the bit-length of each symbol code."""
    lengths: Dict[int, int] = {}
    if root is None:
        return lengths

    def _traverse(node: HuffmanNode, depth: int) -> None:
        if node.is_leaf:
            if node.symbol is not None:
                lengths[node.symbol] = max(1, depth)
            return
        if node.left is not None:
            _traverse(node.left, depth + 1)
        if node.right is not None:
            _traverse(node.right, depth + 1)

    _traverse(root, 0)
    return lengths


def generate_canonical_codes(lengths: Mapping[int, int]) -> Dict[int, Tuple[int, int]]:
    """
    Generates deterministic Canonical Huffman codes from symbol bit-lengths.
    Follows RFC 1951 / JPEG standard: symbols sorted by length ascending, then by symbol ascending.
    Returns a dictionary mapping symbol -> (bit_code, bit_length).
    """
    valid = [(sym, length) for sym, length in lengths.items() if length > 0]
    valid.sort(key=lambda x: (x[1], x[0]))

    codes: Dict[int, Tuple[int, int]] = {}
    if not valid:
        return codes

    current_code = 0
    current_length = valid[0][1]

    for sym, length in valid:
        if length > current_length:
            current_code <<= (length - current_length)
            current_length = length

        codes[sym] = (current_code, length)
        current_code += 1

    return codes


class CanonicalHuffmanTable:
    """
    Pure-Python Canonical Huffman encoder and decoder primitive.
    Encodes and decodes arbitrary symbols using BitReader and BitWriter.
    """

    def __init__(self, lengths: Mapping[int, int]):
        self.lengths = dict(lengths)
        self.symbol_to_code = generate_canonical_codes(self.lengths)
        self.code_to_symbol: Dict[Tuple[int, int], int] = {
            (code, length): sym for sym, (code, length) in self.symbol_to_code.items()
        }
        self.max_length = max(self.lengths.values()) if self.lengths else 0

    @classmethod
    def from_frequencies(cls, frequencies: Mapping[int, int]) -> "CanonicalHuffmanTable":
        """Builds an optimal canonical table from a frequency histogram."""
        tree = build_huffman_tree(frequencies)
        lengths = extract_code_lengths(tree)
        return cls(lengths)

    @classmethod
    def from_lengths(cls, lengths: Mapping[int, int]) -> "CanonicalHuffmanTable":
        """Instantiates a canonical table directly from a mapping of symbol bit-lengths."""
        return cls(lengths)

    def encode_symbol(self, symbol: int) -> Tuple[int, int]:
        """Returns the (bit_code, bit_length) pair for a given symbol."""
        if symbol not in self.symbol_to_code:
            raise KeyError(f"Symbol {symbol} not present in Huffman table")
        return self.symbol_to_code[symbol]

    def encode(self, symbols: Sequence[int], writer: BitWriter) -> None:
        """Encodes a sequence of symbols into a BitWriter."""
        for sym in symbols:
            code, length = self.encode_symbol(sym)
            writer.write_bits(code, length)

    def decode_symbol(self, reader: BitReader) -> int:
        """
        Reads bits one by one from BitReader until a valid canonical code is resolved.
        Returns the decoded symbol integer.
        """
        code = 0
        length = 0

        while length < self.max_length:
            if reader.is_eof:
                raise EOFError("Unexpected end of bitstream while decoding Huffman code")
            bit = reader.read_bit()
            code = (code << 1) | bit
            length += 1

            if (code, length) in self.code_to_symbol:
                return self.code_to_symbol[(code, length)]

        raise ParseError(f"Invalid Huffman bit sequence encountered (length {length})")

    def decode(self, reader: BitReader, count: int) -> List[int]:
        """Decodes count symbols from a BitReader."""
        decoded = []
        for _ in range(count):
            decoded.append(self.decode_symbol(reader))
        return decoded
