import mmap
import os
import struct
from contextlib import contextmanager
from io import BytesIO
from typing import Union, Optional, BinaryIO


class BinaryReader:
    """A fluent, endian-aware binary reader for ROM hacking and reverse engineering."""

    def __init__(self, stream: Union[bytes, bytearray, memoryview, BinaryIO], endian: str = ">"):
        """
        Initialize BinaryReader.
        endian: '>' for Big Endian, '<' for Little Endian.
        """
        if isinstance(stream, (bytes, bytearray)):
            self.stream = BytesIO(stream)
        elif isinstance(stream, memoryview):
            self.stream = BytesIO(bytes(stream))
        else:
            self.stream = stream
        self.endian = endian
        self._owned_file: Optional[BinaryIO] = None

    @classmethod
    def open_file(
        cls,
        path: Union[str, os.PathLike],
        endian: str = ">",
        use_mmap: Optional[bool] = None,
        mmap_min_size: int = 100 * 1024 * 1024,
    ) -> "BinaryReader":
        file_obj = open(path, "rb")
        try:
            file_obj.seek(0, os.SEEK_END)
            size = file_obj.tell()
            should_mmap = size >= mmap_min_size if use_mmap is None else use_mmap
            file_obj.seek(0)
            if should_mmap:
                mapped = mmap.mmap(file_obj.fileno(), 0, access=mmap.ACCESS_READ)
                reader = cls(mapped, endian=endian)
            else:
                reader = cls(file_obj, endian=endian)
        except Exception:
            file_obj.close()
            raise
        reader._owned_file = file_obj
        return reader

    def close(self) -> None:
        close_method = getattr(self.stream, "close", None)
        if close_method:
            close_method()
        if self._owned_file is not None:
            self._owned_file.close()
            self._owned_file = None

    def __enter__(self) -> "BinaryReader":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def set_endian(self, endian: str) -> "BinaryReader":
        self.endian = endian
        return self

    def tell(self) -> int:
        return self.stream.tell()

    def seek(self, offset: int, whence: int = 0) -> int:
        return self.stream.seek(offset, whence)

    @contextmanager
    def at(self, offset: int):
        """Temporarily seek to offset and return back to original position on exit."""
        saved = self.tell()
        self.seek(offset)
        try:
            yield self
        finally:
            self.seek(saved)

    def read_bytes(self, size: int) -> bytes:
        data = self.stream.read(size)
        if len(data) < size:
            raise EOFError(f"Requested {size} bytes, got {len(data)} at offset {self.tell()}")
        return data

    def _unpack(self, fmt: str, size: int):
        return struct.unpack(f"{self.endian}{fmt}", self.read_bytes(size))[0]

    def read_u8(self) -> int:
        return self.read_bytes(1)[0]

    def read_s8(self) -> int:
        return struct.unpack("b", self.read_bytes(1))[0]

    def read_u16(self) -> int:
        return self._unpack("H", 2)

    def read_s16(self) -> int:
        return self._unpack("h", 2)

    def read_u32(self) -> int:
        return self._unpack("I", 4)

    def read_s32(self) -> int:
        return self._unpack("i", 4)

    def read_u64(self) -> int:
        return self._unpack("Q", 8)

    def read_s64(self) -> int:
        return self._unpack("q", 8)

    def read_float(self) -> float:
        return self._unpack("f", 4)

    def read_double(self) -> float:
        return self._unpack("d", 8)

    def read_string(
        self,
        encoding: str = "utf-8",
        null_terminated: bool = True,
        length: Optional[int] = None
    ) -> str:
        """
        Read a string from stream.
        Supports 1-byte encodings (ascii, utf-8, shift_jis) and 2-byte encodings (utf-16-be, utf-16-le).
        """
        if length is not None:
            raw = self.read_bytes(length)
            if null_terminated:
                idx = raw.find(b"\x00")
                if idx != -1:
                    raw = raw[:idx]
            return raw.decode(encoding, errors="replace")

        if not null_terminated:
            return self.stream.read().decode(encoding, errors="replace")

        # Null-terminated variable length
        raw = bytearray()
        char_size = 2 if "utf-16" in encoding.lower() or "ucs-2" in encoding.lower() else 1
        term = b"\x00" * char_size

        while True:
            chunk = self.stream.read(char_size)
            if chunk == term:
                break
            if len(chunk) < char_size:
                raise EOFError(f"Requested {char_size} bytes, got {len(chunk)} at offset {self.tell()}")
            raw.extend(chunk)

        return raw.decode(encoding, errors="replace")


class BinaryWriter:
    """A fluent, endian-aware binary writer for building and repacking game ROMs and archives."""

    def __init__(self, stream: Optional[BinaryIO] = None, endian: str = ">"):
        if stream is None:
            self.stream = BytesIO()
        else:
            self.stream = stream
        self.endian = endian

    def set_endian(self, endian: str) -> "BinaryWriter":
        self.endian = endian
        return self

    def tell(self) -> int:
        return self.stream.tell()

    def seek(self, offset: int, whence: int = 0) -> int:
        return self.stream.seek(offset, whence)

    @contextmanager
    def at(self, offset: int):
        saved = self.tell()
        self.seek(offset)
        try:
            yield self
        finally:
            self.seek(saved)

    def write_bytes(self, data: Union[bytes, bytearray]) -> "BinaryWriter":
        self.stream.write(data)
        return self

    def _pack(self, fmt: str, val) -> "BinaryWriter":
        self.stream.write(struct.pack(f"{self.endian}{fmt}", val))
        return self

    def write_u8(self, val: int) -> "BinaryWriter":
        self.stream.write(bytes([val & 0xFF]))
        return self

    def write_s8(self, val: int) -> "BinaryWriter":
        return self._pack("b", val)

    def write_u16(self, val: int) -> "BinaryWriter":
        return self._pack("H", val)

    def write_s16(self, val: int) -> "BinaryWriter":
        return self._pack("h", val)

    def write_u32(self, val: int) -> "BinaryWriter":
        return self._pack("I", val)

    def write_s32(self, val: int) -> "BinaryWriter":
        return self._pack("i", val)

    def write_u64(self, val: int) -> "BinaryWriter":
        return self._pack("Q", val)

    def write_s64(self, val: int) -> "BinaryWriter":
        return self._pack("q", val)

    def write_float(self, val: float) -> "BinaryWriter":
        return self._pack("f", val)

    def write_double(self, val: float) -> "BinaryWriter":
        return self._pack("d", val)

    def write_string(
        self,
        text: str,
        encoding: str = "utf-8",
        null_terminated: bool = True
    ) -> "BinaryWriter":
        raw = text.encode(encoding, errors="replace")
        self.stream.write(raw)
        if null_terminated:
            term = b"\x00\x00" if "utf-16" in encoding.lower() or "ucs-2" in encoding.lower() else b"\x00"
            self.stream.write(term)
        return self

    def align(self, boundary: int = 4, pad_byte: int = 0) -> int:
        """Pad with pad_byte until current position is a multiple of boundary. Returns bytes added."""
        remainder = self.tell() % boundary
        if remainder != 0:
            pad_len = boundary - remainder
            self.stream.write(bytes([pad_byte]) * pad_len)
            return pad_len
        return 0

    def pad(self, length: int, pad_byte: int = 0) -> "BinaryWriter":
        self.stream.write(bytes([pad_byte]) * length)
        return self

    def to_bytes(self) -> bytes:
        if isinstance(self.stream, BytesIO):
            return self.stream.getvalue()
        saved = self.tell()
        self.seek(0)
        data = self.stream.read()
        self.seek(saved)
        return data
