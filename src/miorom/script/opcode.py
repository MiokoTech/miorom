import struct
from typing import Any, Tuple, Optional, List


class OpcodeArg:
    def __init__(self, name: str, is_jump_target: bool = False):
        self.name = name
        self.is_jump_target = is_jump_target

    def unpack(self, data: bytes, offset: int, endian: str) -> Tuple[Any, int]:
        raise NotImplementedError

    def pack(self, value: Any, endian: str) -> bytes:
        raise NotImplementedError


class ArgU8(OpcodeArg):
    def unpack(self, data: bytes, offset: int, endian: str) -> Tuple[int, int]:
        return struct.unpack_from("B", data, offset)[0], 1

    def pack(self, value: Any, endian: str) -> bytes:
        return struct.pack("B", int(value))


class ArgU16(OpcodeArg):
    def unpack(self, data: bytes, offset: int, endian: str) -> Tuple[int, int]:
        return struct.unpack_from(f"{endian}H", data, offset)[0], 2

    def pack(self, value: Any, endian: str) -> bytes:
        return struct.pack(f"{endian}H", int(value))


class ArgU32(OpcodeArg):
    def unpack(self, data: bytes, offset: int, endian: str) -> Tuple[int, int]:
        return struct.unpack_from(f"{endian}I", data, offset)[0], 4

    def pack(self, value: Any, endian: str) -> bytes:
        return struct.pack(f"{endian}I", int(value))


class ArgString(OpcodeArg):
    def __init__(self, name: str, null_terminated: bool = True, encoding: str = "utf-8"):
        super().__init__(name=name)
        self.null_terminated = null_terminated
        self.encoding = encoding

    def unpack(self, data: bytes, offset: int, endian: str) -> Tuple[str, int]:
        if self.null_terminated:
            null_pos = data.find(b"\x00", offset)
            if null_pos == -1:
                null_pos = len(data)
            raw = data[offset:null_pos]
            consumed = (null_pos - offset) + (1 if null_pos < len(data) else 0)
            return raw.decode(self.encoding, errors="replace"), consumed
        else:
            return data[offset:].decode(self.encoding, errors="replace"), len(data) - offset

    def pack(self, value: Any, endian: str) -> bytes:
        text = str(value)
        raw = text.encode(self.encoding)
        if self.null_terminated:
            raw += b"\x00"
        return raw


class ArgBytes(OpcodeArg):
    def __init__(self, name: str, length: int):
        super().__init__(name=name)
        self.length = length

    def unpack(self, data: bytes, offset: int, endian: str) -> Tuple[bytes, int]:
        return data[offset:offset + self.length], self.length

    def pack(self, value: Any, endian: str) -> bytes:
        raw = bytes(value)
        return raw.ljust(self.length, b"\x00")[:self.length]


class OpcodeDef:
    def __init__(self, id: int, name: str, args: Optional[List[OpcodeArg]] = None, description: str = ""):
        self.id = id
        self.name = name
        self.args = args or []
        self.description = description
