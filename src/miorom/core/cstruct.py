"""
miorom.core.cstruct
~~~~~~~~~~~~~~~~~~~
C Struct Overlay Mapper and Interactive Binary Dissector.
Parses ANSI C / C99 struct declarations, calculates field layouts and byte strides,
and maps binary buffers directly into pythonic dataclass-like instances with full
bidirectional read/write and table inspection capabilities.
"""

from __future__ import annotations

import json
import re
import struct
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

from miorom.result import MioRomResult
from miorom.errors import ParseError


TYPE_SPECS = {
    # 1 byte
    "int8_t": ("b", 1),
    "int8": ("b", 1),
    "s8": ("b", 1),
    "char": ("b", 1),
    "signed char": ("b", 1),
    "uint8_t": ("B", 1),
    "uint8": ("B", 1),
    "u8": ("B", 1),
    "unsigned char": ("B", 1),
    "byte": ("B", 1),
    "bool": ("?", 1),
    "_bool": ("?", 1),

    # 2 bytes
    "int16_t": ("h", 2),
    "int16": ("h", 2),
    "s16": ("h", 2),
    "short": ("h", 2),
    "signed short": ("h", 2),
    "uint16_t": ("H", 2),
    "uint16": ("H", 2),
    "u16": ("H", 2),
    "unsigned short": ("H", 2),
    "word": ("H", 2),

    # 4 bytes
    "int32_t": ("i", 4),
    "int32": ("i", 4),
    "s32": ("i", 4),
    "int": ("i", 4),
    "signed int": ("i", 4),
    "long": ("l", 4),
    "signed long": ("l", 4),
    "uint32_t": ("I", 4),
    "uint32": ("I", 4),
    "u32": ("I", 4),
    "unsigned int": ("I", 4),
    "unsigned long": ("L", 4),
    "dword": ("I", 4),
    "float": ("f", 4),
    "ptr32": ("I", 4),
    "void*": ("I", 4),
    "char*": ("I", 4),
    "uint8_t*": ("I", 4),
    "uint16_t*": ("I", 4),
    "uint32_t*": ("I", 4),

    # 8 bytes
    "int64_t": ("q", 8),
    "int64": ("q", 8),
    "s64": ("q", 8),
    "long long": ("q", 8),
    "signed long long": ("q", 8),
    "uint64_t": ("Q", 8),
    "uint64": ("Q", 8),
    "u64": ("Q", 8),
    "unsigned long long": ("Q", 8),
    "qword": ("Q", 8),
    "double": ("d", 8),
    "ptr64": ("Q", 8),
}


@dataclass
class CField(MioRomResult):
    """Metadata describing a single member field inside a C struct."""
    name: str
    type_name: str
    offset: int
    size: int
    format_char: str = ""
    is_array: bool = False
    array_length: int = 1
    is_string: bool = False
    nested_overlay: Optional["CStructOverlay"] = None

    def __repr__(self) -> str:
        arr_str = f"[{self.array_length}]" if self.is_array else ""
        return f"<CField +0x{self.offset:04X} {self.type_name} {self.name}{arr_str} ({self.size} bytes)>"


