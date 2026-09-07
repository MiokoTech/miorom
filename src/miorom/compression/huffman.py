import heapq
import struct
from typing import Dict, List, Optional, Tuple


class _HuffmanNode:
    def __init__(self, freq: int, symbol: Optional[int] = None, left=None, right=None):
        self.freq = freq
        self.symbol = symbol  # None if internal node
        self.left = left
        self.right = right

    def __lt__(self, other: "_HuffmanNode") -> bool:
        return self.freq < other.freq

    @property
    def is_leaf(self) -> bool:
        return self.symbol is not None


class Huffman:
    """
    Nintendo BIOS Huffman compression codec (Formats 0x24 = 4-bit, 0x28 = 8-bit).
    Implements the standard Nintendo BIOS Huffman tree decoding & encoding.
    """

    @classmethod
    def decompress(cls, data: bytes) -> bytes:
        if len(data) < 5:
            raise ValueError("Data too short for Nintendo Huffman header.")

        type_byte = data[0]
        if type_byte not in (0x24, 0x28):
            raise ValueError(f"Invalid Huffman type byte: 0x{type_byte:02X} (expected 0x24 or 0x28)")

        bit_depth = 4 if type_byte == 0x24 else 8
        uncompressed_size = data[1] | (data[2] << 8) | (data[3] << 16)
        if uncompressed_size == 0 and len(data) >= 8:
            uncompressed_size = struct.unpack("<I", data[4:8])[0]
            tree_pos = 8
        else:
            tree_pos = 4

        tree_size_code = data[tree_pos]
        tree_bytes_len = (tree_size_code + 1) * 2
        tree_start = tree_pos + 1
        tree_end = tree_start + tree_bytes_len

        if tree_end > len(data):
            raise ValueError("Malformed Huffman tree: extends beyond input data.")

        tree_data = data[tree_start:tree_end]
        stream_pos = tree_end

        # Stream is often aligned to 4 bytes
        if stream_pos % 4 != 0 and stream_pos < len(data):
            # Check if padding bytes are 0
            pass

        output = bytearray()
        cur_node_idx = 0
        cur_word = 0
        bits_left = 0
        nibble_shift = 0
        current_byte_val = 0

        while len(output) < uncompressed_size:
            if bits_left == 0:
                if stream_pos + 4 <= len(data):
                    cur_word = struct.unpack("<I", data[stream_pos : stream_pos + 4])[0]
                    stream_pos += 4
                    bits_left = 32
                elif stream_pos < len(data):
                    remaining = data[stream_pos:]
                    cur_word = int.from_bytes(remaining.ljust(4, b"\x00"), "little")
                    stream_pos = len(data)
                    bits_left = 32
                else:
                    break

            # Read bit (MSB down to LSB)
            bit = (cur_word >> 31) & 1
            cur_word = (cur_word << 1) & 0xFFFFFFFF
            bits_left -= 1

            if cur_node_idx >= len(tree_data):
                raise ValueError("Huffman tree index out of range.")

            node_byte = tree_data[cur_node_idx]
            offset_val = node_byte & 0x3F
            child_base = (cur_node_idx & ~1) + (offset_val * 2) + 2

            if bit == 0:
                # Left child
                is_leaf = (node_byte & 0x40) != 0
                child_idx = child_base
            else:
                # Right child
                is_leaf = (node_byte & 0x80) != 0
                child_idx = child_base + 1

            if is_leaf:
                if child_idx >= len(tree_data):
                    raise ValueError("Huffman leaf index out of tree range.")
                symbol = tree_data[child_idx]
                cur_node_idx = 0  # reset to root

                if bit_depth == 8:
                    output.append(symbol)
                else:
                    symbol &= 0x0F
                    if nibble_shift == 0:
                        current_byte_val = symbol
                        nibble_shift = 4
                    else:
                        output.append(current_byte_val | (symbol << 4))
                        current_byte_val = 0
                        nibble_shift = 0
            else:
                cur_node_idx = child_idx

        return bytes(output)

    @classmethod
    def compress(cls, data: bytes, bit_depth: int = 8) -> bytes:
        """
        Compresses data using Nintendo Huffman 4-bit (0x24) or 8-bit (0x28).
        """
        if bit_depth not in (4, 8):
            raise ValueError("bit_depth must be 4 or 8")

        # Extract symbols
        symbols: List[int] = []
        if bit_depth == 8:
            symbols = list(data)
        else:
            for b in data:
                symbols.append(b & 0x0F)
                symbols.append((b >> 4) & 0x0F)

        if not symbols:
            header = bytes([0x20 | bit_depth, 0, 0, 0, 0, 0])
            return header

        # Count frequencies
        freq_map: Dict[int, int] = {}
        for s in symbols:
            freq_map[s] = freq_map.get(s, 0) + 1

        # Build Huffman tree
        heap: List[_HuffmanNode] = [
            _HuffmanNode(freq=f, symbol=s) for s, f in freq_map.items()
        ]
        heapq.heapify(heap)

        if len(heap) == 1:
            # Single symbol case: add a dummy node
            single = heapq.heappop(heap)
            heap.append(_HuffmanNode(freq=single.freq, left=single, right=_HuffmanNode(freq=0, symbol=(single.symbol + 1) % 256)))

        while len(heap) > 1:
            n1 = heapq.heappop(heap)
            n2 = heapq.heappop(heap)
            parent = _HuffmanNode(freq=n1.freq + n2.freq, left=n1, right=n2)
            heapq.heappush(heap, parent)

        root = heap[0]

        # Generate bit codes for symbols
        code_map: Dict[int, str] = {}

        def traverse(node: _HuffmanNode, code: str):
            if node.is_leaf:
                code_map[node.symbol] = code
                return
            if node.left:
                traverse(node.left, code + "0")
            if node.right:
                traverse(node.right, code + "1")

        traverse(root, "")

        # Serialize tree into Nintendo format
        # Flatten tree BFS/DFS:
        tree_bytes = bytearray()

        # Build serialized array
        # Layout: root is at index 0. Internal nodes and leaves are stored.
        # Let's allocate nodes:
        nodes_list = []
        queue = [root]
        while queue:
            curr = queue.pop(0)
            if not curr.is_leaf:
                nodes_list.append(curr)
                queue.append(curr.left)
                queue.append(curr.right)

        # Now assign positions in tree array
        # Each internal node takes 1 byte. Child pair takes 2 bytes (left at 2k, right at 2k+1)
        # Standard approach:
        tree_array: List[Optional[Tuple[bool, Any]]] = [None] * 512
        node_pos_map: Dict[int, int] = {}

        # Root is at pos 0
        tree_array[0] = (False, root)
        node_pos_map[id(root)] = 0
        allocated = 2  # next free pair is at 2, 3

        queue = [root]
        while queue:
            curr = queue.pop(0)
            c_pos = node_pos_map[id(curr)]

            left_is_leaf = curr.left.is_leaf
            right_is_leaf = curr.right.is_leaf

            child_base = allocated
            allocated += 2

            tree_array[child_base] = (left_is_leaf, curr.left.symbol if left_is_leaf else curr.left)
            tree_array[child_base + 1] = (right_is_leaf, curr.right.symbol if right_is_leaf else curr.right)

            if not left_is_leaf:
                node_pos_map[id(curr.left)] = child_base
                queue.append(curr.left)
            if not right_is_leaf:
                node_pos_map[id(curr.right)] = child_base + 1
                queue.append(curr.right)

            # Node byte calculation:
            # child_base = (c_pos & ~1) + (offset * 2) + 2
            # => offset = (child_base - (c_pos & ~1) - 2) // 2
            offset_val = (child_base - (c_pos & ~1) - 2) // 2
            if offset_val > 0x3F:
                raise ValueError("Huffman tree too deep for Nintendo format.")

            flag_byte = offset_val
            if left_is_leaf:
                flag_byte |= 0x40
            if right_is_leaf:
                flag_byte |= 0x80

            tree_array[c_pos] = (False, flag_byte)

        # Trim tree_array to actual size (must be even length)
        final_tree = bytearray()
        for i in range(allocated):
            entry = tree_array[i]
            if entry is None:
                final_tree.append(0)
            else:
                is_leaf, val = entry
                if isinstance(val, int):
                    final_tree.append(val & 0xFF)
                else:
                    final_tree.append(0)

        tree_size_code = (len(final_tree) // 2) - 1

        # Encode stream
        bitstream = []
        for s in symbols:
            bitstream.append(code_map[s])
        all_bits = "".join(bitstream)

        # Pack into 32-bit little-endian words
        # Bits in word are MSB to LSB
        stream_bytes = bytearray()
        for i in range(0, len(all_bits), 32):
            chunk = all_bits[i : i + 32]
            # pad to 32 bits with 0
            if len(chunk) < 32:
                chunk = chunk.ljust(32, "0")
            word_val = int(chunk, 2)
            stream_bytes.extend(struct.pack("<I", word_val))

        # Header
        magic = 0x24 if bit_depth == 4 else 0x28
        uncomp_len = len(data)
        header = bytearray([magic, uncomp_len & 0xFF, (uncomp_len >> 8) & 0xFF, (uncomp_len >> 16) & 0xFF])
        header.append(tree_size_code)
        header.extend(final_tree)

        # Align stream start if necessary
        return bytes(header + stream_bytes)
