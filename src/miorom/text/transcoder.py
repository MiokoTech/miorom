import re
from typing import Any, Dict, List, Optional, Tuple


class ByteTrieNode:
    """Trie node for greedy multi-byte to string matching."""
    __slots__ = ("children", "value")

    def __init__(self):
        self.children: Dict[int, ByteTrieNode] = {}
        self.value: Optional[str] = None


class CharTrieNode:
    """Trie node for greedy string to multi-byte matching."""
    __slots__ = ("children", "value")

    def __init__(self):
        self.children: Dict[str, CharTrieNode] = {}
        self.value: Optional[bytes] = None


class TrieTranscoder:
    """
    High-Performance Prefix-Tree (Trie) Multi-Byte Character Map and Transcoder.
    Supports variable-length multi-byte encodings, DTE/MTE digraphs, control tokens
    (e.g. [A], <WAIT>, [HERO]), and bidirectional greedy longest-prefix matching.
    """

    def __init__(self):
        self.byte_root = ByteTrieNode()
        self.char_root = CharTrieNode()
        self._entry_count = 0

    def add_mapping(self, byte_seq: bytes, text: str):
        """Register a bidirectional mapping between byte sequence and text string."""
        if not byte_seq or not text:
            return

        # Populate byte-to-text trie
        node = self.byte_root
        for b in byte_seq:
            if b not in node.children:
                node.children[b] = ByteTrieNode()
            node = node.children[b]
        node.value = text

        # Populate text-to-byte trie
        cnode = self.char_root
        for ch in text:
            if ch not in cnode.children:
                cnode.children[ch] = CharTrieNode()
            cnode = cnode.children[ch]
        cnode.value = byte_seq

        self._entry_count += 1

    def load_table(self, table_content: str):
        """
        Parse .tbl format string (lines with HEX=TEXT).
        Example:
            00=<END>
            0A=\n
            8140=　
            8260=Ａ
            88=[HERO]
        """
        lines = table_content.splitlines()
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith(";"):
                continue

            if "=" in line:
                parts = line.split("=", 1)
                hex_part = parts[0].strip().replace(" ", "")
                text_part = parts[1]

                # Convert escape sequences like \n, \r, \t
                text_part = (
                    text_part.replace("\\n", "\n")
                    .replace("\\r", "\r")
                    .replace("\\t", "\t")
                )

                try:
                    # Parse hex string
                    byte_seq = bytes.fromhex(hex_part)
                    self.add_mapping(byte_seq, text_part)
                except ValueError:
                    continue

    def load_table_file(self, filepath: str, encoding: str = "utf-8"):
        """Load .tbl character mapping file."""
        with open(filepath, "r", encoding=encoding, errors="replace") as f:
            self.load_table(f.read())

    @property
    def entry_count(self) -> int:
        return self._entry_count

    def decode(self, data: bytes, fallback_format: str = "[{:02X}]") -> str:
        """
        Decode raw byte stream into text using greedy longest-match prefix search.
        Unmapped bytes are formatted using fallback_format.
        """
        result = []
        pos = 0
        length = len(data)

        while pos < length:
            node = self.byte_root
            matched_len = 0
            matched_val = None

            cur_pos = pos
            while cur_pos < length:
                b = data[cur_pos]
                if b in node.children:
                    node = node.children[b]
                    cur_pos += 1
                    if node.value is not None:
                        matched_len = cur_pos - pos
                        matched_val = node.value
                else:
                    break

            if matched_val is not None:
                result.append(matched_val)
                pos += matched_len
            else:
                # Fallback: single unmapped byte
                b = data[pos]
                result.append(fallback_format.format(b))
                pos += 1

        return "".join(result)

    def encode(self, text: str, fallback_bytes: bytes = b"?") -> bytes:
        """
        Encode text string into byte stream using greedy longest-match prefix search.
        Unmapped characters are replaced with fallback_bytes.
        """
        result = bytearray()
        pos = 0
        length = len(text)

        while pos < length:
            node = self.char_root
            matched_len = 0
            matched_val = None

            cur_pos = pos
            while cur_pos < length:
                ch = text[cur_pos]
                if ch in node.children:
                    node = node.children[ch]
                    cur_pos += 1
                    if node.value is not None:
                        matched_len = cur_pos - pos
                        matched_val = node.value
                else:
                    break

            if matched_val is not None:
                result.extend(matched_val)
                pos += matched_len
            else:
                result.extend(fallback_bytes)
                pos += 1

        return bytes(result)