class CStructInstance:
    """
    Dynamic record instance mapped over a binary struct.
    Provides attribute access (instance.hp) and dict access (instance['hp']).
    """

    def __init__(self, overlay: "CStructOverlay", values: Optional[Dict[str, Any]] = None):
        super().__setattr__("_overlay", overlay)
        super().__setattr__("_values", dict(values) if values else {})

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            return super().__getattribute__(name)
        if name in self._values:
            return self._values[name]
        raise AttributeError(f"Struct '{self._overlay.name}' has no field '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            super().__setattr__(name, value)
            return
        if name in self._overlay.fields_by_name:
            self._values[name] = value
        else:
            super().__setattr__(name, value)

    def __getitem__(self, key: str) -> Any:
        return self._values[key]

    def __setitem__(self, key: str, value: Any) -> None:
        if key not in self._overlay.fields_by_name:
            raise KeyError(f"Struct '{self._overlay.name}' has no field '{key}'")
        self._values[key] = value

    def to_dict(self) -> Dict[str, Any]:
        result = {}
        for k, v in self._values.items():
            if isinstance(v, CStructInstance):
                result[k] = v.to_dict()
            elif isinstance(v, list):
                result[k] = [item.to_dict() if isinstance(item, CStructInstance) else item for item in v]
            else:
                result[k] = v
        return result

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def pack(self) -> bytes:
        return self._overlay.pack(self)

    def __repr__(self) -> str:
        fields_repr = ", ".join(f"{k}={v!r}" for k, v in self._values.items())
        return f"{self._overlay.name}({fields_repr})"


class CStructOverlay(MioRomResult):
    """
    Bidirectional C struct layout parser and binary buffer mapper.
    Compiles ANSI C struct declarations into bit-accurate byte layouts.
    """

    def __init__(
        self,
        name: str = "AnonymousStruct",
        fields: Optional[List[CField]] = None,
        endian: str = "<",
        pack_alignment: int = 1,
    ):
        self.name = name
        self.endian = endian
        self.pack_alignment = pack_alignment
        self.fields: List[CField] = fields or []
        self.fields_by_name: Dict[str, CField] = {f.name: f for f in self.fields}
        self.size: int = self._compute_size()

    def _compute_size(self) -> int:
        if not self.fields:
            return 0
        last = self.fields[-1]
        raw_size = last.offset + last.size
        if self.pack_alignment > 1:
            rem = raw_size % self.pack_alignment
            if rem != 0:
                raw_size += (self.pack_alignment - rem)
        return raw_size

    @classmethod
    def from_c(
        cls,
        c_source: str,
        endian: str = "<",
        pack_alignment: int = 1,
        known_structs: Optional[Dict[str, "CStructOverlay"]] = None,
    ) -> "CStructOverlay":
        """
        Parses ANSI C / C99 struct source string.
        Examples:
            struct Enemy {
                uint16_t id;
                char name[16];
                int16_t hp;
                uint32_t flags;
            };
        """
        nested_map = dict(known_structs or {})

        # Strip comments
        clean = re.sub(r"/\*.*?\*/", "", c_source, flags=re.DOTALL)
        clean = re.sub(r"//.*", "", clean)

        # Check for pragma pack
        pack_match = re.search(r"#pragma\s+pack\s*\(\s*(\d+)\s*\)", clean)
        if pack_match:
            pack_alignment = int(pack_match.group(1))

        # Check for struct name
        name_match = re.search(r"struct\s+([A-Za-z0-9_]+)\s*\{", clean)
        if not name_match:
            typedef_match = re.search(r"typedef\s+struct\s*\{.*?\}\s*([A-Za-z0-9_]+)\s*;", clean, flags=re.DOTALL)
            struct_name = typedef_match.group(1) if typedef_match else "CStruct"
        else:
            struct_name = name_match.group(1)

        # Extract body between outer { and }
        body_start = clean.find("{")
        body_end = clean.rfind("}")
        if body_start == -1 or body_end == -1:
            raise ParseError(f"Cannot find struct body braces in: {c_source[:50]}...")
        body = clean[body_start + 1 : body_end]

        field_lines = [stmt.strip() for stmt in body.split(";") if stmt.strip()]
        fields: List[CField] = []
        current_offset = 0

        for stmt in field_lines:
            # Handle possible pointer: e.g. void* ptr or void *ptr
            stmt = re.sub(r"\s*\*\s*", "* ", stmt).strip()
            # Match: type_name field_name[arr_len] or type_name field_name
            m = re.match(r"^([\w\*\s]+?)\s+([A-Za-z0-9_]+)(?:\s*\[\s*(\d+)\s*\])?$", stmt)
            if not m:
                continue

            raw_type = " ".join(m.group(1).split()).lower()
            fname = m.group(2)
            arr_len_str = m.group(3)

            is_arr = arr_len_str is not None
            arr_len = int(arr_len_str) if is_arr else 1

            # Check alignment
            if pack_alignment > 1:
                align = pack_alignment
                rem = current_offset % align
                if rem != 0:
                    current_offset += (align - rem)

            # Check if nested struct
            if raw_type in nested_map:
                sub_ov = nested_map[raw_type]
                elem_sz = sub_ov.size
                total_sz = elem_sz * arr_len
                fld = CField(
                    name=fname,
                    type_name=raw_type,
                    offset=current_offset,
                    size=total_sz,
                    is_array=is_arr,
                    array_length=arr_len,
                    is_string=False,
                    nested_overlay=sub_ov,
                )
            else:
                # Primitive lookup
                spec = TYPE_SPECS.get(raw_type)
                if not spec:
                    # Fallback default 4 bytes unsigned
                    spec = ("I", 4)
                fmt_char, elem_sz = spec
                is_str = (raw_type in ("char", "signed char", "uint8_t", "byte", "u8")) and is_arr
                total_sz = elem_sz * arr_len
                fld = CField(
                    name=fname,
                    type_name=raw_type,
                    offset=current_offset,
                    size=total_sz,
                    format_char=fmt_char,
                    is_array=is_arr,
                    array_length=arr_len,
                    is_string=is_str,
                )

            fields.append(fld)
            current_offset += total_sz

        overlay = cls(name=struct_name, fields=fields, endian=endian, pack_alignment=pack_alignment)
        nested_map[struct_name.lower()] = overlay
        return overlay

    def read(self, buffer: bytes, offset: int = 0) -> CStructInstance:
        """Reads a single struct instance from buffer at given offset."""
        if offset + self.size > len(buffer):
            raise IndexError(
                f"Buffer too short: need {offset + self.size} bytes for struct '{self.name}', got {len(buffer)}"
            )

        values: Dict[str, Any] = {}
        for fld in self.fields:
            field_off = offset + fld.offset
            if fld.nested_overlay:
                if fld.is_array:
                    sub_list = []
                    sub_sz = fld.nested_overlay.size
                    for idx in range(fld.array_length):
                        sub_list.append(fld.nested_overlay.read(buffer, field_off + idx * sub_sz))
                    values[fld.name] = sub_list
                else:
                    values[fld.name] = fld.nested_overlay.read(buffer, field_off)
            elif fld.is_string:
                raw_bytes = buffer[field_off : field_off + fld.size]
                null_idx = raw_bytes.find(b"\x00")
                if null_idx != -1:
                    raw_bytes = raw_bytes[:null_idx]
                try:
                    values[fld.name] = raw_bytes.decode("utf-8", errors="replace")
                except Exception:
                    values[fld.name] = raw_bytes.decode("latin-1", errors="replace")
            elif fld.is_array:
                elem_sz = fld.size // fld.array_length
                fmt = f"{self.endian}{fld.format_char}"
                arr = []
                for idx in range(fld.array_length):
                    arr.append(struct.unpack_from(fmt, buffer, field_off + idx * elem_sz)[0])
                values[fld.name] = arr
            else:
                fmt = f"{self.endian}{fld.format_char}"
                values[fld.name] = struct.unpack_from(fmt, buffer, field_off)[0]

        return CStructInstance(self, values)

    def read_table(
        self,
        buffer: bytes,
        offset: int = 0,
        count: Optional[int] = None,
    ) -> List[CStructInstance]:
        """Reads consecutive records of this struct table from buffer."""
        if self.size == 0:
            return []
        avail = len(buffer) - offset
        max_possible = max(0, avail // self.size)
        total = max_possible if count is None else min(count, max_possible)

        records: List[CStructInstance] = []
        curr = offset
        for _ in range(total):
            records.append(self.read(buffer, curr))
            curr += self.size
        return records

    def write(
        self,
        buffer: bytearray,
        offset: int,
        record: Union[CStructInstance, Dict[str, Any]],
    ) -> None:
        """Encodes and writes record in-place into mutable bytearray buffer."""
        packed_bytes = self.pack(record)
        buffer[offset : offset + len(packed_bytes)] = packed_bytes

    def pack(self, record: Union[CStructInstance, Dict[str, Any]]) -> bytes:
        """Serializes instance or dictionary to packed bytes."""
        out = bytearray(self.size)
        vals = record.to_dict() if isinstance(record, CStructInstance) else record

        for fld in self.fields:
            if fld.name not in vals:
                continue
            v = vals[fld.name]
            field_off = fld.offset

            if fld.nested_overlay:
                if fld.is_array:
                    sub_sz = fld.nested_overlay.size
                    for idx, item in enumerate(v[: fld.array_length]):
                        sub_bytes = fld.nested_overlay.pack(item)
                        out[field_off + idx * sub_sz : field_off + (idx + 1) * sub_sz] = sub_bytes
                else:
                    sub_bytes = fld.nested_overlay.pack(v)
                    out[field_off : field_off + len(sub_bytes)] = sub_bytes

            elif fld.is_string:
                raw = v.encode("utf-8") if isinstance(v, str) else bytes(v)
                raw = raw[: fld.size]
                out[field_off : field_off + len(raw)] = raw

            elif fld.is_array:
                elem_sz = fld.size // fld.array_length
                fmt = f"{self.endian}{fld.format_char}"
                for idx, elem in enumerate(v[: fld.array_length]):
                    struct.pack_into(fmt, out, field_off + idx * elem_sz, elem)

            else:
                fmt = f"{self.endian}{fld.format_char}"
                struct.pack_into(fmt, out, field_off, v)

        return bytes(out)
