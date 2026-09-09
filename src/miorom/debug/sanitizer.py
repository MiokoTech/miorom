"""
miorom.debug.sanitizer
~~~~~~~~~~~~~~~~~~~~~~
Fuzzing & Memory Safety Sanitizer (ROM-ASan).
Shadow memory bounds checker for detecting out-of-bounds reads/writes, buffer overflows
in translated dialogue strings, use-after-free, and dangling pointer dereferences.
"""

from miorom.result import MioRomResult
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


class AccessType(str, Enum):
    READ = "READ"
    WRITE = "WRITE"
    EXECUTE = "EXECUTE"


class ShadowTag(str, Enum):
    VALID = "VALID"
    REDZONE = "REDZONE"
    POISONED = "POISONED"
    READ_ONLY = "READ_ONLY"
    UNMAPPED = "UNMAPPED"


@dataclass
class SanitizerViolation(MioRomResult):
    address: int
    size: int
    access_type: AccessType
    tag: ShadowTag
    message: str

    def summary(self) -> str:
        return (
            f"[ROM-ASan VIOLATION] {self.access_type.value} of size {self.size} at 0x{self.address:08X}: "
            f"Hit {self.tag.value} region. {self.message}"
        )


class MemorySanitizerError(Exception):
    def __init__(self, violation: SanitizerViolation):
        super().__init__(violation.summary())
        self.violation = violation


@dataclass
class SanitizerReport(MioRomResult):
    total_checks: int
    violations: List[SanitizerViolation] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            "==================================================",
            "          ROM-ASan Memory Safety Report           ",
            "==================================================",
            f"  Total Memory Checks : {self.total_checks}",
            f"  Violations Found    : {len(self.violations)}",
        ]
        if self.violations:
            lines.append("  Detected Safety Violations:")
            for v in self.violations:
                lines.append(f"    - {v.summary()}")
        else:
            lines.append("  Status: All memory accesses CLEAN.")
        lines.append("==================================================")
        return "\n".join(lines)


class RomAddressSanitizer:
    """
    Shadow-memory based Address Sanitizer (ASan) for ROM hacking & emulation.
    """

    def __init__(self, default_tag: ShadowTag = ShadowTag.UNMAPPED):
        self.default_tag = default_tag
        # Segment mappings: list of (start_addr, end_addr, ShadowTag, name)
        self.regions: List[Tuple[int, int, ShadowTag, str]] = []
        self.total_checks = 0
        self.violations: List[SanitizerViolation] = []

    def map_region(
        self,
        base_addr: int,
        size: int,
        tag: ShadowTag = ShadowTag.VALID,
        name: str = "",
    ):
        """Map a contiguous memory range with a shadow tag."""
        end_addr = base_addr + size
        self.regions.append((base_addr, end_addr, tag, name))

    def protect_with_redzones(
        self,
        base_addr: int,
        payload_size: int,
        redzone_size: int = 16,
        name: str = "buffer",
    ):
        """
        Surround a memory buffer with front and back REDZONE guard regions
        to detect buffer overflows and underflows.
        """
        # Front Redzone
        self.map_region(base_addr - redzone_size, redzone_size, ShadowTag.REDZONE, f"{name}_front_redzone")
        # Valid Payload
        self.map_region(base_addr, payload_size, ShadowTag.VALID, name)
        # Back Redzone
        self.map_region(base_addr + payload_size, redzone_size, ShadowTag.REDZONE, f"{name}_back_redzone")

    def poison_region(self, base_addr: int, size: int):
        """Mark a region as POISONED (e.g. upon free)."""
        self.map_region(base_addr, size, ShadowTag.POISONED, "poisoned_memory")

    def _query_tag(self, addr: int) -> Tuple[ShadowTag, str]:
        # Scan regions in reverse (latest mapping overrides earlier)
        for start, end, tag, name in reversed(self.regions):
            if start <= addr < end:
                return tag, name
        return self.default_tag, "unmapped"

    def check_access(
        self,
        addr: int,
        size: int,
        access_type: AccessType = AccessType.READ,
    ) -> Optional[SanitizerViolation]:
        """
        Verify that an access of `size` bytes at `addr` does not violate safety policies.
        Returns a SanitizerViolation if an error is caught.
        """
        self.total_checks += 1

        # Check every byte in access range
        for cur_addr in range(addr, addr + size):
            tag, name = self._query_tag(cur_addr)

            if tag == ShadowTag.VALID:
                continue

            if tag == ShadowTag.READ_ONLY and access_type == AccessType.READ:
                continue

            # Violation detected!
            msg = ""
            if tag == ShadowTag.REDZONE:
                msg = f"Buffer overflow/underflow detected in redzone '{name}'"
            elif tag == ShadowTag.POISONED:
                msg = f"Use-after-free or access to poisoned region '{name}'"
            elif tag == ShadowTag.READ_ONLY and access_type == AccessType.WRITE:
                msg = f"Write attempted on read-only region '{name}'"
            elif tag == ShadowTag.UNMAPPED:
                msg = "Out-of-bounds pointer dereference to unmapped memory"

            violation = SanitizerViolation(
                address=cur_addr,
                size=size,
                access_type=access_type,
                tag=tag,
                message=msg,
            )
            self.violations.append(violation)
            return violation

        return None

    def assert_bounds(
        self,
        addr: int,
        size: int,
        access_type: AccessType = AccessType.READ,
    ):
        """Check access and raise MemorySanitizerError immediately on violation."""
        v = self.check_access(addr, size, access_type)
        if v:
            raise MemorySanitizerError(v)

    def report(self) -> SanitizerReport:
        """Generate summary report of all checks and violations."""
        return SanitizerReport(
            total_checks=self.total_checks,
            violations=self.violations,
        )
