import struct
from miorom.errors import ParseError
from typing import Any, Dict, List, Optional, Tuple, Type, Union


class SchemaField:
    """Base class for all declarative binary struct fields."""

    def __init__(
        self,
        default: Any = None,
        endian: Optional[str] = None,
        validate: Optional[Any] = None,
    ):
        self.default = default
        self.endian = endian
        self.validate = validate
        self.name = ""
        self.offset = 0

    def get_size(self, context: Any = None) -> int:
        raise NotImplementedError

    def unpack(self, data: bytes, offset: int, endian: Optional[str] = None, context: Any = None) -> Tuple[Any, int]:
        raise NotImplementedError

    def pack(self, value: Any, endian: Optional[str] = None, context: Any = None) -> bytes:
        raise NotImplementedError


class PrimitiveField(SchemaField):
    def __init__(self, format_char: str, size: int, default: Any = 0, endian: Optional[str] = None, **kwargs):
        super().__init__(default=default, endian=endian, **kwargs)
        self.format_char = format_char
        self._size = size

    def get_size(self, context: Any = None) -> int:
        return self._size

    def unpack(self, data: bytes, offset: int, endian: Optional[str] = None, context: Any = None) -> Tuple[Any, int]:
        used_endian = self.endian or endian or "<"
        fmt = used_endian + self.format_char
        val = struct.unpack_from(fmt, data, offset)[0]
        return val, self._size

    def pack(self, value: Any, endian: Optional[str] = None, context: Any = None) -> bytes:
        used_endian = self.endian or endian or "<"
        fmt = used_endian + self.format_char
        return struct.pack(fmt, value if value is not None else self.default)


class U8(PrimitiveField):
    def __init__(self, default: int = 0, **kwargs):
        super().__init__("B", 1, default=default, **kwargs)


class I8(PrimitiveField):
    def __init__(self, default: int = 0, **kwargs):
        super().__init__("b", 1, default=default, **kwargs)


class U16(PrimitiveField):
    def __init__(self, default: int = 0, endian: Optional[str] = None, **kwargs):
        super().__init__("H", 2, default=default, endian=endian, **kwargs)


class I16(PrimitiveField):
    def __init__(self, default: int = 0, endian: Optional[str] = None, **kwargs):
        super().__init__("h", 2, default=default, endian=endian, **kwargs)


class U32(PrimitiveField):
    def __init__(self, default: int = 0, endian: Optional[str] = None, **kwargs):
        super().__init__("I", 4, default=default, endian=endian, **kwargs)


class I32(PrimitiveField):
    def __init__(self, default: int = 0, endian: Optional[str] = None, **kwargs):
        super().__init__("i", 4, default=default, endian=endian, **kwargs)


class U64(PrimitiveField):
    def __init__(self, default: int = 0, endian: Optional[str] = None, **kwargs):
        super().__init__("Q", 8, default=default, endian=endian, **kwargs)


class Float32(PrimitiveField):
    def __init__(self, default: float = 0.0, endian: Optional[str] = None, **kwargs):
        super().__init__("f", 4, default=default, endian=endian, **kwargs)


class FixedString(SchemaField):
    def __init__(self, length: int, encoding: str = "ascii", pad: bytes = b"\x00", default: str = ""):
        super().__init__(default=default)
        self.length = length
        self.encoding = encoding
        self.pad = pad

    def get_size(self, context: Any = None) -> int:
        return self.length

    def unpack(self, data: bytes, offset: int, endian: Optional[str] = None, context: Any = None) -> Tuple[str, int]:
        raw = data[offset:offset + self.length]
        stripped = raw.rstrip(self.pad)
        text = stripped.decode(self.encoding, errors="replace")
        return text, self.length

    def pack(self, value: Any, endian: Optional[str] = None, context: Any = None) -> bytes:
        if isinstance(value, (bytes, bytearray)):
            raw = bytes(value)
        else:
            text = str(value if value is not None else self.default)
            raw = text.encode(self.encoding, errors="replace")
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

    def unpack(self, data: bytes, offset: int, endian: Optional[str] = None, context: Any = None) -> Tuple[bytes, int]:
        return data[offset:offset + self.length], self.length

    def pack(self, value: Any, endian: Optional[str] = None, context: Any = None) -> bytes:
        val = bytes(value if value is not None else self.default)
        return val.ljust(self.length, b"\x00")[:self.length]


