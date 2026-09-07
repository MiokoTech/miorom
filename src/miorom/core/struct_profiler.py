"""
miorom.core.struct_profiler
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Heuristic Struct Profiler and Binary Record Stride Auto-Detector.
Discovers record length (stride) of unknown table structures using autocorrelation
and column variance, profiles field types (integers, floats, pointers, bitflags,
padding, strings), and synthesizes C struct and JSON definitions.
"""

from dataclasses import dataclass, field
from enum import Enum
import math
import struct
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union


class FieldType(Enum):
    PADDING = "padding"
    UINT8 = "uint8"
    INT8 = "int8"
    UINT16_LE = "uint16_le"
    UINT16_BE = "uint16_be"
    INT16_LE = "int16_le"
    INT16_BE = "int16_be"
    UINT32_LE = "uint32_le"
    UINT32_BE = "uint32_be"
    INT32_LE = "int32_le"
    INT32_BE = "int32_be"
    FLOAT32_LE = "float32_le"
    FLOAT32_BE = "float32_be"
    POINTER_LE = "pointer_le"
    POINTER_BE = "pointer_be"
    BITFIELD = "bitfield"
    STRING = "string"
    UNKNOWN = "unknown"


@dataclass
class StrideCandidate:
    """Represents a potential record stride with statistical confidence."""
    stride: int
    score: float
    record_count: int


@dataclass
class FieldProfile:
    """Profile of a single column/field within a repetitive struct."""
    offset: int
    size: int
    field_type: FieldType
    name: str
    is_constant: bool = False
    constant_value: Optional[Any] = None
    min_value: Optional[Union[int, float]] = None
    max_value: Optional[Union[int, float]] = None
    sample_values: List[Any] = field(default_factory=list)


@dataclass
class StructProfile:
    """Complete profile of a repetitive binary record table."""
    stride: int
    record_count: int
    total_bytes: int
    fields: List[FieldProfile] = field(default_factory=list)

    def to_c_struct(self, struct_name: str = "DissectedRecord") -> str:
        """Synthesizes a valid C struct declaration."""
        lines = [f"typedef struct {{"]
        type_c_map = {
            FieldType.PADDING: "uint8_t",
            FieldType.UINT8: "uint8_t",
            FieldType.INT8: "int8_t",
            FieldType.UINT16_LE: "uint16_t",
            FieldType.UINT16_BE: "uint16_t",
            FieldType.INT16_LE: "int16_t",
            FieldType.INT16_BE: "int16_t",
            FieldType.UINT32_LE: "uint32_t",
            FieldType.UINT32_BE: "uint32_t",
            FieldType.INT32_LE: "int32_t",
            FieldType.INT32_BE: "int32_t",
            FieldType.FLOAT32_LE: "float",
            FieldType.FLOAT32_BE: "float",
            FieldType.POINTER_LE: "void*",
            FieldType.POINTER_BE: "void*",
            FieldType.BITFIELD: "uint32_t",
            FieldType.STRING: "char",
            FieldType.UNKNOWN: "uint8_t",
        }

        for f in self.fields:
            c_type = type_c_map.get(f.field_type, "uint8_t")
            if f.field_type == FieldType.PADDING and f.size > 1:
                lines.append(f"    {c_type} {f.name}[{f.size}]; /* +0x{f.offset:02X} padding */")
            elif f.field_type == FieldType.STRING:
                lines.append(f"    {c_type} {f.name}[{f.size}]; /* +0x{f.offset:02X} string */")
            elif f.size > 4 and f.field_type == FieldType.UNKNOWN:
                lines.append(f"    {c_type} {f.name}[{f.size}]; /* +0x{f.offset:02X} raw */")
            else:
                extra = f" /* +0x{f.offset:02X}"
                if f.is_constant:
                    extra += f", const={f.constant_value}"
                elif f.min_value is not None and f.max_value is not None:
                    extra += f", range=[{f.min_value}..{f.max_value}]"
                extra += " */"
                lines.append(f"    {c_type} {f.name};{extra}")

        lines.append(f"}} {struct_name}; /* Stride: {self.stride} bytes, Records: {self.record_count} */")
        return "\n".join(lines)

    def to_json_schema(self) -> Dict[str, Any]:
        """Generates JSON schema descriptor for the record structure."""
        return {
            "stride": self.stride,
            "record_count": self.record_count,
            "total_bytes": self.total_bytes,
            "fields": [
                {
                    "name": f.name,
                    "offset": f.offset,
                    "size": f.size,
                    "type": f.field_type.value,
                    "is_constant": f.is_constant,
                    "constant_value": f.constant_value,
                    "min_value": f.min_value,
                    "max_value": f.max_value,
                }
                for f in self.fields
            ],
        }


