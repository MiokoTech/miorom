import struct
from typing import Any, Dict, List, Optional, Tuple, Type, Union


class SchemaField:
    """Base class for all declarative binary struct fields."""

    def __init__(self, default: Any = None, endian: Optional[str] = None):
        self.default = default
        self.endian = endian
        self.name = ""
        self.offset = 0

    def get_size(self, context: Any = None) -> int:
        raise NotImplementedError

    def unpack(self, data: bytes, offset: int, endian: str, context: Any = None) -> Tuple[Any, int]:
        raise NotImplementedError

    def pack(self, value: Any, endian: str, context: Any = None) -> bytes:
        raise NotImplementedError


class PrimitiveField(SchemaField):
    def __init__(self, format_char: str, size: int, default: Any = 0, endian: Optional[str] = None):
        super().__init__(default=default, endian=endian)
        self.format_char = format_char
        self._size = size

    def get_size(self, context: Any = None) -> int:
        return self._size

    def unpack(self, data: bytes, offset: int, endian: str, context: Any = None) -> Tuple[Any, int]:
        fmt = (self.endian or endian) + self.format_char
        val = struct.unpack_from(fmt, data, offset)[0]
        return val, self._size

    def pack(self, value: Any, endian: str, context: Any = None) -> bytes:
        fmt = (self.endian or endian) + self.format_char
        return struct.pack(fmt, value if value is not None else self.default)


class U8(PrimitiveField):
    def __init__(self, default: int = 0):
        super().__init__("B", 1, default=default)


class I8(PrimitiveField):
    def __init__(self, default: int = 0):
        super().__init__("b", 1, default=default)


class U16(PrimitiveField):
    def __init__(self, default: int = 0, endian: Optional[str] = None):
        super().__init__("H", 2, default=default, endian=endian)


class I16(PrimitiveField):
    def __init__(self, default: int = 0, endian: Optional[str] = None):
        super().__init__("h", 2, default=default, endian=endian)


class U32(PrimitiveField):
    def __init__(self, default: int = 0, endian: Optional[str] = None):
        super().__init__("I", 4, default=default, endian=endian)


class I32(PrimitiveField):
    def __init__(self, default: int = 0, endian: Optional[str] = None):
        super().__init__("i", 4, default=default, endian=endian)


class U64(PrimitiveField):
    def __init__(self, default: int = 0, endian: Optional[str] = None):
        super().__init__("Q", 8, default=default, endian=endian)


class Float32(PrimitiveField):
    def __init__(self, default: float = 0.0, endian: Optional[str] = None):
        super().__init__("f", 4, default=default, endian=endian)


class FixedString(SchemaField):
    def __init__(self, length: int, encoding: str = "ascii", pad: bytes = b"\x00", default: str = ""):
        super().__init__(default=default)
        self.length = length
        self.encoding = encoding
        self.pad = pad

    def get_size(self, context: Any = None) -> int:
        return self.length

    def unpack(self, data: bytes, offset: int, endian: str, context: Any = None) -> Tuple[str, int]:
        raw = data[offset:offset + self.length]
        stripped = raw.rstrip(self.pad)
        text = stripped.decode(self.encoding, errors="replace")
        return text, self.length

    def pack(self, value: Any, endian: str, context: Any = None) -> bytes:
        text = str(value if value is not None else self.default)
        raw = text.encode(self.encoding)
        if len(raw) < self.length:
            raw = raw.ljust(self.length, self.pad)
        else:
            raw = raw[:self.length]
        return raw


class RawBytes(SchemaField):
    def __init__(self, length: int, default: bytes = b""):
        super().__init__(default=default)
        self.length = length

    def get_size(self, context: Any = None) -> int:
        return self.length

    def unpack(self, data: bytes, offset: int, endian: str, context: Any = None) -> Tuple[bytes, int]:
        return data[offset:offset + self.length], self.length

    def pack(self, value: Any, endian: str, context: Any = None) -> bytes:
        val = bytes(value if value is not None else self.default)
        return val.ljust(self.length, b"\x00")[:self.length]


class SubStruct(SchemaField):
    """Encapsulates a nested BinaryStruct as a field."""

    def __init__(self, struct_cls: Type["BinaryStruct"]):
        super().__init__()
        self.struct_cls = struct_cls

    def get_size(self, context: Any = None) -> int:
        return self.struct_cls.sizeof(context)

    def unpack(self, data: bytes, offset: int, endian: str, context: Any = None) -> Tuple[Any, int]:
        inst = self.struct_cls.from_bytes(data, offset=offset, endian=endian)
        return inst, self.struct_cls.sizeof(inst)

    def pack(self, value: Any, endian: str, context: Any = None) -> bytes:
        if isinstance(value, BinaryStruct):
            return value.to_bytes(endian=endian)
        elif isinstance(value, dict):
            inst = self.struct_cls(**value)
            return inst.to_bytes(endian=endian)
        inst = self.struct_cls()
        return inst.to_bytes(endian=endian)