class SubStruct(SchemaField):
    """Encapsulates a nested BinaryStruct as a field."""

    def __init__(self, struct_cls: Type["BinaryStruct"]):
        super().__init__()
        self.struct_cls = struct_cls

    def get_size(self, context: Any = None) -> int:
        return self.struct_cls.sizeof(context)

    def unpack(self, data: bytes, offset: int, endian: Optional[str] = None, context: Any = None) -> Tuple[Any, int]:
        inst = self.struct_cls.from_bytes(data, offset=offset, endian=endian)
        return inst, self.struct_cls.sizeof(inst)

    def pack(self, value: Any, endian: Optional[str] = None, context: Any = None) -> bytes:
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

    def unpack(self, data: bytes, offset: int, endian: Optional[str] = None, context: Any = None) -> Tuple[List[Any], int]:
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

    def pack(self, value: Any, endian: Optional[str] = None, context: Any = None) -> bytes:
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
    def sizeof_dynamic(cls, data: bytes, offset: int = 0, endian: Optional[str] = None) -> int:
        """Measure dynamic layouts (PascalString, SentinelArray, If, Alignment) from bytes."""
        probe = cls.from_bytes(data, offset=offset, endian=endian)
        return probe._current_offset

    @classmethod
    def offset_of(cls, field_name: str) -> int:
        offset = 0
        for name, f in cls._fields.items():
            if name == field_name:
                return offset
            offset += f.get_size()
        raise KeyError(f"Field '{field_name}' not found in {cls.__name__}")

    @classmethod
    def offset_of_dynamic(cls, field_name: str, data: bytes, offset: int = 0, endian: Optional[str] = None) -> int:
        """Resolve field offset for dynamic layouts from actual bytes."""
        start = offset
        probe = cls.from_bytes(data, offset=offset, endian=endian)
        for name in cls._fields:
            if name == field_name:
                return start + getattr(probe, "_field_offsets", {}).get(name, 0)
        raise KeyError(f"Field '{field_name}' not found in {cls.__name__}")

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, endian: Optional[str] = None) -> "BinaryStruct":
        inst = cls()
        used_endian = endian or cls._endian
        curr_offset = offset
        field_offsets: Dict[str, int] = {}
        available = len(data)

        for name, field in cls._fields.items():
            inst._current_offset = curr_offset - offset
            field_offsets[name] = curr_offset - offset
            required_size = field.get_size(context=inst)
            if required_size > 0 and curr_offset + required_size > available:
                raise ParseError(
                    f"Truncated {cls.__name__}.{name}: requires {required_size} bytes at offset "
                    f"0x{curr_offset:X}, but only {max(0, available - curr_offset)} bytes remain.",
                    offset=curr_offset,
                    expected=required_size,
                    actual=max(0, available - curr_offset),
                )
            val, consumed = field.unpack(data, curr_offset, used_endian, context=inst)
            if curr_offset + consumed > available:
                raise ParseError(
                    f"Truncated {cls.__name__}.{name}: requires {consumed} bytes at offset "
                    f"0x{curr_offset:X}, but only {max(0, available - curr_offset)} bytes remain.",
                    offset=curr_offset,
                    expected=consumed,
                    actual=max(0, available - curr_offset),
                )
            if field.validate is not None:
                if not field.validate(val):
                    raise ParseError(
                        f"Validation constraint failed for {cls.__name__}.{name} with value {val!r} at offset 0x{curr_offset:X}",
                        offset=curr_offset,
                        actual=val,
                    )
            setattr(inst, name, val)
            curr_offset += consumed
        inst._current_offset = curr_offset - offset
        inst._field_offsets = field_offsets

        return inst

    def to_bytes(self, endian: Optional[str] = None) -> bytes:
        used_endian = endian or self._endian
        out = bytearray()
        curr_offset = 0

        for name, field in self._fields.items():
            self._current_offset = curr_offset
            self._packing_prefix = bytes(out)
            val = getattr(self, name, field.default)
            packed = field.pack(val, used_endian, context=self)
            out.extend(packed)
            curr_offset += len(packed)
        self._current_offset = curr_offset

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


class PascalString(SchemaField):
    """Length-prefixed string with the prefix type declared explicitly."""

    def __init__(self, length_type: SchemaField, encoding: str = "ascii", default: str = ""):
        self._endian = None
        super().__init__(default=default)
        self.length_type = length_type
        self.encoding = encoding

    @property
    def endian(self) -> Optional[str]:
        return self._endian if self._endian is not None else self.length_type.endian

    @endian.setter
    def endian(self, value: Optional[str]):
        self._endian = value

    def get_size(self, context: Any = None) -> int:
        return self.length_type.get_size(context)

    def unpack(self, data: bytes, offset: int, endian: Optional[str] = None, context: Any = None) -> Tuple[str, int]:
        length, prefix_size = self.length_type.unpack(data, offset, endian, context)
        start = offset + prefix_size
        raw = data[start:start + length]
        return raw.decode(self.encoding, errors="replace"), prefix_size + length

    def pack(self, value: Any, endian: Optional[str] = None, context: Any = None) -> bytes:
        raw = str(value if value is not None else self.default).encode(self.encoding, errors="replace")
        return self.length_type.pack(len(raw), endian, context) + raw


