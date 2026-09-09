from miorom.result import MioRomResult
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class CascadingShiftReport(MioRomResult):
    shift_boundary: int
    delta_bytes: int
    direct_pointers_updated: int
    split_pointers_updated: int
    new_total_size: int

    def summary(self) -> str:
        return (
            f"Cascading Relocation Report:\n"
            f"  Shift Boundary    : 0x{self.shift_boundary:08X}\n"
            f"  Delta Shift       : +{self.delta_bytes} bytes\n"
            f"  Direct Pointers   : {self.direct_pointers_updated} updated\n"
            f"  Split Pointers    : {self.split_pointers_updated} updated\n"
            f"  New Buffer Size   : {self.new_total_size} bytes"
        )


class CascadingRelocator:
    """
    Autonomous cascading pointer table relocator and delta shifter.
    Automatically shifts downstream binary sections forward when string pools expand,
    updating direct (32-bit/16-bit) and split (hi16/lo16) pointer tables in tandem.
    """

    @classmethod
    def shift_and_relocate(
        cls,
        data: bytearray,
        shift_boundary: int,
        delta_bytes: int,
        direct_tables: Optional[List[Tuple[int, int]]] = None,  # list of (table_offset, count)
        split_pointers: Optional[List[Tuple[int, int]]] = None, # list of (hi_offset, lo_offset)
        ram_base: int = 0,
        endian: str = ">",
        arch: str = "ppc",
    ) -> CascadingShiftReport:
        """
        Shifts all data from shift_boundary forward by delta_bytes,
        and updates all pointers that point to or beyond shift_boundary.
        """
        if delta_bytes <= 0:
            return CascadingShiftReport(shift_boundary, 0, 0, 0, len(data))

        # 1. Expand buffer at shift_boundary
        # Insert delta_bytes of 0x00 at shift_boundary
        tail = data[shift_boundary:]
        data[shift_boundary : shift_boundary + delta_bytes] = b"\x00" * delta_bytes
        data[shift_boundary + delta_bytes :] = tail

        direct_count = 0
        boundary_ram = shift_boundary + ram_base

        # 2. Update direct pointer tables
        tables = direct_tables or []
        for tbl_off, count in tables:
            # If the table itself was located after the boundary, its file offset shifted!
            actual_tbl_off = tbl_off + (delta_bytes if tbl_off >= shift_boundary else 0)
            for i in range(count):
                p_off = actual_tbl_off + i * 4
                if p_off + 4 <= len(data):
                    val = struct.unpack_from(f"{endian}I", data, p_off)[0]
                    if val >= boundary_ram:
                        struct.pack_into(f"{endian}I", data, p_off, val + delta_bytes)
                        direct_count += 1

        # 3. Update split pointers (e.g. lis + addi in PPC, lui + addiu in MIPS)
        split_count = 0
        splits = split_pointers or []
        for hi_off, lo_off in splits:
            actual_hi = hi_off + (delta_bytes if hi_off >= shift_boundary else 0)
            actual_lo = lo_off + (delta_bytes if lo_off >= shift_boundary else 0)

            if actual_hi + 4 <= len(data) and actual_lo + 4 <= len(data):
                hi_instr = struct.unpack_from(f"{endian}I", data, actual_hi)[0]
                lo_instr = struct.unpack_from(f"{endian}I", data, actual_lo)[0]

                # Extract existing target
                if arch.lower() in ("ppc", "powerpc", "wii", "gc"):
                    ha = hi_instr & 0xFFFF
                    lo = struct.unpack(">h", struct.pack(">H", lo_instr & 0xFFFF))[0]
                    old_target = (ha << 16) + lo

                    if old_target >= boundary_ram:
                        new_target = old_target + delta_bytes
                        # Recalculate HA and LO
                        new_ha = ((new_target + 0x8000) >> 16) & 0xFFFF
                        new_lo = new_target & 0xFFFF

                        struct.pack_into(f"{endian}I", data, actual_hi, (hi_instr & 0xFFFF0000) | new_ha)
                        struct.pack_into(f"{endian}I", data, actual_lo, (lo_instr & 0xFFFF0000) | new_lo)
                        split_count += 1

                elif "mips" in arch.lower():
                    hi = (hi_instr & 0xFFFF) << 16
                    lo = struct.unpack(">h", struct.pack(">H", lo_instr & 0xFFFF))[0]
                    old_target = hi + lo

                    if old_target >= boundary_ram:
                        new_target = old_target + delta_bytes
                        new_hi = ((new_target + 0x8000) >> 16) & 0xFFFF
                        new_lo = new_target & 0xFFFF

                        struct.pack_into(f"{endian}I", data, actual_hi, (hi_instr & 0xFFFF0000) | new_hi)
                        struct.pack_into(f"{endian}I", data, actual_lo, (lo_instr & 0xFFFF0000) | new_lo)
                        split_count += 1

        return CascadingShiftReport(
            shift_boundary=shift_boundary,
            delta_bytes=delta_bytes,
            direct_pointers_updated=direct_count,
            split_pointers_updated=split_count,
            new_total_size=len(data),
        )