class Array(SchemaField):
    """Array of primitive fields or sub-structs."""

    def __init__(self, field_or_struct: Union[SchemaField, Type["BinaryStruct"]], count: Union[int, str]):
        super().__init__()
        self.item_type = field_or_struct
        self.count_param = count

    def _resolve_count(self, context: Any) -> int:
        if isinstance(self.count_param, int):
            return self.count_param
        elif isinstance(self.count_param, str) and context is not None:
            # Check context attributes or nested fields
            if hasattr(context, self.count_param):
                return getattr(context, self.count_param)
            # Check context sub-structs
            for f_val in context.__dict__.values():
                if hasattr(f_val, "_is_binary_struct") and hasattr(f_val, self.count_param):
                    return getattr(f_val, self.count_param)
        return 0

    def get_size(self, context: Any = None) -> int:
        cnt = self._resolve_count(context)
        if isinstance(self.item_type, SchemaField):
            return cnt * self.item_type.get_size(context)
        elif hasattr(self.item_type, "_is_binary_struct"):
            return cnt * self.item_type.sizeof(context)
        return 0

    def unpack(self, data: bytes, offset: int, endian: str, context: Any = None) -> Tuple[List[Any], int]:
        count = self._resolve_count(context)
        items = []
        curr_offset = offset

        for _ in range(count):
            if isinstance(self.item_type, SchemaField):
                val, consumed = self.item_type.unpack(data, curr_offset, endian, context)
            else:
                val = self.item_type.from_bytes(data, offset=curr_offset, endian=endian)
                consumed = self.item_type.sizeof(val)
            items.append(val)
            curr_offset += consumed

        return items, curr_offset - offset

    def pack(self, value: Any, endian: str, context: Any = None) -> bytes:
        items = list(value) if value is not None else []
        out = bytearray()
        for item in items:
            if isinstance(self.item_type, SchemaField):
                out.extend(self.item_type.pack(item, endian, context))
            elif hasattr(item, "_is_binary_struct"):
                out.extend(item.to_bytes(endian=endian))
            elif isinstance(item, dict) and hasattr(self.item_type, "_is_binary_struct"):
                inst = self.item_type(**item)
                out.extend(inst.to_bytes(endian=endian))
        return bytes(out)


class StructMeta(type):
    """Metaclass for collecting declared fields in order."""

    def __new__(mcs, name, bases, namespace):
        fields: Dict[str, SchemaField] = {}
        for base in bases:
            if hasattr(base, "_fields"):
                fields.update(base._fields)

        for key, value in list(namespace.items()):
            if isinstance(value, SchemaField):
                value.name = key
                fields[key] = value
            elif isinstance(value, type) and hasattr(value, "_is_binary_struct"):
                sub = SubStruct(value)
                sub.name = key
                fields[key] = sub
            elif hasattr(value, "_is_binary_struct"):
                sub = SubStruct(type(value))
                sub.name = key
                fields[key] = sub

        namespace["_fields"] = fields
        return super().__new__(mcs, name, bases, namespace)


class BinaryStruct(metaclass=StructMeta):
    """
    Declarative binary structure base class for reverse engineering formats.
    Provides automatic binary serialization, deserialization, and offset tracking.
    """

    _is_binary_struct = True
    _fields: Dict[str, SchemaField] = {}
    _endian: str = "<"

    def __init__(self, **kwargs):
        for name, field in self._fields.items():
            if name in kwargs:
                setattr(self, name, kwargs[name])
            elif isinstance(field, SubStruct):
                setattr(self, name, field.struct_cls())
            elif isinstance(field, Array):
                setattr(self, name, [])
            else:
                setattr(self, name, field.default)

    @classmethod
    def sizeof(cls, context: Any = None) -> int:
        total = 0
        for f in cls._fields.values():
            total += f.get_size(context)
        return total

    @classmethod
    def offset_of(cls, field_name: str) -> int:
        offset = 0
        for name, f in cls._fields.items():
            if name == field_name:
                return offset
            offset += f.get_size()
        raise KeyError(f"Field '{field_name}' not found in {cls.__name__}")

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, endian: Optional[str] = None) -> "BinaryStruct":
        inst = cls()
        used_endian = endian or cls._endian
        curr_offset = offset

        for name, field in cls._fields.items():
            val, consumed = field.unpack(data, curr_offset, used_endian, context=inst)
            setattr(inst, name, val)
            curr_offset += consumed

        return inst

    def to_bytes(self, endian: Optional[str] = None) -> bytes:
        used_endian = endian or self._endian
        out = bytearray()

        for name, field in self._fields.items():
            val = getattr(self, name, field.default)
            out.extend(field.pack(val, used_endian, context=self))

        return bytes(out)

    def to_dict(self) -> Dict[str, Any]:
        d = {}
        for name in self._fields:
            val = getattr(self, name)
            if isinstance(val, BinaryStruct):
                d[name] = val.to_dict()
            elif isinstance(val, list) and val and isinstance(val[0], BinaryStruct):
                d[name] = [item.to_dict() for item in val]
            else:
                d[name] = val
        return d

    def __repr__(self) -> str:
        attrs = ", ".join(f"{k}={getattr(self, k)!r}" for k in self._fields)
        return f"<{self.__class__.__name__} {attrs}>"