class SentinelArray(SchemaField):
    """Reads fixed-size items until a sentinel prefix is found."""

    def __init__(self, field_or_struct: Union[SchemaField, Type["BinaryStruct"]], sentinel: bytes, max_count: Optional[int] = None):
        super().__init__(default=[])
        self.item_type = field_or_struct
        self.sentinel = bytes(sentinel)
        self.max_count = max_count

    def get_size(self, context: Any = None) -> int:
        return 0

    def unpack(self, data: bytes, offset: int, endian: Optional[str] = None, context: Any = None) -> Tuple[List[Any], int]:
        items: List[Any] = []
        curr_offset = offset

        while self.max_count is None or len(items) < self.max_count:
            if data[curr_offset:curr_offset + len(self.sentinel)] == self.sentinel:
                break
            if isinstance(self.item_type, SchemaField):
                item, consumed = self.item_type.unpack(data, curr_offset, endian, context)
            else:
                item = self.item_type.from_bytes(data, offset=curr_offset, endian=endian)
                consumed = self.item_type.sizeof(item)
            if consumed == 0:
                break
            items.append(item)
            curr_offset += consumed
        return items, curr_offset - offset

    def pack(self, value: Any, endian: Optional[str] = None, context: Any = None) -> bytes:
        out = bytearray()
        for item in list(value or []):
            if isinstance(self.item_type, SchemaField):
                out.extend(self.item_type.pack(item, endian, context))
            elif isinstance(item, dict):
                out.extend(self.item_type(**item).to_bytes(endian=endian))
            elif hasattr(item, "_is_binary_struct"):
                out.extend(item.to_bytes(endian=endian))
        out.extend(self.sentinel)
        return bytes(out)


class ChecksumField(SchemaField):
    """Checksum slot computed from every byte preceding it during pack."""

    def __init__(self, size: int, algorithm: Optional[Any] = None, endian: Optional[str] = None):
        super().__init__(default=0, endian=endian)
        self.size = size
        self.algorithm = algorithm or self._default_algorithm

    def _default_algorithm(self, data: bytes) -> int:
        return sum(data) & ((1 << (self.size * 8)) - 1)

    def get_size(self, context: Any = None) -> int:
        return self.size

    def unpack(self, data: bytes, offset: int, endian: Optional[str] = None, context: Any = None) -> Tuple[int, int]:
        return int.from_bytes(data[offset:offset + self.size], "little" if endian == "<" else "big"), self.size

    def pack(self, value: Any, endian: Optional[str] = None, context: Any = None) -> bytes:
        prefix = b"" if context is None else bytes(getattr(context, "_packing_prefix", b""))
        checksum = self.algorithm(prefix)
        return int(checksum).to_bytes(self.size, "little" if endian == "<" else "big")


class EnumField(SchemaField):
    """Integer-backed binary enum."""

    def __init__(self, base_field: SchemaField, enum_type: Type[Any], default: Optional[Any] = None):
        self._endian = None
        super().__init__(default=default)
        self.base_field = base_field
        self.enum_type = enum_type

    @property
    def endian(self) -> Optional[str]:
        return self._endian if self._endian is not None else self.base_field.endian

    @endian.setter
    def endian(self, value: Optional[str]):
        self._endian = value

    def get_size(self, context: Any = None) -> int:
        return self.base_field.get_size(context)

    def unpack(self, data: bytes, offset: int, endian: Optional[str] = None, context: Any = None) -> Tuple[Any, int]:
        raw, consumed = self.base_field.unpack(data, offset, endian, context)
        return self.enum_type(raw), consumed

    def pack(self, value: Any, endian: Optional[str] = None, context: Any = None) -> bytes:
        raw = value.value if isinstance(value, self.enum_type) else value
        return self.base_field.pack(raw, endian, context)


class Bitfield(SchemaField):
    """Integer-backed bitfield with documented flag mappings."""

    def __init__(
        self,
        base_field: SchemaField,
        flags: Optional[Dict[str, int]] = None,
        default: Union[int, Dict[str, bool], None] = None,
    ):
        self._endian = None
        super().__init__(default=default)
        self.base_field = base_field
        self.flags = flags or {}

    @property
    def endian(self) -> Optional[str]:
        return self._endian if self._endian is not None else self.base_field.endian

    @endian.setter
    def endian(self, value: Optional[str]):
        self._endian = value

    def get_size(self, context: Any = None) -> int:
        return self.base_field.get_size(context)

    def unpack(self, data: bytes, offset: int, endian: Optional[str] = None, context: Any = None) -> Tuple[Any, int]:
        raw, consumed = self.base_field.unpack(data, offset, endian, context)
        return BitfieldView(raw, self.flags), consumed

    def pack(self, value: Any, endian: Optional[str] = None, context: Any = None) -> bytes:
        if isinstance(value, dict):
            value = sum(mask for name, mask in self.flags.items() if value.get(name, False))
        elif isinstance(value, BitfieldView):
            value = value.raw
        return self.base_field.pack(value, endian, context)


