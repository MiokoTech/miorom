import mmap
import os
import struct
from contextlib import contextmanager
from io import BytesIO
from typing import Any, BinaryIO, Optional, Tuple, Type, Union


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

    def skip(self, count: int) -> int:
        """Advance current position by count bytes."""
        return self.stream.seek(count, os.SEEK_CUR)

    @property
    def size(self) -> int:
        """Returns total size of the stream."""
        saved = self.tell()
        self.stream.seek(0, os.SEEK_END)
        total = self.stream.tell()
        self.stream.seek(saved)
        return total

    @property
    def remaining(self) -> int:
        """Returns number of unread bytes remaining in the stream."""
        return max(0, self.size - self.tell())

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

    def read_struct(self, struct_cls: Type[Any], endian: Optional[str] = None) -> Any:
        """
        Reads and unpacks a declarative BinaryStruct directly from the current stream position,
        advancing the stream offset by the struct's consumed bytes.
        """
        return struct_cls.from_stream(self, endian=endian)

    # ----------------------------------------------------------------------
    # Static zero-allocation unpacking helpers
    # ----------------------------------------------------------------------

    @staticmethod
    def unpack_u8(data: Union[bytes, bytearray, memoryview], offset: int = 0) -> int:
        """Unpack an unsigned 8-bit integer from buffer at offset."""
        return data[offset]

    @staticmethod
    def unpack_s8(data: Union[bytes, bytearray, memoryview], offset: int = 0) -> int:
        """Unpack a signed 8-bit integer from buffer at offset."""
        return struct.unpack_from("b", data, offset)[0]

    @staticmethod
    def unpack_u16(data: Union[bytes, bytearray, memoryview], offset: int = 0, endian: str = ">") -> int:
        """Unpack an unsigned 16-bit integer from buffer at offset."""
        return struct.unpack_from(f"{endian}H", data, offset)[0]

    @staticmethod
    def unpack_s16(data: Union[bytes, bytearray, memoryview], offset: int = 0, endian: str = ">") -> int:
        """Unpack a signed 16-bit integer from buffer at offset."""
        return struct.unpack_from(f"{endian}h", data, offset)[0]

    @staticmethod
    def unpack_u32(data: Union[bytes, bytearray, memoryview], offset: int = 0, endian: str = ">") -> int:
        """Unpack an unsigned 32-bit integer from buffer at offset."""
        return struct.unpack_from(f"{endian}I", data, offset)[0]

    @staticmethod
    def unpack_s32(data: Union[bytes, bytearray, memoryview], offset: int = 0, endian: str = ">") -> int:
        """Unpack a signed 32-bit integer from buffer at offset."""
        return struct.unpack_from(f"{endian}i", data, offset)[0]

    @staticmethod
    def unpack_u64(data: Union[bytes, bytearray, memoryview], offset: int = 0, endian: str = ">") -> int:
        """Unpack an unsigned 64-bit integer from buffer at offset."""
        return struct.unpack_from(f"{endian}Q", data, offset)[0]

    @staticmethod
    def unpack_s64(data: Union[bytes, bytearray, memoryview], offset: int = 0, endian: str = ">") -> int:
        """Unpack a signed 64-bit integer from buffer at offset."""
        return struct.unpack_from(f"{endian}q", data, offset)[0]

    @staticmethod
    def unpack_float(data: Union[bytes, bytearray, memoryview], offset: int = 0, endian: str = ">") -> float:
        """Unpack a 32-bit single-precision float from buffer at offset."""
        return struct.unpack_from(f"{endian}f", data, offset)[0]

    @staticmethod
    def unpack_double(data: Union[bytes, bytearray, memoryview], offset: int = 0, endian: str = ">") -> float:
        """Unpack a 64-bit double-precision float from buffer at offset."""
        return struct.unpack_from(f"{endian}d", data, offset)[0]

    @staticmethod
    def calcsize(fmt: str) -> int:
        """Calculate the size of struct format string."""
        return struct.calcsize(fmt)

    @staticmethod
    def unpack(fmt: str, data: Union[bytes, bytearray, memoryview]) -> Tuple[Any, ...]:
        """Unpack binary data according to format string."""
        return struct.unpack(fmt, data)

    @staticmethod
    def unpack_from(fmt: str, buffer: Union[bytes, bytearray, memoryview], offset: int = 0) -> Tuple[Any, ...]:
        """Unpack binary data from buffer at offset according to format string."""
        return struct.unpack_from(fmt, buffer, offset)


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

    @property
    def size(self) -> int:
        """Returns current total size of written bytes."""
        if isinstance(self.stream, BytesIO):
            return len(self.stream.getvalue())
        saved = self.tell()
        self.stream.seek(0, os.SEEK_END)
        total = self.stream.tell()
        self.stream.seek(saved)
        return total

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

    def write_struct(self, struct_inst: Any, endian: Optional[str] = None) -> "BinaryWriter":
        """
        Serializes and writes a declarative BinaryStruct instance directly into the stream.
        """
        struct_inst.to_stream(self, endian=endian)
        return self

    def to_bytes(self) -> bytes:
        if isinstance(self.stream, BytesIO):
            return self.stream.getvalue()
        saved = self.tell()
        self.seek(0)
        data = self.stream.read()
        self.seek(saved)
        return data

    # ----------------------------------------------------------------------
    # Static atomic packing helpers
    # ----------------------------------------------------------------------

    @staticmethod
    def pack_u8(val: int) -> bytes:
        """Pack an unsigned 8-bit integer into bytes."""
        return bytes([val & 0xFF])

    @staticmethod
    def pack_s8(val: int) -> bytes:
        """Pack a signed 8-bit integer into bytes."""
        return struct.pack("b", val)

    @staticmethod
    def pack_u16(val: int, endian: str = ">") -> bytes:
        """Pack an unsigned 16-bit integer into bytes."""
        return struct.pack(f"{endian}H", val)

    @staticmethod
    def pack_s16(val: int, endian: str = ">") -> bytes:
        """Pack a signed 16-bit integer into bytes."""
        return struct.pack(f"{endian}h", val)

    @staticmethod
    def pack_u32(val: int, endian: str = ">") -> bytes:
        """Pack an unsigned 32-bit integer into bytes."""
        return struct.pack(f"{endian}I", val)

    @staticmethod
    def pack_s32(val: int, endian: str = ">") -> bytes:
        """Pack a signed 32-bit integer into bytes."""
        return struct.pack(f"{endian}i", val)

    @staticmethod
    def pack_u64(val: int, endian: str = ">") -> bytes:
        """Pack an unsigned 64-bit integer into bytes."""
        return struct.pack(f"{endian}Q", val)

    @staticmethod
    def pack_s64(val: int, endian: str = ">") -> bytes:
        """Pack a signed 64-bit integer into bytes."""
        return struct.pack(f"{endian}q", val)

    @staticmethod
    def pack_float(val: float, endian: str = ">") -> bytes:
        """Pack a 32-bit single-precision float into bytes."""
        return struct.pack(f"{endian}f", val)

    @staticmethod
    def pack_double(val: float, endian: str = ">") -> bytes:
        """Pack a 64-bit double-precision float into bytes."""
        return struct.pack(f"{endian}d", val)

    # ----------------------------------------------------------------------
    # Static buffer in-place packing helpers (pack_into)
    # ----------------------------------------------------------------------

    @staticmethod
    def pack_into_u8(buf: Union[bytearray, memoryview], offset: int, val: int) -> None:
        """Pack an unsigned 8-bit integer into a mutable buffer at offset."""
        buf[offset] = val & 0xFF

    @staticmethod
    def pack_into_s8(buf: Union[bytearray, memoryview], offset: int, val: int) -> None:
        """Pack a signed 8-bit integer into a mutable buffer at offset."""
        struct.pack_into("b", buf, offset, val)

    @staticmethod
    def pack_into_u16(buf: Union[bytearray, memoryview], offset: int, val: int, endian: str = ">") -> None:
        """Pack an unsigned 16-bit integer into a mutable buffer at offset."""
        struct.pack_into(f"{endian}H", buf, offset, val)

    @staticmethod
    def pack_into_s16(buf: Union[bytearray, memoryview], offset: int, val: int, endian: str = ">") -> None:
        """Pack a signed 16-bit integer into a mutable buffer at offset."""
        struct.pack_into(f"{endian}h", buf, offset, val)

    @staticmethod
    def pack_into_u32(buf: Union[bytearray, memoryview], offset: int, val: int, endian: str = ">") -> None:
        """Pack an unsigned 32-bit integer into a mutable buffer at offset."""
        struct.pack_into(f"{endian}I", buf, offset, val)

    @staticmethod
    def pack_into_s32(buf: Union[bytearray, memoryview], offset: int, val: int, endian: str = ">") -> None:
        """Pack a signed 32-bit integer into a mutable buffer at offset."""
        struct.pack_into(f"{endian}i", buf, offset, val)

    @staticmethod
    def pack_into_u64(buf: Union[bytearray, memoryview], offset: int, val: int, endian: str = ">") -> None:
        """Pack an unsigned 64-bit integer into a mutable buffer at offset."""
        struct.pack_into(f"{endian}Q", buf, offset, val)

    @staticmethod
    def pack_into_s64(buf: Union[bytearray, memoryview], offset: int, val: int, endian: str = ">") -> None:
        """Pack a signed 64-bit integer into a mutable buffer at offset."""
        struct.pack_into(f"{endian}q", buf, offset, val)

    @staticmethod
    def pack(fmt: str, *values: Any) -> bytes:
        """Pack values into bytes according to format string."""
        return struct.pack(fmt, *values)

    @staticmethod
    def pack_into(fmt: str, buffer: Union[bytearray, memoryview], offset: int, *values: Any) -> None:
        """Pack values into mutable buffer at offset according to format string."""
        struct.pack_into(fmt, buffer, offset, *values)
