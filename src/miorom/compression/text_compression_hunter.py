"""
miorom.compression.text_compression_hunter
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Automated Retro Text Compression Scanner, Huffman Tree Reconstructor, and DTE Hunter.

Reverses proprietary text compression in classic retro games (Dragon Quest,
Mother/Earthbound, Final Fantasy, Pokemon, Shin Megami Tensei) by scanning ROM
dumps for array-based binary Huffman trees and DTE (Dual Tile Encoding) tables,
decompressing text streams, and generating optimal tree repacks for translations.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import heapq
import struct
from typing import Dict, List, Optional, Sequence, Set, Tuple, Union

from miorom.core.bitstream import BitReader, BitWriter
from miorom.errors import CompressionError, ParseError
from miorom.result import MioRomResult


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class HuffmanNodeEntry(MioRomResult):
    """
    A single node entry in an array-based retro console Huffman tree.
    """
    node_index: int
    left_val: int
    right_val: int
    left_is_leaf: bool
    right_is_leaf: bool
    left_symbol: Optional[int]
    right_symbol: Optional[int]


@dataclass
class HuffmanTreeCandidate(MioRomResult):
    """
    Candidate Huffman tree discovered in binary ROM data.
    """
    offset: int
    node_count: int
    entry_size: int  # 1 or 2 bytes per branch (2 or 4 bytes per node)
    endian: str  # '<' (little) or '>' (big)
    leaf_symbols: List[int]
    confidence: float
    nodes: List[HuffmanNodeEntry]
    root_index: int = 0

    @property
    def offset_hex(self) -> str:
        return f"0x{self.offset:08X}"

    @property
    def total_bytes(self) -> int:
        return self.node_count * (self.entry_size * 2)

    def decompress_bitstream(
        self,
        data: bytes,
        stream_offset: int,
        max_symbols: int = 512,
        msb_first: bool = True,
        terminators: Tuple[int, ...] = (0x00, 0xFF),
    ) -> Tuple[bytes, int]:
        """
        Decompresses a bitstream from stream_offset using this Huffman tree.

        Args:
            data: Binary ROM or payload buffer.
            stream_offset: Starting byte offset in data.
            max_symbols: Safety limit on decoded symbols.
            msb_first: If True, reads bits MSB-to-LSB (standard retro console order).
            terminators: Symbol values that terminate the string.

        Returns:
            (decoded_bytes, bits_consumed)
        """
        if stream_offset >= len(data):
            return b"", 0

        stream_slice = data[stream_offset:]
        reader = BitReader(stream_slice, bit_order="msb" if msb_first else "lsb")
        decoded = bytearray()
        cur_node_idx = self.root_index
        bits_read = 0

        while len(decoded) < max_symbols and not reader.is_eof:
            try:
                bit = reader.read_bit()
                bits_read += 1
            except (ParseError, EOFError):
                break

            if cur_node_idx < 0 or cur_node_idx >= len(self.nodes):
                break

            node = self.nodes[cur_node_idx]
            if bit == 0:
                is_leaf = node.left_is_leaf
                val = node.left_val
                symbol = node.left_symbol
            else:
                is_leaf = node.right_is_leaf
                val = node.right_val
                symbol = node.right_symbol

            if is_leaf:
                if symbol is not None:
                    decoded.append(symbol & 0xFF)
                    if symbol in terminators:
                        break
                cur_node_idx = self.root_index
            else:
                cur_node_idx = val

        return bytes(decoded), bits_read


@dataclass
class DteDictionaryCandidate(MioRomResult):
    """
    Discovered Dual Tile Encoding (DTE) or Multi-Tile (MTE) dictionary table.
    """
    offset: int
    token_base: int  # Starting byte token, typically 0x80
    entry_count: int  # Typically 128 (covering 0x80..0xFF)
    expansion_map: Dict[int, bytes]
    confidence: float

    @property
    def offset_hex(self) -> str:
        return f"0x{self.offset:08X}"

    def decompress_text(self, data: bytes) -> bytes:
        """
        Expands DTE tokens in data into raw decompressed bytes.
        """
        out = bytearray()
        for b in data:
            if b in self.expansion_map:
                out.extend(self.expansion_map[b])
            else:
                out.append(b)
        return bytes(out)


# ============================================================================
# Text Compression Hunter Engine
# ============================================================================

class TextCompressionHunter:
    """
    Automated Retro Text Compression Scanner, Huffman Tree Reconstructor, and DTE Hunter.
    """

    @classmethod
    def parse_huffman_node_array(
        cls,
        data: bytes,
        offset: int,
        node_count: int,
        entry_size: int = 2,
        endian: str = "<",
    ) -> Optional[List[HuffmanNodeEntry]]:
        """
        Attempts to parse node_count contiguous nodes starting at offset.
        Validates tree topology (DAG, reachability, leaf consistency).
        """
        node_size = entry_size * 2
        total_bytes = node_count * node_size
        if offset + total_bytes > len(data):
            return None

        leaf_mask = 0x8000 if entry_size == 2 else 0x80
        val_mask = 0x7FFF if entry_size == 2 else 0x7F
        fmt = f"{endian}{'H' if entry_size == 2 else 'B'}"

        nodes: List[HuffmanNodeEntry] = []
        for i in range(node_count):
            pos = offset + (i * node_size)
            left_raw = struct.unpack_from(fmt, data, pos)[0]
            right_raw = struct.unpack_from(fmt, data, pos + entry_size)[0]

            left_is_leaf = bool(left_raw & leaf_mask)
            right_is_leaf = bool(right_raw & leaf_mask)

            left_symbol = (left_raw & val_mask) if left_is_leaf else None
            right_symbol = (right_raw & val_mask) if right_is_leaf else None

            left_val = (left_raw & val_mask)
            right_val = (right_raw & val_mask)

            nodes.append(
                HuffmanNodeEntry(
                    node_index=i,
                    left_val=left_val,
                    right_val=right_val,
                    left_is_leaf=left_is_leaf,
                    right_is_leaf=right_is_leaf,
                    left_symbol=left_symbol,
                    right_symbol=right_symbol,
                )
            )

        # Validate tree topology from root index 0
        visited_nodes: Set[int] = set()
        leaf_symbols: List[int] = []

        def traverse(idx: int, depth: int) -> bool:
            if depth > node_count:
                # Cycle detected
                return False
            if idx < 0 or idx >= node_count:
                return False

            visited_nodes.add(idx)
            n = nodes[idx]

            # Traverse left branch
            if n.left_is_leaf:
                if n.left_symbol is not None:
                    leaf_symbols.append(n.left_symbol)
            else:
                # In standard retro trees, children are strictly non-cyclic
                if n.left_val in visited_nodes or not traverse(n.left_val, depth + 1):
                    return False

            # Traverse right branch
            if n.right_is_leaf:
                if n.right_symbol is not None:
                    leaf_symbols.append(n.right_symbol)
            else:
                if n.right_val in visited_nodes or not traverse(n.right_val, depth + 1):
                    return False

            return True

        if not traverse(0, 0):
            return None

        # Full binary tree invariant: leaves = nodes + 1
        internal_count = len(visited_nodes)
        if len(leaf_symbols) != internal_count + 1:
            return None

        # Leaf symbol sanity check: characters must have distinct symbols
        unique_leaves = len(set(leaf_symbols))
        if unique_leaves < max(4, int(len(leaf_symbols) * 0.40)):
            return None

        return nodes

    @classmethod
    def parse_huffman_tree_auto(
        cls,
        data: bytes,
        offset: int,
        entry_size: int = 2,
        endian: str = "<",
        min_nodes: int = 16,
        max_nodes: int = 256,
    ) -> Optional[List[HuffmanNodeEntry]]:
        """
        Dynamically traverses from root node 0 to discover the full extent of
        an array-based binary Huffman tree without prior knowledge of node count.
        """
        node_size = entry_size * 2
        leaf_mask = 0x8000 if entry_size == 2 else 0x80
        val_mask = 0x7FFF if entry_size == 2 else 0x7F
        fmt = f"{endian}{'H' if entry_size == 2 else 'B'}"

        from collections import deque
        queue = deque([0])
        visited: Set[int] = set()
        nodes_dict: Dict[int, HuffmanNodeEntry] = {}
        leaf_symbols: List[int] = []

        while queue:
            idx = queue.popleft()
            if idx in visited:
                return None
            visited.add(idx)

            if idx >= max_nodes:
                return None

            pos = offset + (idx * node_size)
            if pos + node_size > len(data):
                return None

            left_raw = struct.unpack_from(fmt, data, pos)[0]
            right_raw = struct.unpack_from(fmt, data, pos + entry_size)[0]

            left_is_leaf = bool(left_raw & leaf_mask)
            right_is_leaf = bool(right_raw & leaf_mask)

            left_symbol = (left_raw & val_mask) if left_is_leaf else None
            right_symbol = (right_raw & val_mask) if right_is_leaf else None

            left_val = left_raw & val_mask
            right_val = right_raw & val_mask

            nodes_dict[idx] = HuffmanNodeEntry(
                node_index=idx,
                left_val=left_val,
                right_val=right_val,
                left_is_leaf=left_is_leaf,
                right_is_leaf=right_is_leaf,
                left_symbol=left_symbol,
                right_symbol=right_symbol,
            )

            # Left child
            if left_is_leaf:
                if left_symbol is not None:
                    leaf_symbols.append(left_symbol)
            else:
                if left_val <= idx:  # Must be strictly forward-referenced in array
                    return None
                queue.append(left_val)

            # Right child
            if right_is_leaf:
                if right_symbol is not None:
                    leaf_symbols.append(right_symbol)
            else:
                if right_val <= idx:
                    return None
                queue.append(right_val)

        node_count = len(visited)
        if node_count < min_nodes or node_count > max_nodes:
            return None

        # Verify contiguous node indices
        if set(range(node_count)) != visited:
            return None

        # Binary tree invariant: leaves = nodes + 1
        if len(leaf_symbols) != node_count + 1:
            return None

        # Diversity check
        if len(set(leaf_symbols)) < max(4, int(len(leaf_symbols) * 0.40)):
            return None

        return [nodes_dict[i] for i in range(node_count)]

    @classmethod
    def scan_huffman_trees(
        cls,
        data: bytes,
        min_nodes: int = 16,
        max_nodes: int = 256,
        step: int = 4,
    ) -> List[HuffmanTreeCandidate]:
        """
        Scans a binary ROM buffer for array-based Huffman trees.

        Args:
            data: Binary ROM buffer.
            min_nodes: Minimum number of internal nodes in the tree.
            max_nodes: Maximum number of internal nodes to check.
            step: Offset stepping increment.
        """
        candidates: List[HuffmanTreeCandidate] = []
        data_len = len(data)

        for entry_size in (2, 1):
            for endian in ("<", ">"):
                node_size = entry_size * 2
                min_bytes = min_nodes * node_size

                pos = 0
                while pos <= data_len - min_bytes:
                    nodes = cls.parse_huffman_tree_auto(
                        data,
                        offset=pos,
                        entry_size=entry_size,
                        endian=endian,
                        min_nodes=min_nodes,
                        max_nodes=max_nodes,
                    )
                    if nodes is not None:
                        node_count = len(nodes)
                        leaves = [n.left_symbol for n in nodes if n.left_is_leaf and n.left_symbol is not None]
                        leaves += [n.right_symbol for n in nodes if n.right_is_leaf and n.right_symbol is not None]

                        unique_ratio = len(set(leaves)) / len(leaves)
                        conf = min(0.99, 0.70 + unique_ratio * 0.25)

                        candidates.append(
                            HuffmanTreeCandidate(
                                offset=pos,
                                node_count=node_count,
                                entry_size=entry_size,
                                endian=endian,
                                leaf_symbols=leaves,
                                confidence=round(conf, 4),
                                nodes=nodes,
                                root_index=0,
                            )
                        )
                        pos += node_count * node_size
                        continue

                    pos += step

        # Sort by confidence, then node count
        candidates.sort(key=lambda c: (c.confidence, c.node_count), reverse=True)
        return candidates

    @classmethod
    def scan_dte_tables(
        cls,
        data: bytes,
        token_base: int = 0x80,
        entry_count: int = 128,
        step: int = 2,
    ) -> List[DteDictionaryCandidate]:
        """
        Scans binary ROM buffer for 2-byte DTE bigram tables.

        Args:
            data: Binary ROM buffer.
            token_base: Base token byte (typically 0x80).
            entry_count: Number of DTE entries (typically 128, covering 0x80..0xFF).
            step: Stepping increment in bytes.
        """
        table_bytes = entry_count * 2
        data_len = len(data)
        candidates: List[DteDictionaryCandidate] = []

        if data_len < table_bytes:
            return []

        for pos in range(0, data_len - table_bytes + 1, step):
            slice_bytes = data[pos : pos + table_bytes]

            # Null or 0xFF padding guard
            if slice_bytes[0:2] in (b"\x00\x00", b"\xFF\xFF"):
                continue

            # Printable character pairs count
            printable_pairs = 0
            expansion_map: Dict[int, bytes] = {}

            for i in range(entry_count):
                b0 = slice_bytes[i * 2]
                b1 = slice_bytes[i * 2 + 1]

                # ASCII printable or Japanese kana range
                is_p0 = (0x20 <= b0 <= 0x7E) or (0x01 <= b0 <= 0x60) or (0xA1 <= b0 <= 0xDF)
                is_p1 = (0x20 <= b1 <= 0x7E) or (0x01 <= b1 <= 0x60) or (0xA1 <= b1 <= 0xDF)

                if is_p0 and is_p1:
                    printable_pairs += 1

                token = token_base + i
                expansion_map[token] = bytes([b0, b1])

            ratio = printable_pairs / entry_count
            # Realistic DTE tables have >= 70% printable pairs
            if ratio >= 0.70:
                non_dummy_pairs = [p for p in expansion_map.values() if p not in (b"  ", b"\x00\x00", b"\xFF\xFF")]
                unique_pairs = len(set(non_dummy_pairs))
                if unique_pairs >= 16:
                    conf = min(0.99, 0.70 + (ratio - 0.70) * 1.0)
                    candidates.append(
                        DteDictionaryCandidate(
                            offset=pos,
                            token_base=token_base,
                            entry_count=entry_count,
                            expansion_map=expansion_map,
                            confidence=round(conf, 4),
                        )
                    )

        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return candidates

    @classmethod
    def compress_huffman(
        cls,
        strings: Sequence[bytes],
        entry_size: int = 2,
        endian: str = "<",
        msb_first: bool = True,
    ) -> Tuple[bytes, List[bytes]]:
        """
        Builds an optimal array-based Huffman tree for the input text corpus,
        serializes the tree in retro console format, and compresses all strings.

        Args:
            strings: List of raw byte strings to compress.
            entry_size: Branch width (1 or 2 bytes).
            endian: '<' (little) or '>' (big).
            msb_first: If True, writes bitstream MSB to LSB.

        Returns:
            (serialized_tree_bytes, list_of_compressed_bitstreams)
        """
        if not strings:
            return b"", []

        # 1. Frequency analysis
        freqs: Counter[int] = Counter()
        for s in strings:
            freqs.update(s)

        if not freqs:
            return b"", [b"" for _ in strings]

        # 2. Build Huffman tree nodes via Priority Queue
        # Node representation: (freq, uid, symbol, left_node, right_node)
        heap: List[Tuple[int, int, Optional[int], Optional[tuple], Optional[tuple]]] = []
        uid = 0
        for symbol, freq in freqs.items():
            heapq.heappush(heap, (freq, uid, symbol, None, None))
            uid += 1

        if len(heap) == 1:
            single = heapq.heappop(heap)
            heapq.heappush(heap, (single[0], uid, None, single, None))
            uid += 1

        while len(heap) > 1:
            left = heapq.heappop(heap)
            right = heapq.heappop(heap)
            parent = (left[0] + right[0], uid, None, left, right)
            uid += 1
            heapq.heappush(heap, parent)

        root = heap[0]

        # 3. Extract prefix bit codes for each symbol
        code_map: Dict[int, List[int]] = {}

        def get_codes(node, prefix: List[int]) -> None:
            _, _, symbol, left_child, right_child = node
            if symbol is not None:
                code_map[symbol] = prefix
                return
            if left_child:
                get_codes(left_child, prefix + [0])
            if right_child:
                get_codes(right_child, prefix + [1])

        get_codes(root, [])

        # 4. Flatten tree into contiguous retro console node array
        # Root is node 0
        node_list: List[Tuple[int, int, bool, bool]] = []
        # Layout: assign sequential node indices using BFS
        from collections import deque
        queue = deque([root])
        internal_nodes: List[tuple] = []
        while queue:
            curr = queue.popleft()
            if curr[2] is None:  # Internal node
                internal_nodes.append(curr)
                if curr[3] is not None and curr[3][2] is None:
                    queue.append(curr[3])
                if curr[4] is not None and curr[4][2] is None:
                    queue.append(curr[4])

        node_index_map: Dict[int, int] = {node[1]: idx for idx, node in enumerate(internal_nodes)}

        leaf_mask = 0x8000 if entry_size == 2 else 0x80
        val_mask = 0x7FFF if entry_size == 2 else 0x7F
        fmt = f"{endian}{'H' if entry_size == 2 else 'B'}"

        tree_bytes = bytearray()
        for node in internal_nodes:
            _, _, _, left, right = node

            # Left child
            if left is not None and left[2] is not None:
                # Leaf
                left_val = (left[2] & val_mask) | leaf_mask
            elif left is not None:
                left_val = node_index_map[left[1]] & val_mask
            else:
                left_val = leaf_mask  # dummy leaf

            # Right child
            if right is not None and right[2] is not None:
                # Leaf
                right_val = (right[2] & val_mask) | leaf_mask
            elif right is not None:
                right_val = node_index_map[right[1]] & val_mask
            else:
                right_val = leaf_mask

            tree_bytes.extend(struct.pack(fmt, left_val))
            tree_bytes.extend(struct.pack(fmt, right_val))

        # 5. Compress each string into bitstream
        compressed_streams: List[bytes] = []
        for s in strings:
            writer = BitWriter(bit_order="msb" if msb_first else "lsb")
            for b in s:
                bits = code_map[b]
                for bit in bits:
                    writer.write_bit(bit)
            compressed_streams.append(writer.to_bytes())

        return bytes(tree_bytes), compressed_streams
