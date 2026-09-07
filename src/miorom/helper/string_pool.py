"""
miorom.helper.string_pool
~~~~~~~~~~~~~~~~~~~~~~~~~
Developer helper for building string pools and calculating pointer tables.
Simplifies the most common and error-prone task in translation repacking.
"""

import struct
from typing import Dict, Iterable, List, Optional, Tuple, Union


class StringPoolBuilder:
    """
    Constructs a contiguous string pool and calculates the corresponding pointer table.

    Example:
        pool = StringPoolBuilder(encoding="utf-16-be", endian=">", stride=4, deduplicate=True)
        for s in translated_dialogues:
            pool.add(s)

        table_bytes, pool_bytes = pool.build()
    """

    def __init__(
        self,
        encoding: str = "utf-16-be",
        endian: str = ">",
        stride: int = 4,
        base_offset: int = 0,
        align: int = 2,
        null_terminate: bool = True,
        deduplicate: bool = False,
        length_prefix: Optional[int] = None,
        prefix_offset: int = 0,
        pad_byte: bytes = b"\x00",
    ):
        self.encoding = encoding
        self.endian = endian
        self.stride = stride
        self.base_offset = base_offset + prefix_offset
        self.align = align
        self.null_terminate = null_terminate
        self.deduplicate = deduplicate
        self.length_prefix = length_prefix
        self.pad_byte = pad_byte

        self._strings: List[str] = []
        self._flags: List[Optional[int]] = []
        self._offsets: List[int] = []
        self._dedup_map: Dict[str, int] = {}
        self._pool_buffer = bytearray()

    def add(self, text: str, flag: Optional[int] = None, align: Optional[int] = None) -> int:
        """
        Add a string to the pool and compute its offset.
        Returns the 0-based index of the added string.

        Keyword Args:
            flag: Optional 32-bit integer flag associated with the pointer entry.
            align: Custom alignment boundary for this specific string (overrides default).
        """
        index = len(self._strings)
        self._strings.append(text)
        self._flags.append(flag)

        # If deduplication is enabled and we have already added this string, reuse offset
        if self.deduplicate and text in self._dedup_map:
            self._offsets.append(self._dedup_map[text])
            return index

        # Pad current pool buffer to alignment
        cur_align = align if align is not None else self.align
        if cur_align > 1 and len(self._pool_buffer) % cur_align != 0:
            pad_len = cur_align - (len(self._pool_buffer) % cur_align)
            self._pool_buffer.extend(self.pad_byte * pad_len)

        cur_offset = len(self._pool_buffer) + self.base_offset
        self._offsets.append(cur_offset)
        if self.deduplicate:
            self._dedup_map[text] = cur_offset

        # Encode text
        encoded = text.encode(self.encoding, errors="replace")

        # Optional length prefix
        if self.length_prefix == 1:
            self._pool_buffer.extend(struct.pack(f"{self.endian}B", min(255, len(encoded))))
        elif self.length_prefix == 2:
            self._pool_buffer.extend(struct.pack(f"{self.endian}H", min(0xFFFF, len(encoded))))
        elif self.length_prefix == 4:
            self._pool_buffer.extend(struct.pack(f"{self.endian}I", len(encoded)))

        self._pool_buffer.extend(encoded)

        if self.null_terminate:
            term = b"\x00\x00" if ("utf-16" in self.encoding.lower() or "ucs-2" in self.encoding.lower()) else b"\x00"
            self._pool_buffer.extend(term)

        return index

    def add_many(
        self,
        texts: Iterable[str],
        flags: Optional[Iterable[Optional[int]]] = None,
        align: Optional[int] = None,
    ) -> List[int]:
        """
        Add multiple strings at once and return their indices.
        """
        flag_list = list(flags) if flags is not None else [None] * len(list(texts)) if not isinstance(texts, list) else [None] * len(texts)
        return [self.add(t, f, align=align) for t, f in zip(texts, flag_list)]

    def get_offset(self, index: int) -> int:
        """Return the calculated offset for the string at index."""
        return self._offsets[index]

    @property
    def count(self) -> int:
        return len(self._strings)

    @property
    def pool_size(self) -> int:
        return len(self._pool_buffer)

    def build_pool(self, pad_to_size: Optional[int] = None) -> bytes:
        """
        Return the raw bytes of the encoded string pool.

        Keyword Args:
            pad_to_size: If specified, zero-pads the pool buffer up to this size.
        """
        data = bytearray(self._pool_buffer)
        if pad_to_size is not None and len(data) < pad_to_size:
            data.extend(self.pad_byte * (pad_to_size - len(data)))
        return bytes(data)

    def build_table(self, flags_stride: int = 0) -> bytes:
        """
        Build the pointer table bytes.
        If flags_stride is 4 (i.e. 8-byte entry = offset + flag), writes offset and flag.
        """
        out = bytearray()
        fmt_ptr = f"{self.endian}{'H' if self.stride == 2 else 'I'}"

        for i, off in enumerate(self._offsets):
            out.extend(struct.pack(fmt_ptr, off))
            if flags_stride > 0:
                flag_val = self._flags[i] if self._flags[i] is not None else 0
                out.extend(struct.pack(f"{self.endian}I", flag_val))

        return bytes(out)

    def build(self, flags_stride: int = 0, pad_to_size: Optional[int] = None) -> Tuple[bytes, bytes]:
        """Return (table_bytes, pool_bytes)."""
        return self.build_table(flags_stride=flags_stride), self.build_pool(pad_to_size=pad_to_size)

    def build_combined(
        self,
        padding_between: int = 0,
        flags_stride: int = 0,
        pad_to_size: Optional[int] = None,
    ) -> bytes:
        """Return table + padding + pool concatenated into a single bytes block."""
        tbl = self.build_table(flags_stride=flags_stride)
        pool = self.build_pool()
        pad = self.pad_byte * padding_between if padding_between > 0 else b""
        combined = tbl + pad + pool
        if pad_to_size is not None and len(combined) < pad_to_size:
            combined = combined + self.pad_byte * (pad_to_size - len(combined))
        return bytes(combined)