class BitfieldView:
    """Small integer proxy for inspecting declared bit flags."""

    def __init__(self, raw: int, flags: Dict[str, int]):
        self.raw = raw
        self.flags = flags

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw": self.raw,
            "flags": {name: bool(self.raw & mask) for name, mask in self.flags.items()},
        }

    def __getattr__(self, name: str) -> bool:
        try:
            return bool(self.raw & self.flags[name])
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __int__(self) -> int:
        return self.raw

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, BitfieldView):
            return self.raw == other.raw
        if isinstance(other, dict):
            return self.to_dict() == other
        if isinstance(other, int):
            return self.raw == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.raw)

    def __repr__(self) -> str:
        enabled = [name for name, mask in self.flags.items() if self.raw & mask]
        return f"BitfieldView(0x{self.raw:X}, enabled={enabled!r})"


class If(SchemaField):
    """Conditional field; evaluated when context is available."""

    def __init__(self, condition: Any, field: SchemaField, default: Any = None):
        self._endian = None
        super().__init__(default=default)
        self.condition = condition
        self.field = field

    @property
    def endian(self) -> Optional[str]:
        return self._endian if self._endian is not None else self.field.endian

    @endian.setter
    def endian(self, value: Optional[str]):
        self._endian = value

    def _active(self, context: Any) -> bool:
        if callable(self.condition):
            return bool(self.condition(context))
        if isinstance(self.condition, str):
            return bool(getattr(context, self.condition, False))
        return bool(self.condition)

    def get_size(self, context: Any = None) -> int:
        return self.field.get_size(context) if self._active(context) else 0

    def unpack(self, data: bytes, offset: int, endian: Optional[str] = None, context: Any = None) -> Tuple[Any, int]:
        if not self._active(context):
            return self.default, 0
        return self.field.unpack(data, offset, endian, context)

    def pack(self, value: Any, endian: Optional[str] = None, context: Any = None) -> bytes:
        if not self._active(context):
            return b""
        return self.field.pack(value, endian, context)


class Padding(SchemaField):
    """Zero-filled padding that preserves bytes during unpack and writes zeros on pack."""

    def __init__(self, length: int):
        super().__init__(default=b"")
        self.length = length

    def get_size(self, context: Any = None) -> int:
        return self.length

    def unpack(self, data: bytes, offset: int, endian: Optional[str] = None, context: Any = None) -> Tuple[bytes, int]:
        return data[offset:offset + self.length], self.length

    def pack(self, value: Any, endian: Optional[str] = None, context: Any = None) -> bytes:
        return bytes(value if value is not None else b"").ljust(self.length, b"\x00")[:self.length]


class Alignment(SchemaField):
    """Padding up to the next multiple of boundary from struct start."""

    def __init__(self, boundary: int, default: bytes = b""):
        super().__init__(default=default)
        self.boundary = boundary

    def get_size(self, context: Any = None) -> int:
        return 0

    def unpack(self, data: bytes, offset: int, endian: Optional[str] = None, context: Any = None) -> Tuple[bytes, int]:
        start = 0 if context is None else getattr(context, "_current_offset", offset)
        padding = (self.boundary - (start % self.boundary)) % self.boundary
        return data[offset:offset + padding], padding

    def pack(self, value: Any, endian: Optional[str] = None, context: Any = None) -> bytes:
        start = 0 if context is None else getattr(context, "_current_offset", 0)
        padding = (self.boundary - (start % self.boundary)) % self.boundary
        return bytes(value if value is not None else self.default).ljust(padding, b"\x00")[:padding]


class Computed(SchemaField):
    """Zero-sized derived value. Primary use is read-only computed metadata."""

    def __init__(self, calculate: Any):
        super().__init__()
        self.calculate = calculate

    def get_size(self, context: Any = None) -> int:
        return 0

    def unpack(self, data: bytes, offset: int, endian: Optional[str] = None, context: Any = None) -> Tuple[Any, int]:
        return self.calculate(context, data, offset), 0

    def pack(self, value: Any, endian: Optional[str] = None, context: Any = None) -> bytes:
        return b""