class StructProfiler:
    """
    Automated Record Stride Detector and Field Type Classifier.
    """

    @classmethod
    def autodetect_stride(
        cls,
        data: bytes,
        min_stride: int = 4,
        max_stride: int = 128,
        min_records: int = 4,
    ) -> List[StrideCandidate]:
        """
        Discovers record stride by evaluating autocorrelation and cross-record byte constancy.
        Returns scored stride candidates sorted from highest confidence to lowest.
        """
        n = len(data)
        candidates: List[StrideCandidate] = []
        if n < min_stride * min_records:
            return candidates

        for stride in range(min_stride, max_stride + 1):
            records = n // stride
            if records < min_records:
                break

            # 1. Measure byte constancy across records:
            # If `stride` is the true record length, certain columns (like padding, flags, IDs)
            # will have lower variance or high constancy across records.
            constancy_score = 0.0
            for col in range(stride):
                col_bytes = [data[r * stride + col] for r in range(records)]
                unique_ratio = len(set(col_bytes)) / records
                # Zero variance (all same) or moderate variance is characteristic of structured fields
                if unique_ratio == (1.0 / records):  # Constant column
                    constancy_score += 2.0
                elif unique_ratio < 0.5:
                    constancy_score += 1.0

            # 2. Alignment preference (multiples of 2 or 4 are standard in console memory)
            align_bonus = 1.2 if (stride % 4 == 0) else (1.1 if stride % 2 == 0 else 1.0)
            final_score = (constancy_score / stride) * align_bonus

            if final_score > 0.1:
                candidates.append(
                    StrideCandidate(stride=stride, score=round(final_score, 4), record_count=records)
                )

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates

    @classmethod
    def profile_struct(
        cls,
        data: bytes,
        stride: int,
        record_count: Optional[int] = None,
        pointer_range: Optional[Tuple[int, int]] = None,
        endian: str = "<",
    ) -> StructProfile:
        """
        Profiles each field inside the detected stride across all records.
        """
        available_records = len(data) // stride
        records = min(available_records, record_count) if record_count else available_records
        if records <= 0:
            return StructProfile(stride=stride, record_count=0, total_bytes=0, fields=[])

        fields: List[FieldProfile] = []
        col = 0

        while col < stride:
            # Try 4-byte analysis first if col + 4 <= stride
            if col + 4 <= stride:
                u32_vals = []
                all_zeros = True
                for r in range(records):
                    off = r * stride + col
                    val = struct.unpack_from(f"{endian}I", data, off)[0]
                    u32_vals.append(val)
                    if val != 0:
                        all_zeros = False

                if all_zeros:
                    # Check how long the zero run is
                    fields.append(
                        FieldProfile(
                            offset=col,
                            size=4,
                            field_type=FieldType.PADDING,
                            name=f"pad_{col:02X}",
                            is_constant=True,
                            constant_value=0,
                        )
                    )
                    col += 4
                    continue

                # Check if it looks like a valid pointer
                if pointer_range:
                    ptr_min, ptr_max = pointer_range
                    if all(ptr_min <= v <= ptr_max for v in u32_vals if v != 0):
                        fields.append(
                            FieldProfile(
                                offset=col,
                                size=4,
                                field_type=FieldType.POINTER_LE if endian == "<" else FieldType.POINTER_BE,
                                name=f"ptr_{col:02X}",
                                min_value=min(u32_vals),
                                max_value=max(u32_vals),
                                sample_values=u32_vals[:3],
                            )
                        )
                        col += 4
                        continue

                # Check if values are small integers fitting into 16-bit or 8-bit
                max_val = max(u32_vals)
                if max_val > 0xFFFF:
                    # Genuine 32-bit field
                    is_const = len(set(u32_vals)) == 1
                    fields.append(
                        FieldProfile(
                            offset=col,
                            size=4,
                            field_type=FieldType.UINT32_LE if endian == "<" else FieldType.UINT32_BE,
                            name=f"val32_{col:02X}",
                            is_constant=is_const,
                            constant_value=u32_vals[0] if is_const else None,
                            min_value=min(u32_vals),
                            max_value=max(u32_vals),
                            sample_values=u32_vals[:3],
                        )
                    )
                    col += 4
                    continue

            # Try 2-byte analysis
            if col + 2 <= stride:
                u16_vals = [struct.unpack_from(f"{endian}H", data, r * stride + col)[0] for r in range(records)]
                max_u16 = max(u16_vals)
                if max_u16 > 0xFF or (col % 2 == 0 and not all(v == 0 for v in u16_vals)):
                    is_const = len(set(u16_vals)) == 1
                    fields.append(
                        FieldProfile(
                            offset=col,
                            size=2,
                            field_type=FieldType.UINT16_LE if endian == "<" else FieldType.UINT16_BE,
                            name=f"val16_{col:02X}",
                            is_constant=is_const,
                            constant_value=u16_vals[0] if is_const else None,
                            min_value=min(u16_vals),
                            max_value=max(u16_vals),
                            sample_values=u16_vals[:3],
                        )
                    )
                    col += 2
                    continue

            # Fall back to 1-byte field
            u8_vals = [data[r * stride + col] for r in range(records)]
            is_const = len(set(u8_vals)) == 1
            f_type = FieldType.PADDING if (is_const and u8_vals[0] == 0) else FieldType.UINT8
            fields.append(
                FieldProfile(
                    offset=col,
                    size=1,
                    field_type=f_type,
                    name=f"val8_{col:02X}",
                    is_constant=is_const,
                    constant_value=u8_vals[0] if is_const else None,
                    min_value=min(u8_vals),
                    max_value=max(u8_vals),
                    sample_values=u8_vals[:3],
                )
            )
            col += 1

        return StructProfile(
            stride=stride,
            record_count=records,
            total_bytes=records * stride,
            fields=fields,
        )
